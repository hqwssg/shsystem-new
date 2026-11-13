package com.ruoyi.carbon.report.generation;

import java.nio.file.Path;

public class RenderResult
{
    private final Path outputPath;
    private final boolean llmUsed;

    public RenderResult(Path outputPath, boolean llmUsed)
    {
        this.outputPath = outputPath;
        this.llmUsed = llmUsed;
    }

    public Path getOutputPath() { return outputPath; }
    public boolean isLlmUsed() { return llmUsed; }
}
