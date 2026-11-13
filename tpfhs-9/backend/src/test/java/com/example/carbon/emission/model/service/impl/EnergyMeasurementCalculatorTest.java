package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.CollectionRecord;
import com.example.carbon.emission.model.entity.FossilFuelMeterInfo;
import com.example.carbon.emission.model.entity.MeterInfo;
import com.example.carbon.emission.model.entity.PurchasedHeatMeterInfo;
import com.example.carbon.emission.model.repository.CollectionRecordRepository;
import com.example.carbon.emission.model.repository.FossilFuelMeterInfoRepository;
import com.example.carbon.emission.model.repository.MeterInfoRepository;
import com.example.carbon.emission.model.repository.PurchasedHeatMeterInfoRepository;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * EnergyMeasurementCalculator 单元测试（纯 Mockito，不启动 Spring 容器）
 * <p>
 * 覆盖采集节点（type_id=3）能耗计量值核算的三大块逻辑：
 * <ul>
 *   <li>算法A：累加量采集点——起止记录选取（6点规则、最近日期、平局规则）、
 *       数据状态判定（完整/无数据/不完整/超范围/不完整且超范围）、
 *       采集点启停例外、能耗差值计算、超限/缺失修正</li>
 *   <li>算法B：非累加量采集点——计费周期记录求和、首尾衔接检查、
 *       空缺/重叠修正、前中尾部缺失的启停例外</li>
 *   <li>虚拟电表/分摊子电表——父表推导、兄弟表扣减、负值截0、父表无数据</li>
 *   <li>边界条件——6点整分界、单条记录、读数倒退、双侧超范围、启停时间恰好等于核算边界、
 *       空缺部分落入停用区间、完全包含重叠、分摊比例为空、循环引用等</li>
 * </ul>
 */
@ExtendWith(MockitoExtension.class)
@DisplayName("能耗计量值计算器测试")
class EnergyMeasurementCalculatorTest {

    /** 测试用电力表ID（普通电表，无特殊标记时 findById 返回 empty 即可） */
    private static final Long METER_ID = 10L;

    private static final LocalDate CYCLE_START = LocalDate.parse("2026-04-01");
    private static final LocalDate CYCLE_END = LocalDate.parse("2026-04-30");

    @Mock
    private CollectionRecordRepository collectionRecordRepository;

    @Mock
    private MeterInfoRepository meterInfoRepository;

    @Mock
    private FossilFuelMeterInfoRepository fossilFuelMeterInfoRepository;

    @Mock
    private PurchasedHeatMeterInfoRepository purchasedHeatMeterInfoRepository;

    @InjectMocks
    private EnergyMeasurementCalculator calculator;

    // ========================= 测试数据构造 =========================

    /** 构造采集记录（累加量场景：按采集时间+表读数） */
    private CollectionRecord rec(String date, int hour, String value) {
        CollectionRecord r = new CollectionRecord();
        r.setCollectionTime(LocalDate.parse(date).atTime(hour, 0));
        r.setReadingValue(new BigDecimal(value));
        r.setCollectionStatus(1);
        return r;
    }

    /** 构造计费周期记录（非累加量场景：按 billing 周期+周期用量） */
    private CollectionRecord cycleRec(String start, String end, String value) {
        CollectionRecord r = new CollectionRecord();
        r.setCollectionTime(LocalDate.parse(start).atTime(6, 0));
        r.setReadingValue(new BigDecimal(value));
        r.setBillingCycleStartDate(LocalDate.parse(start));
        r.setBillingCycleEndDate(LocalDate.parse(end));
        r.setCollectionStatus(1);
        return r;
    }

    /** 构造普通电表（非虚拟、非分摊） */
    private MeterInfo normalMeter(Long id, Integer isCumulative) {
        MeterInfo m = new MeterInfo();
        m.setId(id);
        m.setIsCumulative(isCumulative);
        m.setIsVirtualMeter(0);
        m.setIsAllocationChild(0);
        return m;
    }

    /** 桩：返回指定采集点的成功采集记录（collection_status=1，电力表） */
    private void stubRecords(long pointId, List<CollectionRecord> records) {
        when(collectionRecordRepository.findByCollectionPointTypeAndCollectionPointIdAndCollectionStatus(
                1, pointId, 1)).thenReturn(records);
    }

    // ========================= 公共入口守卫 =========================

    @Test
    @DisplayName("核算周期日期为空：状态=2（无数据），计量值=0")
    void calculate_nullCycleDates_returnsNoData() {
        EnergyMeasurementCalculator.Result r = calculator.calculate(1, METER_ID, 1, null, null);

        assertThat(r.getDataStatus()).isEqualTo(2);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("0");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("0");
        assertThat(r.getDataMissingDescription()).contains("核算周期日期为空");
    }

    // ========================= 算法A：累加量采集点 =========================

    @ParameterizedTest
    @CsvSource({"true,260", "false,250"})
    @DisplayName("首尾启停豁免与中间真实缺口并存时只补中间")
    void nonCumulative_lifecycleExemptionAndGap(boolean leading, String expected) {
        MeterInfo meter = normalMeter(METER_ID, 0);
        if (leading) meter.setEnableTime(LocalDate.parse("2026-04-03").atStartOfDay());
        else meter.setDisableTime(LocalDate.parse("2026-04-26").atStartOfDay());
        when(meterInfoRepository.findById(METER_ID)).thenReturn(java.util.Optional.of(meter));
        stubRecords(METER_ID, leading
                ? List.of(cycleRec("2026-04-05", "2026-04-10", "60"), cycleRec("2026-04-13", "2026-04-30", "180"))
                : List.of(cycleRec("2026-04-01", "2026-04-10", "100"), cycleRec("2026-04-13", "2026-04-25", "130")));
        EnergyMeasurementCalculator.Result result = calculator.calculate(1, METER_ID, 0, CYCLE_START, CYCLE_END);
        assertThat(result.getDataStatus()).isEqualTo(3);
        assertThat(result.getAdjustedEnergyValue()).isEqualByComparingTo(expected);
    }

    @ParameterizedTest(name = "periodic boundary gap type={0}, leading={1}")
    @CsvSource({"1,true", "1,false", "2,true", "2,false", "3,true", "3,false"})
    @DisplayName("周期量首尾缺失：有日均依据且无生命周期豁免时补足缺失两天")
    void nonCumulative_boundaryGap_addsMissingDays(int type, boolean leading) {
        CollectionRecord record = leading
                ? cycleRec("2026-04-03", "2026-04-30", "280")
                : cycleRec("2026-04-01", "2026-04-28", "280");
        when(collectionRecordRepository.findByCollectionPointTypeAndCollectionPointIdAndCollectionStatus(
                type, METER_ID, 1)).thenReturn(List.of(record));
        EnergyMeasurementCalculator.Result result = calculator.calculate(type, METER_ID, 0, CYCLE_START, CYCLE_END);
        assertThat(result.getDataStatus()).isEqualTo(3);
        assertThat(result.getEnergyMeasurementValue()).isEqualByComparingTo("280");
        assertThat(result.getAdjustedEnergyValue()).isEqualByComparingTo("300");
        assertThat(result.getDataMissingDescription()).isNotBlank();
    }

