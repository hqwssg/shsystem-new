package com.railway.carbon.platform.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import java.util.Arrays;

@Configuration
public class WebConfig implements WebMvcConfigurer {

    private final PlatformProperties properties;

    public WebConfig(PlatformProperties properties) {
        this.properties = properties;
    }

    @Override
    public void addCorsMappings(CorsRegistry registry) {
        String origins = properties.cors() == null ? "*" : properties.cors().allowedOrigins();
        String[] allowed = origins == null || origins.isBlank() || "*".equals(origins)
                ? new String[]{"*"}
                : Arrays.stream(origins.split(",")).map(String::trim).toArray(String[]::new);
        registry.addMapping("/api/**")
                .allowedOrigins(allowed)
                .allowedMethods("GET", "POST", "PUT", "DELETE", "OPTIONS")
                .allowedHeaders("*")
                .allowCredentials(!"*".equals(origins))
                .maxAge(3600);
    }
}
