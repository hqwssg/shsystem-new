package com.ruoyi.carbon.report.generation;

import org.junit.jupiter.api.Test;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import static org.junit.jupiter.api.Assertions.assertFalse;

class ReportDefaultImageSeederTest
{
    @Test
    void doesNotRecreateRetiredOrUnconfirmedImagesOnNormalStartup()
    {
        try (AnnotationConfigApplicationContext context = new AnnotationConfigApplicationContext())
        {
            // No dependencies are needed because normal startup must skip this legacy importer.
            context.register(ReportDefaultImageSeeder.class);
            context.refresh();
            assertFalse(context.containsBean("reportDefaultImageSeeder"));
        }
    }
}
