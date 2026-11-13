package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.dto.MonthlyAnalysisRequest;
import com.example.carbon.emission.model.service.impl.MonthlyAnalysisDataService.Detail;
import org.apache.poi.xssf.streaming.SXSSFWorkbook;
import org.springframework.beans.BeanUtils;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.YearMonth;
import java.util.*;
import static com.example.carbon.emission.model.service.impl.MonthlyAnalysisDataService.*;

@Service
@Transactional(readOnly = true)
public class MonthlyAnalysisService {
    private final MonthlyAnalysisDataService source;
    private final JdbcTemplate jdbc;
    public MonthlyAnalysisService(MonthlyAnalysisDataService source,JdbcTemplate jdbc) { this.source=source;this.jdbc=jdbc; }

    public Map<String,Object> query(MonthlyAnalysisRequest request) {
        return nodeRollup(request) ? rollup(request) : summarize(source.load(request),request,labels());
    }
    private static boolean nodeRollup(MonthlyAnalysisRequest request) {
        return request!=null && Set.of("CALC_NODE","ROOT").contains(Objects.toString(request.getRollup(),""));
    }
    public Map<String,Object> compare(MonthlyAnalysisRequest request) {
        MonthlyAnalysisDataService.validate(request);
        if ("ORGANIZATION".equals(request.getCompareType())) {
            if (request.getSelections().size()<2 && !("DEPARTMENT".equals(request.getDimension()) && request.getDepartmentIds().size()>=2) && !("STATION".equals(request.getDimension()) && request.getStationIds().size()>=2)) throw bad("组织对比请选择至少两个公司、部门或站点");
            return query(request);
        }
        if (!Set.of("YOY","MOM").contains(request.getCompareType()==null?"":request.getCompareType())) throw bad("对比方式不正确");
        Map<String,Object> current=query(request), previous=query(previousRequest(request));
        return pair(current,previous,request);
    }
    private Map<String,String> labels() {
        Map<String,String> names=new HashMap<>(Map.of("ENERGY:electricity","电力","ENERGY:diesel","柴油","ENERGY:gasoline","汽油","ENERGY:natural_gas","天然气","ENERGY:heat","热力"));
        for(var row:jdbc.queryForList("select category_code code,category_name name from emission_energy_category")) names.put("SCENE:"+row.get("code"),String.valueOf(row.get("name")));
        for(var row:jdbc.queryForList("select subcategory_code code,subcategory_name name from emission_calc_unit_default")) names.put("ENERGY:"+row.get("code"),String.valueOf(row.get("name")));
        return names;
    }
    private Map<String,String> attributionLabels(List<Detail> rows) {
        Map<String,String> result=new HashMap<>();Set<Long> depts=new HashSet<>(),stations=new HashSet<>();
        rows.forEach(d -> { if(d.data().getEnergyAttributionDeptId()!=null) depts.add(d.data().getEnergyAttributionDeptId());if(d.data().getEnergyAttributionStationId()!=null) stations.add(d.data().getEnergyAttributionStationId()); });
        source.namedOptions(depts,false).forEach(o -> result.put("DEPARTMENT:"+o.get("id"),String.valueOf(o.get("name"))));
        source.namedOptions(stations,true).forEach(o -> result.put("STATION:"+o.get("id"),String.valueOf(o.get("name"))));return result;
    }

