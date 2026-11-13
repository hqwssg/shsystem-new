package com.ruoyi.carbon.report.generation;

/** Per-request LLM settings. The API key is deliberately excluded from toString(). */
public class LlmRuntimeConfig
{
    private final String baseUrl;
    private final String model;
    private final String apiKey;

    public LlmRuntimeConfig(String baseUrl, String model, String apiKey)
    {
        this.baseUrl = baseUrl;
        this.model = model;
        this.apiKey = apiKey;
    }

    public String getBaseUrl() { return baseUrl; }
    public String getModel() { return model; }
    public String getApiKey() { return apiKey; }

    @Override
    public String toString()
    {
        return "LlmRuntimeConfig{baseUrl='" + baseUrl + "', model='" + model + "', apiKey='[REDACTED]'}";
    }
}
