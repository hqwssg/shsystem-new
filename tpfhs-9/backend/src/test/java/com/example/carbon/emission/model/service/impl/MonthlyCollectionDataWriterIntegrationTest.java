package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.MeterInfo;
import com.example.carbon.emission.model.entity.MonthlyCollectionNodeData;
import com.example.carbon.emission.model.repository.MeterInfoRepository;
import com.example.carbon.emission.model.repository.MonthlyCollectionNodeDataRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.context.annotation.Import;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.test.context.TestPropertySource;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@DataJpaTest
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
@Import(MonthlyCollectionDataWriter.class)
@Transactional(propagation = Propagation.NOT_SUPPORTED)
@TestPropertySource(properties = {
        "spring.datasource.url=jdbc:h2:mem:monthlywritertest;MODE=MySQL;NON_KEYWORDS=MONTH,YEAR;DATABASE_TO_LOWER=TRUE;CASE_INSENSITIVE_IDENTIFIERS=TRUE;DB_CLOSE_DELAY=-1",
        "spring.datasource.driver-class-name=org.h2.Driver",
        "spring.datasource.username=sa",
        "spring.datasource.password=",
        "spring.sql.init.mode=never",
        "spring.jpa.hibernate.ddl-auto=create-drop"
})
class MonthlyCollectionDataWriterIntegrationTest {

    @Autowired MonthlyCollectionDataWriter writer;
    @Autowired MonthlyCollectionNodeDataRepository monthlyRepository;
    @Autowired MeterInfoRepository meterRepository;

    private long meterId;

    @BeforeEach
    void setUp() {
        monthlyRepository.deleteAll();
        meterRepository.deleteAll();
        MeterInfo meter = new MeterInfo();
        meter.setName("月度事务测试电表");
        meter.setPointId(1L);
        meterId = meterRepository.saveAndFlush(meter).getId();
    }

    @Test
    void duplicateBatchRollsBackDeleteAndKeepsOldRow() {
        MonthlyCollectionNodeData old = row("0.5");
        long oldId = monthlyRepository.saveAndFlush(old).getId();

        assertThatThrownBy(() -> writer.replace(List.of(row("0.8"), row("0.9"))))
                .isInstanceOf(DataIntegrityViolationException.class);

        List<MonthlyCollectionNodeData> stored = monthlyRepository.findAll();
        assertThat(stored).hasSize(1);
        assertThat(stored.get(0).getId()).isEqualTo(oldId);
        assertThat(stored.get(0).getCarbonEmissionFactor()).isEqualByComparingTo("0.5");
    }

    @Test
    void concurrentReplacementKeepsExactlyOneLatestRow() throws Exception {
        monthlyRepository.saveAndFlush(row("0.5"));
        CountDownLatch start = new CountDownLatch(1);
        ExecutorService pool = Executors.newFixedThreadPool(2);
        try {
            Future<?> first = pool.submit(() -> replaceAfter(start, "0.8"));
            Future<?> second = pool.submit(() -> replaceAfter(start, "0.9"));
            start.countDown();
            first.get();
            second.get();
        } finally {
            pool.shutdownNow();
        }

        List<MonthlyCollectionNodeData> stored = monthlyRepository.findAll();
        assertThat(stored).hasSize(1);
        BigDecimal finalFactor = stored.get(0).getCarbonEmissionFactor();
        assertThat(finalFactor.compareTo(new BigDecimal("0.8")) == 0
                || finalFactor.compareTo(new BigDecimal("0.9")) == 0).isTrue();
    }

    private void replaceAfter(CountDownLatch start, String factor) {
        try {
            start.await();
            writer.replace(List.of(row(factor)));
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException(error);
        }
    }

    private MonthlyCollectionNodeData row(String factor) {
        MonthlyCollectionNodeData row = new MonthlyCollectionNodeData();
        row.setCollectionPointType(1);
        row.setCollectionPointId(meterId);
        row.setYear(2026);
        row.setMonth(1);
        row.setCarbonEmissionFactor(new BigDecimal(factor));
        return row;
    }
}