    private Map<String,Object> summarize(List<Detail> details,MonthlyAnalysisRequest request,Map<String,String> names) {
        names.putAll(attributionLabels(details));
        return aggregate(details,request,names);
    }
    public static Map<String,Object> aggregate(List<Detail> details,MonthlyAnalysisRequest request,Map<String,String> names) {
        Map<String,Bucket> groups=new LinkedHashMap<>();Map<String,Detail> unique=new LinkedHashMap<>();
        for(Detail d:details) {
            var data=d.data();String energy=Objects.toString(data.getEmissionSubcategory(),"未分类能源"),unit=Objects.toString(data.getMeasurementUnit(),"未注明单位");
            String group=switch(request.getDimension()) {
                case "SCENE" -> Objects.toString(request.getCategoryLevel()==1?data.getEnergyCategoryL1():data.getEnergyCategoryL2(),"未分类");
                case "DEPARTMENT" -> Objects.toString(data.getEnergyAttributionDeptId(),"0");
                case "STATION" -> Objects.toString(data.getEnergyAttributionStationId(),"0");
                default -> energy;
            };
            String period=period(YearMonth.parse(d.month()),request.getGrain());
            String key=d.companyId()+"|"+group+"|"+energy+"|"+unit+"|"+period;
            String label=names.getOrDefault(request.getDimension()+":"+group,group.equals("0")?"未明确归属":group);
            Bucket bucket=groups.computeIfAbsent(key,k -> new Bucket(map("companyId",d.companyId(),"companyName",d.companyName(),"groupKey",group,"groupName",label,"energy",energy,
                    "energyName",names.getOrDefault("ENERGY:"+energy,energy),"unit",unit,"period",period)));
            bucket.add(d,request.getValueMode());unique.putIfAbsent(d.point().key()+":"+d.month(),d);
        }
        List<Map<String,Object>> rows=groups.values().stream().map(Bucket::finish).sorted(Comparator.comparing((Map<String,Object> r) -> r.get("period").toString()).thenComparing(r -> r.get("companyId").toString()).thenComparing(r -> r.get("groupName").toString())).toList();
        Bucket total=new Bucket(new LinkedHashMap<>());Map<String,Bucket> energies=new LinkedHashMap<>();
        for(Detail d:unique.values()) {
            total.add(d,request.getValueMode());String code=Objects.toString(d.data().getEmissionSubcategory(),"未分类能源"),unit=Objects.toString(d.data().getMeasurementUnit(),"未注明单位");
            energies.computeIfAbsent(code+"|"+unit,k -> new Bucket(map("energy",code,"energyName",names.getOrDefault("ENERGY:"+code,code),"unit",unit))).add(d,request.getValueMode());
        }
        var summary=total.finish();summary.remove("selectedEnergy");summary.remove("rawEnergy");summary.remove("adjustedEnergy");summary.remove("adoptedEnergy");summary.remove("energyDifference");
        summary.put("energies",energies.values().stream().map(Bucket::finish).toList());
        List<String> notices=new ArrayList<>();
        if(total.missing>0) notices.add("已统计可用部分；有"+total.missing+"条采集点月份未生成或所选数值缺失，未按零补齐。");
        if(total.abnormal>0) notices.add("包含"+total.abnormal+"条补全、估算或异常记录，可在修正明细中查看原因。");
        if(unique.size()!=details.size()) notices.add("所选模板范围有重叠，汇总卡片已按物理采集点和月份去重；各公司行分别展示其范围。");
        List<String> periods=MonthlyAnalysisDataService.months(request).stream().map(m -> period(m,request.getGrain())).distinct().toList();
        return map("rows",rows,"summary",summary,"periods",periods,"notices",notices,"valueMode",request.getValueMode(),"grain",request.getGrain(),"dimension",request.getDimension(),"startMonth",request.getStartMonth(),"endMonth",request.getEndMonth(),"unit","tCO₂e");
    }

