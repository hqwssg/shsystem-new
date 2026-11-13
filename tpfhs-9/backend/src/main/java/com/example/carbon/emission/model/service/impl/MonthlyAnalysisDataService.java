package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.dto.MonthlyAnalysisRequest;
import com.example.carbon.emission.model.entity.*;
import com.example.carbon.emission.model.repository.*;
import com.example.carbon.emission.model.security.*;
import org.springframework.dao.DataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.BeanPropertyRowMapper;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.time.YearMonth;
import java.util.*;

@Service
@Transactional(readOnly = true)
public class MonthlyAnalysisDataService {
    private static final int LIMIT = 100_000;
    private final JdbcTemplate jdbc;
    private final TemplateRepository templates;
    private final EmissionNodeRepository nodes;
    private final EmissionNodeConfigRepository configs;
    private final CompanyOwnershipService companies;
    private final StatisticsBaselineTemplateService baselines;
    private final CarbonDataScopeService scopes;
    private final CollectionScopeService points;
    private final NodeInclusionResolver inclusion;

    public MonthlyAnalysisDataService(JdbcTemplate jdbc, TemplateRepository templates,
            EmissionNodeRepository nodes, EmissionNodeConfigRepository configs,
            CompanyOwnershipService companies, StatisticsBaselineTemplateService baselines,
            CarbonDataScopeService scopes, CollectionScopeService points, NodeInclusionResolver inclusion) {
        this.jdbc=jdbc; this.templates=templates; this.nodes=nodes; this.configs=configs;
        this.companies=companies; this.baselines=baselines; this.scopes=scopes; this.points=points; this.inclusion=inclusion;
    }

    public record Point(int type, long id) { public String key() { return type+":"+id; } }
    public record Context(CompanyOwnershipService.Company company, Template template,
                          List<EmissionNode> nodes, Map<Point, Map<String,Object>> points) { }
    public record Detail(Long companyId, String companyName, Long templateId, String templateName,
                         Point point, String pointName, String month, MonthlyCollectionNodeData data) { }

