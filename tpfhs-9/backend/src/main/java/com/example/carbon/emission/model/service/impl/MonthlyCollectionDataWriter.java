package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.MonthlyCollectionNodeData;
import com.example.carbon.emission.model.repository.MonthlyCollectionNodeDataRepository;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.util.Comparator;
import java.util.List;

/** 在独立事务中原子替换一批物理采集点月度结果。 */
@Service
public class MonthlyCollectionDataWriter {

    private final MonthlyCollectionNodeDataRepository repository;
    private final JdbcTemplate jdbc;

    public MonthlyCollectionDataWriter(MonthlyCollectionNodeDataRepository repository, JdbcTemplate jdbc) {
        this.repository = repository;
        this.jdbc = jdbc;
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void replace(List<MonthlyCollectionNodeData> rows) {
        List<PointKey> pointKeys = rows.stream()
                .map(row -> new PointKey(row.getCollectionPointType(), row.getCollectionPointId()))
                .distinct()
                .sorted(Comparator.comparing(PointKey::type).thenComparing(PointKey::id))
                .toList();
        for (PointKey key : pointKeys) {
            lockPhysicalPoint(key);
        }
        for (MonthlyCollectionNodeData row : rows) {
            repository.deleteByCollectionPointTypeAndCollectionPointIdAndYearAndMonth(
                    row.getCollectionPointType(), row.getCollectionPointId(), row.getYear(), row.getMonth());
        }
        repository.flush();
        repository.saveAll(rows);
        repository.flush();
    }

    private void lockPhysicalPoint(PointKey key) {
        String table = switch (key.type()) {
            case 1 -> "emission_meter_info";
            case 2 -> "emission_fossil_fuel_meter_info";
            case 3 -> "emission_purchased_heat_meter_info";
            default -> throw new IllegalArgumentException("不支持的采集点类型: " + key.type());
        };
        List<Long> found = jdbc.queryForList("select id from " + table + " where id=? for update",
                Long.class, key.id());
        if (found.isEmpty()) {
            throw new IllegalStateException("采集点不存在: type=" + key.type() + ", id=" + key.id());
        }
    }

    private record PointKey(Integer type, Long id) {}
}
