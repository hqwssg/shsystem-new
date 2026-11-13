package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.*;
import com.example.carbon.emission.model.repository.*;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.context.annotation.Import;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.TestPropertySource;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.YearMonth;
import java.util.List;
import java.util.Set;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@DataJpaTest
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
@Import(MonthlyPublicationWriter.class)
@Transactional(propagation = Propagation.NOT_SUPPORTED)
@TestPropertySource(properties = {
        "spring.datasource.url=jdbc:h2:mem:monthlypublicationtest;MODE=MySQL;NON_KEYWORDS=MONTH,YEAR;DATABASE_TO_LOWER=TRUE;CASE_INSENSITIVE_IDENTIFIERS=TRUE;DB_CLOSE_DELAY=-1",
        "spring.datasource.driver-class-name=org.h2.Driver",
        "spring.datasource.username=sa",
        "spring.datasource.password=",
        "spring.sql.init.mode=never",
        "spring.jpa.hibernate.ddl-auto=create-drop"
})
class MonthlyPublicationWriterIntegrationTest {

    @Autowired MonthlyPublicationWriter writer;
    @Autowired MonthlyCollectionNodeDataRepository collections;
    @Autowired MonthlyCalcNodeSummaryRepository nodes;
    @Autowired MonthlyCompanyEnergySummaryRepository companies;
    @Autowired MeterInfoRepository meters;
    @Autowired TemplateRepository templates;
    @Autowired JdbcTemplate jdbc;

    private long templateId;
    private long meterId;

    @BeforeEach
    void setUp() {
        companies.deleteAll(); nodes.deleteAll(); collections.deleteAll();
        meters.deleteAll(); templates.deleteAll();
        Template template = new Template();
        template.setName("月度三表事务模板"); template.setCreatedBy(1L); template.setTemplateType(2);
        templateId = templates.saveAndFlush(template).getId();
        MeterInfo meter = new MeterInfo(); meter.setName("月度三表事务电表"); meter.setPointId(1L);
        meterId = meters.saveAndFlush(meter).getId();
    }

    @Test
    void anyInsertFailureRollsBackDeletesAndPreservesAllThreeOldVersions() {
        MonthlyCollectionNodeData oldCollection = collections.saveAndFlush(collection("0.5"));
        MonthlyCalcNodeSummary oldNode = nodes.saveAndFlush(node("5"));
        MonthlyCompanyEnergySummary oldCompany = companies.saveAndFlush(company("5"));

        MonthlyCalcNodeSummary duplicateA = node("8");
        MonthlyCalcNodeSummary duplicateB = node("9");
        MonthlyPublicationPlan plan = new MonthlyPublicationPlan(templateId, 100L, true,
                List.of(YearMonth.of(2026, 1)), List.of(collection("0.8")),
                List.of(duplicateA, duplicateB), List.of(company("8")));

        assertThatThrownBy(() -> writer.replace(plan))
                .isInstanceOf(DataIntegrityViolationException.class);

        assertThat(collections.findAll()).singleElement()
                .satisfies(row -> {
                    assertThat(row.getId()).isEqualTo(oldCollection.getId());
                    assertThat(row.getCarbonEmissionFactor()).isEqualByComparingTo("0.5");
                });
        assertThat(nodes.findAll()).singleElement()
                .satisfies(row -> {
                    assertThat(row.getId()).isEqualTo(oldNode.getId());
                    assertThat(row.getSubtotalCarbonEmission()).isEqualByComparingTo("5");
                });
        assertThat(companies.findAll()).singleElement()
                .satisfies(row -> {
                    assertThat(row.getId()).isEqualTo(oldCompany.getId());
                    assertThat(row.getCarbonEmission()).isEqualByComparingTo("5");
                });
    }

    @Test
    void concurrentSameTemplatePublicationsLeaveOneCoherentThreeTableVersion() throws Exception {
        MonthlyPublicationPlan first = plan(templateId, "0.5", "5");
        MonthlyPublicationPlan second = plan(templateId, "0.8", "8");

        runConcurrently(first, second);

        assertSharedRowsAreCoherent();
        assertThat(nodes.findAll()).singleElement().satisfies(row ->
                assertThat(row.getSubtotalCarbonEmission()).isEqualByComparingTo(
                        companies.findAll().get(0).getCarbonEmission()));
    }

    @Test
    void concurrentTemplatesSharingOnePointDoNotMixSharedMonthlyVersions() throws Exception {
        Template other = new Template();
        other.setName("月度三表并发模板二"); other.setCreatedBy(1L); other.setTemplateType(2);
        long otherTemplateId = templates.saveAndFlush(other).getId();

        runConcurrently(plan(templateId, "0.5", "5"), plan(otherTemplateId, "0.8", "8"));

        assertSharedRowsAreCoherent();
        assertThat(nodes.findAll()).hasSize(2)
                .extracting(MonthlyCalcNodeSummary::getTemplateId)
                .containsExactlyInAnyOrder(templateId, otherTemplateId);
    }

