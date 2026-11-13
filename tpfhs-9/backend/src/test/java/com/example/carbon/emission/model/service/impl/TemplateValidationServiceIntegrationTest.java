package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.dto.TemplateValidationResultVO;
import com.example.carbon.emission.model.entity.DefaultFactor;
import com.example.carbon.emission.model.entity.EmissionFactorTemplate;
import com.example.carbon.emission.model.entity.EmissionNode;
import com.example.carbon.emission.model.entity.EmissionNodeConfig;
import com.example.carbon.emission.model.entity.ElectricityCarbonEmissionFactor;
import com.example.carbon.emission.model.entity.FossilFuelMeterInfo;
import com.example.carbon.emission.model.entity.MeterInfo;
import com.example.carbon.emission.model.entity.Template;
import com.example.carbon.emission.model.repository.DefaultFactorRepository;
import com.example.carbon.emission.model.repository.EmissionFactorTemplateRepository;
import com.example.carbon.emission.model.repository.EmissionNodeConfigRepository;
import com.example.carbon.emission.model.repository.EmissionNodeRepository;
import com.example.carbon.emission.model.repository.ElectricityCarbonEmissionFactorRepository;
import com.example.carbon.emission.model.repository.FossilFuelMeterInfoRepository;
import com.example.carbon.emission.model.repository.MeterInfoRepository;
import com.example.carbon.emission.model.repository.TemplateRepository;
import com.example.carbon.emission.model.service.TemplateService;
import com.example.carbon.emission.model.service.TemplateValidationService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.boot.test.autoconfigure.orm.jpa.TestEntityManager;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.TestPropertySource;

import java.math.BigDecimal;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 模版校验服务集成测试
 * <p>
 * 使用 H2 内存库（MySQL 兼容模式）+ 真实 Repository 层验证完整持久化链路：
 * 数据经由 Repository 真实入库，校验结果真实写入 emission_template，
 * 并通过 flush/clear 后重新从数据库加载进行断言（绕过一级缓存）。
 * <p>
 * 说明：不使用 schema.sql（含 MySQL 特有语句），改由 Hibernate 按实体
 * 自动建表（ddl-auto=create-drop）；每个测试方法在事务内运行并自动回滚，
 * 保证用例间隔离。
 */
@DataJpaTest
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
@Import({TemplateValidationServiceImpl.class, TemplateServiceImpl.class, NodeInclusionResolver.class,
        EffectiveFactorResolver.class})
@TestPropertySource(properties = {
        "spring.datasource.url=jdbc:h2:mem:validationtest;MODE=MySQL;DATABASE_TO_LOWER=TRUE;CASE_INSENSITIVE_IDENTIFIERS=TRUE;DB_CLOSE_DELAY=-1",
        "spring.datasource.driver-class-name=org.h2.Driver",
        "spring.datasource.username=sa",
        "spring.datasource.password=",
        "spring.sql.init.mode=never",
        "spring.jpa.hibernate.ddl-auto=create-drop"
})
@DisplayName("碳排放核算模版校验服务集成测试")
class TemplateValidationServiceIntegrationTest {
    @org.springframework.boot.test.mock.mockito.MockBean
    private CompanyOwnershipService companies;


    @MockBean
    private TaskScheduleConfigService taskScheduleConfigService;

    @Autowired
    private TestEntityManager entityManager;

    @Autowired
    private TemplateRepository templateRepository;

    @Autowired
    private EmissionNodeRepository nodeRepository;

    @Autowired
    private EmissionNodeConfigRepository configRepository;

    @Autowired
    private MeterInfoRepository meterInfoRepository;

    @Autowired
    private FossilFuelMeterInfoRepository fossilFuelMeterInfoRepository;

    @Autowired
    private DefaultFactorRepository defaultFactorRepository;

    @Autowired
    private ElectricityCarbonEmissionFactorRepository electricityFactorRepository;

    @Autowired
    private EmissionFactorTemplateRepository factorTemplateRepository;

    @Autowired
    private TemplateValidationService validationService;

    @Autowired
    private TemplateService templateService;

    /**
     * 本类关注校验结果的真实持久化；量纲解析本身由 FactorDimensionServiceTest 覆盖。
     */
    @MockBean
    private FactorDimensionService factorDimensionService;

    // ========================= 测试数据准备 =========================

