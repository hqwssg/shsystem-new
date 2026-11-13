package com.ruoyi.carbon.report.source;

import java.time.LocalDate;
import java.time.format.DateTimeParseException;
import java.util.Date;
import java.util.List;
import java.util.Objects;
import java.util.Comparator;
import com.alibaba.fastjson2.JSON;
import com.alibaba.fastjson2.JSONObject;
import com.ruoyi.carbon.report.domain.CalculationCandidate;
import com.ruoyi.carbon.report.domain.CalculationNodeDataRow;
import com.ruoyi.carbon.report.domain.ReportTask;
import com.ruoyi.carbon.report.domain.dto.CreateReportRequest;
import com.ruoyi.carbon.report.domain.dto.PrefillResult;
import com.ruoyi.carbon.report.generation.SnapshotHasher;
import com.ruoyi.common.core.exception.ServiceException;

/** Versioned period contract. Absence of the marker deliberately means legacy behavior. */
public final class ReportPeriodSnapshot
{
    public static final String KEY = "_report_period";
    private ReportPeriodSnapshot() { }

    public static JSONObject saved(ReportTask task) {
        if (task == null) return null;
        JSONObject value = ReportSourceSnapshot.metadata(task).getJSONObject(KEY);
        return value != null && value.getIntValue("version") == 1 ? value : null;
    }
    public static boolean enabled(ReportTask task) { return saved(task) != null; }
    public static String date(Date value) {
        return value == null ? null : new java.text.SimpleDateFormat("yyyy-MM-dd").format(value);
    }
    public static LocalDate parse(String value) {
        try {
            LocalDate d = LocalDate.parse(value);
            if (d.getYear() < 2000 || d.getYear() > 2100) throw new IllegalArgumentException();
            return d;
        } catch (DateTimeParseException | NullPointerException ex) {
            throw new ServiceException("请选择有效的起止日期（2000 至 2100 年）", 400);
        } catch (IllegalArgumentException ex) {
            throw new ServiceException("报告期间须在 2000 至 2100 年内", 400);
        }
    }
    public static String classify(LocalDate start, LocalDate end) {
        if (start.isAfter(end)) throw new ServiceException("报告开始日期不能晚于结束日期", 400);
        if (start.equals(LocalDate.of(start.getYear(), 1, 1)) && end.equals(LocalDate.of(start.getYear(), 12, 31))) return "YEAR";
        if (start.getDayOfMonth() == 1 && end.equals(start.withDayOfMonth(start.lengthOfMonth()))) return "MONTH";
        return "RANGE";
    }
    public static void initialize(ReportTask task, CreateReportRequest request, CalculationCandidate source, String companyName) {
        String mode = request.getPeriodMode();
        if (!"CALCULATION".equals(mode) && !"MANUAL".equals(mode)) throw new ServiceException("报告期间模式无效", 400);
        if ("CALCULATION".equals(mode) && source == null) throw new ServiceException("请选择成功核算任务", 400);
        if ("MANUAL".equals(mode) && request.getCalculationTemplateId() != null) throw new ServiceException("空白报告不能同时绑定核算任务", 400);
        String start = source == null ? request.getPeriodStart() : date(source.getCycleStart());
        String end = source == null ? request.getPeriodEnd() : date(source.getCycleEnd());
        if (source != null && ((request.getPeriodStart() != null && !Objects.equals(start,request.getPeriodStart()))
                || (request.getPeriodEnd() != null && !Objects.equals(end,request.getPeriodEnd()))))
            throw new ServiceException("报告期间必须与选中核算任务一致", 400);
        LocalDate a = parse(start), b = parse(end);
        String kind = classify(a, b);
        task.setPeriodType(kind); task.setPeriodStart(java.sql.Date.valueOf(a)); task.setPeriodEnd(java.sql.Date.valueOf(b));
        task.setReportYear(b.getYear()); task.setReportMonth("MONTH".equals(kind) ? a.getMonthValue() : null);
        String name = source == null ? companyName : source.getTemplateName();
        if (name == null || name.isBlank()) throw new ServiceException("报告公司或模板名称缺失", 400);
        String title = name + "（" + start + "至" + end + "）碳排放报告";
        if (title.length() > 255) throw new ServiceException("报告名称过长，请缩短模板名称后重新创建", 400);
        task.setTitle(title); task.setDeptName(companyName);
        if (source != null) task.setEmissionTemplateId(source.getTemplateId());
        JSONObject period = new JSONObject();
        period.put("version", 1); period.put("mode", mode); period.put("start", start); period.put("end", end);
        period.put("companyName", companyName); period.put("templateName", source == null ? "" : name);
        period.put("calculationTaskId", source == null ? null : source.getId());
        period.put("templateId", source == null ? null : source.getTemplateId());
        period.put("confirmedCompanyId", source == null ? null : source.getCompanyDeptId());
        JSONObject meta = ReportSourceSnapshot.metadata(task); meta.put(KEY, period); task.setMetadataJson(meta.toJSONString());
    }
    public static void requireSelection(ReportTask task, Long id, CalculationCandidate candidate) {
        JSONObject period = saved(task);
        if (period == null) return;
        requireDates(task, period);
        if (!"CALCULATION".equals(period.getString("mode")) || !Objects.equals(id, period.getLong("calculationTaskId")))
            throw new ServiceException("本报告的核算来源和期间已固定；更换来源请新建报告", 400);
        if (candidate == null || !candidate.isSuccess()
                || !Objects.equals(period.getLong("templateId"), candidate.getTemplateId())
                || !Objects.equals(period.getLong("confirmedCompanyId"), candidate.getCompanyDeptId())
                || !Objects.equals(period.getString("start"), date(candidate.getCycleStart()))
                || !Objects.equals(period.getString("end"), date(candidate.getCycleEnd())))
            throw new ServiceException("核算来源期间已变化，请保留草稿并重新创建报告", 409);
    }
    public static void requireDates(ReportTask task, JSONObject period) {
        if (!Objects.equals(period.getString("start"), date(task.getPeriodStart()))
                || !Objects.equals(period.getString("end"), date(task.getPeriodEnd())))
            throw new ServiceException("报告期间与冻结记录不一致", 409);
        LocalDate start = parse(period.getString("start")), end = parse(period.getString("end"));
        String kind = classify(start, end);
        if (!kind.equals(task.getPeriodType()) || !Objects.equals(task.getReportYear(), end.getYear())
                || ("MONTH".equals(kind) && !Objects.equals(task.getReportMonth(), start.getMonthValue())))
            throw new ServiceException("报告期间类型与冻结记录不一致", 409);
    }
    public static void freezeSource(ReportTask task, PrefillResult result) {
        JSONObject period = saved(task);
        if (period == null) return;
        period.put("sourceSignature", result.getSourceSignature()); period.put("scopeSignature", result.getScopeSignature());
        JSONObject meta = ReportSourceSnapshot.metadata(task); meta.put(KEY, period); task.setMetadataJson(meta.toJSONString());
    }
    /** Excludes live template/config factors: editing a template must not alter old task evidence. */
    public static String sourceSignature(List<CalculationNodeDataRow> rows) {
        List<Object> values = rows.stream().sorted(Comparator.comparing(CalculationNodeDataRow::getId,
                Comparator.nullsFirst(Comparator.naturalOrder()))).map(r -> (Object) java.util.Arrays.asList(
                r.getId(), r.getCollectionPointType(), r.getCollectionPointId(), r.getEnergyAllocation(),
                r.getEmissionCategory(), r.getEmissionSubcategory(), r.getMeasurementUnit(),
                number(r.preferredEnergyValue()), number(r.preferredCarbonValue()),
                r.getAdjustedEnergyValue() == null ? "RAW" : "ADJUSTED", number(r.getCarbonEmissionFactor()),
                r.getCarbonEmissionFactorUnit(), r.getCarbonEmissionUnit(), r.getDataStatus(), r.getDataMissingDescription())).toList();
        // Preserve legacy signatures exactly when all rows use the legacy field.
        if (rows.stream().anyMatch(r -> r.getAttributionDeptId() != null)) {
            List<Object> ownership = rows.stream().sorted(Comparator.comparing(CalculationNodeDataRow::getId,
                Comparator.nullsFirst(Comparator.naturalOrder()))).map(r -> (Object) java.util.Arrays.asList(
                    r.getId(), r.getAttributionDeptId(), r.getAttributionCompanyDeptId())).toList();
            return SnapshotHasher.sha256(JSON.toJSONString(java.util.Arrays.asList(values, ownership)));
        }
        return SnapshotHasher.sha256(JSON.toJSONString(values));
    }
    public static String scopeSignature(List<CalculationNodeDataRow> rows, java.util.Set<String> allocations) {
        return scopeSignature(rows, null, allocations);
    }
    public static String scopeSignature(List<CalculationNodeDataRow> rows, Long company, java.util.Set<String> allocations) {
        List<String> keys = rows.stream().filter(r -> ReportMeterOwnership.decide(company, allocations, r)
                == ReportMeterOwnership.Decision.ACCEPT)
            .map(r -> r.getCollectionPointId() == null || r.getCollectionPointType() == null ? "UNKNOWN"
                : r.getCollectionPointType() + ":" + r.getCollectionPointId() + ":"
                  + ActivityClassifier.canonical(r.getEmissionSubcategory(), r.getMeasurementUnit()) + ":"
                  + (r.getAdjustedEnergyValue() == null ? "RAW" : "ADJUSTED"))
            .distinct().sorted().toList();
        return keys.isEmpty() || keys.contains("UNKNOWN") ? null : SnapshotHasher.sha256(JSON.toJSONString(keys));
    }
    private static String number(java.math.BigDecimal value) { return value == null ? null : value.stripTrailingZeros().toPlainString(); }
    public static String fileName(String title, String extension) {
        String safe = title == null ? "报告" : title.replaceAll("[\\\\/:*?\"<>|\\p{Cntrl}]", "_").replaceAll("[. ]+$", "");
        return (safe.isBlank() ? "报告" : safe) + "." + extension;
    }
}
