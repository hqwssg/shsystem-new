package com.ruoyi.carbon.energy.service;

import java.io.InputStream;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import org.springframework.web.multipart.MultipartFile;
import com.alibaba.fastjson2.JSONObject;

public interface IEnergyService
{
    List<Map<String, Object>> listBindings(Long deptId);

    Map<String, Object> bindProject(Long deptId, String projectCode, String username);

    List<Map<String, Object>> listVersions(Long deptId);

    List<Map<String, Object>> listVersionFiles(Long deptId, String projectCode, String versionCode);

    Map<String, Object> parameterPreset(Long deptId, String projectCode, String versionCode, String runType);

    JSONObject publishVersion(Long deptId, String username, String projectCode, String projectName, String routeName,
            String versionCode, String dataStatus, String sourceNote, List<MultipartFile> files, List<String> relativePaths);

    JSONObject publishExcelVersion(Long deptId, String username, String projectCode, String projectName, String routeName,
            String versionCode, String dataStatus, String sourceNote, String baseProjectCode, String baseVersionCode,
            List<MultipartFile> files);

    List<Map<String, Object>> listExcelTemplates();

    Path excelTemplateFile(String code);

    byte[] excelTemplateZip();

    JSONObject versionTables(Long deptId, String projectCode, String versionCode, String topic, String sheet);

    JSONObject replaceVersionTables(Long deptId, String projectCode, String versionCode, String topic,
            String sourceNote, Object sheets);

    List<Map<String, Object>> listRuns(Long deptId, String runType, String status);

    JSONObject createRun(Long deptId, String username, String projectCode, String versionCode, String runType,
            String parametersJson, String idempotencyKey);

    Map<String, Object> getRun(Long deptId, String runId);

    JSONObject cancelRun(Long deptId, String runId, String reason);

    JSONObject deleteRun(Long deptId, String runId);

    Map<String, Object> storagePlanning(Long deptId, String runId, String planId, int pageNum, int pageSize);

    Map<String, Object> summary(Long deptId, String runId);

    Map<String, Object> timetable(Long deptId, String runId);

    Map<String, Object> optimization(Long deptId, String runId);

    Map<String, Object> rolling(Long deptId, String runId);

    Map<String, Object> robustness(Long deptId, String runId);

    List<Map<String, Object>> artifacts(Long deptId, String runId);

    Map<String, Object> downloadMeta(Long deptId, String runId, String relativePath);

    InputStream downloadStream(Long deptId, String runId, String relativePath);

    Path resolveUploadRoot();
}
