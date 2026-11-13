package com.ruoyi.carbon.report.source;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import com.ruoyi.carbon.report.domain.dto.ReportDraft;

public final class ReportValidator
{
    private ReportValidator()
    {
    }

    public static Map<String, Object> validate(ReportDraft draft)
    {
        List<String> mustFix = new ArrayList<>();
        List<String> shouldConfirm = new ArrayList<>();
        boolean missingWorkload = draft == null || draft.getWorkloadCount() <= 0;
        if (missingWorkload)
        {
            shouldConfirm.add("工作量未填写，允许生成报告；不按 0 补齐，不计算排放强度");
        }
        int activity = draft == null ? 0
                : draft.getFuels().size() + draft.getElectricity().size() + draft.getHeat().size();
        if (activity == 0)
        {
            mustFix.add("缺少自动带入的活动数据");
        }
        mustFix.addAll(ReportSourceSnapshot.problems(draft));
        if (draft != null && draft.getTask() != null) {
            mustFix.addAll(ReportComparisonService.problems(draft.getTask()));
            if (ReportPeriodSnapshot.enabled(draft.getTask())) {
                try {
                    com.alibaba.fastjson2.JSONObject period = ReportPeriodSnapshot.saved(draft.getTask());
                    ReportPeriodSnapshot.requireDates(draft.getTask(), period);
                    com.alibaba.fastjson2.JSONObject source = ReportSourceSnapshot.saved(draft.getTask());
                    if (source != null && (!period.getString("start").equals(source.getString("cycleStart"))
                            || !period.getString("end").equals(source.getString("cycleEnd"))))
                        mustFix.add("报告期间与带入的核算来源期间不同，请新建报告");
                } catch (com.ruoyi.common.core.exception.ServiceException ex) { mustFix.add(ex.getMessage()); }
            }
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("mustFix", mustFix);
        result.put("shouldConfirm", shouldConfirm);
        result.put("missingWorkload", missingWorkload);
        result.put("ok", mustFix.isEmpty());
        return result;
    }
}
