package com.ruoyi.carbon.report.source;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import org.springframework.stereotype.Service;
import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONObject;
import com.ruoyi.carbon.report.domain.CalculationCandidate;
import com.ruoyi.carbon.report.domain.CalculationNodeDataRow;
import com.ruoyi.carbon.report.domain.ReportDeptSubject;
import com.ruoyi.carbon.report.domain.ReportTask;
import com.ruoyi.carbon.report.domain.dto.PrefillLine;
import com.ruoyi.carbon.report.domain.dto.PrefillResult;
import com.ruoyi.carbon.report.generation.SnapshotHasher;
import com.ruoyi.carbon.report.mapper.EmissionCalculationMapper;
import com.ruoyi.carbon.report.mapper.ReportDeptSubjectMapper;
import com.ruoyi.common.core.exception.ServiceException;

/** Exact calendar comparison periods, explicit selection, and immutable adopted totals. */
@Service
public class ReportComparisonService
{
    private final EmissionCalculationMapper calculations;
    private final ReportDeptSubjectMapper subjects;
    public ReportComparisonService(EmissionCalculationMapper calculations, ReportDeptSubjectMapper subjects) {
        this.calculations = calculations; this.subjects = subjects;
    }
    public JSONObject candidates(ReportTask task) {
        JSONObject out = new JSONObject();
        if (!ReportPeriodSnapshot.enabled(task) || "RANGE".equals(task.getPeriodType())) return out;
        LocalDate start = ReportPeriodSnapshot.parse(ReportPeriodSnapshot.date(task.getPeriodStart()));
        LocalDate end = ReportPeriodSnapshot.parse(ReportPeriodSnapshot.date(task.getPeriodEnd()));
        out.put("yoy", slot(task, start.minusYears(1), "MONTH".equals(task.getPeriodType())
                ? start.minusYears(1).withDayOfMonth(start.minusYears(1).lengthOfMonth()) : end.minusYears(1)));
        if ("MONTH".equals(task.getPeriodType())) {
            LocalDate prev = start.minusMonths(1);
            out.put("mom", slot(task, prev, prev.withDayOfMonth(prev.lengthOfMonth())));
        }
        return out;
    }
    private JSONObject slot(ReportTask task, LocalDate start, LocalDate end) {
        JSONObject out = new JSONObject(); out.put("start", start.toString()); out.put("end", end.toString());
        List<JSONObject> options = new ArrayList<>(); out.put("candidates", options);
        ReportDeptSubject current = subjects.selectByDeptId(task.getDeptId());
        ReportDeptSubject subject = ReportSubjectSnapshot.resolve(task, current);
        Set<String> allocations = ReportAllocationScope.accepted(task.getDeptId(), subject, current,
                subjects.selectCompanies(new ReportDeptSubject()));
        String scope = ReportPeriodSnapshot.saved(task).getString("scopeSignature");
        if (scope == null) return out; // Blank/manual reports can still enter a labelled manual baseline.
        for (CalculationCandidate candidate : ReportCalculationSelection.companyCandidates(calculations,
                task.getDeptId(), subject.getSubjectNodeId(), java.sql.Date.valueOf(start), java.sql.Date.valueOf(end))) {
            if (!task.getDeptId().equals(candidate.getCompanyDeptId())
                || !start.toString().equals(ReportPeriodSnapshot.date(candidate.getCycleStart()))
                || !end.toString().equals(ReportPeriodSnapshot.date(candidate.getCycleEnd()))) continue;
            List<CalculationNodeDataRow> rows = calculations.selectNodeData(candidate.getId());
            if (rows == null || !scope.equals(ReportPeriodSnapshot.scopeSignature(rows, task.getDeptId(), allocations))) continue;
            PrefillResult result = new PrefillAssembler(new ReportUnitConverter()).assembleForCompany(task.getDeptId(), allocations, rows);
            if (result.getLineCount() == 0 || !result.getGaps().isEmpty() || result.getIssues().stream().anyMatch(i -> Boolean.TRUE.equals(i.get("blocking")))) continue;
            JSONObject values = totals(result);
            JSONObject option = new JSONObject();
            option.put("taskId", candidate.getId()); option.put("templateName", candidate.getTemplateName());
            option.put("finishedAt", candidate.getFinishedAt()); option.put("values", values);
            option.put("sourceSignature", ReportPeriodSnapshot.sourceSignature(rows));
            option.put("selectionHash", SnapshotHasher.sha256(option.toJSONString() + context(task)));
            options.add(option);
        }
        return out;
    }
    public String save(ReportTask task, String payload) {
        JSONObject input = payload == null ? new JSONObject() : JSON.parseObject(payload);
        if ("RANGE".equals(task.getPeriodType())) {
            if (!input.isEmpty()) throw new ServiceException("非标准期间不自动进行同比或环比", 400);
            return null;
        }
        JSONObject slots = candidates(task);
        JSONObject previous = task.getPriorYearJson() == null ? new JSONObject() : JSON.parseObject(task.getPriorYearJson());
        JSONObject yoy = adopt(task, input.getJSONObject("yoy"), slots.getJSONObject("yoy"),
                "MONTH".equals(task.getPeriodType()) ? previous.getJSONObject("yoy") : previous);
        if (!"MONTH".equals(task.getPeriodType())) return yoy == null ? null : yoy.toJSONString();
        JSONObject mom = adopt(task, input.getJSONObject("mom"), slots.getJSONObject("mom"), previous.getJSONObject("mom"));
        JSONObject out = new JSONObject(); if (yoy != null) out.put("yoy", yoy); if (mom != null) out.put("mom", mom);
        return out.isEmpty() ? null : out.toJSONString();
    }
    private JSONObject adopt(ReportTask task, JSONObject input, JSONObject slot, JSONObject previous) {
        if (input == null || input.getString("mode") == null || "NONE".equals(input.getString("mode"))) return null;
        if ("KEEP".equals(input.getString("mode"))) {
            JSONObject evidence = previous == null ? null : previous.getJSONObject("_comparison");
            if (evidence == null || !context(task).equals(evidence.getString("contextHash")))
                throw new ServiceException("对比口径已变化，请重新确认基准", 409);
            return new JSONObject(previous);
        }
        JSONObject values;
        JSONObject evidence = new JSONObject();
        if ("TASK".equals(input.getString("mode"))) {
            JSONObject selected = null;
            for (Object obj : slot.getJSONArray("candidates")) {
                JSONObject option = (JSONObject) obj;
                if (Objects.equals(option.getLong("taskId"), input.getLong("taskId"))) selected = option;
            }
            if (selected == null || !Objects.equals(selected.getString("selectionHash"), input.getString("selectionHash")))
                throw new ServiceException("对比来源已变化或不符合期间/边界口径，请重新选择基准", 409);
            values = new JSONObject(selected.getJSONObject("values"));
            evidence.put("taskId", selected.getLong("taskId")); evidence.put("templateName", selected.getString("templateName"));
            evidence.put("sourceSignature", selected.getString("sourceSignature"));
            evidence.put("finishedAt", selected.get("finishedAt"));
        } else if ("MANUAL".equals(input.getString("mode"))) {
            if (input.get("total_emissions_tco2") == null || "".equals(input.get("total_emissions_tco2"))) return null;
            values = new JSONObject();
            for (String key : List.of("total_emissions_tco2","fuel_combustion_tco2","electricity_emissions_tco2","heat_emissions_tco2")) {
                if (input.get(key) == null || "".equals(input.get(key))) continue;
                try {
                    BigDecimal n = new BigDecimal(String.valueOf(input.get(key)));
                    if (n.signum() < 0) throw new NumberFormatException();
                    values.put(key, n);
                } catch (NumberFormatException ex) { throw new ServiceException("对比数值须为非负数，缺失请留空", 400); }
            }
        } else throw new ServiceException("对比来源模式无效", 400);
        LocalDate start = LocalDate.parse(slot.getString("start"));
        values.put("report_year", start.getYear());
        if ("MONTH".equals(task.getPeriodType())) values.put("report_month", start.getMonthValue());
        evidence.put("mode", input.getString("mode")); evidence.put("start", slot.getString("start")); evidence.put("end", slot.getString("end"));
        evidence.put("contextHash", context(task)); values.put("_comparison", evidence);
        return values;
    }
    private static JSONObject totals(PrefillResult result) {
        JSONObject values = new JSONObject(); BigDecimal total = BigDecimal.ZERO;
        List<List<PrefillLine>> groups = List.of(result.getFuels(), result.getElectricity(), result.getHeat());
        List<String> keys = List.of("fuel_combustion_tco2", "electricity_emissions_tco2", "heat_emissions_tco2");
        for (int i=0;i<groups.size();i++) {
            BigDecimal amount = groups.get(i).stream().map(PrefillLine::getCarbonEmission).reduce(BigDecimal.ZERO, BigDecimal::add);
            values.put(keys.get(i), amount); total = total.add(amount);
        }
        values.put("total_emissions_tco2", total); return values;
    }
    public static String context(ReportTask task) {
        JSONObject period = ReportPeriodSnapshot.saved(task);
        return SnapshotHasher.sha256(String.valueOf(period == null ? null : period.getString("scopeSignature"))
                + "|" + String.valueOf(task.getOrganizationBoundaryJson()) + "|" + String.valueOf(task.getEmissionBoundaryNotesJson()));
    }
    public static List<String> problems(ReportTask task) {
        if (!ReportPeriodSnapshot.enabled(task) || task.getPriorYearJson() == null) return List.of();
        JSONObject prior = JSON.parseObject(task.getPriorYearJson());
        if ("RANGE".equals(task.getPeriodType())) return prior.isEmpty() ? List.of() : List.of("期间报告不应包含自动年度/月度对比，请清除对比数据");
        List<JSONObject> entries = "MONTH".equals(task.getPeriodType())
                ? java.util.Arrays.asList(prior.getJSONObject("yoy"), prior.getJSONObject("mom")) : List.of(prior);
        for (JSONObject entry : entries) {
            if (entry == null || entry.isEmpty()) continue;
            JSONObject evidence = entry.getJSONObject("_comparison");
            if (evidence == null || !context(task).equals(evidence.getString("contextHash")))
                return List.of("报告边界或活动口径已变化，请重新保存对比基准或清除对比");
        }
        return List.of();
    }
}
