package com.example.carbon.emission.model.service;

import com.example.carbon.emission.model.dto.UncertaintyReportDto;

/**
 * 不确定性分析报告生成 Service（O5）
 * <p>
 * 按 runId 聚合单次模拟运行的全部落库输出（运行记录 O3/O4、
 * Scope 级完整性 O7、参数级结果 O1），生成全量章节报告，
 * 支持 JSON 结构化响应与 PDF 文件导出。
 */
public interface UncertaintyReportService {

    /**
     * 生成单次模拟运行的不确定性报告（全量章节）
     *
     * @param runId 模拟运行ID
     * @return 不确定性报告
     * @throws IllegalArgumentException 运行记录不存在
     * @throws IllegalStateException    运行未成功完成（status 非 SUCCESS）
     */
    UncertaintyReportDto getReport(Long runId);

    /**
     * 生成单次模拟运行的不确定性报告 PDF 字节流
     *
     * @param runId 模拟运行ID
     * @return PDF 文件字节数组
     * @throws IllegalArgumentException 运行记录不存在
     * @throws IllegalStateException    运行未成功完成（status 非 SUCCESS）
     * @throws RuntimeException         PDF 渲染失败
     */
    byte[] getReportPdf(Long runId);
}
