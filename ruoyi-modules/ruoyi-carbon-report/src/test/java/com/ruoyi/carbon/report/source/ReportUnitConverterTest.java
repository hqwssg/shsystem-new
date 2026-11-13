package com.ruoyi.carbon.report.source;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import java.math.BigDecimal;
import org.junit.jupiter.api.Test;

class ReportUnitConverterTest
{
    private final ReportUnitConverter converter = new ReportUnitConverter();

    @Test
    void naturalGasStaysReportUnit()
    {
        ReportUnitConverter.Conversion conversion = converter.convert("FF_NG", new BigDecimal("12.5"), "10k_m3");
        assertTrue(conversion.ok);
        assertEquals(0, new BigDecimal("12.5").compareTo(conversion.normalizedValue));
        assertEquals("10k_m3", conversion.normalizedUnit);
    }

    @Test
    void dieselLitersConvertToTonnes()
    {
        ReportUnitConverter.Conversion conversion = converter.convert("FF_D", new BigDecimal("1000"), "L");
        assertTrue(conversion.ok);
        assertEquals(0, new BigDecimal("0.850000").compareTo(conversion.normalizedValue));
        assertEquals("t", conversion.normalizedUnit);
    }

    @Test
    void missingFactorIsGap()
    {
        ReportUnitConverter.Conversion conversion = converter.convert("FF_NG", new BigDecimal("1"), "kg");
        assertFalse(conversion.ok);
    }

    @Test
    void purchasedHeatAreaExposesActualFactor()
    {
        converter.register("PH_HA", "m2", "GJ", new BigDecimal("1.5"));
        ReportUnitConverter.Conversion conversion = converter.convert("PH_HA", new BigDecimal("12000"), "m2");
        assertTrue(conversion.ok);
        assertEquals(0, new BigDecimal("1.5").compareTo(conversion.factor));
        assertEquals(0, new BigDecimal("18000.000000").compareTo(conversion.normalizedValue));
    }

    @Test
    void purchasedHeatInGjHasNoConversionFactor()
    {
        ReportUnitConverter.Conversion conversion = converter.convert("PH_HD", new BigDecimal("50"), "GJ");
        assertTrue(conversion.ok);
        assertNull(conversion.factor);
        assertEquals(0, new BigDecimal("50").compareTo(conversion.normalizedValue));
    }
}
