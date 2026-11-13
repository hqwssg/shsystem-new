package com.ruoyi.carbon.report.source;

/**
 * Maps emission subcategory codes to report activity buckets.
 */
public final class ActivityClassifier
{
    private ActivityClassifier()
    {
    }

    /** Read-side compatibility only; never rewrite the calculation snapshot. */
    public static String canonical(String subcategory, String unit)
    {
        if (subcategory == null) return null;
        String value = subcategory.trim();
        return switch (value)
        {
            case "天然气" -> "FF_NG";
            case "汽油" -> "FF_G";
            case "柴油" -> "FF_D";
            case "外购电力" -> "PE";
            // The display name does not distinguish heat quantity from heating area.
            // Only the observed, unambiguous GJ representation is accepted here.
            case "热力数据" -> "GJ".equalsIgnoreCase(unit == null ? "" : unit.trim()) ? "PH_HD" : value;
            default -> value;
        };
    }

    public static boolean isFuel(String subcategory)
    {
        return subcategory != null && subcategory.startsWith("FF_");
    }

    public static boolean isElectricity(String subcategory)
    {
        if (subcategory == null || subcategory.isBlank())
        {
            return false;
        }
        return subcategory.regionMatches(true, 0, "EL", 0, 2)
                || "PE".equalsIgnoreCase(subcategory)
                || subcategory.regionMatches(true, 0, "PE_", 0, 3)
                || "purchased-electricity".equalsIgnoreCase(subcategory);
    }

    public static boolean isHeat(String subcategory)
    {
        return subcategory != null && subcategory.startsWith("PH_");
    }

    public static String bucket(String subcategory)
    {
        if (isFuel(subcategory))
        {
            return "fuel";
        }
        if (isElectricity(subcategory))
        {
            return "electricity";
        }
        if (isHeat(subcategory))
        {
            return "heat";
        }
        return "unknown";
    }
}
