package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.MonthlyCalcNodeSummary;
import com.example.carbon.emission.model.entity.MonthlyCollectionNodeData;
import com.example.carbon.emission.model.entity.MonthlyCompanyEnergySummary;

import java.time.YearMonth;
import java.util.List;

/** 三张月度表的一次完整候选版本。 */
public record MonthlyPublicationPlan(Long templateId,
                                     Long companyDeptId,
                                     boolean baselineTemplate,
                                     List<YearMonth> months,
                                     List<MonthlyCollectionNodeData> collectionRows,
                                     List<MonthlyCalcNodeSummary> nodeRows,
                                     List<MonthlyCompanyEnergySummary> companyRows) {
    public MonthlyPublicationPlan {
        months = List.copyOf(months);
        collectionRows = List.copyOf(collectionRows);
        nodeRows = List.copyOf(nodeRows);
        companyRows = List.copyOf(companyRows);
    }

    public int totalRows() {
        return collectionRows.size() + nodeRows.size() + companyRows.size();
    }
}
