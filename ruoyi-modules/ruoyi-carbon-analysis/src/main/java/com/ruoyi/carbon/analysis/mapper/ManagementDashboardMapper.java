package com.ruoyi.carbon.analysis.mapper;

import java.util.List;
import java.util.Map;
import org.apache.ibatis.annotations.Param;

public interface ManagementDashboardMapper {
    List<Map<String, Object>> selectCompanies();
    List<Integer> selectYears();
    List<Map<String, Object>> selectTasks(@Param("start") String start, @Param("end") String end,
            @Param("companyId") Long companyId);
}
