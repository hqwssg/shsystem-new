package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.MonthlyCalcNodeSummary;
import com.example.carbon.emission.model.entity.MonthlyCollectionNodeData;
import com.example.carbon.emission.model.entity.MonthlyCompanyEnergySummary;
import com.example.carbon.emission.model.repository.MonthlyCalcNodeSummaryRepository;
import com.example.carbon.emission.model.repository.MonthlyCollectionNodeDataRepository;
import com.example.carbon.emission.model.repository.MonthlyCompanyEnergySummaryRepository;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InOrder;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.time.YearMonth;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class MonthlyPublicationWriterTest {

    @Mock MonthlyCollectionNodeDataRepository collections;
    @Mock MonthlyCalcNodeSummaryRepository nodes;
    @Mock MonthlyCompanyEnergySummaryRepository companies;
    @Mock JdbcTemplate jdbc;

    @Test
    void locksTemplateAndReplacesAllThreeTablesInOneWriterCall() throws Exception {
        MonthlyCollectionNodeData collection = new MonthlyCollectionNodeData();
        collection.setCollectionPointType(1); collection.setCollectionPointId(36L);
        collection.setYear(2026); collection.setMonth(1);
        MonthlyCalcNodeSummary node = new MonthlyCalcNodeSummary();
        MonthlyCompanyEnergySummary company = new MonthlyCompanyEnergySummary();
        MonthlyPublicationPlan plan = new MonthlyPublicationPlan(20L, 100L, true,
                List.of(YearMonth.of(2026, 1)), List.of(collection), List.of(node), List.of(company));
        when(jdbc.queryForList(contains("emission_template"), eq(Long.class), eq(20L))).thenReturn(List.of(20L));
        when(jdbc.queryForList(contains("emission_meter_info"), eq(Long.class), eq(36L))).thenReturn(List.of(36L));

        new MonthlyPublicationWriter(collections, nodes, companies, jdbc).replace(plan);

        InOrder order = inOrder(jdbc, collections, nodes, companies);
        order.verify(jdbc).queryForList(contains("emission_template"), eq(Long.class), eq(20L));
        order.verify(jdbc).queryForList(contains("emission_meter_info"), eq(Long.class), eq(36L));
        order.verify(collections).deleteByCollectionPointTypeAndCollectionPointIdAndYearAndMonth(1, 36L, 2026, 1);
        order.verify(nodes).deleteByTemplateIdAndYearAndMonth(20L, 2026, 1);
        order.verify(companies).deleteByCompanyDeptIdAndYearAndMonth(100L, 2026, 1);
        verify(collections).saveAll(List.of(collection));
        verify(nodes).saveAll(List.of(node));
        verify(companies).saveAll(List.of(company));

        Transactional tx = MonthlyPublicationWriter.class.getMethod("replace", MonthlyPublicationPlan.class)
                .getAnnotation(Transactional.class);
        assertThat(tx.propagation()).isEqualTo(Propagation.REQUIRES_NEW);
    }
}
