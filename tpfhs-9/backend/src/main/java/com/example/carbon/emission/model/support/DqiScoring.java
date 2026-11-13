package com.example.carbon.emission.model.support;

import java.time.LocalDate;
import java.util.Map;

/** Central DQI option mapping and runtime score rules. */
public final class DqiScoring {
    private static final Map<String, Integer> A1 = ordered(
            "online_meter", "manual_ledger", "statistical_report",
            "literature_thirdparty", "default_or_estimated");
    private static final Map<String, Integer> A2 = Map.of(
            "calib_valid_cert", 5,
            "calib_valid_internal", 4,
            "calib_overdue_verified", 3,
            "calib_overdue_no_record", 2,
            "calib_status_unknown", 1,
            "calib_not_applicable", 5);
    private static final Map<String, Integer> A4 = ordered(
            "direct_metered", "ledger_complete", "allocated", "analogized", "default_value");
    private static final Map<String, Integer> E1 = ordered(
            "official_national", "national_standard", "ipcc_default",
            "authoritative_literature", "general_or_estimated");
    private static final Map<String, Integer> E2 = ordered(
            "full", "minor_missing", "partial_missing", "major_only", "unknown");
    private static final Map<String, Integer> E3 = ordered(
            "in_boundary", "same_grid", "national", "similar_economy", "other_country");
    private static final Map<String, Integer> E5 = ordered(
            "same_equipment_condition", "railway_same_traction", "railway_generic",
            "adjacent_industry", "generic_default");
    private static final Map<String, Integer> E6 = ordered(
            "direct_match", "standard_single", "multi_step", "derived_from_other", "unclear");

    private DqiScoring() {
    }

    private static Map<String, Integer> ordered(String five, String four, String three,
                                                String two, String one) {
        return Map.of(five, 5, four, 4, three, 3, two, 2, one, 1);
    }

    private static Integer lookup(Map<String, Integer> mapping, String value) {
        return value == null ? null : mapping.get(value);
    }

    public static Integer a1(String value) { return lookup(A1, value); }
    public static Integer a2(String value) { return lookup(A2, value); }
    public static Integer a4(String value) { return lookup(A4, value); }
    public static Integer e1(String value) { return lookup(E1, value); }
    public static Integer e2(String value) { return lookup(E2, value); }
    public static Integer e3(String value) { return lookup(E3, value); }
    public static Integer e5(String value) { return lookup(E5, value); }
    public static Integer e6(String value) { return lookup(E6, value); }

    public static Integer e4(Integer fixedScore, Integer factorYear, LocalDate calculationStart) {
        if (isValidScore(fixedScore)) {
            return fixedScore;
        }
        if (factorYear == null || calculationStart == null) {
            return 1;
        }
        int delta = calculationStart.getYear() - factorYear;
        if (delta >= 0 && delta <= 2) {
            return 5;
        }
        if (delta >= 3 && delta <= 6) {
            return 7 - delta;
        }
        return 1;
    }

    /** Maps the current calculation result to the conservative A6 score. */
    public static int a6(Integer dataStatus, String missingDescription,
                         boolean hasAdjustedValue, boolean manuallyEnteredPeriodic) {
        if (manuallyEnteredPeriodic || (dataStatus != null && dataStatus == 1)) {
            return 5;
        }
        String description = missingDescription == null ? "" : missingDescription;
        if (dataStatus != null && dataStatus == 3 && hasAdjustedValue) {
            if (description.contains("人工") || description.contains("佐证") || description.contains("签名")) {
                return 4;
            }
            return 3;
        }
        if (dataStatus != null && dataStatus == 5 && hasAdjustedValue) {
            return 2;
        }
        return 1;
    }

    public static boolean isValidScore(Integer score) {
        return score != null && score >= 1 && score <= 5;
    }
}
