package com.example.carbon.emission.model.dto;

import lombok.Data;
import java.util.ArrayList;
import java.util.List;

@Data
public class MonthlyAnalysisRequest {
    private List<Selection> selections = new ArrayList<>();
    private String startMonth;
    private String endMonth;
    private String grain = "MONTH";
    private String dimension = "ENERGY";
    private Integer categoryLevel = 1;
    private String energy;
    private String category;
    private String valueMode = "ADOPTED";
    /** COLLECTION reads meters. CALC_NODE and ROOT read calculation-node monthly subtotals. */
    private String rollup = "COLLECTION";
    private String compareType = "NONE";
    private List<Long> departmentIds = new ArrayList<>();
    private List<Long> stationIds = new ArrayList<>();
    private int page = 0;
    private int size = 20;

    @Data
    public static class Selection {
        private Long companyId;
        private Long templateId;
        private Long nodeId;
    }
}
