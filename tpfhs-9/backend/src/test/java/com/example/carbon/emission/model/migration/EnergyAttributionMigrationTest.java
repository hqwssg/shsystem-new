package com.example.carbon.emission.model.migration;

import org.junit.jupiter.api.Test;

import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.junit.jupiter.api.Assertions.*;

class EnergyAttributionMigrationTest {
    @Test
    void schemaAndMigrationContainTheCompleteIdempotentCatalog() throws Exception {
        String schema = resource("schema.sql");
        String migration = resource("schema-update-20261015-energy-attribution.sql");
        for (String sql : new String[]{schema, migration}) {
            assertTrue(sql.contains("emission_energy_attribution_station"));
            assertTrue(sql.contains("'shuohuang_railway_line'"));
            assertTrue(Pattern.compile("'shuohuang'\\s*,\\s*'朔黄线'").matcher(sql).find());
            assertTrue(Pattern.compile("'huangwan'\\s*,\\s*'黄万线'").matcher(sql).find());
            assertEquals(52, seedCount(sql), "能耗归属目录必须包含文档约定的52项");
            assertTrue(sql.contains("s.line_name <=> seed.line_name"));
            assertTrue(sql.contains("s.branch_company <=> seed.branch_company"));
        }
    }

    @Test
    void migrationAddsNewFieldsWithoutRewritingLegacyAllocationData() throws Exception {
        String migration = resource("schema-update-20261015-energy-attribution.sql");
        for (String table : new String[]{"emission_meter_info", "emission_fossil_fuel_meter_info", "emission_purchased_heat_meter_info"}) {
            assertTrue(migration.contains("ALTER TABLE " + table + " ADD COLUMN energy_attribution_station_id"));
            assertTrue(migration.contains("ALTER TABLE " + table + " ADD COLUMN energy_attribution_dept_id"));
        }
        assertFalse(Pattern.compile("(?i)update\\s+emission_(meter|fossil_fuel_meter|purchased_heat_meter)_info").matcher(migration).find());
        assertFalse(Pattern.compile("(?i)drop\\s+column\\s+energy_allocation").matcher(migration).find());
    }

    @Test
    void migrationDeclaresUtf8AndRepairsMojibakeBeforeSeedingWithoutReplacingIds() throws Exception {
        String migration = resource("schema-update-20261015-energy-attribution.sql");
        int charset = migration.indexOf("SET NAMES utf8mb4");
        int firstChineseStatement = migration.indexOf("INSERT INTO emission_data_dict");
        int repair = migration.indexOf("SET name=CONVERT(CAST(CONVERT(name USING latin1)");
        int seed = migration.indexOf("INSERT INTO emission_energy_attribution_station");

        assertTrue(charset >= 0 && charset < firstChineseStatement,
                "客户端字符集必须在第一条中文DDL/DML前声明");
        assertTrue(migration.contains("WHEN 'shuohuang' THEN '朔黄线'"));
        assertTrue(migration.contains("WHEN 'huangwan' THEN '黄万线'"));
        assertTrue(repair >= 0 && repair < seed, "乱码修复必须先于缺失目录补种");
        assertTrue(migration.contains("LOCATE('3F', HEX(CONVERT(name USING latin1)))=0"));
        assertTrue(migration.contains("BINARY name <> BINARY CONVERT"));
        assertFalse(Pattern.compile("(?i)(delete\\s+from|truncate\\s+table)\\s+emission_energy_attribution_station")
                .matcher(migration).find());
        assertFalse(Pattern.compile("(?i)update\\s+emission_energy_attribution_station\\s+set\\s+id")
                .matcher(migration).find());
    }

    private static int seedCount(String sql) {
        int start = sql.indexOf("INSERT INTO emission_energy_attribution_station");
        int end = sql.indexOf(") seed", start);
        assertTrue(start >= 0 && end > start);
        Matcher matcher = Pattern.compile("SELECT '").matcher(sql.substring(start, end));
        int count = 0;
        while (matcher.find()) count++;
        return count;
    }

    private static String resource(String name) throws Exception {
        try (InputStream input = EnergyAttributionMigrationTest.class.getClassLoader().getResourceAsStream(name)) {
            assertNotNull(input, "找不到资源：" + name);
            return new String(input.readAllBytes(), StandardCharsets.UTF_8).replace("\r\n", "\n");
        }
    }
}
