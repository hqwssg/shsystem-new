package com.example.carbon.emission.model.controller;

import com.example.carbon.emission.model.dto.MonthlyAnalysisRequest;
import com.example.carbon.emission.model.service.impl.MonthlyAnalysisDataService;
import com.example.carbon.emission.model.service.impl.MonthlyAnalysisService;
import org.springframework.http.ResponseEntity;
import org.springframework.http.MediaType;
import java.io.IOException;
import org.springframework.web.bind.annotation.*;
import java.util.Map;

@RestController
@RequestMapping("/api/monthly-analysis")
public class MonthlyAnalysisController {
    private final MonthlyAnalysisDataService data;
    private final MonthlyAnalysisService analysis;
    public MonthlyAnalysisController(MonthlyAnalysisDataService data,MonthlyAnalysisService analysis) { this.data=data;this.analysis=analysis; }
    @GetMapping("/options") public Map<String,Object> options() { return data.options(); }
    @PostMapping("/details") public Map<String,Object> details(@RequestBody MonthlyAnalysisRequest request) { return data.details(request); }
    @PostMapping("/query") public Map<String,Object> query(@RequestBody MonthlyAnalysisRequest request) { return analysis.query(request); }
    @PostMapping("/compare") public Map<String,Object> compare(@RequestBody MonthlyAnalysisRequest request) { return analysis.compare(request); }
    @PostMapping("/export") public ResponseEntity<byte[]> export(@RequestBody MonthlyAnalysisRequest request) throws IOException {
        return ResponseEntity.ok().contentType(MediaType.parseMediaType("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")).header("Content-Disposition","attachment; filename=monthly-analysis.xlsx").body(analysis.export(request));
    }
}
