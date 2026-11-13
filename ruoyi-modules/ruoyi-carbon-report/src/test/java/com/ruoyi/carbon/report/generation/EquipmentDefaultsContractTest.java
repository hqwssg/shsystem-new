package com.ruoyi.carbon.report.generation;

import static org.junit.jupiter.api.Assertions.*;
import java.nio.file.*;
import java.util.Map;
import org.junit.jupiter.api.Test;
import com.alibaba.fastjson2.*;
import com.ruoyi.carbon.report.domain.*;
import com.ruoyi.carbon.report.domain.dto.ReportDraft;

class EquipmentDefaultsContractTest {
    @Test void defaultsKeepEverySourceRowAndUnknownQuantities() throws Exception {
        Path root=Path.of(System.getProperty("user.dir")).toAbsolutePath();
        while(root!=null && !Files.exists(root.resolve("scripts/report-compat/equipment/equipment-defaults.json")))root=root.getParent();
        assertNotNull(root);
        JSONArray companies=JSON.parseObject(Files.readString(root.resolve("scripts/report-compat/equipment/equipment-defaults.json"))).getJSONArray("companies");
        Map<String,Integer> counts=Map.of("suning",9,"yuanping",4,"jiliang",57);
        Map<String,Integer> missing=Map.of("suning",1,"yuanping",0,"jiliang",6);
        for(Object entry:companies) {
            JSONObject source=(JSONObject)entry;String key=source.getString("company_key");
            ReportDraft draft=new ReportDraft();ReportTask task=new ReportTask();task.setReportYear(2025);task.setPeriodType("YEAR");draft.setTask(task);
            ReportDeptProfile profile=new ReportDeptProfile();profile.setEntityCode(key);profile.setDefaultEquipmentJson(source.getJSONArray("equipment").toJSONString());
            JSONArray rows=JSON.parseObject(new ReportSnapshotAssembler().assemble(draft,profile,Map.of())).getJSONArray("equipment");
            assertEquals(counts.get(key),rows.size());
            assertEquals(missing.get(key).longValue(),rows.stream().filter(r->((JSONObject)r).getBigDecimal("quantity")==null).count());
            if("jiliang".equals(key)) {
                assertEquals("SS4B",rows.getJSONObject(0).getString("model"));
                assertEquals(87,rows.getJSONObject(0).getIntValue("quantity"));
            }
        }
    }

    @Test void manuallySavedRowsOverrideHistoricalDefaultsAndPreserveNullQuantity() {
        ReportDraft draft=new ReportDraft();ReportTask task=new ReportTask();task.setReportYear(2025);draft.setTask(task);
        ReportEquipment equipment=new ReportEquipment();equipment.setName("本期人工设备");draft.getEquipment().add(equipment);
        ReportDeptProfile profile=new ReportDeptProfile();profile.setDefaultEquipmentJson("[{\"name\":\"历史设备\",\"quantity\":87}]");
        JSONArray rows=JSON.parseObject(new ReportSnapshotAssembler().assemble(draft,profile,Map.of())).getJSONArray("equipment");
        assertEquals(1,rows.size());assertEquals("本期人工设备",rows.getJSONObject(0).getString("name"));
        assertNull(rows.getJSONObject(0).getBigDecimal("quantity"));
    }
}
