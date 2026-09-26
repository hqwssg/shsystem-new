package com.ruoyi.carbon.energy.config;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import org.junit.jupiter.api.Test;
import com.ruoyi.common.core.exception.ServiceException;

class EnergyPropertiesTest
{
    @Test
    void buildsMysqlUrlFromJdbc()
    {
        String url = EnergyProperties.fromJdbc(
                "jdbc:mysql://localhost:3306/carbon_emissions?useUnicode=true",
                "root",
                "2523407276");
        assertEquals("mysql://root:2523407276@localhost:3306/carbon_emissions", url);
    }

    @Test
    void rejectsBlankJdbc()
    {
        assertThrows(ServiceException.class, () -> EnergyProperties.fromJdbc("", "root", "x"));
    }
}