    static final class Bucket {
        final Map<String,Object> row;final Set<String> seen=new HashSet<>(),missingMonths=new TreeSet<>();int expected,generated,missing,abnormal;boolean energyDifferenceMissing,carbonDifferenceMissing;
        Bucket(Map<String,Object> row) {this.row=row;}
        void add(Detail d,String mode) {
            if(!seen.add(d.point().key()+":"+d.month())) return;
            expected++;if(d.data().getId()!=null) generated++;
            for(String basis:List.of("RAW","ADJUSTED","ADOPTED")) {
                var value=MonthlyAnalysisValues.select(d.data(),basis);String prefix=basis.toLowerCase();
                addNumber(prefix+"Energy",value.energy());addNumber(prefix+"Carbon",value.carbon());
            }
            var raw=MonthlyAnalysisValues.select(d.data(),"RAW");var adjusted=MonthlyAnalysisValues.select(d.data(),"ADJUSTED");
            energyDifferenceMissing |= raw.energy()==null || adjusted.energy()==null;
            carbonDifferenceMissing |= raw.carbon()==null || adjusted.carbon()==null;
            var value=MonthlyAnalysisValues.select(d.data(),mode);addNumber("selectedEnergy",value.energy());addNumber("selectedCarbon",value.carbon());
            if(value.energy()==null || value.carbon()==null) {missing++;missingMonths.add(d.month());}
            if(d.data().getId()!=null && !Integer.valueOf(1).equals(d.data().getDataStatus()) && !Integer.valueOf(2).equals(d.data().getDataStatus())) abnormal++;
        }
        void addNumber(String key,BigDecimal value) {if(value!=null) row.put(key,((BigDecimal)row.getOrDefault(key,BigDecimal.ZERO)).add(value));}
        Map<String,Object> finish() {
            for(String key:List.of("rawEnergy","rawCarbon","adjustedEnergy","adjustedCarbon","adoptedEnergy","adoptedCarbon","selectedEnergy","selectedCarbon")) row.putIfAbsent(key,null);
            row.put("expectedCount",expected);row.put("generatedCount",generated);row.put("missingCount",missing);row.put("abnormalCount",abnormal);row.put("missingMonths",new ArrayList<>(missingMonths));row.put("incomplete",missing>0);
            row.put("energyDifference",energyDifferenceMissing?null:MonthlyAnalysisValues.difference((BigDecimal)row.get("adjustedEnergy"),(BigDecimal)row.get("rawEnergy")));
            row.put("carbonDifference",carbonDifferenceMissing?null:MonthlyAnalysisValues.difference((BigDecimal)row.get("adjustedCarbon"),(BigDecimal)row.get("rawCarbon")));return row;
        }
    }
    public static String period(YearMonth month,String grain) {
        return "YEAR".equals(grain)?String.valueOf(month.getYear()):"QUARTER".equals(grain)?month.getYear()+"-Q"+((month.getMonthValue()-1)/3+1):month.toString();
    }
    public static int shift(MonthlyAnalysisRequest request) {
        return "YOY".equals(request.getCompareType()) || "YEAR".equals(request.getGrain())?12:"QUARTER".equals(request.getGrain())?3:1;
    }
    public static MonthlyAnalysisRequest previousRequest(MonthlyAnalysisRequest request) {
        MonthlyAnalysisRequest previous=new MonthlyAnalysisRequest();BeanUtils.copyProperties(request,previous);
        previous.setStartMonth(YearMonth.parse(request.getStartMonth()).minusMonths(shift(request)).toString());
        previous.setEndMonth(YearMonth.parse(request.getEndMonth()).minusMonths(shift(request)).toString());return previous;
    }
    @SuppressWarnings("unchecked") public static Map<String,Object> pair(Map<String,Object> current,Map<String,Object> previous,MonthlyAnalysisRequest request) {
        Map<String,Map<String,Object>> now=new LinkedHashMap<>(),then=new LinkedHashMap<>();
        for(var r:(List<Map<String,Object>>)current.get("rows")) now.put(rowKey(r,r.get("period").toString()),r);
        for(var r:(List<Map<String,Object>>)previous.get("rows")) then.put(rowKey(r,shiftPeriod(r.get("period").toString(),request)),r);
        Set<String> keys=new LinkedHashSet<>(now.keySet());keys.addAll(then.keySet());List<Map<String,Object>> rows=new ArrayList<>();
        for(String key:keys) {
            var n=now.get(key);var p=then.get(key);var row=new LinkedHashMap<>(n==null?p:n);
            if(n==null) {row.put("period",shiftPeriod(p.get("period").toString(),request));for(String metric:List.of("rawEnergy","rawCarbon","adjustedEnergy","adjustedCarbon","adoptedEnergy","adoptedCarbon","selectedEnergy","selectedCarbon")) row.put(metric,null);}
            for(String metric:List.of("Energy","Carbon")) {
                BigDecimal a=n==null?null:(BigDecimal)n.get("selected"+metric),b=p==null?null:(BigDecimal)p.get("selected"+metric);
                row.put("previous"+metric,b);row.put("delta"+metric,a==null||b==null?null:a.subtract(b));
                row.put("rate"+metric,a==null||b==null||b.signum()==0?null:a.subtract(b).divide(b.abs(),8,RoundingMode.HALF_UP).multiply(new BigDecimal("100")));
            }
            row.put("previousPeriod",p==null?null:p.get("period"));row.put("previousIncomplete",p==null||Boolean.TRUE.equals(p.get("incomplete")));
            row.put("incomplete",n==null||Boolean.TRUE.equals(n.get("incomplete")));rows.add(row);
        }
        var result=new LinkedHashMap<>(current);result.put("rows",rows);result.put("compareType",request.getCompareType());result.put("previousSummary",previous.get("summary"));
        var baseline=previousRequest(request);result.put("previousStartMonth",baseline.getStartMonth());result.put("previousEndMonth",baseline.getEndMonth());
        Set<String> notices=new LinkedHashSet<>((List<String>)current.get("notices"));
        for(String notice:(List<String>)previous.get("notices")) notices.add("基期："+notice);
        result.put("notices",new ArrayList<>(notices));return result;
    }
    private static String rowKey(Map<String,Object> row,String period) {return row.get("companyId")+"|"+row.get("groupKey")+"|"+row.get("energy")+"|"+row.get("unit")+"|"+period;}
    private static String shiftPeriod(String period,MonthlyAnalysisRequest r) {
        YearMonth month="YEAR".equals(r.getGrain())?YearMonth.of(Integer.parseInt(period),1):"QUARTER".equals(r.getGrain())?YearMonth.of(Integer.parseInt(period.substring(0,4)),(Integer.parseInt(period.substring(6))-1)*3+1):YearMonth.parse(period);
        return period(month.plusMonths(shift(r)),r.getGrain());
    }

