package com.ruoyi.carbon.report.mapper;

import java.util.List;
import org.apache.ibatis.annotations.Param;
import com.ruoyi.carbon.report.domain.ReportTask;

public interface ReportTaskMapper
{
    ReportTask selectById(Long id);

    List<ReportTask> selectByDeptId(Long deptId);

    List<ReportTask> selectList(ReportTask query);

    int insert(ReportTask task);

    Long lockCreationCompany(Long deptId);
    ReportTask selectCreationRequest(@Param("deptId") Long deptId, @Param("username") String username, @Param("requestKey") String requestKey);

    int update(ReportTask task);

    int updateWithVersion(ReportTask task);

    int markDeleted(ReportTask task);

    int markGenerated(@Param("id") Long id, @Param("deptId") Long deptId);
}
