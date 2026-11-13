package com.example.carbon.emission.model.controller;

import com.example.carbon.emission.model.security.UncertaintyAuthorizationFilter;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Import;
import org.springframework.mock.web.MockServletContext;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.client.RestClient;
import org.springframework.web.context.support.AnnotationConfigWebApplicationContext;
import org.springframework.web.servlet.config.annotation.EnableWebMvc;
import org.springframework.web.servlet.config.annotation.ResourceHandlerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;
import static org.hamcrest.Matchers.containsString;

/** Exercises the actual static page and API filter without connecting to a database. */
class UncertaintyPageRouteTest {
    @Configuration
    @EnableWebMvc
    @Import(GlobalExceptionHandler.class)
    static class MvcConfiguration implements WebMvcConfigurer {
        @Override
        public void addResourceHandlers(ResourceHandlerRegistry registry) {
            registry.addResourceHandler("/**").addResourceLocations("classpath:/static/");
        }
    }

    @Test
    void wizardAndProtectedApiUseTheDeploymentProbeRoutes() throws Exception {
        try (var context = new AnnotationConfigWebApplicationContext()) {
            context.setServletContext(new MockServletContext());
            context.register(MvcConfiguration.class);
            context.refresh();
            MockMvc mvc = MockMvcBuilders.webAppContextSetup(context)
                    .addFilter(new UncertaintyAuthorizationFilter(RestClient.builder(),
                            new ObjectMapper(), "http://127.0.0.1:1/unused", true))
                    .build();
            mvc.perform(get("/uncertainty-wizard.html"))
                    .andExpect(status().isOk())
                    .andExpect(content().string(containsString("DQI+MCS")));
            mvc.perform(get("/api/uncertainty/calculation-tasks"))
                    .andExpect(status().isUnauthorized());
        }
    }
}