    private Map<String,Object> rollup(MonthlyAnalysisRequest request) {
        if (!"ENERGY".equals(request.getDimension())) throw bad("核算节点月度表只按排放小类汇总");
        List<Map<String,Object>> selections=source.authorizedSelections(request);
        List<YearMonth> range=MonthlyAnalysisDataService.months(request);
        int from=range.get(0).getYear()*12+range.get(0).getMonthValue();
        int to=range.get(range.size()-1).getYear()*12+range.get(range.size()-1).getMonthValue();
        Map<String,String> names=labels();
        Map<String,Map<String,Object>> groups=new LinkedHashMap<>();
        int included=0;
        for (var selection:selections) {
            Long nodeId=selection.get("nodeId") instanceof Number number ? number.longValue() : null;
            List<Map<String,Object>> stored=jdbc.queryForList(
                    "select source_node_id, parent_source_node_id, year, month, emission_subcategory, direct_energy_value, direct_carbon_emission, subtotal_energy_value, subtotal_carbon_emission, calculation_unit_code, result_status, missing_collection_point_ids from emission_calc_node_summary_month where template_id=? and (year*12+month) between ? and ?",
                    selection.get("templateId"), from, to);
            for (var row:stored) {
                boolean root=row.get("parent_source_node_id")==null;
                Long sourceNode=row.get("source_node_id") instanceof Number number ? number.longValue() : null;
                if ("ROOT".equals(request.getRollup()) || nodeId==null) { if (!root) continue; }
                else if (!nodeId.equals(sourceNode)) continue;
                String energy=Objects.toString(row.get("emission_subcategory"),"未分类能源");
                if (request.getEnergy()!=null && !request.getEnergy().isBlank() && !request.getEnergy().equals(energy)) continue;
                included++;
                String unit=Objects.toString(row.get("calculation_unit_code"),"未注明单位");
                String period=period(YearMonth.of(((Number)row.get("year")).intValue(), ((Number)row.get("month")).intValue()), request.getGrain());
                String key=selection.get("companyId")+"|"+energy+"|"+unit+"|"+period;
                Map<String,Object> bucket=groups.computeIfAbsent(key, ignored -> new LinkedHashMap<>(map(
                        "companyId",selection.get("companyId"),"companyName",selection.get("companyName"),
                        "groupKey",energy,"groupName",names.getOrDefault("ENERGY:"+energy,energy),
                        "energy",energy,"energyName",names.getOrDefault("ENERGY:"+energy,energy),
                        "unit",unit,"period",period,"selectedEnergy",BigDecimal.ZERO,"selectedCarbon",BigDecimal.ZERO,
                        "adoptedEnergy",BigDecimal.ZERO,"adoptedCarbon",BigDecimal.ZERO,"directEnergy",BigDecimal.ZERO,
                        "directCarbon",BigDecimal.ZERO,"incomplete",false,"missingPoints",new LinkedHashSet<String>())));
                addDecimal(bucket,"selectedEnergy",row.get("subtotal_energy_value"));
                addDecimal(bucket,"selectedCarbon",row.get("subtotal_carbon_emission"));
                addDecimal(bucket,"adoptedEnergy",row.get("subtotal_energy_value"));
                addDecimal(bucket,"adoptedCarbon",row.get("subtotal_carbon_emission"));
                addDecimal(bucket,"directEnergy",row.get("direct_energy_value"));
                addDecimal(bucket,"directCarbon",row.get("direct_carbon_emission"));
                if (!Integer.valueOf(1).equals(row.get("result_status") instanceof Number number ? number.intValue() : null)) {
                    bucket.put("incomplete",true);
                    String missing=Objects.toString(row.get("missing_collection_point_ids"),"");
                    @SuppressWarnings("unchecked") Set<String> ids=(Set<String>)bucket.get("missingPoints");
                    for (String id:missing.split(",")) if (!id.isBlank()) ids.add(id.trim());
                }
            }
        }
        List<Map<String,Object>> rows=new ArrayList<>();
        BigDecimal carbon=BigDecimal.ZERO; boolean incomplete=false;
        Map<String,Map<String,Object>> energies=new LinkedHashMap<>();
        for (var bucket:groups.values()) {
            @SuppressWarnings("unchecked") Set<String> ids=(Set<String>)bucket.get("missingPoints");
            bucket.put("missingPoints",new ArrayList<>(ids));
            rows.add(bucket);
            carbon=carbon.add((BigDecimal)bucket.get("selectedCarbon"));
            incomplete |= Boolean.TRUE.equals(bucket.get("incomplete"));
            String energyKey=bucket.get("energy")+"|"+bucket.get("unit");
            Map<String,Object> energy=energies.computeIfAbsent(energyKey, ignored -> new LinkedHashMap<>(map(
                    "energy",bucket.get("energy"),"energyName",bucket.get("energyName"),"unit",bucket.get("unit"),
                    "selectedEnergy",BigDecimal.ZERO,"selectedCarbon",BigDecimal.ZERO,"incomplete",false)));
            addDecimal(energy,"selectedEnergy",bucket.get("selectedEnergy"));
            addDecimal(energy,"selectedCarbon",bucket.get("selectedCarbon"));
            energy.put("incomplete",Boolean.TRUE.equals(energy.get("incomplete")) || Boolean.TRUE.equals(bucket.get("incomplete")));
        }
        rows.sort(Comparator.comparing((Map<String,Object> row) -> row.get("period").toString()).thenComparing(row -> row.get("companyId").toString()).thenComparing(row -> row.get("groupName").toString()));
        List<String> notices=new ArrayList<>();
        notices.add("排放小类合计来自核算节点月度表的子树合计，单位是核算单位。");
        if (!"ADOPTED".equals(request.getValueMode())) notices.add("核算节点月度表只有采用值，已按采用值展示。");
        if (included==0) notices.add("未生成核算节点月度结果。");
        if (incomplete) notices.add("结果状态为部分缺失时，数值包含未齐备的采集点，不能视为完整真实值。");
        Map<String,Object> summary=map("selectedCarbon",carbon,"incomplete",incomplete,"generatedCount",included,"energies",new ArrayList<>(energies.values()));
        List<String> periods=range.stream().map(month -> period(month,request.getGrain())).distinct().toList();
        return map("rows",rows,"summary",summary,"periods",periods,"notices",notices,"valueMode","ADOPTED","grain",request.getGrain(),"dimension",request.getDimension(),"startMonth",request.getStartMonth(),"endMonth",request.getEndMonth(),"unit","tCO₂e","rollup",request.getRollup());
    }
    private static void addDecimal(Map<String,Object> row,String key,Object value) {
        BigDecimal current=row.get(key) instanceof BigDecimal decimal ? decimal : BigDecimal.ZERO;
        BigDecimal extra=value instanceof BigDecimal decimal ? decimal : value instanceof Number number ? new BigDecimal(number.toString()) : BigDecimal.ZERO;
        row.put(key,current.add(extra));
    }