    @Test
    void nightlyIncompleteCompanyIsDeferredUntilDeadlineAndCannotReplaceACompleteVersion() {
        jdbc.execute("create table if not exists emission_data_freshness (template_id bigint primary key, data_revision bigint)");
        jdbc.update("insert into emission_data_freshness values (?,?)", templateId, 5L);
        YearMonth month = YearMonth.of(2026, 1);
        var point = new MonthlyRepairContext.Point(1, meterId);
        var beforeDeadline = new MonthlyRepairContext(month, false, Set.of(point), 5);
        var pastDeadline = new MonthlyRepairContext(month, true, Set.of(point), 5);

        writer.repair(plan(templateId, "0.5", "5"), beforeDeadline);
        assertThat(companies.findAll()).isEmpty();
        assertThat(collections.findAll()).isEmpty();
        assertThat(nodes.findAll()).hasSize(1);

        writer.repair(plan(templateId, "0.5", "5"), pastDeadline);
        assertThat(companies.findAll()).singleElement().satisfies(row ->
                assertThat(row.getResultStatus()).isEqualTo(2));

        var partial = collection("0.5");
        partial.setDataStatus(3);
        collections.saveAndFlush(partial);
        var lateReading = plan(templateId, "0.6", "6");
        lateReading.collectionRows().get(0).setDataStatus(1);
        writer.repair(lateReading, new MonthlyRepairContext(month, true, Set.of(), 5));
        assertThat(collections.findAll()).singleElement().satisfies(row -> {
            assertThat(row.getDataStatus()).isEqualTo(1);
            assertThat(row.getCarbonEmissionFactor()).isEqualByComparingTo("0.6");
        });

        writer.replace(plan(templateId, "0.8", "8"));
        long official = companies.findAll().get(0).getId();
        writer.repair(plan(templateId, "0.5", "5"), pastDeadline);
        assertThat(companies.findAll()).singleElement().satisfies(row -> {
            assertThat(row.getId()).isEqualTo(official);
            assertThat(row.getResultStatus()).isEqualTo(1);
            assertThat(row.getCarbonEmission()).isEqualByComparingTo("8");
        });
    }

    private void runConcurrently(MonthlyPublicationPlan first, MonthlyPublicationPlan second) throws Exception {
        ExecutorService executor = Executors.newFixedThreadPool(2);
        CountDownLatch start = new CountDownLatch(1);
        try {
            Future<?> firstRun = executor.submit(() -> {
                await(start);
                writer.replace(first);
            });
            Future<?> secondRun = executor.submit(() -> {
                await(start);
                writer.replace(second);
            });
            start.countDown();
            firstRun.get(10, TimeUnit.SECONDS);
            secondRun.get(10, TimeUnit.SECONDS);
        } finally {
            executor.shutdownNow();
        }
    }

    private void assertSharedRowsAreCoherent() {
        MonthlyCollectionNodeData collection = collections.findAll().get(0);
        MonthlyCompanyEnergySummary company = companies.findAll().get(0);
        String version = collection.getCarbonEmissionFactor().stripTrailingZeros().toPlainString();
        assertThat(version).isIn("0.5", "0.8");
        assertThat(company.getCarbonEmission()).isEqualByComparingTo(
                version.equals("0.5") ? "5" : "8");
        assertThat(collections.findAll()).hasSize(1);
        assertThat(companies.findAll()).hasSize(1);
        Set<String> nodeVersions = nodes.findAll().stream()
                .map(row -> row.getSubtotalCarbonEmission().stripTrailingZeros().toPlainString())
                .collect(java.util.stream.Collectors.toSet());
        assertThat(nodeVersions).isSubsetOf("5", "8");
    }

    private void await(CountDownLatch start) {
        try {
            start.await(5, TimeUnit.SECONDS);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("并发月度发布等待被中断", interrupted);
        }
    }

    private MonthlyPublicationPlan plan(long planTemplateId, String factor, String carbon) {
        return new MonthlyPublicationPlan(planTemplateId, 100L, true,
                List.of(YearMonth.of(2026, 1)), List.of(collection(factor)),
                List.of(node(planTemplateId, carbon)), List.of(company(carbon)));
    }

    private MonthlyCollectionNodeData collection(String factor) {
        MonthlyCollectionNodeData row = new MonthlyCollectionNodeData();
        row.setCollectionPointType(1); row.setCollectionPointId(meterId);
        row.setYear(2026); row.setMonth(1); row.setCarbonEmissionFactor(new BigDecimal(factor));
        return row;
    }

    private MonthlyCalcNodeSummary node(String carbon) {
        return node(templateId, carbon);
    }

    private MonthlyCalcNodeSummary node(long nodeTemplateId, String carbon) {
        MonthlyCalcNodeSummary row = new MonthlyCalcNodeSummary();
        row.setTemplateId(nodeTemplateId); row.setSourceNodeId(10L); row.setYear(2026); row.setMonth(1);
        row.setNodeLevel(1); row.setEmissionSubcategory("PE_PF"); row.setSummarySource(1);
        row.setDirectEnergyValue(BigDecimal.TEN); row.setDirectCarbonEmission(new BigDecimal(carbon));
        row.setSubtotalEnergyValue(BigDecimal.TEN); row.setSubtotalCarbonEmission(new BigDecimal(carbon));
        return row;
    }

    private MonthlyCompanyEnergySummary company(String carbon) {
        MonthlyCompanyEnergySummary row = new MonthlyCompanyEnergySummary();
        row.setCompanyDeptId(100L); row.setYear(2026); row.setMonth(1);
        row.setEnergyCategoryL1("electricity"); row.setEmissionSubcategory("PE_PF");
        row.setStandardEnergyValue(BigDecimal.TEN); row.setCarbonEmission(new BigDecimal(carbon));
        row.setCalculationUnitCode("MWh");
        return row;
    }
}