    /**
     * 标准场景数据：因子模版（含"外购电力"缺省因子）+ 核算模版 +
     * 根节点→核算节点→采集节点 三级树 + 启用的电力表 + 节点配置
     *
     * @param configSubcategory 节点配置的小类（null 表示不设置，触发回退逻辑）
     * @param ownFactor         节点单独设置的因子（null 表示不设置）
     * @param meterStatus       电力表状态（1-启用，0-停用）
     * @return 持久化后的核算模版
     */
    private Template setupStandardData(String configSubcategory, BigDecimal ownFactor, Integer meterStatus) {
        // 因子模版 + 缺省因子（真实入库以生成自增ID）
        EmissionFactorTemplate ft = new EmissionFactorTemplate();
        ft.setTemplateName("因子模版A");
        ft = factorTemplateRepository.save(ft);

        ElectricityCarbonEmissionFactor sourceFactor = new ElectricityCarbonEmissionFactor();
        sourceFactor.setFactorName("测试电力因子");
        sourceFactor.setFactorValue(new BigDecimal("0.5568"));
        sourceFactor.setUnit("tCO₂/MWh");
        sourceFactor.setEfSourceAuthority("official_national");
        sourceFactor.setEfCompletenessScope("full");
        sourceFactor.setEfDataRegion("in_boundary");
        sourceFactor.setEfDataYear(2025);
        sourceFactor.setEfTechApplicability("same_equipment_condition");
        sourceFactor.setEfConversionChain("direct_match");
        sourceFactor = electricityFactorRepository.save(sourceFactor);

        DefaultFactor factor = new DefaultFactor();
        factor.setTemplateId(ft.getId());
        factor.setSubcategoryCode("PE_01");
        factor.setSubcategoryName("外购电力");
        factor.setFactorSource("ELECTRICITY");
        factor.setFactorId(sourceFactor.getId());
        factor.setFactorValue(new BigDecimal("0.5568"));
        factor.setFactorUnit("tCO₂/MWh");
        defaultFactorRepository.save(factor);

        // 核算模版
        Template template = new Template();
        template.setName("核算模版A");
        template.setTemplateType(2);
        template.setCreatedBy(1L);
        template.setFactorTemplateId(ft.getId());
        template = templateRepository.save(template);

        // 电力表（point_id 非空约束，填占位值；仅实体层校验，无表间FK）
        MeterInfo meter = new MeterInfo();
        meter.setName("一号电表");
        meter.setEmissionSubcategory("外购电力");
        meter.setMeasurementUnit("MWh");
        meter.setStatus(meterStatus);
        meter.setPointId(0L);
        meter.setAdMeteringTier("online_meter");
        meter.setAdMeterCalibration("calib_valid_cert");
        meter.setAdGeoBasis("direct_metered");
        meter = meterInfoRepository.save(meter);

        // 三级节点树
        EmissionNode root = persistNode(template, "厂区", 1, null);
        EmissionNode calc = persistNode(template, "车间", 2, root.getId());
        EmissionNode collection = persistNode(template, "电表节点", 3, calc.getId());

        // 采集节点配置
        EmissionNodeConfig config = new EmissionNodeConfig();
        config.setNodeId(collection.getId());
        config.setCollectionPointType(1);
        config.setCollectionPointId(meter.getId());
        config.setEmissionSubcategory(configSubcategory);
        config.setCarbonEmissionFactor(ownFactor);
        if (ownFactor != null) {
            config.setCarbonEmissionFactorUnit("tCO₂/MWh");
        }
        configRepository.save(config);

        return template;
    }

    /** 持久化节点 */
    private EmissionNode persistNode(Template template, String name, int typeId, Long parentId) {
        EmissionNode node = new EmissionNode();
        node.setName(name);
        node.setTypeId(typeId);
        node.setParentId(parentId);
        node.setTemplateId(template.getId());
        return nodeRepository.save(node);
    }

    /** 刷新一级缓存后从数据库重新加载模版（验证真实落库） */
    private Template reloadTemplate(Long id) {
        entityManager.flush();
        entityManager.clear();
        return templateRepository.findById(id).orElseThrow();
    }

    // ========================= 集成测试用例 =========================

    @Test
    @DisplayName("完整正确场景：校验结果=1并真实写入emission_template")
    void validate_happyPath_persistsResultToDatabase() {
        Template template = setupStandardData("外购电力", null, 1);

        TemplateValidationResultVO vo = validationService.validateTemplate(template.getId());

        assertThat(vo.getCheckResult()).isEqualTo(1);
        assertThat(vo.getItems()).isEmpty();

        // flush+clear 后从数据库重新加载，验证结果真实落库（而非仅内存对象）
        Template reloaded = reloadTemplate(template.getId());
        assertThat(reloaded.getCheckResult()).isEqualTo(1);
        assertThat(reloaded.getCheckTime()).isNotNull();
        assertThat(reloaded.getCheckMessage()).contains("【通过】").contains("校验时间：");
    }

