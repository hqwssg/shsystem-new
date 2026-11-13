package com.example.carbon.emission.model.controller;

import com.example.carbon.emission.model.service.impl.EmissionStatisticsService;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDate;
import java.util.Map;
import java.util.List;

@RestController
@RequestMapping("/api/emission-data")
@CrossOrigin(origins = "*")
public class EmissionStatisticsController {
    private final EmissionStatisticsService statistics;

    public EmissionStatisticsController(EmissionStatisticsService statistics) {
        this.statistics = statistics;
    }

    @GetMapping("/query")
    public Map<String, Object> query(@RequestParam(required = false) Long templateId,
                                     @RequestParam(required = false) Long nodeId,
                                     @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate startDate,
                                     @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate endDate,
                                     @RequestParam(required = false) Integer energyType,
                                     @RequestParam(required = false) String dataSource,
                                     @RequestParam(defaultValue = "0") int page,
                                     @RequestParam(defaultValue = "20") int size,
                                     @RequestParam(defaultValue = "dataDate") String sortBy,
                                     @RequestParam(defaultValue = "DESC") String sortDirection) {
        return statistics.query(criteria(templateId, nodeId, startDate, endDate, energyType, dataSource,
                page, size, sortBy, sortDirection));
    }

    @GetMapping({"/statistics", "/dashboard"})
    public Map<String, Object> dashboard(@RequestParam(required = false) Long templateId,
                                         @RequestParam(required = false) Long nodeId,
                                         @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate startDate,
                                         @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate endDate,
                                         @RequestParam(required = false) Integer energyType,
                                         @RequestParam(required = false) String dataSource) {
        return statistics.dashboard(criteria(templateId, nodeId, startDate, endDate, energyType, dataSource,
                0, 20, "dataDate", "ASC"));
    }

    @GetMapping("/surface")
    public Map<String, Object> surface(@RequestParam(defaultValue = "month") String granularity,
                                       @RequestParam(required = false) Long templateId,
                                       @RequestParam(required = false) Long nodeId,
                                       @RequestParam(required = false) Integer energyType,
                                       @RequestParam(required = false) String dataSource) {
        return statistics.surface(criteria(templateId, nodeId, null, null, energyType, dataSource,
                0, 20, "dataDate", "ASC"), granularity);
    }

    @GetMapping("/segment-energy")
    public List<Map<String, Object>> segmentEnergy() {
        return statistics.segmentEnergy();
    }

    private EmissionStatisticsService.Criteria criteria(Long templateId, Long nodeId, LocalDate startDate,
                                                         LocalDate endDate, Integer energyType, String dataSource,
                                                         int page, int size, String sortBy, String sortDirection) {
        EmissionStatisticsService.Criteria criteria = new EmissionStatisticsService.Criteria();
        criteria.templateId = templateId;
        criteria.nodeId = nodeId;
        criteria.startDate = startDate;
        criteria.endDate = endDate;
        criteria.energyType = energyType;
        criteria.dataSource = dataSource == null || dataSource.isBlank() ? null : dataSource.trim().toUpperCase();
        criteria.page = page;
        criteria.size = size;
        criteria.sortBy = sortBy;
        criteria.sortDirection = sortDirection;
        return criteria;
    }
}
