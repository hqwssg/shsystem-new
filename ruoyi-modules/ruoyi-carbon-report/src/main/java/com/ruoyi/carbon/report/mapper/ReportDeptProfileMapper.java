package com.ruoyi.carbon.report.mapper;

import org.apache.ibatis.annotations.Param;
import com.ruoyi.carbon.report.domain.ReportDeptProfile;

public interface ReportDeptProfileMapper
{
    ReportDeptProfile selectByDeptId(Long deptId);

    Long selectDeptIdByEntityCode(@Param("entityCode") String entityCode);

    int insert(ReportDeptProfile profile);

    int update(ReportDeptProfile profile);

    int updateActivityProse(@Param("deptId") Long deptId, @Param("proseJson") String proseJson,
            @Param("updateBy") String updateBy);
}