    @Test
    @DisplayName("电力表不存在：校验结果=4并真实落库")
    void validate_meterMissing_persistsError() {
        Template template = setupStandardData("外购电力", null, 1);
        // 将节点配置指向不存在的采集点ID
        EmissionNodeConfig config = configRepository.findAll().get(0);
        config.setCollectionPointId(99999L);
        configRepository.save(config);

        TemplateValidationResultVO vo = validationService.validateTemplate(template.getId());

        assertThat(vo.getCheckResult()).isEqualTo(4);
        assertThat(vo.getItems()).anySatisfy(item ->
                assertThat(item.getMessage()).contains("电力表不存在"));

        Template reloaded = reloadTemplate(template.getId());
        assertThat(reloaded.getCheckResult()).isEqualTo(4);
        assertThat(reloaded.getCheckMessage()).contains("【错误】");
    }

    @Test
    @DisplayName("电力表停用：校验结果=4并真实落库")
    void validate_meterDisabled_persistsError() {
        Template template = setupStandardData("外购电力", null, 0);

        TemplateValidationResultVO vo = validationService.validateTemplate(template.getId());

        assertThat(vo.getCheckResult()).isEqualTo(4);
        assertThat(vo.getItems()).anySatisfy(item ->
                assertThat(item.getMessage()).contains("停用状态"));

        Template reloaded = reloadTemplate(template.getId());
        assertThat(reloaded.getCheckResult()).isEqualTo(4);
    }

    @Test
    @DisplayName("化石燃料采集点停用：走真实FossilFuel表校验，结果=4")
    void validate_fossilMeterDisabled_persistsError() {
        // 因子模版改含"天然气"因子
        EmissionFactorTemplate ft = new EmissionFactorTemplate();
        ft.setTemplateName("化石因子模版");
        ft = factorTemplateRepository.save(ft);
        DefaultFactor factor = new DefaultFactor();
        factor.setTemplateId(ft.getId());
        factor.setSubcategoryCode("FF_D");
        factor.setSubcategoryName("天然气");
        factor.setFactorSource("系统缺省");
        factor.setFactorValue(new BigDecimal("2.1622"));
        defaultFactorRepository.save(factor);

        Template template = new Template();
        template.setName("化石模版");
        template.setTemplateType(2);
        template.setCreatedBy(1L);
        template.setFactorTemplateId(ft.getId());
        template = templateRepository.save(template);

        // 停用的化石燃料采集点（name/sub_scope_id 非空约束）
        FossilFuelMeterInfo fossilMeter = new FossilFuelMeterInfo();
        fossilMeter.setName("天然气表");
        fossilMeter.setFuelType("天然气");
        fossilMeter.setStatus(0);
        fossilMeter.setSubScopeId(0L);
        fossilMeter = fossilFuelMeterInfoRepository.save(fossilMeter);

        EmissionNode collection = persistNode(template, "燃气节点", 3, null);
        EmissionNodeConfig config = new EmissionNodeConfig();
        config.setNodeId(collection.getId());
        config.setCollectionPointType(2);
        config.setCollectionPointId(fossilMeter.getId());
        config.setEmissionSubcategory("天然气");
        configRepository.save(config);

        TemplateValidationResultVO vo = validationService.validateTemplate(template.getId());

        assertThat(vo.getCheckResult()).isEqualTo(4);
        assertThat(vo.getItems()).anySatisfy(item -> {
            assertThat(item.getLevel()).isEqualTo("ERROR");
            assertThat(item.getMessage()).contains("天然气表").contains("停用状态");
        });

        Template reloaded = reloadTemplate(template.getId());
        assertThat(reloaded.getCheckResult()).isEqualTo(4);
    }

    @Test
    @DisplayName("小类未覆盖且节点覆盖因子不可追溯：保留告警并以DQI错误阻断")
    void validate_subcategoryNotCovered_persistsWarning() {
        Template template = setupStandardData("天然气", new BigDecimal("2.1"), 1);
        MeterInfo meter = meterInfoRepository.findAll().get(0);
        meter.setEmissionSubcategory("天然气");
        meterInfoRepository.save(meter);

        TemplateValidationResultVO vo = validationService.validateTemplate(template.getId());

        assertThat(vo.getCheckResult()).isEqualTo(4);
        assertThat(vo.getItems()).anySatisfy(item ->
                assertThat(item.getMessage()).contains("天然气").contains("未被碳排放因子模版覆盖"));
        assertThat(vo.getItems()).anySatisfy(item ->
                assertThat(item.getMessage()).contains("无法取得排放因子 DQI").contains("历史节点覆盖缺少正式因子来源"));

        Template reloaded = reloadTemplate(template.getId());
        assertThat(reloaded.getCheckResult()).isEqualTo(4);
        assertThat(reloaded.getCheckMessage()).contains("【错误】").contains("【告警】");
    }

