package com.ruoyi.carbon.report.generation;

import java.nio.file.Path;

public interface ReportRenderer
{
    RenderResult generateDocx(String snapshotJson, boolean aiEnabled, Path outputPath);

    default RenderResult generateDocx(String snapshotJson, boolean aiEnabled, Path outputPath, LlmRuntimeConfig config)
    {
        return generateDocx(snapshotJson, aiEnabled, outputPath);
    }

    default void testLlmConnection(LlmRuntimeConfig config)
    {
        throw new UnsupportedOperationException("当前报告渲染器不支持 AI 连通性检查");
    }

    RenderResult convertPdf(Path docxPath, Path outputPath);
}