    @Test
    @DisplayName("累加量-完整：起止日期精确匹配，状态=1，能耗=截止值-起始值，修正值=原值")
    void cumulative_complete_exactDates() {
        stubRecords(METER_ID, List.of(
                rec("2026-04-01", 6, "100"),
                rec("2026-04-30", 6, "400")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 1, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(1);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("300");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("300");
        assertThat(r.getCollectionRecordStartDate()).isEqualTo(CYCLE_START);
        assertThat(r.getCollectionRecordEndDate()).isEqualTo(CYCLE_END);
        assertThat(r.getDataMissingDescription()).isNull();
    }

    @ParameterizedTest
    @CsvSource({"1","2","3"})
    @DisplayName("周期量首尾同时缺失：26天260补4天后300，保持不完整")
    void nonCumulative_bothBoundariesMissing_addsBothSides(int type) {
        when(collectionRecordRepository.findByCollectionPointTypeAndCollectionPointIdAndCollectionStatus(type,METER_ID,1))
                .thenReturn(List.of(cycleRec("2026-04-03","2026-04-28","260")));
        EnergyMeasurementCalculator.Result r=calculator.calculate(type,METER_ID,0,CYCLE_START,CYCLE_END);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("260");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("300");
        assertThat(r.getDataStatus()).isEqualTo(3);
    }

    @Test
    @DisplayName("周期量多个不连续缺口：各缺口只补一次")
    void nonCumulative_multipleGaps_fillEachOnce() {
        stubRecords(METER_ID,List.of(cycleRec("2026-04-01","2026-04-05","50"),
                cycleRec("2026-04-11","2026-04-15","50"),cycleRec("2026-04-21","2026-04-30","100")));
        EnergyMeasurementCalculator.Result r=calculator.calculate(1,METER_ID,0,CYCLE_START,CYCLE_END);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("200");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("300");
        assertThat(r.getDataStatus()).isEqualTo(3);
        assertThat(r.getDataMissingDescription()).contains("2026-04-06至2026-04-10","2026-04-16至2026-04-20");
    }

    @Test
    @DisplayName("累计电表-上月末读数：视为本月有效起始边界，不扣减一天日均量")
    void cumulativeElectricMeter_previousDayIsValidStartBoundary() {
        stubRecords(METER_ID, List.of(
                rec("2026-03-31", 23, "100"),
                rec("2026-04-30", 23, "400")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 1, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(1);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("300");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("300");
        assertThat(r.getCollectionRecordStartDate()).isEqualTo(LocalDate.parse("2026-03-31"));
        assertThat(r.getDataMissingDescription()).isNull();
    }

    @Test
    @DisplayName("累计燃料采集点-前一日读数：仍按超范围规则扣减，不套用电表月末边界")
    void cumulativeNonElectric_previousDayRemainsOverRange() {
        when(collectionRecordRepository.findByCollectionPointTypeAndCollectionPointIdAndCollectionStatus(
                2, METER_ID, 1)).thenReturn(List.of(
                rec("2026-03-31", 23, "100"),
                rec("2026-04-30", 23, "400")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(2, METER_ID, 1, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(4);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("300");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("290");
        assertThat(r.getDataMissingDescription()).contains("起始日期超限");
    }

    @Test
    @DisplayName("累加量-无采集数据：状态=2，计量值=0，修正值=0")
    void cumulative_noRecords_status2() {
        stubRecords(METER_ID, new ArrayList<>());

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 1, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(2);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("0");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("0");
        assertThat(r.getDataMissingDescription()).contains("无采集数据");
    }

    @Test
    @DisplayName("累加量-6点规则：截止日次日凌晨3点采集算前一天，状态仍为完整；记录截止日字段为实际采集日期")
    void cumulative_before6am_countsAsPreviousDay() {
        // 5月1日凌晨3点采集 → 有效日期=4月30日，与核算截止日精确匹配
        stubRecords(METER_ID, List.of(
                rec("2026-04-01", 6, "100"),
                rec("2026-05-01", 3, "400")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 1, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(1);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("300");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("300");
        // "采集记录的截止日期"记录实际采集日期（2026-05-01），而非有效日期
        assertThat(r.getCollectionRecordEndDate()).isEqualTo(LocalDate.parse("2026-05-01"));
        assertThat(r.getDataMissingDescription()).isNull();
    }

    @Test
    @DisplayName("累加量-起始日在核算周期之前：状态=4（超范围），按日均×超限天数扣减")
    void cumulative_startBeforeCycle_overRange_deduction() {
        // 记录：03-30→100、04-10→180、04-20→280、04-30→410；日均=(410-100)/31天=10
        stubRecords(METER_ID, List.of(
                rec("2026-03-30", 6, "100"),
                rec("2026-04-10", 6, "180"),
                rec("2026-04-20", 6, "280"),
                rec("2026-04-30", 6, "410")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 1, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(4);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("310");
        // 修正值 = 310 - 超限2天×日均10 = 290
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("290");
        assertThat(r.getDataMissingDescription()).contains("起始日期超限").contains("2026-03-30");
    }

    @Test
    @DisplayName("累加量-起始日在核算周期之后：状态=3（不完整），按日均×缺失天数补加")
    void cumulative_startAfterCycle_incomplete_addition() {
        // 记录：04-05→100、04-25→200、04-30→260；日均=(260-100)/25天=6.4
        stubRecords(METER_ID, List.of(
                rec("2026-04-05", 6, "100"),
                rec("2026-04-25", 6, "200"),
                rec("2026-04-30", 6, "260")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 1, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(3);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("160");
        // 修正值 = 160 + 缺失4天×日均6.4 = 185.6
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("185.6");
        assertThat(r.getDataMissingDescription()).contains("起始日期无数据");
    }

    @Test
    @DisplayName("累加量-截止日在核算周期之后：状态=4（超范围），按日均×超限天数扣减")
    void cumulative_endAfterCycle_overRange_deduction() {
        // 记录：04-01→100、05-01→400；日均=(400-100)/30天=10
        stubRecords(METER_ID, List.of(
                rec("2026-04-01", 6, "100"),
                rec("2026-05-01", 6, "400")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 1, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(4);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("300");
        // 修正值 = 300 - 超限1天×日均10 = 290
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("290");
        assertThat(r.getDataMissingDescription()).contains("截止日期数据超限").contains("2026-05-01");
    }

    @Test
    @DisplayName("累加量-起始超范围+截止不完整：状态=5（不完整且超范围）")
    void cumulative_startOverRangeAndEndIncomplete_status5() {
        // 记录：03-30→100、04-10→200、04-28→390；日均=(390-100)/29天=10
        stubRecords(METER_ID, List.of(
                rec("2026-03-30", 6, "100"),
                rec("2026-04-10", 6, "200"),
                rec("2026-04-28", 6, "390")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 1, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(5);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("290");
        // 扣减超限2天×10 + 补加缺失2天×10 = 原值290
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("290");
        assertThat(r.getDataMissingDescription())
                .contains("起始日期超限").contains("2026-03-30")
                .contains("截止日期无数据");
    }

    @Test
    @DisplayName("累加量-例外①：采集点在核算起始日之后才启用，起始不匹配不视为不完整")
    void cumulative_startAfterCycle_meterEnabledLater_exempt() {
        // 电表启用时间 2026-04-03（晚于核算起始日 04-01）
        MeterInfo meter = normalMeter(METER_ID, 1);
        meter.setEnableTime(LocalDate.parse("2026-04-03").atTime(0, 0));
        when(meterInfoRepository.findById(METER_ID)).thenReturn(java.util.Optional.of(meter));
        stubRecords(METER_ID, List.of(
                rec("2026-04-05", 6, "100"),
                rec("2026-04-30", 6, "400")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 1, CYCLE_START, CYCLE_END);

        // 起始记录04-05在起始日之后，但电表04-03才启用 → 视为完整，不补加缺失值
        assertThat(r.getDataStatus()).isEqualTo(1);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("300");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("300");
        assertThat(r.getDataMissingDescription()).isNull();
    }

    @Test
    @DisplayName("累加量-例外②：采集点在核算截止日之前被停用，截止不匹配不视为不完整")
    void cumulative_endBeforeCycle_meterDisabledEarlier_exempt() {
        // 电表停用时间 2026-04-26（早于核算截止日 04-30）
        MeterInfo meter = normalMeter(METER_ID, 1);
        meter.setDisableTime(LocalDate.parse("2026-04-26").atTime(0, 0));
        when(meterInfoRepository.findById(METER_ID)).thenReturn(java.util.Optional.of(meter));
        stubRecords(METER_ID, List.of(
                rec("2026-04-01", 6, "100"),
                rec("2026-04-25", 6, "350")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 1, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(1);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("250");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("250");
        assertThat(r.getDataMissingDescription()).isNull();
    }

    @Test
    @DisplayName("累加量-平局规则：与起始日差值相等时选起始日之后的记录，与截止日差值相等时选截止日之前的记录")
    void cumulative_tieBreak_prefersAfterForStartAndBeforeForEnd() {
        // 起始侧：03-30与04-03距04-01均为2天 → 选04-03（之后）
        // 截止侧：04-28与05-02距04-30均为2天 → 选04-28（之前）
        stubRecords(METER_ID, List.of(
                rec("2026-03-30", 6, "100"),
                rec("2026-04-03", 6, "150"),
                rec("2026-04-28", 6, "450"),
                rec("2026-05-02", 6, "500")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 1, CYCLE_START, CYCLE_END);

        assertThat(r.getCollectionRecordStartDate()).isEqualTo(LocalDate.parse("2026-04-03"));
        assertThat(r.getCollectionRecordEndDate()).isEqualTo(LocalDate.parse("2026-04-28"));
        assertThat(r.getDataStatus()).isEqualTo(3);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("300");
        // 日均=(500-100)/33天≈12.121212；补加(2+2)天 → 300+48.484848
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("348.484848");
    }

    @Test
    @DisplayName("累加量-只统计collection_status=1的记录，且过滤读数/时间为空的记录")
    void cumulative_filtersInvalidRecords_andQueriesStatus1Only() {
        CollectionRecord nullReading = rec("2026-04-01", 6, "999");
        nullReading.setReadingValue(null);
        CollectionRecord nullTime = rec("2026-04-15", 6, "200");
        nullTime.setCollectionTime(null);

        stubRecords(METER_ID, List.of(
                nullReading, nullTime,
                rec("2026-04-01", 6, "100"),
                rec("2026-04-30", 6, "400")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 1, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(1);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("300");
        // 验证查询条件为 collection_status=1
        verify(collectionRecordRepository).findByCollectionPointTypeAndCollectionPointIdAndCollectionStatus(
                1, METER_ID, 1);
    }

    // ========================= 算法B：非累加量采集点 =========================

    @Test
    @DisplayName("非累加量-完整：周期首尾衔接且起止匹配，状态=1，能耗=各周期读数之和")
    void nonCumulative_complete() {
        stubRecords(METER_ID, List.of(
                cycleRec("2026-04-01", "2026-04-10", "100"),
                cycleRec("2026-04-11", "2026-04-20", "100"),
                cycleRec("2026-04-21", "2026-04-30", "100")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 0, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(1);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("300");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("300");
        assertThat(r.getCollectionRecordStartDate()).isEqualTo(CYCLE_START);
        assertThat(r.getCollectionRecordEndDate()).isEqualTo(CYCLE_END);
        assertThat(r.getDataMissingDescription()).isNull();
    }

    @Test
    @DisplayName("非累加量-历史空周期按采集时间所在自然月回填")
    void nonCumulative_missingPeriod_backfillsCalendarMonth() {
        CollectionRecord bad = cycleRec("2026-04-01", "2026-04-10", "100");
        bad.setBillingCycleStartDate(null);
        bad.setBillingCycleEndDate(null);
        stubRecords(METER_ID, List.of(bad));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 0, CYCLE_START, CYCLE_END);

        assertThat(bad.getBillingCycleStartDate()).isEqualTo(CYCLE_START);
        assertThat(bad.getBillingCycleEndDate()).isEqualTo(CYCLE_END);
        assertThat(r.getDataStatus()).isEqualTo(1);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("100");
    }

    @Test
    @DisplayName("非累加量-核算周期内无记录：状态=2，说明为核算周期内无采集数据")
    void nonCumulative_noRecordsInCycle_status2() {
        stubRecords(METER_ID, List.of(
                cycleRec("2026-03-01", "2026-03-10", "50"),
                cycleRec("2026-05-01", "2026-05-10", "60")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 0, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(2);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("0");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("0");
        assertThat(r.getDataMissingDescription()).contains("核算周期内无采集数据");
    }

    @Test
    @DisplayName("非累加量-中间空缺：状态=3，按日均×缺失天数补加")
    void nonCumulative_middleGap_addition() {
        // 04-11至04-12空缺2天；总读数280/28天=日均10
        stubRecords(METER_ID, List.of(
                cycleRec("2026-04-01", "2026-04-10", "100"),
                cycleRec("2026-04-13", "2026-04-20", "80"),
                cycleRec("2026-04-21", "2026-04-30", "100")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 0, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(3);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("280");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("300");
        assertThat(r.getDataMissingDescription()).contains("存在空缺(2026-04-11至2026-04-12)");
    }

    @Test
    @DisplayName("非累加量-周期重叠：状态=3，按日均×重叠天数扣减")
    void nonCumulative_overlap_deduction() {
        // 重叠04-08至04-10共3天；总读数330/33天=日均10
        stubRecords(METER_ID, List.of(
                cycleRec("2026-04-01", "2026-04-10", "100"),
                cycleRec("2026-04-08", "2026-04-20", "130"),
                cycleRec("2026-04-21", "2026-04-30", "100")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 0, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(3);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("330");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("300");
        assertThat(r.getDataMissingDescription()).contains("存在重叠(2026-04-08至2026-04-10)");
    }

    @Test
    @DisplayName("非累加量-起始记录超范围（billing起始早于核算起始）：按日均×超限天数扣减")
    void nonCumulative_startRecordBeforeCycle_deduction() {
        // 起始记录03-30（距04-01差2天），周期内仅04-05..04-30记录；日均=260/26天=10
        stubRecords(METER_ID, List.of(
                cycleRec("2026-03-30", "2026-03-31", "40"),
                cycleRec("2026-04-05", "2026-04-30", "260")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 0, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(3);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("260");
        // 修正值 = 260 - 超限2天×10 = 240
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("240");
        assertThat(r.getDataMissingDescription()).contains("起始日期不匹配").contains("2026-03-30");
    }

    @Test
    @DisplayName("非累加量-截止记录超范围（billing截止晚于核算截止）：按日均×超限天数扣减")
    void nonCumulative_endRecordAfterCycle_deduction() {
        // 截止记录05-03（距04-30差3天），周期内仅04-01..04-25记录；日均=250/25天=10
        stubRecords(METER_ID, List.of(
                cycleRec("2026-04-01", "2026-04-25", "250"),
                cycleRec("2026-05-01", "2026-05-03", "30")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 0, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(3);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("250");
        // 修正值 = 250 - 超限3天×10 = 220
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("220");
        assertThat(r.getDataMissingDescription()).contains("截止日期不匹配").contains("2026-05-03");
    }

    @Test
    @DisplayName("非累加量-例外①：采集点在核算起始日之后才启用，前部缺失不视为不完整")
    void nonCumulative_startAfterCycle_meterEnabledLater_exempt() {
        MeterInfo meter = normalMeter(METER_ID, 0);
        meter.setEnableTime(LocalDate.parse("2026-04-03").atTime(0, 0));
        when(meterInfoRepository.findById(METER_ID)).thenReturn(java.util.Optional.of(meter));
        stubRecords(METER_ID, List.of(
                cycleRec("2026-04-05", "2026-04-30", "260")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 0, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(1);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("260");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("260");
        assertThat(r.getDataMissingDescription()).isNull();
    }

    @Test
    @DisplayName("非累加量-例外②：采集点在核算截止日之前被停用，尾部缺失不视为不完整")
    void nonCumulative_endBeforeCycle_meterDisabledEarlier_exempt() {
        MeterInfo meter = normalMeter(METER_ID, 0);
        meter.setDisableTime(LocalDate.parse("2026-04-26").atTime(0, 0));
        when(meterInfoRepository.findById(METER_ID)).thenReturn(java.util.Optional.of(meter));
        stubRecords(METER_ID, List.of(
                cycleRec("2026-04-01", "2026-04-25", "250")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 0, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(1);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("250");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("250");
        assertThat(r.getDataMissingDescription()).isNull();
    }

    @Test
    @DisplayName("非累加量-例外③：空缺段在停用-再启用区间内属正常空缺，不补加且不计入说明")
    void nonCumulative_gapInDisabledPeriod_exempt_notAdded() {
        // 电表04-09停用、04-21重新启用；真实覆盖空缺[04-11..04-19]落在停用区间内 → 不补加。
        MeterInfo meter = normalMeter(METER_ID, 0);
        meter.setDisableTime(LocalDate.parse("2026-04-09").atTime(0, 0));
        meter.setEnableTime(LocalDate.parse("2026-04-21").atTime(0, 0));
        when(meterInfoRepository.findById(METER_ID)).thenReturn(java.util.Optional.of(meter));
        // 04-05..04-08完全被第一条包含，真实重叠4天。
        stubRecords(METER_ID, List.of(
                cycleRec("2026-04-01", "2026-04-10", "100"),
                cycleRec("2026-04-05", "2026-04-08", "40"),
                cycleRec("2026-04-20", "2026-04-30", "110")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 0, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(3);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("250");
        // 修正值 = 250 - 重叠4天×日均10 = 210；生命周期例外空缺不补加。
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("210");
        assertThat(r.getDataMissingDescription()).contains("存在重叠");
        assertThat(r.getDataMissingDescription()).doesNotContain("存在空缺");
    }

    // ========================= 虚拟电表 / 分摊子电表 =========================

    @Test
    @DisplayName("分摊子电表：用电量=父电表用电量×分摊比例")
    void allocationChild_usageEqualToParentTimesRatio() {
        MeterInfo child = new MeterInfo();
        child.setId(100L);
        child.setIsAllocationChild(1);
        child.setParentMeterId(200L);
        child.setAllocationRatio(new BigDecimal("0.25"));
        MeterInfo parent = normalMeter(200L, 1);
        when(meterInfoRepository.findById(100L)).thenReturn(java.util.Optional.of(child));
        when(meterInfoRepository.findById(200L)).thenReturn(java.util.Optional.of(parent));
        when(meterInfoRepository.findByParentMeterId(200L))
                .thenReturn(List.of(child, normalMeter(201L, 1)));
        stubRecords(200L, List.of(
                rec("2026-04-01", 6, "100"),
                rec("2026-04-30", 6, "500")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, 100L, 0, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(1);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("100"); // 400×0.25
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("100");
        // 推导值无自身采集记录，起止日期为空
        assertThat(r.getCollectionRecordStartDate()).isNull();
        assertThat(r.getCollectionRecordEndDate()).isNull();
    }

    @Test
    @DisplayName("虚拟电表：用电量=父电表用电量-其余子电表用电量之和")
    void virtualMeter_parentMinusSiblings() {
        MeterInfo virtual = new MeterInfo();
        virtual.setId(300L);
        virtual.setIsVirtualMeter(1);
        virtual.setParentMeterId(200L);
        MeterInfo parent = normalMeter(200L, 1);
        MeterInfo sibling1 = normalMeter(400L, 1);
        MeterInfo sibling2 = normalMeter(500L, 1);
        when(meterInfoRepository.findById(300L)).thenReturn(java.util.Optional.of(virtual));
        when(meterInfoRepository.findById(200L)).thenReturn(java.util.Optional.of(parent));
        when(meterInfoRepository.findById(400L)).thenReturn(java.util.Optional.of(sibling1));
        when(meterInfoRepository.findById(500L)).thenReturn(java.util.Optional.of(sibling2));
        when(meterInfoRepository.findByParentMeterId(200L))
                .thenReturn(List.of(virtual, sibling1, sibling2));
        // 父表用电量400，兄弟子表150+100 → 虚拟电表=150
        stubRecords(200L, List.of(
                rec("2026-04-01", 6, "100"),
                rec("2026-04-30", 6, "500")));
        stubRecords(400L, List.of(
                rec("2026-04-01", 6, "50"),
                rec("2026-04-30", 6, "200")));
        stubRecords(500L, List.of(
                rec("2026-04-01", 6, "50"),
                rec("2026-04-30", 6, "150")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, 300L, 0, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(1);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("150");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("150");
    }

    @Test
    @DisplayName("虚拟电表-兄弟表之和大于父表：负值截断为0")
    void virtualMeter_negativeClampedToZero() {
        MeterInfo virtual = new MeterInfo();
        virtual.setId(300L);
        virtual.setIsVirtualMeter(1);
        virtual.setParentMeterId(200L);
        MeterInfo parent = normalMeter(200L, 1);
        MeterInfo sibling1 = normalMeter(400L, 1);
        MeterInfo sibling2 = normalMeter(500L, 1);
        when(meterInfoRepository.findById(300L)).thenReturn(java.util.Optional.of(virtual));
        when(meterInfoRepository.findById(200L)).thenReturn(java.util.Optional.of(parent));
        when(meterInfoRepository.findById(400L)).thenReturn(java.util.Optional.of(sibling1));
        when(meterInfoRepository.findById(500L)).thenReturn(java.util.Optional.of(sibling2));
        when(meterInfoRepository.findByParentMeterId(200L))
                .thenReturn(List.of(virtual, sibling1, sibling2));
        // 父表400 - 兄弟表250+200=450 → -50 → 截0
        stubRecords(200L, List.of(
                rec("2026-04-01", 6, "100"),
                rec("2026-04-30", 6, "500")));
        stubRecords(400L, List.of(
                rec("2026-04-01", 6, "50"),
                rec("2026-04-30", 6, "300")));
        stubRecords(500L, List.of(
                rec("2026-04-01", 6, "50"),
                rec("2026-04-30", 6, "250")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, 300L, 0, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(1);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("0");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("0");
    }

    @Test
    @DisplayName("虚拟电表父表无数据但自身有读数：回退使用自身审核记录")
    void virtualMeter_parentNoData_fallsBackToOwnRecords() {
        MeterInfo virtual = new MeterInfo();
        virtual.setId(300L);
        virtual.setIsVirtualMeter(1);
        virtual.setIsCumulative(1);
        virtual.setParentMeterId(200L);
        MeterInfo parent = normalMeter(200L, 1);
        when(meterInfoRepository.findById(300L)).thenReturn(java.util.Optional.of(virtual));
        when(meterInfoRepository.findById(200L)).thenReturn(java.util.Optional.of(parent));
        stubRecords(200L, new ArrayList<>());
        stubRecords(300L, List.of(
                rec("2026-04-01", 6, "100"),
                rec("2026-04-30", 6, "300")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, 300L, 0, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(1);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("200");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("200");
    }

    @Test
    @DisplayName("虚拟电表-父电表无采集数据：状态=2，说明包含父电表信息")
    void virtualMeter_parentNoData_status2() {
        MeterInfo virtual = new MeterInfo();
        virtual.setId(300L);
        virtual.setIsVirtualMeter(1);
        virtual.setParentMeterId(200L);
        MeterInfo parent = normalMeter(200L, 1);
        when(meterInfoRepository.findById(300L)).thenReturn(java.util.Optional.of(virtual));
        when(meterInfoRepository.findById(200L)).thenReturn(java.util.Optional.of(parent));
        stubRecords(200L, new ArrayList<>());

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, 300L, 0, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(2);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("0");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("0");
        assertThat(r.getDataMissingDescription()).contains("父电表").contains("200");
    }

    // ========================= 边界条件补充测试 =========================

    /** 桩：指定采集点类型与ID返回成功采集记录（用于化石燃料/外购热能采集点） */
    private void stubRecords(int pointType, long pointId, List<CollectionRecord> records) {
        when(collectionRecordRepository.findByCollectionPointTypeAndCollectionPointIdAndCollectionStatus(
                pointType, pointId, 1)).thenReturn(records);
    }

    // ---------- 累加量边界 ----------

    @Test
    @DisplayName("累加量-6点整边界：恰好6点采集算当天（次日凌晨6点整→截止日超范围1天）")
    void cumulative_exactly6am_countsAsSameDay() {
        // 05-01 06:00 整点采集 → 有效日期=05-01（不算前一天），距截止日超范围1天
        stubRecords(METER_ID, List.of(
                rec("2026-04-01", 6, "100"),
                rec("2026-05-01", 6, "400")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 1, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(4);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("300");
        // 日均=(400-100)/30天=10，扣减超限1天×10=290
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("290");
        assertThat(r.getDataMissingDescription()).contains("截止日期数据超限(实际:2026-05-01)");
    }

    @Test
    @DisplayName("累加量-仅一条记录：起止为同一条记录，能耗=0，日均=0，修正值=0")
    void cumulative_singleRecord_zeroEnergyZeroAvg() {
        stubRecords(METER_ID, List.of(rec("2026-04-01", 6, "100")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 1, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(3);
        assertThat(r.getCollectionRecordStartDate()).isEqualTo(CYCLE_START);
        assertThat(r.getCollectionRecordEndDate()).isEqualTo(CYCLE_START);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("0");
        // 记录数<2 → 日均=0，缺失29天补加0
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("0");
        assertThat(r.getDataMissingDescription()).contains("截止日期无数据");
    }

    @Test
    @DisplayName("累加量-截止读数小于起始读数（表计重置）：能耗截断为0")
    void cumulative_readingDecreased_clampedToZero() {
        stubRecords(METER_ID, List.of(
                rec("2026-04-01", 6, "500"),
                rec("2026-04-30", 6, "400")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 1, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(3);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("0");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("0");
        assertThat(r.getDataMissingDescription()).contains("累计读数倒退");
    }

    @Test
    @DisplayName("累加量-双侧均超范围：状态=4（非5），扣减两侧超限天数×日均")
    void cumulative_bothOverRange_status4() {
        // 记录：03-30→100、05-02→500；日均=400/33天=12.121212
        stubRecords(METER_ID, List.of(
                rec("2026-03-30", 6, "100"),
                rec("2026-05-02", 6, "500")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 1, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(4);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("400");
        // 修正值 = 400 - (2+2)天×12.121212 = 351.515152
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("351.515152");
        assertThat(r.getDataMissingDescription())
                .contains("起始日期超限(实际:2026-03-30)")
                .contains("截止日期数据超限(实际:2026-05-02)");
    }

    @Test
    @DisplayName("累加量-例外①变体：创建时间晚于起始日（enableTime为空）同样豁免")
    void cumulative_createdAtAfterCycleStart_exempt() {
        MeterInfo meter = normalMeter(METER_ID, 1);
        meter.setCreatedAt(LocalDate.parse("2026-04-02").atTime(0, 0));
        when(meterInfoRepository.findById(METER_ID)).thenReturn(java.util.Optional.of(meter));
        stubRecords(METER_ID, List.of(
                rec("2026-04-05", 6, "100"),
                rec("2026-04-30", 6, "400")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 1, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(1);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("300");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("300");
        assertThat(r.getDataMissingDescription()).isNull();
    }

    @Test
    @DisplayName("累加量-启用时间恰好等于起始日：例外不适用，状态=3并补加缺失")
    void cumulative_enableTimeEqualsCycleStart_notExempt() {
        MeterInfo meter = normalMeter(METER_ID, 1);
        meter.setEnableTime(LocalDate.parse("2026-04-01").atTime(0, 0));
        when(meterInfoRepository.findById(METER_ID)).thenReturn(java.util.Optional.of(meter));
        // 记录：04-03→100、04-30→400；日均=(400-100)/27天=11.111111
        stubRecords(METER_ID, List.of(
                rec("2026-04-03", 6, "100"),
                rec("2026-04-30", 6, "400")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 1, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(3);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("300");
        // 补加缺失2天×11.111111 = 322.222222
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("322.222222");
        assertThat(r.getDataMissingDescription()).contains("起始日期无数据");
    }

    @Test
    @DisplayName("累加量-停用时间恰好等于截止日：例外不适用，状态=3并补加缺失")
    void cumulative_disableTimeEqualsCycleEnd_notExempt() {
        MeterInfo meter = normalMeter(METER_ID, 1);
        meter.setDisableTime(LocalDate.parse("2026-04-30").atTime(0, 0));
        when(meterInfoRepository.findById(METER_ID)).thenReturn(java.util.Optional.of(meter));
        // 记录：04-01→100、04-28→390；日均=290/27天=10.740741
        stubRecords(METER_ID, List.of(
                rec("2026-04-01", 6, "100"),
                rec("2026-04-28", 6, "390")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 1, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(3);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("290");
        // 补加缺失2天×10.740741 = 311.481482
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("311.481482");
        assertThat(r.getDataMissingDescription()).contains("截止日期无数据");
    }

    @Test
    @DisplayName("累加量-化石燃料采集点(type=2)：创建时间例外同样生效")
    void cumulative_fossilMeter_createdAtExempt() {
        FossilFuelMeterInfo fossil = new FossilFuelMeterInfo();
        fossil.setId(20L);
        fossil.setCreatedAt(LocalDate.parse("2026-04-02").atTime(0, 0));
        when(fossilFuelMeterInfoRepository.findById(20L)).thenReturn(java.util.Optional.of(fossil));
        stubRecords(2, 20L, List.of(
                rec("2026-04-05", 6, "100"),
                rec("2026-04-30", 6, "400")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(2, 20L, 1, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(1);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("300");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("300");
        assertThat(r.getDataMissingDescription()).isNull();
    }

    @Test
    @DisplayName("累加量-外购热能采集点(type=3)：停用时间例外同样生效")
    void cumulative_heatMeter_disabledEarlier_exempt() {
        PurchasedHeatMeterInfo heat = new PurchasedHeatMeterInfo();
        heat.setId(30L);
        heat.setDisableTime(LocalDate.parse("2026-04-26").atTime(0, 0));
        when(purchasedHeatMeterInfoRepository.findById(30L)).thenReturn(java.util.Optional.of(heat));
        stubRecords(3, 30L, List.of(
                rec("2026-04-01", 6, "100"),
                rec("2026-04-25", 6, "350")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(3, 30L, 1, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(1);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("250");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("250");
        assertThat(r.getDataMissingDescription()).isNull();
    }

    // ---------- 非累加量边界 ----------

    @Test
    @DisplayName("非累加量-相邻周期共享1天：重叠1天，按日均扣减")
    void nonCumulative_adjacentCyclesShareOneDay_overlap1() {
        // 周期[04-01..04-10]与[04-10..04-20]共享04-10；21天210 → 日均10
        stubRecords(METER_ID, List.of(
                cycleRec("2026-04-01", "2026-04-10", "100"),
                cycleRec("2026-04-10", "2026-04-20", "110")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 0, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(3);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("210");
        // 2026-11-10确认：扣重叠1天，再补月末10天，210-10+100=300。
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("300");
        assertThat(r.getDataMissingDescription()).contains("存在重叠(2026-04-10至2026-04-10)");
    }

    @Test
    @DisplayName("非累加量-记录完全包含另一条：按包含天数扣减重叠")
    void nonCumulative_fullyContainedRecord_deduction() {
        // [04-01..04-20]完全包含[04-05..04-10]，真实重叠6天；26天260 → 日均10。
        stubRecords(METER_ID, List.of(
                cycleRec("2026-04-01", "2026-04-20", "200"),
                cycleRec("2026-04-05", "2026-04-10", "60")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 0, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(3);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("260");
        // 扣重叠6天，补首尾规则下月末10天：260-60+100=300。
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("300");
        assertThat(r.getDataMissingDescription()).contains("存在重叠(2026-04-05至2026-04-10)");
    }

    @Test
    @DisplayName("非累加量-多个嵌套周期按真实交集扣重叠，不虚构中间缺口")
    void nonCumulative_nestedPeriods_useCoveredUnion() {
        stubRecords(METER_ID, List.of(
                cycleRec("2026-04-01", "2026-04-30", "300"),
                cycleRec("2026-04-05", "2026-04-10", "60"),
                cycleRec("2026-04-08", "2026-04-15", "80")));
        EnergyMeasurementCalculator.Result r = calculator.calculate(1, METER_ID, 0, CYCLE_START, CYCLE_END);
        assertThat(r.getDataStatus()).isEqualTo(3);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("440");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("300");
        assertThat(r.getDataMissingDescription()).contains("2026-04-05至2026-04-10", "2026-04-08至2026-04-15").doesNotContain("存在空缺");
    }

    @Test
    @DisplayName("非累加量-空缺段仅部分落入停用区间：例外不适用，仍按日均补加")
    void nonCumulative_gapPartiallyInDisabledPeriod_stillAdded() {
        // 停用[04-07..04-15]，空缺[04-05..04-12]起始早于停用日 → 不完全包含 → 补加
        MeterInfo meter = normalMeter(METER_ID, 0);
        meter.setDisableTime(LocalDate.parse("2026-04-07").atTime(0, 0));
        meter.setEnableTime(LocalDate.parse("2026-04-15").atTime(0, 0));
        when(meterInfoRepository.findById(METER_ID)).thenReturn(java.util.Optional.of(meter));
        // 空缺04-05..04-12共8天；周期内22天220 → 日均10
        stubRecords(METER_ID, List.of(
                cycleRec("2026-04-01", "2026-04-04", "40"),
                cycleRec("2026-04-13", "2026-04-30", "180")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 0, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(3);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("220");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("300");
        assertThat(r.getDataMissingDescription()).contains("存在空缺(2026-04-05至2026-04-12)");
    }

    @Test
    @DisplayName("非累加量-启用时间早于停用时间（非停用后再启用）：空缺例外不适用，仍补加")
    void nonCumulative_enableBeforeDisable_gapStillAdded() {
        // enableTime(03-01)早于disableTime(04-20)，不构成"停用后再启用" → 空缺补加
        MeterInfo meter = normalMeter(METER_ID, 0);
        meter.setEnableTime(LocalDate.parse("2026-03-01").atTime(0, 0));
        meter.setDisableTime(LocalDate.parse("2026-04-20").atTime(0, 0));
        when(meterInfoRepository.findById(METER_ID)).thenReturn(java.util.Optional.of(meter));
        // 空缺04-11..04-14共4天；26天260 → 日均10
        stubRecords(METER_ID, List.of(
                cycleRec("2026-04-01", "2026-04-10", "100"),
                cycleRec("2026-04-15", "2026-04-30", "160")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 0, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(3);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("260");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("300");
        assertThat(r.getDataMissingDescription()).contains("存在空缺(2026-04-11至2026-04-14)");
    }

    @Test
    @DisplayName("非累加量-停用时间恰好等于截止日：尾部例外不适用，状态=3")
    void nonCumulative_disableTimeEqualsCycleEnd_notExempt() {
        MeterInfo meter = normalMeter(METER_ID, 0);
        meter.setDisableTime(LocalDate.parse("2026-04-30").atTime(0, 0));
        when(meterInfoRepository.findById(METER_ID)).thenReturn(java.util.Optional.of(meter));
        stubRecords(METER_ID, List.of(
                cycleRec("2026-04-01", "2026-04-25", "250")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 0, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(3);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("250");
        assertThat(r.getDataMissingDescription()).contains("截止日期不匹配(实际:2026-04-25)");
        // 2026-11-10确认：非生命周期豁免，按日均10补月末5天，保留状态3。
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("300");
    }

    @Test
    @DisplayName("非累加量-创建时间恰好等于起始日：前部例外不适用，状态=3")
    void nonCumulative_createdAtEqualsCycleStart_notExempt() {
        MeterInfo meter = normalMeter(METER_ID, 0);
        meter.setCreatedAt(LocalDate.parse("2026-04-01").atTime(0, 0));
        when(meterInfoRepository.findById(METER_ID)).thenReturn(java.util.Optional.of(meter));
        stubRecords(METER_ID, List.of(
                cycleRec("2026-04-03", "2026-04-30", "280")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 0, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(3);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("280");
        assertThat(r.getDataMissingDescription()).contains("起始日期不匹配(实际:2026-04-03)");
        // 2026-11-10确认：非生命周期豁免，按日均10补月初2天，保留状态3。
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("300");
    }

    @Test
    @DisplayName("非累加量-空读数与空采集时间记录被过滤，仅有效记录参与求和")
    void nonCumulative_nullReadingAndNullCollectionTime_filtered() {
        CollectionRecord nullReading = cycleRec("2026-04-01", "2026-04-15", "999");
        nullReading.setReadingValue(null);
        CollectionRecord nullCollectionTime = cycleRec("2026-04-10", "2026-04-20", "999");
        nullCollectionTime.setCollectionTime(null);

        stubRecords(METER_ID, List.of(
                nullReading, nullCollectionTime,
                cycleRec("2026-04-01", "2026-04-30", "300")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, 0, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(1);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("300");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("300");
        assertThat(r.getDataMissingDescription()).isNull();
    }

    // ---------- 虚拟电表 / 分摊子电表边界 ----------

    @Test
    @DisplayName("分摊子电表-分摊比例为空：运行期防线拒绝计算")
    void allocationChild_nullRatio_rejected() {
        MeterInfo child = new MeterInfo();
        child.setId(100L);
        child.setIsAllocationChild(1);
        child.setParentMeterId(200L);
        child.setAllocationRatio(null);
        MeterInfo parent = normalMeter(200L, 1);
        when(meterInfoRepository.findById(100L)).thenReturn(java.util.Optional.of(child));
        when(meterInfoRepository.findById(200L)).thenReturn(java.util.Optional.of(parent));
        when(meterInfoRepository.findByParentMeterId(200L))
                .thenReturn(List.of(child, normalMeter(201L, 1)));
        stubRecords(200L, List.of(
                rec("2026-04-01", 6, "100"),
                rec("2026-04-30", 6, "500")));

        assertThatThrownBy(() -> calculator.calculate(1, 100L, 0, CYCLE_START, CYCLE_END))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("分摊比例");
    }

    @Test
    @DisplayName("分摊子电表-父表数据不完整：状态与说明继承父表")
    void allocationChild_parentIncomplete_statusInherited() {
        MeterInfo child = new MeterInfo();
        child.setId(100L);
        child.setIsAllocationChild(1);
        child.setParentMeterId(200L);
        child.setAllocationRatio(new BigDecimal("0.5"));
        MeterInfo parent = normalMeter(200L, 1);
        when(meterInfoRepository.findById(100L)).thenReturn(java.util.Optional.of(child));
        when(meterInfoRepository.findById(200L)).thenReturn(java.util.Optional.of(parent));
        when(meterInfoRepository.findByParentMeterId(200L))
                .thenReturn(List.of(child, normalMeter(201L, 1)));
        // 父表起始记录晚于核算起始日 → 状态3；父表能耗=400-100=300
        stubRecords(200L, List.of(
                rec("2026-04-05", 6, "100"),
                rec("2026-04-30", 6, "400")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, 100L, 0, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(3);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("150"); // 原始300×0.5
        // 父表缺失4天，修正值348；分摊表修正值=348×0.5
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("174");
        assertThat(r.getDataMissingDescription()).contains("父电表数据不完整");
    }

    @Test
    @DisplayName("嵌套虚拟分摊：补差后的两个0.5子表分别传递原始量与修正量")
    void nestedVirtualAllocation_propagatesRawAndAdjustedValues() {
        MeterInfo allocationA = new MeterInfo();
        allocationA.setId(100L);
        allocationA.setIsVirtualMeter(1);
        allocationA.setIsAllocationChild(1);
        allocationA.setParentMeterId(300L);
        allocationA.setAllocationRatio(new BigDecimal("0.5"));

        MeterInfo allocationB = new MeterInfo();
        allocationB.setId(101L);
        allocationB.setIsVirtualMeter(1);
        allocationB.setIsAllocationChild(1);
        allocationB.setParentMeterId(300L);
        allocationB.setAllocationRatio(new BigDecimal("0.5"));

        MeterInfo virtualPool = new MeterInfo();
        virtualPool.setId(300L);
        virtualPool.setIsVirtualMeter(1);
        virtualPool.setIsAllocationChild(0);
        virtualPool.setParentMeterId(200L);

        MeterInfo parent = normalMeter(200L, 1);
        MeterInfo sibling = normalMeter(400L, 1);
        sibling.setParentMeterId(200L);

        when(meterInfoRepository.findById(100L)).thenReturn(java.util.Optional.of(allocationA));
        when(meterInfoRepository.findById(300L)).thenReturn(java.util.Optional.of(virtualPool));
        when(meterInfoRepository.findById(200L)).thenReturn(java.util.Optional.of(parent));
        when(meterInfoRepository.findById(400L)).thenReturn(java.util.Optional.of(sibling));
        when(meterInfoRepository.findByParentMeterId(300L)).thenReturn(List.of(allocationA, allocationB));
        when(meterInfoRepository.findByParentMeterId(200L)).thenReturn(List.of(virtualPool, sibling));

        // 父表原始300，起始缺4天后修正348；兄弟表完整100。
        // 虚拟补差原始200/修正248，再按0.5分配为原始100/修正124。
        stubRecords(200L, List.of(
                rec("2026-04-05", 6, "100"),
                rec("2026-04-30", 6, "400")));
        stubRecords(400L, List.of(
                rec("2026-04-01", 6, "50"),
                rec("2026-04-30", 6, "150")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, 100L, 0, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(3);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("100");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("124");
        assertThat(r.getDataMissingDescription()).contains("父电表数据不完整");
    }

    @Test
    @DisplayName("分摊子电表-父表无采集数据：状态=2，说明含父电表信息")
    void allocationChild_parentNoData_status2() {
        MeterInfo child = new MeterInfo();
        child.setId(100L);
        child.setIsAllocationChild(1);
        child.setParentMeterId(200L);
        MeterInfo parent = normalMeter(200L, 1);
        when(meterInfoRepository.findById(100L)).thenReturn(java.util.Optional.of(child));
        when(meterInfoRepository.findById(200L)).thenReturn(java.util.Optional.of(parent));
        stubRecords(200L, new ArrayList<>());

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, 100L, 0, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(2);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("0");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("0");
        assertThat(r.getDataMissingDescription()).contains("父电表(id=200)");
    }

    @Test
    @DisplayName("虚拟电表-父表下无其他子表：用电量=父表用电量")
    void virtualMeter_noSiblings_usageEqualsParent() {
        MeterInfo virtual = new MeterInfo();
        virtual.setId(300L);
        virtual.setIsVirtualMeter(1);
        virtual.setParentMeterId(200L);
        MeterInfo parent = normalMeter(200L, 1);
        when(meterInfoRepository.findById(300L)).thenReturn(java.util.Optional.of(virtual));
        when(meterInfoRepository.findById(200L)).thenReturn(java.util.Optional.of(parent));
        when(meterInfoRepository.findByParentMeterId(200L)).thenReturn(List.of(virtual));
        stubRecords(200L, List.of(
                rec("2026-04-01", 6, "100"),
                rec("2026-04-30", 6, "500")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, 300L, 0, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(1);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("400");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("400");
    }

    @Test
    @DisplayName("虚拟电表-部分兄弟表无数据：状态=3，说明含无数据子表ID")
    void virtualMeter_siblingNoData_status3() {
        MeterInfo virtual = new MeterInfo();
        virtual.setId(300L);
        virtual.setIsVirtualMeter(1);
        virtual.setParentMeterId(200L);
        MeterInfo parent = normalMeter(200L, 1);
        MeterInfo sibling1 = normalMeter(400L, 1);
        MeterInfo sibling2 = normalMeter(500L, 1);
        when(meterInfoRepository.findById(300L)).thenReturn(java.util.Optional.of(virtual));
        when(meterInfoRepository.findById(200L)).thenReturn(java.util.Optional.of(parent));
        when(meterInfoRepository.findById(400L)).thenReturn(java.util.Optional.of(sibling1));
        when(meterInfoRepository.findById(500L)).thenReturn(java.util.Optional.of(sibling2));
        when(meterInfoRepository.findByParentMeterId(200L))
                .thenReturn(List.of(virtual, sibling1, sibling2));
        // 父表400，兄弟表sibling1=150，sibling2无数据 → 虚拟电表=250
        stubRecords(200L, List.of(
                rec("2026-04-01", 6, "100"),
                rec("2026-04-30", 6, "500")));
        stubRecords(400L, List.of(
                rec("2026-04-01", 6, "50"),
                rec("2026-04-30", 6, "200")));
        stubRecords(500L, new ArrayList<>());

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, 300L, 0, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(3);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("250");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("250");
        assertThat(r.getDataMissingDescription())
                .contains("部分子电表无数据")
                .contains("子电表(id=500)无数据");
    }

    @Test
    @DisplayName("虚拟电表-父表数据不完整：状态=3，说明含父表状态")
    void virtualMeter_parentIncomplete_descContainsParentStatus() {
        MeterInfo virtual = new MeterInfo();
        virtual.setId(300L);
        virtual.setIsVirtualMeter(1);
        virtual.setParentMeterId(200L);
        MeterInfo parent = normalMeter(200L, 1);
        MeterInfo sibling = normalMeter(400L, 1);
        when(meterInfoRepository.findById(300L)).thenReturn(java.util.Optional.of(virtual));
        when(meterInfoRepository.findById(200L)).thenReturn(java.util.Optional.of(parent));
        when(meterInfoRepository.findById(400L)).thenReturn(java.util.Optional.of(sibling));
        when(meterInfoRepository.findByParentMeterId(200L))
                .thenReturn(List.of(virtual, sibling));
        // 父表起始记录04-05晚于核算起始日 → 状态3，值300；兄弟表100 → 虚拟电表=200
        stubRecords(200L, List.of(
                rec("2026-04-05", 6, "100"),
                rec("2026-04-30", 6, "400")));
        stubRecords(400L, List.of(
                rec("2026-04-01", 6, "50"),
                rec("2026-04-30", 6, "150")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, 300L, 0, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(3);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("200");
        // 父表原始300修正348，兄弟表完整100，虚拟表修正值应为248
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("248");
        assertThat(r.getDataMissingDescription()).contains("虚拟电表推导").contains("父电表数据不完整");
    }

    @Test
    @DisplayName("虚拟电表-父表相互循环引用：visited防护生效，状态=2")
    void virtualMeter_circularReference_guard() {
        // 电表300(虚拟,父=200)与电表200(虚拟,父=300)互相引用
        MeterInfo virtualA = new MeterInfo();
        virtualA.setId(300L);
        virtualA.setIsVirtualMeter(1);
        virtualA.setParentMeterId(200L);
        MeterInfo virtualB = new MeterInfo();
        virtualB.setId(200L);
        virtualB.setIsVirtualMeter(1);
        virtualB.setParentMeterId(300L);
        when(meterInfoRepository.findById(300L)).thenReturn(java.util.Optional.of(virtualA));
        when(meterInfoRepository.findById(200L)).thenReturn(java.util.Optional.of(virtualB));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, 300L, 0, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(2);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("0");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("0");
        assertThat(r.getDataMissingDescription()).contains("父电表(id=200)");
    }

    // ---------- 公共入口边界 ----------

    @Test
    @DisplayName("isCumulative为空：按非累加量算法处理")
    void calculate_nullIsCumulative_treatedAsNonCumulative() {
        when(meterInfoRepository.findById(METER_ID))
                .thenReturn(java.util.Optional.of(normalMeter(METER_ID, null)));
        stubRecords(METER_ID, List.of(
                cycleRec("2026-04-01", "2026-04-10", "100"),
                cycleRec("2026-04-11", "2026-04-20", "100"),
                cycleRec("2026-04-21", "2026-04-30", "100")));

        EnergyMeasurementCalculator.Result r =
                calculator.calculate(1, METER_ID, null, CYCLE_START, CYCLE_END);

        assertThat(r.getDataStatus()).isEqualTo(1);
        assertThat(r.getEnergyMeasurementValue()).isEqualByComparingTo("300");
        assertThat(r.getAdjustedEnergyValue()).isEqualByComparingTo("300");
    }
}