    @SuppressWarnings("unchecked") public byte[] export(MonthlyAnalysisRequest request) throws IOException {
        MonthlyAnalysisDataService.validate(request);
        Map<String,Object> result="NONE".equals(request.getCompareType())?query(request):compare(request);
        List<Detail> details=source.load(request);boolean temporal=Set.of("YOY","MOM").contains(Objects.toString(request.getCompareType(),""));
        List<Detail> baseline=temporal?source.load(previousRequest(request)):List.of();
        if(details.size()+baseline.size()>100000) throw bad("导出明细超过十万行，请缩小范围");
        SXSSFWorkbook book=new SXSSFWorkbook(100);
        try(ByteArrayOutputStream out=new ByteArrayOutputStream()) {
            write(book,"统计汇总",(List<Map<String,Object>>)result.get("rows"),List.of("companyName","period","groupName","energyName","unit","selectedEnergy","selectedCarbon","rawEnergy","adjustedEnergy","adoptedEnergy","previousEnergy","rateEnergy","previousCarbon","rateCarbon","incomplete","previousIncomplete"),
                    List.of("公司","期间","分组","能源","单位","当前口径用量","当前口径排放tCO2e","原始用量","修正用量","核算采用用量","基期用量","用量变化率%","基期排放","排放变化率%","本期不完整","基期不完整"));
            writeDetails(book,"本期修正明细",details,request.getValueMode());if(temporal) writeDetails(book,"基期修正明细",baseline,request.getValueMode());
            var summary=(Map<String,Object>)result.get("summary");
            List<Map<String,Object>> totals=new ArrayList<>((List<Map<String,Object>>)summary.get("energies"));
            totals.add(map("energyName","全部能源碳排放合计","selectedCarbon",summary.get("selectedCarbon"),"incomplete",summary.get("incomplete")));
            write(book,"期间合计",totals,List.of("energyName","unit","selectedEnergy","selectedCarbon","incomplete"),List.of("能源或合计项","能耗单位","所选口径能耗","所选口径排放tCO2e","不完整"));
            write(book,"统计口径",List.of(map("mode",request.getValueMode(),"period",request.getStartMonth()+"至"+request.getEndMonth(),"notices",String.join("；",(List<String>)result.get("notices")))),List.of("mode","period","notices"),List.of("数据口径","本期","质量提示"));
            book.write(out);return out.toByteArray();
        } finally {book.close();book.dispose();}
    }
    private static void writeDetails(SXSSFWorkbook book,String name,List<Detail> details,String mode) {
        write(book,name,details.stream().map(d -> MonthlyAnalysisDataService.detail(d,mode)).toList(),
                List.of("companyName","templateName","pointType","pointId","pointName","month","energy","unit","rawEnergy","adjustedEnergy","adoptedEnergy","selectedEnergy","energyDifference","rawCarbon","adjustedCarbon","adoptedCarbon","selectedCarbon","carbonDifference","method","generated","dataStatus","description"),
                List.of("公司","模板","采集点类型","采集点ID","采集点","月份","能源","单位","原始用量","修正用量","采用用量","当前口径用量","修正差额","原始排放tCO2e","修正排放tCO2e","采用排放tCO2e","当前口径排放tCO2e","排放修正差额","核算方式1修正2原始","已生成月度记录","数据状态","说明"));
    }
    private static void write(SXSSFWorkbook book,String name,List<Map<String,Object>> rows,List<String> keys,List<String> labels) {
        var sheet=book.createSheet(name);var header=sheet.createRow(0);for(int i=0;i<keys.size();i++){header.createCell(i).setCellValue(labels.get(i));sheet.setColumnWidth(i,20*256);}
        int index=1;for(var row:rows){var line=sheet.createRow(index++);for(int i=0;i<keys.size();i++){Object v=row.get(keys.get(i));if(v!=null){var cell=line.createCell(i);if(v instanceof Number n) cell.setCellValue(n.doubleValue());else if(v instanceof Boolean b) cell.setCellValue(b?"是":"否");else cell.setCellValue(v.toString());}}}sheet.createFreezePane(0,1);
    }
}