    public Map<String,Object> options() {
        requirePermission();
        List<CompanyOwnershipService.Company> allowed = companies.accessibleOptions();
        Map<Long,Long> defaults = new HashMap<>();
        baselines.accessible().forEach(b -> { if (b.templateId()!=null) defaults.put(b.companyDeptId(),b.templateId()); });
        List<Map<String,Object>> companyOptions = new ArrayList<>();
        Map<Point,Map<String,Object>> visiblePoints = new LinkedHashMap<>();
        List<Template> availableTemplates = templates.findAllByOrderByCreatedAtDesc();
        for (var company : allowed) {
            List<Map<String,Object>> choices = new ArrayList<>();
            for (Template template : availableTemplates) {
                if (!Objects.equals(template.getDeptId(),company.deptId()) || !usable(template) || !scopes.canReadSafely(template)) continue;
                try {
                    Context context = context(company,template,null);
                    if (context.points().isEmpty()) continue;
                    visiblePoints.putAll(context.points());
                    List<Map<String,Object>> tree = new ArrayList<>();
                    for (EmissionNode node : context.nodes()) {
                        boolean visible = context.points().values().stream().anyMatch(p ->
                                ((Set<?>)p.get("nodeIds")).stream().anyMatch(id -> below((Long)id,node.getId(),context.nodes())));
                        if (visible) tree.add(map("id",node.getId(),"name",node.getName(),"parentId",node.getParentId()));
                    }
                    choices.add(map("id",template.getId(),"name",template.getName(),"nodes",tree));
                } catch (IllegalStateException invalidTree) {
                    // An invalid legacy tree does not hide the other usable templates.
                }
            }
            Long defaultId = defaults.get(company.deptId());
            if (choices.stream().noneMatch(t -> Objects.equals(t.get("id"),defaults.get(company.deptId())))) defaultId=null;
            companyOptions.add(map("id",company.deptId(),"name",company.deptName(),"defaultTemplateId",defaultId,"templates",choices));
        }
        Set<Long> departments=new LinkedHashSet<>(),stations=new LinkedHashSet<>();Set<String> energies=new TreeSet<>();
        visiblePoints.values().forEach(p -> {
            if(number(p.get("energy_attribution_dept_id"))!=null) departments.add(number(p.get("energy_attribution_dept_id")));
            if(number(p.get("energy_attribution_station_id"))!=null) stations.add(number(p.get("energy_attribution_station_id")));
            if(text(p.get("emission_subcategory"))!=null) energies.add(text(p.get("emission_subcategory")));
        });
        // Historical attribution belongs to the monthly snapshot, not today's meter settings.
        for (int type:List.of(1,2,3)) {
            List<Long> ids=visiblePoints.keySet().stream().filter(p -> p.type()==type).map(Point::id).toList();
            for(int from=0;from<ids.size();from+=500) {
                List<Long> batch=ids.subList(from,Math.min(from+500,ids.size()));
                List<Object> args=new ArrayList<>();args.add(type);args.addAll(batch);
                try {
                    for(var row:jdbc.queryForList("select distinct energy_attribution_dept_id,energy_attribution_station_id,emission_subcategory from emission_collection_node_data_month where collection_point_type=? and collection_point_id in ("+String.join(",",Collections.nCopies(batch.size(),"?"))+")",args.toArray())) {
                        if(number(row.get("energy_attribution_dept_id"))!=null) departments.add(number(row.get("energy_attribution_dept_id")));
                        if(number(row.get("energy_attribution_station_id"))!=null) stations.add(number(row.get("energy_attribution_station_id")));
                        if(text(row.get("emission_subcategory"))!=null) energies.add(text(row.get("emission_subcategory")));
                    }
                } catch(DataAccessException e) { throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"月度结果表读取失败，请核对月度表迁移和数据库连接",e); }
            }
        }
        return map("companies",companyOptions,"categories",jdbc.queryForList("select category_code code,category_name name,level from emission_energy_category where status=1 order by level,sort_order,id"),
                "departments",namedOptions(departments,false),"stations",namedOptions(stations,true),"energies",energies,
                "basis","月度核算表；按所选模板的有效采集点取数");
    }

    public List<Detail> load(MonthlyAnalysisRequest request) {
        validate(request);
        Map<Long,CompanyOwnershipService.Company> allowed=new HashMap<>();
        companies.accessibleOptions().forEach(c -> allowed.put(c.deptId(),c));
        Set<Long> selectedCompanies=new HashSet<>();
        List<Context> contexts=new ArrayList<>();
        for (var selection:request.getSelections()) {
            if (selection==null || !allowed.containsKey(selection.getCompanyId())) throw forbidden("公司不在当前授权范围内");
            if (!selectedCompanies.add(selection.getCompanyId())) throw bad("每家公司只能选择一个统计模板");
            Template template=templates.findById(selection.getTemplateId()==null ? -1L : selection.getTemplateId()).orElseThrow(() -> bad("请选择有效的核算模板"));
            if (!usable(template) || !Objects.equals(template.getDeptId(),selection.getCompanyId()) || !scopes.canReadSafely(template)) throw forbidden("模板不属于所选公司或无权访问");
            contexts.add(context(allowed.get(selection.getCompanyId()),template,selection.getNodeId()));
        }
        Set<Point> unique=new LinkedHashSet<>(); contexts.forEach(c -> unique.addAll(c.points().keySet()));
        List<YearMonth> months=months(request);
        if ((long)unique.size()*months.size()*contexts.size()>LIMIT) throw bad("统计范围过大，请缩小月份或节点范围");
        Map<String,MonthlyCollectionNodeData> stored=readMonthly(unique,months.get(0),months.get(months.size()-1));
        List<Detail> result=new ArrayList<>();
        for (Context context:contexts) for (var entry:context.points().entrySet()) for (YearMonth month:months) {
            Point point=entry.getKey(); var meta=entry.getValue();
            MonthlyCollectionNodeData row=stored.get(point.key()+":"+month);
            if (row==null) {
                row=new MonthlyCollectionNodeData(); row.setId(null);row.setYear(month.getYear());row.setMonth(month.getMonthValue());
                row.setEmissionSubcategory(text(meta.get("emission_subcategory")));row.setMeasurementUnit(text(meta.get("measurement_unit")));
                row.setEnergyCategoryL1(text(meta.get("energy_category_l1")));row.setEnergyCategoryL2(text(meta.get("energy_category_l2")));
                row.setEnergyAttributionDeptId(number(meta.get("energy_attribution_dept_id")));row.setEnergyAttributionStationId(number(meta.get("energy_attribution_station_id")));
                row.setDataStatus(2);row.setDataMissingDescription("未生成月度结果");
            }
            if (!matches(request,row)) continue;
            result.add(new Detail(context.company().deptId(),context.company().deptName(),context.template().getId(),context.template().getName(),
                    point,text(meta.get("name")),month.toString(),row));
        }
        result.sort(Comparator.comparing(Detail::companyId).thenComparing(d -> d.point().type()).thenComparing(d -> d.point().id()).thenComparing(Detail::month));
        return result;
    }

    public List<Map<String,Object>> authorizedSelections(MonthlyAnalysisRequest request) {
        validate(request);
        Map<Long,CompanyOwnershipService.Company> allowed=new HashMap<>();
        companies.accessibleOptions().forEach(c -> allowed.put(c.deptId(),c));
        Set<Long> selectedCompanies=new HashSet<>();
        List<Map<String,Object>> result=new ArrayList<>();
        for (var selection:request.getSelections()) {
            if (selection==null || !allowed.containsKey(selection.getCompanyId())) throw forbidden("公司不在当前授权范围内");
            if (!selectedCompanies.add(selection.getCompanyId())) throw bad("每家公司只能选择一个统计模板");
            Template template=templates.findById(selection.getTemplateId()==null ? -1L : selection.getTemplateId()).orElseThrow(() -> bad("请选择有效的核算模板"));
            if (!usable(template) || !Objects.equals(template.getDeptId(),selection.getCompanyId()) || !scopes.canReadSafely(template)) throw forbidden("模板不属于所选公司或无权访问");
            if (selection.getNodeId()!=null && nodes.findByTemplateId(template.getId()).stream().noneMatch(node -> selection.getNodeId().equals(node.getId()))) throw forbidden("核算点不属于所选模板");
            CompanyOwnershipService.Company company=allowed.get(selection.getCompanyId());
            result.add(map("companyId",company.deptId(),"companyName",company.deptName(),"templateId",template.getId(),"nodeId",selection.getNodeId()));
        }
        return result;
    }

    @SuppressWarnings("unchecked")
    private Context context(CompanyOwnershipService.Company company, Template template, Long rootId) {
        List<EmissionNode> tree=nodes.findByTemplateId(template.getId());
        var decisions=inclusion.resolve(tree);
        if (rootId!=null && tree.stream().noneMatch(n -> rootId.equals(n.getId()))) throw forbidden("核算点不属于所选模板");
        Map<Long,EmissionNode> byId=new HashMap<>();tree.forEach(n -> byId.put(n.getId(),n));
        Map<Point,Map<String,Object>> selected=new LinkedHashMap<>();
        for (var config:configs.findCollectionPointConfigsByTemplateId(template.getId())) {
            EmissionNode node=byId.get(config.getNodeId());
            if (node==null || !Integer.valueOf(3).equals(node.getTypeId()) || !decisions.get(node.getId()).included()) continue;
            if (rootId!=null && !below(node.getId(),rootId,tree)) continue;
            CarbonSecurityContext auth=CarbonSecurityContext.current();
            if (!auth.allData() && !auth.nodeIds().isEmpty() && auth.nodeIds().stream().noneMatch(id -> below(node.getId(),id,tree))) continue;
            if (!Set.of(1,2,3).contains(config.getCollectionPointType())) continue;
            Point point=new Point(config.getCollectionPointType(),config.getCollectionPointId());
            if (selected.containsKey(point)) { ((Set<Long>)selected.get(point).get("nodeIds")).add(node.getId());continue; }
            try {
                if (!points.canView(point.type()==1?"electricity":point.type()==2?"fossil":"heat","meter",point.id())) continue;
            } catch (ResponseStatusException e) { if (e.getStatusCode().value()==404) continue;throw e; }
            String table=point.type()==1?"emission_meter_info":point.type()==2?"emission_fossil_fuel_meter_info":"emission_purchased_heat_meter_info";
            List<Map<String,Object>> meta=jdbc.queryForList("select name,emission_subcategory,measurement_unit,energy_category_l1,energy_category_l2,energy_attribution_dept_id,energy_attribution_station_id from "+table+" where id=?",point.id());
            if (!meta.isEmpty()) { meta.get(0).put("nodeIds",new LinkedHashSet<>(List.of(node.getId())));selected.put(point,meta.get(0)); }
        }
        if (rootId!=null && selected.isEmpty()) throw forbidden("核算点没有当前可访问的有效采集点");
        return new Context(company,template,tree,selected);
    }

    private Map<String,MonthlyCollectionNodeData> readMonthly(Set<Point> points, YearMonth start,YearMonth end) {
        Map<String,MonthlyCollectionNodeData> result=new HashMap<>();
        if (points.isEmpty()) return result;
        List<Object> args=new ArrayList<>(List.of(start.getYear()*12+start.getMonthValue(),end.getYear()*12+end.getMonthValue()));
        List<String> clauses=new ArrayList<>();
        for (int type:List.of(1,2,3)) {
            List<Long> ids=points.stream().filter(p -> p.type()==type).map(Point::id).toList();
            if (ids.isEmpty()) continue;
            clauses.add("(collection_point_type=? and collection_point_id in ("+String.join(",",Collections.nCopies(ids.size(),"?"))+"))");args.add(type);args.addAll(ids);
        }
        try {
            List<MonthlyCollectionNodeData> rows=jdbc.query("select * from emission_collection_node_data_month where (year*12+month) between ? and ? and ("+String.join(" or ",clauses)+") limit "+(LIMIT+1),
                    BeanPropertyRowMapper.newInstance(MonthlyCollectionNodeData.class),args.toArray());
            if (rows.size()>LIMIT) throw bad("统计结果过多，请缩小范围");
            for (var row:rows) result.put(row.getCollectionPointType()+":"+row.getCollectionPointId()+":"+YearMonth.of(row.getYear(),row.getMonth()),row);
        } catch (DataAccessException e) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"月度结果表读取失败，请核对月度表迁移和数据库连接",e);
        }
        return result;
    }

    public Map<String,Object> details(MonthlyAnalysisRequest request) {
        List<Detail> rows=load(request);
        int from=Math.min(request.getPage()*request.getSize(),rows.size());
        return map("content",rows.subList(from,Math.min(from+request.getSize(),rows.size())).stream().map(d -> detail(d,request.getValueMode())).toList(),"totalElements",rows.size());
    }
    public static Map<String,Object> detail(Detail d,String mode) {
        var raw=MonthlyAnalysisValues.select(d.data(),"RAW");var adjusted=MonthlyAnalysisValues.select(d.data(),"ADJUSTED");var adopted=MonthlyAnalysisValues.select(d.data(),"ADOPTED");var selected=MonthlyAnalysisValues.select(d.data(),mode);
        boolean missing=selected.energy()==null || selected.carbon()==null;
        String description=Objects.toString(d.data().getDataMissingDescription(),"");
        if(missing && d.data().getId()!=null && !Integer.valueOf(2).equals(d.data().getDataStatus())) description+=(description.isBlank()?"":"；")+"所选口径数值缺失";
        return map("companyId",d.companyId(),"companyName",d.companyName(),"templateId",d.templateId(),"templateName",d.templateName(),"pointType",d.point().type(),"pointId",d.point().id(),"pointName",d.pointName(),"month",d.month(),
                "energy",d.data().getEmissionSubcategory(),"unit",d.data().getMeasurementUnit(),"rawEnergy",raw.energy(),"rawCarbon",raw.carbon(),"adjustedEnergy",adjusted.energy(),"adjustedCarbon",adjusted.carbon(),"adoptedEnergy",adopted.energy(),"adoptedCarbon",adopted.carbon(),
                "selectedEnergy",selected.energy(),"selectedCarbon",selected.carbon(),"energyDifference",MonthlyAnalysisValues.difference(adjusted.energy(),raw.energy()),"carbonDifference",MonthlyAnalysisValues.difference(adjusted.carbon(),raw.carbon()),
                "carbonUnit",d.data().getCarbonEmissionUnit(),"departmentId",d.data().getEnergyAttributionDeptId(),"stationId",d.data().getEnergyAttributionStationId(),
                "method",d.data().getTotalEmissionCalcMethod(),"dataStatus",d.data().getDataStatus(),"generated",d.data().getId()!=null,"missing",missing,"description",description);
    }
    public static void validate(MonthlyAnalysisRequest r) {
        requirePermission();
        if (r==null || r.getSelections()==null || r.getSelections().isEmpty() || r.getSelections().size()>20) throw bad("请选择1至20个公司和统计模板");
        if (r.getValueMode()==null || r.getGrain()==null || r.getDimension()==null || !Set.of("RAW","ADJUSTED","ADOPTED").contains(r.getValueMode()) || !Set.of("MONTH","QUARTER","YEAR").contains(r.getGrain()) || !Set.of("ENERGY","SCENE","DEPARTMENT","STATION").contains(r.getDimension())) throw bad("统计口径、粒度或维度不正确");
        if (r.getCategoryLevel()==null || r.getCategoryLevel()<1 || r.getCategoryLevel()>2 || r.getPage()<0 || r.getPage()>100000 || r.getSize()<1 || r.getSize()>500) throw bad("分类层级或分页参数不正确");
        List<YearMonth> months=months(r);
        var first=months.get(0);var last=months.get(months.size()-1);
        if ("YEAR".equals(r.getGrain()) && (first.getMonthValue()!=1 || last.getMonthValue()!=12)) throw bad("年度统计请选择完整自然年");
        if ("QUARTER".equals(r.getGrain()) && ((first.getMonthValue()-1)%3!=0 || last.getMonthValue()%3!=0)) throw bad("季度统计请选择完整自然季度");
        if (r.getDepartmentIds()==null || r.getStationIds()==null) throw bad("组织筛选参数不正确");
        if (r.getCompareType()==null || !Set.of("NONE","ORGANIZATION","YOY","MOM").contains(r.getCompareType())) throw bad("对比方式不正确");
    }
    public static List<YearMonth> months(MonthlyAnalysisRequest r) {
        try {
            YearMonth first=YearMonth.parse(r.getStartMonth()),last=YearMonth.parse(r.getEndMonth());
            if (first.getYear()<1900 || last.getYear()>2200 || last.isBefore(first) || first.plusYears(10).isBefore(last)) throw bad("月份范围不正确或超过十年");
            List<YearMonth> result=new ArrayList<>();for (var m=first;!m.isAfter(last);m=m.plusMonths(1)) result.add(m);return result;
        } catch (java.time.DateTimeException|NullPointerException e) { throw bad("请选择有效的起止月份，格式yyyy-MM"); }
    }
    private static boolean matches(MonthlyAnalysisRequest r,MonthlyCollectionNodeData d) {
        String category=r.getCategoryLevel()==1?d.getEnergyCategoryL1():d.getEnergyCategoryL2();
        return (r.getEnergy()==null || r.getEnergy().isBlank() || Objects.equals(r.getEnergy(),d.getEmissionSubcategory()))
                && (r.getCategory()==null || r.getCategory().isBlank() || Objects.equals(r.getCategory(),category))
                && (r.getDepartmentIds().isEmpty() || r.getDepartmentIds().contains(d.getEnergyAttributionDeptId()==null?0L:d.getEnergyAttributionDeptId()))
                && (r.getStationIds().isEmpty() || r.getStationIds().contains(d.getEnergyAttributionStationId()==null?0L:d.getEnergyAttributionStationId()));
    }
    static boolean below(Long id,Long root,List<EmissionNode> tree) {
        Map<Long,EmissionNode> nodes=new HashMap<>();tree.forEach(n -> nodes.put(n.getId(),n));Set<Long> seen=new HashSet<>();
        while (id!=null && seen.add(id)) { if (id.equals(root)) return true;EmissionNode n=nodes.get(id);id=n==null?null:n.getParentId(); }return false;
    }
    private static boolean usable(Template t) { return Integer.valueOf(2).equals(t.getTemplateType()) && !Boolean.FALSE.equals(t.getEnabled()); }
    public static void requirePermission() { if (!CarbonSecurityContext.current().hasPermission("carbon:analysis:view")) throw forbidden("没有能耗统计分析权限"); }
    public static Map<String,Object> map(Object... pairs) { Map<String,Object> result=new LinkedHashMap<>();for(int i=0;i<pairs.length;i+=2) result.put((String)pairs[i],pairs[i+1]);return result; }
    static String text(Object value) { return value==null?null:value.toString(); }
    static Long number(Object value) { return value instanceof Number n?n.longValue():null; }
    public List<Map<String,Object>> namedOptions(Set<Long> ids,boolean station) {
        List<Map<String,Object>> result=new ArrayList<>();
        if(!ids.isEmpty()) {
            String sql=station?"select id,concat_ws(' / ',nullif(branch_company,''),name) name from emission_energy_attribution_station"
                    :"select d.dept_id id,concat_ws(' / ',nullif(p.dept_name,''),d.dept_name) name from sys_dept d left join sys_dept p on p.dept_id=d.parent_id";
            result.addAll(jdbc.queryForList(sql+" where "+(station?"id":"d.dept_id")+" in ("+String.join(",",Collections.nCopies(ids.size(),"?"))+")",ids.toArray()));
        }
        result.add(map("id",0L,"name","未明确归属"));return result;
    }
    public static ResponseStatusException bad(String message) { return new ResponseStatusException(HttpStatus.BAD_REQUEST,message); }
    static ResponseStatusException forbidden(String message) { return new ResponseStatusException(HttpStatus.FORBIDDEN,message); }
}
