package com.ruoyi.carbon.report.mapper;

import java.util.Date;
import java.util.List;
import org.apache.ibatis.annotations.Param;
import com.ruoyi.carbon.report.domain.CalculationCandidate;
import com.ruoyi.carbon.report.domain.CalculationNodeDataRow;
import com.ruoyi.carbon.report.domain.MonthlyCollectionActivityRow;
import com.ruoyi.carbon.report.domain.DefaultFactorRow;
import com.ruoyi.carbon.report.domain.FactorTemplateLink;
import com.ruoyi.carbon.report.domain.FossilFactorRow;

public interface EmissionCalculationMapper
{
    CalculationCandidate selectTask(@Param("id") Long id);
    List<CalculationCandidate> selectCompanyCandidates(@Param("companyDeptId") Long companyDeptId,
            @Param("periodStart") Date periodStart, @Param("periodEnd") Date periodEnd);
    List<CalculationCandidate> selectCandidates(
            @Param("subjectNodeId") Long subjectNodeId,
            @Param("periodStart") Date periodStart,
            @Param("periodEnd") Date periodEnd);

    default List<CalculationNodeDataRow> selectNodeData(Long calculationTemplateId) {
        return selectNodeDataCompatible(calculationTemplateId, selectAttributionTables());
    }

    /** Introspection prevents referencing newer columns on a legacy deployment. */
    java.util.Set<String> selectAttributionTables();
    List<CalculationNodeDataRow> selectNodeDataCompatible(@Param("calculationTemplateId") Long calculationTemplateId,
            @Param("attributionTables") java.util.Set<String> attributionTables);

    /** Compatibility overload retained for older integrations; the SQL returns all rows and Java filters them. */
    @Deprecated
    default List<CalculationNodeDataRow> selectNodeData(Long calculationTemplateId, String energyAllocation) {
        return selectNodeData(calculationTemplateId);
    }

    FactorTemplateLink selectFactorTemplateLink(@Param("calculationTemplateId") Long calculationTemplateId);

    List<DefaultFactorRow> selectDefaultFactors(@Param("templateId") Long templateId);

    FossilFactorRow selectFossilFactor(@Param("id") Long id);

    List<MonthlyCollectionActivityRow> selectMonthlyCollection(@Param("year") int year,
            @Param("startMonth") int startMonth, @Param("endMonth") int endMonth,
            @Param("electricIds") List<Long> electricIds, @Param("fossilIds") List<Long> fossilIds,
            @Param("heatIds") List<Long> heatIds);

    List<MonthlyCollectionActivityRow> selectMonthlyCollectionBetween(@Param("startYear") int startYear,
            @Param("startMonth") int startMonth, @Param("endYear") int endYear, @Param("endMonth") int endMonth,
            @Param("electricIds") List<Long> electricIds, @Param("fossilIds") List<Long> fossilIds,
            @Param("heatIds") List<Long> heatIds);
}
