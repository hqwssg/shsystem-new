package com.ruoyi.carbon.energy.cli;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import com.alibaba.fastjson2.JSON;

class EnergyCliClientTest
{
    @Test
    void cliErrorUsesLastTracebackLine()
    {
        String err = """
                Traceback (most recent call last):
                  File "cli.py", line 34, in _load_parameters
                json.decoder.JSONDecodeError: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)
                """;
        assertEquals(
                "json.decoder.JSONDecodeError: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)",
                EnergyCliClient.cliErrorMessage(err));
    }

    @Test
    void cliErrorKeepsExcelConflictText()
    {
        String err = "线路几何.xlsx / 区间 / 第4行：里程与第2行（A）重叠\n这一版没有发布。\n";
        assertEquals("线路几何.xlsx / 区间 / 第4行：里程与第2行（A）重叠\n这一版没有发布。",
                EnergyCliClient.cliErrorMessage(err));
    }

    @Test
    void cliErrorFallsBackWhenEmpty()
    {
        assertEquals("能量任务命令失败", EnergyCliClient.cliErrorMessage(""));
        assertEquals("能量任务命令失败", EnergyCliClient.cliErrorMessage(null));
    }

    @Test
    void writeParametersFileKeepsQuotes() throws Exception
    {
        Path dir = Files.createTempDirectory("energy-params-test");
        String json = "{\"population_size\":2,\"storage_devices\":[{\"storage_section_id\":\"storage_section_1:K145-K164\",\"available\":true}]}";
        Path file = EnergyCliClient.writeParametersFile(dir, json);
        try
        {
            String stored = Files.readString(file, StandardCharsets.UTF_8);
            assertEquals(json, stored);
            assertTrue(JSON.parseObject(stored).containsKey("storage_devices"));
        }
        finally
        {
            Files.deleteIfExists(file);
            Files.deleteIfExists(dir);
        }
    }
}
