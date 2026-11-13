package com.ruoyi.carbon.analysis.mapper;

import java.util.List;
import org.apache.ibatis.annotations.Param;
import com.ruoyi.carbon.analysis.domain.AnalysisCategoryOption;
import com.ruoyi.carbon.analysis.domain.AnalysisFact;
import com.ruoyi.carbon.analysis.domain.AnalysisNode;
import com.ruoyi.carbon.analysis.domain.AnalysisOrgOption;
import com.ruoyi.carbon.analysis.domain.AnalysisSubcategoryOption;

public interface AnalysisMapper
{
    List<AnalysisNode> selectNodes(@Param("rangeStart") String rangeStart, @Param("rangeEnd") String rangeEnd);

    List<AnalysisFact> selectFacts(@Param("rangeStart") String rangeStart, @Param("rangeEnd") String rangeEnd);

    List<AnalysisFact> selectDirectFacts(@Param("rangeStart") String rangeStart, @Param("rangeEnd") String rangeEnd);

    List<AnalysisOrgOption> selectOrgs();

    List<AnalysisCategoryOption> selectCategories();

    List<AnalysisSubcategoryOption> selectSubcategories();
}
