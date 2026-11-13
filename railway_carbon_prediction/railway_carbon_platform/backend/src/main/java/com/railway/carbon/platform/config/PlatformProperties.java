package com.railway.carbon.platform.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "platform")
public record PlatformProperties(Prediction prediction, Cors cors, Security security) {

    public record Prediction(String baseUrl, String apiKey, int timeoutSeconds) {
    }

    public record Cors(String allowedOrigins) {
    }

    public record Security(boolean enabled, String endpoint) {
    }
}
