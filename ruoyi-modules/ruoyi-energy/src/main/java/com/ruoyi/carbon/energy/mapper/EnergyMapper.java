package com.ruoyi.carbon.energy.mapper;

import java.util.List;
import java.util.Map;
import org.apache.ibatis.annotations.Param;

public interface EnergyMapper
{
    int countDeptProject(@Param("deptId") Long deptId, @Param("projectCode") String projectCode);

    List<Map<String, Object>> selectDeptProjects(@Param("deptId") Long deptId);

    int insertDeptProject(Map<String, Object> row);

    List<Map<String, Object>> selectVersions(@Param("deptId") Long deptId);

    List<Map<String, Object>> selectVersionFiles(@Param("deptId") Long deptId, @Param("projectCode") String projectCode,
            @Param("versionCode") String versionCode);

    Map<String, Object> selectLatestRunParameters(@Param("deptId") Long deptId, @Param("projectCode") String projectCode,
            @Param("versionCode") String versionCode, @Param("runType") String runType);

    List<Map<String, Object>> selectStorageDevices(@Param("deptId") Long deptId, @Param("projectCode") String projectCode,
            @Param("versionCode") String versionCode);

    List<String> selectPendingRunIds();

    List<Map<String, Object>> selectRuns(@Param("deptId") Long deptId, @Param("runType") String runType, @Param("status") String status);

    Map<String, Object> selectRun(@Param("runId") String runId);

    String selectRunProjectCode(@Param("runId") String runId);

    List<Map<String, Object>> selectStateEvents(@Param("runId") String runId);

    Map<String, Object> selectAuditSummary(@Param("runId") String runId);

    Map<String, Object> selectStoragePlanningDecision(@Param("runId") String runId);
    String selectNoBuildStoragePlanId(@Param("runId") String runId);
    long countStoragePlans(@Param("runId") String runId);
    List<Map<String, Object>> selectStoragePlans(@Param("runId") String runId, @Param("offset") int offset, @Param("pageSize") int pageSize);
    Map<String, Object> selectStoragePlan(@Param("runId") String runId, @Param("planId") String planId);
    List<Map<String, Object>> selectStoragePlanDevices(@Param("planId") String planId);
    List<Map<String, Object>> selectStoragePlanScenarios(@Param("planId") String planId);

    Map<String, Object> selectDecision(@Param("runId") String runId);

    List<Map<String, Object>> selectKpis(@Param("runId") String runId);

    List<Map<String, Object>> selectRunningArcs(@Param("runId") String runId);

    List<Map<String, Object>> selectTimeSlices(@Param("runId") String runId);

    List<Map<String, Object>> selectSettlements(@Param("runId") String runId);

    List<Map<String, Object>> selectIssues(@Param("runId") String runId);

    List<Map<String, Object>> selectSuggestions(@Param("runId") String runId);

    List<Map<String, Object>> selectCandidates(@Param("runId") String runId);

    List<Map<String, Object>> selectAdjustments(@Param("runId") String runId);

    List<Map<String, Object>> selectConflicts(@Param("runId") String runId);

    List<Map<String, Object>> selectScenarioResults(@Param("runId") String runId);

    List<Map<String, Object>> selectRollingEvents(@Param("runId") String runId);

    List<Map<String, Object>> selectArtifactMeta(@Param("runId") String runId);

    Map<String, Object> selectArtifact(@Param("runId") String runId, @Param("relativePath") String relativePath);
}