    @Test
    @DisplayName("节点单独因子与模版不一致且不可追溯：保留提示并以DQI错误阻断")
    void validate_ownFactorMismatch_persistsInfo() {
        Template template = setupStandardData("外购电力", new BigDecimal("0.6"), 1);

        TemplateValidationResultVO vo = validationService.validateTemplate(template.getId());

        assertThat(vo.getCheckResult()).isEqualTo(4);
        assertThat(vo.getItems()).hasSize(2);
        assertThat(vo.getItems()).anySatisfy(item -> {
            assertThat(item.getLevel()).isEqualTo("INFO");
            assertThat(item.getMessage()).contains("不一致");
        });
        assertThat(vo.getItems()).anySatisfy(item -> {
            assertThat(item.getLevel()).isEqualTo("ERROR");
            assertThat(item.getMessage()).contains("无法取得排放因子 DQI").contains("历史节点覆盖缺少正式因子来源");
        });

        Template reloaded = reloadTemplate(template.getId());
        assertThat(reloaded.getCheckResult()).isEqualTo(4);
        assertThat(reloaded.getCheckMessage()).contains("【错误】").contains("【提示】");
    }

    @Test
    @DisplayName("模版被修改后校验结果自动重置为未检查（经TemplateService真实更新链路）")
    void templateUpdate_resetsCheckStatusToZero() {
        Template template = setupStandardData("外购电力", null, 1);

        // 先校验：结果落库为 1
        validationService.validateTemplate(template.getId());
        Template afterValidate = reloadTemplate(template.getId());
        assertThat(afterValidate.getCheckResult()).isEqualTo(1);
        assertThat(afterValidate.getCheckMessage()).isNotNull();

        // 修改模版（经真实 TemplateService 链路）
        templateService.updateTemplate(template.getId(), "核算模版B", 1L);

        // 校验状态被自动重置为 0
        Template afterUpdate = reloadTemplate(template.getId());
        assertThat(afterUpdate.getName()).isEqualTo("核算模版B");
        assertThat(afterUpdate.getCheckResult()).isZero();
        assertThat(afterUpdate.getCheckTime()).isNull();
        assertThat(afterUpdate.getCheckMessage()).isNull();
    }

    @Test
    @DisplayName("校验后getValidationResult从数据库读回最近一次结果")
    void getValidationResult_roundtripAfterValidate() {
        Template template = setupStandardData("天然气", new BigDecimal("2.1"), 1);
        MeterInfo meter = meterInfoRepository.findAll().get(0);
        meter.setEmissionSubcategory("天然气");
        meterInfoRepository.save(meter);

        TemplateValidationResultVO validated = validationService.validateTemplate(template.getId());
        TemplateValidationResultVO stored = validationService.getValidationResult(template.getId());

        assertThat(stored.getCheckResult()).isEqualTo(validated.getCheckResult());
        assertThat(stored.getCheckTime()).isEqualTo(validated.getCheckTime());
        assertThat(stored.getCheckMessage()).isEqualTo(validated.getCheckMessage());
        assertThat(stored.getCheckResult()).isEqualTo(4);
    }

    @Test
    @DisplayName("节点配置小类为空时回退采集点表小类参与覆盖检查（真实数据链路）")
    void validate_subcategoryFallbackToMeterViaDatabase() {
        // 配置小类为null，电力表小类为"外购电力"（setup中已设），因子模版覆盖 → 结果=1
        Template template = setupStandardData(null, null, 1);

        TemplateValidationResultVO vo = validationService.validateTemplate(template.getId());

        assertThat(vo.getCheckResult()).isEqualTo(1);
        assertThat(vo.getItems()).isEmpty();
    }

    @Test
    @DisplayName("多个采集节点数据经Repository真实查询：混合级别错误优先")
    void validate_mixedLevels_errorWins() {
        Template template = setupStandardData("外购电力", new BigDecimal("0.6"), 1);
        // 将采集点指向不存在的ID（错误）+ 新增空核算节点（告警）+ 单独因子不一致（提示）
        EmissionNodeConfig config = configRepository.findAll().get(0);
        config.setCollectionPointId(99999L);
        configRepository.save(config);
        persistNode(template, "空车间", 2, null);

        TemplateValidationResultVO vo = validationService.validateTemplate(template.getId());

        assertThat(vo.getCheckResult()).isEqualTo(4);
        assertThat(vo.getItems()).extracting(TemplateValidationResultVO.Item::getLevel)
                .contains("ERROR", "WARNING", "INFO");

        Template reloaded = reloadTemplate(template.getId());
        assertThat(reloaded.getCheckResult()).isEqualTo(4);
    }
}
