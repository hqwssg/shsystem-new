package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.MonthlyCollectionNodeData;
import com.example.carbon.emission.model.repository.MonthlyCollectionNodeDataRepository;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InOrder;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.jdbc.core.JdbcTemplate;

import java.util.List;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class MonthlyCollectionDataWriterTest {

    @Mock MonthlyCollectionNodeDataRepository repository;
    @Mock JdbcTemplate jdbc;

    @Test
    void locksPhysicalPointThenDeletesAndInsertsTheWholeBatch() {
        MonthlyCollectionNodeData row = new MonthlyCollectionNodeData();
        row.setCollectionPointType(1); row.setCollectionPointId(36L); row.setYear(2026); row.setMonth(1);
        when(jdbc.queryForList(anyString(), eq(Long.class), eq(36L))).thenReturn(List.of(36L));

        new MonthlyCollectionDataWriter(repository, jdbc).replace(List.of(row));

        InOrder order = inOrder(jdbc, repository);
        order.verify(jdbc).queryForList(contains("emission_meter_info"), eq(Long.class), eq(36L));
        order.verify(repository).deleteByCollectionPointTypeAndCollectionPointIdAndYearAndMonth(1, 36L, 2026, 1);
        order.verify(repository).flush();
        order.verify(repository).saveAll(List.of(row));
        order.verify(repository).flush();
    }
}
