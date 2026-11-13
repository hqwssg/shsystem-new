package com.example.carbon.emission.model.service;

import com.example.carbon.emission.model.entity.DataDict;
import com.example.carbon.emission.model.entity.DataDictItem;
import com.example.carbon.emission.model.entity.EnergyAttributionStation;
import com.example.carbon.emission.model.repository.*;
import com.example.carbon.emission.model.security.CarbonSecurityContext;
import com.example.carbon.emission.model.util.PinyinUtils;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.util.*;

@Service
public class EnergyAttributionService {
    private final EnergyAttributionStationRepository stations;
    private final DataDictRepository dicts;
    private final DataDictItemRepository dictItems;
    private final MeterInfoRepository electricity;
    private final FossilFuelMeterInfoRepository fossil;
    private final PurchasedHeatMeterInfoRepository heat;
    private final JdbcTemplate jdbc;

    public EnergyAttributionService(EnergyAttributionStationRepository stations, DataDictRepository dicts,
            DataDictItemRepository dictItems, MeterInfoRepository electricity,
            FossilFuelMeterInfoRepository fossil, PurchasedHeatMeterInfoRepository heat, JdbcTemplate jdbc) {
        this.stations = stations;
        this.dicts = dicts;
        this.dictItems = dictItems;
        this.electricity = electricity;
        this.fossil = fossil;
        this.heat = heat;
        this.jdbc = jdbc;
    }

    public List<EnergyAttributionStation> listStations(String keyword, String lineName, String branchCompany) {
        return stations.search(clean(keyword), clean(lineName), clean(branchCompany));
    }

    @Transactional
    public EnergyAttributionStation createStation(EnergyAttributionStation request) {
        EnergyAttributionStation station = new EnergyAttributionStation();
        applyStation(station, request);
        station.setCreatedBy(CarbonSecurityContext.current().userId());
        station.setUpdatedBy(CarbonSecurityContext.current().userId());
        return stations.save(station);
    }

    @Transactional
    public EnergyAttributionStation updateStation(Long id, EnergyAttributionStation request) {
        EnergyAttributionStation station = stations.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "能耗归属站点不存在"));
        applyStation(station, request);
        station.setUpdatedBy(CarbonSecurityContext.current().userId());
        return stations.save(station);
    }

    @Transactional
    public void deleteStation(Long id) {
        if (!stations.existsById(id)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "能耗归属站点不存在");
        }
        long references = electricity.countByEnergyAttributionStationId(id)
                + fossil.countByEnergyAttributionStationId(id)
                + heat.countByEnergyAttributionStationId(id);
        if (references > 0) {
            throw new ResponseStatusException(HttpStatus.CONFLICT,
                    "该能耗归属站点已被" + references + "个采集点引用，不能删除");
        }
        stations.deleteById(id);
    }

    public EnergyAttributionStation requireStation(Long id) {
        if (id == null) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "请选择能耗归属站点/区间");
        return stations.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.BAD_REQUEST, "所选能耗归属站点/区间不存在"));
    }

    public Map<String, Object> requireDepartment(Long id) {
        if (id == null) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "请选择能耗归属部门");
        Map<String, Object> dept = jdbc.query("select dept_id,dept_name,parent_id,ancestors from sys_dept " +
                        "where dept_id=? and status='0' and del_flag='0'",
                rs -> rs.next() ? Map.of("deptId", rs.getLong("dept_id"), "deptName", rs.getString("dept_name"),
                        "parentId", rs.getLong("parent_id"), "ancestors", Objects.toString(rs.getString("ancestors"), "")) : null, id);
        if (dept == null) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "所选能耗归属部门不存在或已停用");
        CarbonSecurityContext context = CarbonSecurityContext.current();
        Set<Long> allowed = new LinkedHashSet<>();
        if (context.deptIds() != null) allowed.addAll(context.deptIds());
        if (context.deptId() != null) allowed.add(context.deptId());
        if (!context.allData() && !allowed.contains(id)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "所选能耗归属部门超出当前数据权限范围");
        }
        return dept;
    }

    public List<Map<String, Object>> listDepartments(String keyword) {
        CarbonSecurityContext context = CarbonSecurityContext.current();
        List<Map<String, Object>> all = jdbc.queryForList("select dept_id,dept_name,parent_id,ancestors from sys_dept " +
                "where status='0' and del_flag='0' order by order_num,dept_id");
        Map<Long, String> names = new HashMap<>();
        for (Map<String, Object> row : all) names.put(number(row.get("dept_id")), Objects.toString(row.get("dept_name"), ""));
        Set<Long> allowed = new LinkedHashSet<>();
        if (context.deptIds() != null) allowed.addAll(context.deptIds());
        if (context.deptId() != null) allowed.add(context.deptId());
        String key = clean(keyword);
        List<Map<String, Object>> result = new ArrayList<>();
        for (Map<String, Object> row : all) {
            Long id = number(row.get("dept_id"));
            String name = Objects.toString(row.get("dept_name"), "");
            if (!context.allData() && !allowed.contains(id)) continue;
            if (key != null && !name.contains(key)) continue;
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("deptId", id);
            item.put("deptName", name);
            item.put("parentId", number(row.get("parent_id")));
            List<String> path = new ArrayList<>();
            for (String value : Objects.toString(row.get("ancestors"), "").split(",")) {
                try { String parent = names.get(Long.parseLong(value)); if (parent != null) path.add(parent); }
                catch (NumberFormatException ignored) { }
            }
            path.add(name);
            item.put("deptPath", String.join(" / ", path));
            result.add(item);
        }
        return result;
    }

    public String stationName(Long id) {
        return id == null ? null : stations.findById(id).map(EnergyAttributionStation::getName).orElse(null);
    }

    public String departmentName(Long id) {
        if (id == null) return null;
        List<String> names = jdbc.queryForList("select dept_name from sys_dept where dept_id=?", String.class, id);
        return names.isEmpty() ? null : names.get(0);
    }

    private void applyStation(EnergyAttributionStation station, EnergyAttributionStation request) {
        String name = clean(request.getName());
        String lineName = clean(request.getLineName());
        String branchCompany = clean(request.getBranchCompany());
        if (name == null) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "请输入站点/区间名称");
        requireDictValue("shuohuang_railway_line", lineName, true, "所属线路");
        requireDictValue("energy_allocation", branchCompany, false, "所属分公司");
        if (stations.countDuplicate(name, lineName, branchCompany, station.getId()) > 0) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "相同线路和分公司下已存在同名能耗归属站点");
        }
        station.setName(name);
        station.setPinyinCode(PinyinUtils.generatePinyinCode(name));
        station.setLineName(lineName);
        station.setBranchCompany(branchCompany);
    }

    private void requireDictValue(String code, String value, boolean nullable, String label) {
        if (value == null && nullable) return;
        if (value == null) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "请选择" + label);
        DataDict dict = dicts.findByDictCode(code)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.BAD_REQUEST, label + "字典不存在"));
        Optional<DataDictItem> item = dictItems.findByDictIdAndItemValue(dict.getId(), value);
        if (item.isEmpty() || !Integer.valueOf(1).equals(item.get().getStatus())) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, label + "不在有效字典范围内");
        }
    }

    private String clean(String value) { return value == null || value.isBlank() ? null : value.trim(); }
    private Long number(Object value) { return value instanceof Number n ? n.longValue() : Long.valueOf(value.toString()); }
}
