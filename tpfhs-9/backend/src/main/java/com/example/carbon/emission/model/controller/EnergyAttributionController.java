package com.example.carbon.emission.model.controller;

import com.example.carbon.emission.model.entity.EnergyAttributionStation;
import com.example.carbon.emission.model.service.EnergyAttributionService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api")
public class EnergyAttributionController {
    private final EnergyAttributionService service;

    public EnergyAttributionController(EnergyAttributionService service) { this.service = service; }

    @GetMapping("/energy-attribution-stations")
    public List<EnergyAttributionStation> stations(@RequestParam(required = false) String keyword,
            @RequestParam(required = false) String lineName,
            @RequestParam(required = false) String branchCompany) {
        return service.listStations(keyword, lineName, branchCompany);
    }

    @PostMapping("/energy-attribution-stations")
    public EnergyAttributionStation create(@RequestBody EnergyAttributionStation request) {
        return service.createStation(request);
    }

    @PutMapping("/energy-attribution-stations/{id}")
    public EnergyAttributionStation update(@PathVariable Long id, @RequestBody EnergyAttributionStation request) {
        return service.updateStation(id, request);
    }

    @DeleteMapping("/energy-attribution-stations/{id}")
    public ResponseEntity<Void> delete(@PathVariable Long id) {
        service.deleteStation(id);
        return ResponseEntity.noContent().build();
    }

    @GetMapping("/energy-attribution-departments")
    public List<Map<String, Object>> departments(@RequestParam(required = false) String keyword) {
        return service.listDepartments(keyword);
    }
}
