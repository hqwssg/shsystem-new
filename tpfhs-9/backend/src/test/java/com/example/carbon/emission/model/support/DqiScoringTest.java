package com.example.carbon.emission.model.support;

import org.junit.jupiter.api.Test;

import java.time.LocalDate;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

class DqiScoringTest {

    @Test
    void mapsActivityAndFactorOptions() {
        assertEquals(5, DqiScoring.a1("online_meter"));
        assertEquals(1, DqiScoring.a1("default_or_estimated"));
        assertEquals(5, DqiScoring.a2("calib_not_applicable"));
        assertEquals(3, DqiScoring.a4("allocated"));
        assertEquals(5, DqiScoring.e1("official_national"));
        assertEquals(1, DqiScoring.e6("unclear"));
        assertNull(DqiScoring.e3("unsupported"));
    }

    @Test
    void calculatesE4AtAllBoundariesAndHonorsFixedScore() {
        LocalDate calculationDate = LocalDate.of(2026, 6, 1);
        assertEquals(4, DqiScoring.e4(4, 1990, calculationDate));
        assertEquals(5, DqiScoring.e4(null, 2026, calculationDate));
        assertEquals(5, DqiScoring.e4(null, 2024, calculationDate));
        assertEquals(4, DqiScoring.e4(null, 2023, calculationDate));
        assertEquals(1, DqiScoring.e4(null, 2020, calculationDate));
        assertEquals(1, DqiScoring.e4(null, 2019, calculationDate));
        assertEquals(1, DqiScoring.e4(null, 2027, calculationDate));
        assertEquals(1, DqiScoring.e4(null, null, calculationDate));
    }

    @Test
    void calculatesA6ConservativelyFromCurrentResult() {
        assertEquals(5, DqiScoring.a6(1, null, false, false));
        assertEquals(5, DqiScoring.a6(3, "", false, true));
        assertEquals(4, DqiScoring.a6(3, "人工补录且有签名佐证", true, false));
        assertEquals(3, DqiScoring.a6(3, "经计算修正", true, false));
        assertEquals(2, DqiScoring.a6(5, "两端缺失", true, false));
        assertEquals(1, DqiScoring.a6(2, "没有可用数据", false, false));
    }
}
