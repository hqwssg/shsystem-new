package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.dto.ParamResultData;
import com.example.carbon.emission.model.dto.ScopeCompletenessResult;
import com.example.carbon.emission.model.dto.SimulationConfig;
import com.example.carbon.emission.model.dto.UncertaintyRunDetailDto;
import com.example.carbon.emission.model.entity.UncertaintyDimensionRule;
import com.example.carbon.emission.model.entity.UncertaintyParamResult;
import com.example.carbon.emission.model.entity.UncertaintyRuleset;
import com.example.carbon.emission.model.entity.UncertaintyRun;
import com.example.carbon.emission.model.entity.UncertaintyRunScope;
import com.example.carbon.emission.model.entity.UncertaintyScore;
import com.example.carbon.emission.model.entity.UncertaintySourceMeta;
import com.example.carbon.emission.model.repository.UncertaintyDimensionRuleRepository;
import com.example.carbon.emission.model.repository.UncertaintyParamResultRepository;
import com.example.carbon.emission.model.repository.UncertaintyRulesetRepository;
import com.example.carbon.emission.model.repository.UncertaintyRunRepository;
import com.example.carbon.emission.model.repository.UncertaintyRunScopeRepository;
import com.example.carbon.emission.model.repository.UncertaintyScoreRepository;
import com.example.carbon.emission.model.repository.UncertaintySourceMetaRepository;
import com.example.carbon.emission.model.service.ScopeCompletenessService;
import com.example.carbon.emission.model.service.UncertaintyParameterService;
import com.example.carbon.emission.model.service.UncertaintySimulationService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.commons.math3.distribution.BetaDistribution;
import org.apache.commons.math3.random.RandomGenerator;
import org.apache.commons.math3.random.Well19937c;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Random;
import java.util.concurrent.Executor;
import java.util.stream.Collectors;

/**
 * 不确定性分析模拟运行 Service 实现（M4+M5，规范 5.4/5.5/5.6）
 * <p>
 * 本类不使用类级事务：运行记录的每次保存独立提交，确保异常时
 * FAILED 状态与 error_message 能够落库后再重抛异常。
 */
@Service
public class UncertaintySimulationServiceImpl implements UncertaintySimulationService {

    private static final Logger log = LoggerFactory.getLogger(UncertaintySimulationServiceImpl.class);

    /**
     * 默认迭代次数
     */
    private static final int DEFAULT_N_ITERATIONS = 10000;

    /**
     * 迭代次数下界
     */
    private static final int MIN_N_ITERATIONS = 1000;

    /**
     * 迭代次数上界
     */
    private static final int MAX_N_ITERATIONS = 1000000;

    /**
     * 异步执行阈值：nIterations ≥ 该值时改为异步执行并立即返回 runId
     */
    private static final int ASYNC_N_ITERATIONS_THRESHOLD = 100000;

    /**
     * 默认置信水平
     */
    private static final BigDecimal DEFAULT_CONFIDENCE_LEVEL = new BigDecimal("0.95");

    /**
     * 本期唯一支持的完整性作用范围
     */
    private static final String SCOPE_LEVEL = "scope";

    /**
     * 空scope源的默认分组名（与 ScopeCompletenessServiceImpl 保持一致）
     */
    private static final String UNGROUPED = "未分组";

    /**
     * 数值计算统一保留小数位
     */
    private static final int SCALE = 6;

    /**
     * 排放源元信息 Repository
     */
    @Autowired
    private UncertaintySourceMetaRepository uncertaintySourceMetaRepository;

    /**
     * DQI 评分 Repository
     */
    @Autowired
    private UncertaintyScoreRepository uncertaintyScoreRepository;

    /**
     * 规则库版本 Repository
     */
    @Autowired
    private UncertaintyRulesetRepository uncertaintyRulesetRepository;

    /**
     * 规则库维度规则 Repository
     */
    @Autowired
    private UncertaintyDimensionRuleRepository uncertaintyDimensionRuleRepository;

    /**
     * 模拟运行 Repository
     */
    @Autowired
    private UncertaintyRunRepository uncertaintyRunRepository;

    /**
     * Scope 级完整性评估 Repository
     */
    @Autowired
    private UncertaintyRunScopeRepository uncertaintyRunScopeRepository;

    /**
     * 参数级结果 Repository
     */
    @Autowired
    private UncertaintyParamResultRepository uncertaintyParamResultRepository;

    /**
     * M3 参数化 Service
     */
    @Autowired
    private UncertaintyParameterService uncertaintyParameterService;

    /**
     * Scope 级完整性 Service
     */
    @Autowired
    private ScopeCompletenessService scopeCompletenessService;

    /**
     * JSON 解析器（分位数与警告序列化）
     */
    @Autowired
    private ObjectMapper objectMapper;

    /**
     * 大样本量 MCS 异步执行线程池（见 UncertaintySimulationAsyncConfig）
     */
    @Autowired
    @Qualifier("uncertaintyTaskExecutor")
    private Executor uncertaintyTaskExecutor;

    @Override
    public Long run(Long calculationTemplateId, SimulationConfig config) {
        if (calculationTemplateId == null) {
            throw new IllegalArgumentException("核算任务ID不能为空");
        }
        SimulationConfig effectiveConfig = config != null ? config : new SimulationConfig();

        // 步骤1：配置校验与默认值填充
        int nIterations = effectiveConfig.getNIterations() != null
                ? effectiveConfig.getNIterations() : DEFAULT_N_ITERATIONS;
        if (nIterations < MIN_N_ITERATIONS || nIterations > MAX_N_ITERATIONS) {
            throw new IllegalArgumentException("迭代次数 nIterations 须在 [" + MIN_N_ITERATIONS
                    + ", " + MAX_N_ITERATIONS + "] 范围内");
        }
        BigDecimal confidenceLevel = effectiveConfig.getConfidenceLevel() != null
                ? effectiveConfig.getConfidenceLevel() : DEFAULT_CONFIDENCE_LEVEL;
        String completenessScopeLevel = effectiveConfig.getCompletenessScopeLevel() != null
                ? effectiveConfig.getCompletenessScopeLevel() : SCOPE_LEVEL;
        if (!SCOPE_LEVEL.equals(completenessScopeLevel)) {
            throw new IllegalArgumentException("本期仅实现 scope 粒度的完整性分量，不支持：" + completenessScopeLevel);
        }
        Long randomSeed = effectiveConfig.getRandomSeed() != null
                ? effectiveConfig.getRandomSeed() : new Random().nextLong();

        // 步骤2：规则库解析（config 指定版本或取最新）
        UncertaintyRuleset ruleset = resolveRuleset(effectiveConfig.getRulesetVersion());
        List<UncertaintyDimensionRule> dimRules = uncertaintyDimensionRuleRepository
                .findByRulesetId(ruleset.getId());

        // 步骤3：前置校验——排放源存在性、名义值正性、DQI 评分完整性
        List<UncertaintySourceMeta> sources = uncertaintySourceMetaRepository
                .findByCalculationTemplateId(calculationTemplateId);
        if (sources == null || sources.isEmpty()) {
            throw new IllegalStateException("核算任务下无排放源元数据，禁止运行模拟");
        }
        for (UncertaintySourceMeta source : sources) {
            if (source.getAdValue() == null || source.getAdValue().compareTo(BigDecimal.ZERO) <= 0
                    || source.getEfValue() == null || source.getEfValue().compareTo(BigDecimal.ZERO) <= 0) {
                throw new IllegalStateException("排放源 " + source.getSourceName()
                        + " 的 ad_value/ef_value 必须为正数，禁止运行模拟");
            }
        }
        List<Long> sourceIds = sources.stream().map(UncertaintySourceMeta::getId).collect(Collectors.toList());
        Map<Long, List<UncertaintyScore>> scoresBySource = uncertaintyScoreRepository
                .findBySourceMetaIdIn(sourceIds).stream()
                .collect(Collectors.groupingBy(UncertaintyScore::getSourceMetaId));
        validateScoresComplete(sources, scoresBySource, dimRules);

        // 步骤4：创建运行记录（RUNNING，配置快照 + 记录下锚点估计）
        UncertaintyRun run = new UncertaintyRun();
        run.setCalculationTemplateId(calculationTemplateId);
        run.setRulesetVersion(ruleset.getRulesetVersion());
        run.setNIterations(nIterations);
        run.setConfidenceLevel(confidenceLevel);
        run.setRandomSeed(randomSeed);
        run.setCompletenessScopeLevel(completenessScopeLevel);
        run.setStatus("RUNNING");
        run.setStartedAt(LocalDateTime.now());
        BigDecimal ePointRaw = BigDecimal.ZERO;
        for (UncertaintySourceMeta source : sources) {
            if (source.getEmissionValue() != null) {
                ePointRaw = ePointRaw.add(source.getEmissionValue());
            }
        }
        run.setEPointRaw(ePointRaw.setScale(SCALE, RoundingMode.HALF_UP));
        run = uncertaintyRunRepository.save(run);

        // 大样本量：提交异步执行并立即返回 runId，前端轮询运行状态/结果
        if (nIterations >= ASYNC_N_ITERATIONS_THRESHOLD) {
            final Long runId = run.getId();
            log.info("大样本量 MCS（nIterations={}）转为异步执行，runId={}", nIterations, runId);
            uncertaintyTaskExecutor.execute(() -> executeRunById(runId));
            return runId;
        }

        // 小样本量：同步执行；异常时标记 FAILED 后重抛（本类无类级事务，本次保存独立提交）
        try {
            executeRun(run, sources, scoresBySource, ruleset, dimRules, nIterations,
                    confidenceLevel, randomSeed, ePointRaw);
            return run.getId();
        } catch (Exception e) {
            markFailed(run, e);
            throw e instanceof RuntimeException ? (RuntimeException) e : new RuntimeException(e);
        }
    }

    /**
     * 异步执行入口：按 runId 重新加载运行记录与全部输入，执行后在异步线程内落库。
     * <p>
     * 异步线程不持有请求线程的持久化上下文与安全上下文，故全部输入按 runId
     * 从数据库重新加载；运行记录已在提交前以 RUNNING 状态落库，前端可据此轮询。
     * 失败时仅标记 FAILED 并写入 error_message，不再向上抛出（无调用方接收）。
     */
    private void executeRunById(Long runId) {
        UncertaintyRun run = uncertaintyRunRepository.findById(runId)
                .orElseThrow(() -> new IllegalStateException("模拟运行记录不存在：id=" + runId));
        try {
            UncertaintyRuleset ruleset = resolveRuleset(run.getRulesetVersion());
            List<UncertaintyDimensionRule> dimRules = uncertaintyDimensionRuleRepository
                    .findByRulesetId(ruleset.getId());
            List<UncertaintySourceMeta> sources = uncertaintySourceMetaRepository
                    .findByCalculationTemplateId(run.getCalculationTemplateId());
            List<Long> sourceIds = sources.stream().map(UncertaintySourceMeta::getId)
                    .collect(Collectors.toList());
            Map<Long, List<UncertaintyScore>> scoresBySource = uncertaintyScoreRepository
                    .findBySourceMetaIdIn(sourceIds).stream()
                    .collect(Collectors.groupingBy(UncertaintyScore::getSourceMetaId));

            executeRun(run, sources, scoresBySource, ruleset, dimRules, run.getNIterations(),
                    run.getConfidenceLevel(), run.getRandomSeed(), run.getEPointRaw());
        } catch (Exception e) {
            markFailed(run, e);
        }
    }

    /**
     * 将运行记录标记为 FAILED 并写入失败原因（独立保存提交）
     */
    private void markFailed(UncertaintyRun run, Exception e) {
        log.error("不确定性模拟运行失败，runId={}", run.getId(), e);
        run.setStatus("FAILED");
        run.setErrorMessage(e.getMessage());
        run.setFinishedAt(LocalDateTime.now());
        uncertaintyRunRepository.save(run);
    }

    /**
     * 运行主流程：M3 参数化 → Scope 完整性 → M4 蒙特卡洛 → M5 统计验证
     */
    private void executeRun(UncertaintyRun run, List<UncertaintySourceMeta> sources,
                            Map<Long, List<UncertaintyScore>> scoresBySource,
                            UncertaintyRuleset ruleset, List<UncertaintyDimensionRule> dimRules,
                            int nIterations, BigDecimal confidenceLevel,
                            long randomSeed, BigDecimal ePointRaw) throws Exception {
        Long runId = run.getId();
        List<String> allWarnings = new ArrayList<>();

        // 步骤5（M3）：每 source × (AD,EF) 参数化并落库 uncertainty_param_result
        Map<Long, ParamResultData> adParams = new HashMap<>();
        Map<Long, ParamResultData> efParams = new HashMap<>();
        List<UncertaintyParamResult> paramRows = new ArrayList<>();
        for (UncertaintySourceMeta source : sources) {
            List<UncertaintyScore> scores = scoresBySource.getOrDefault(source.getId(), new ArrayList<>());
            for (String paramType : new String[]{"AD", "EF"}) {
                ParamResultData param = uncertaintyParameterService.parameterize(
                        source, scores, ruleset, dimRules, paramType);
                if (param.isIncomplete()) {
                    // 双保险：前置校验已拦截，此处兜底
                    throw new IllegalStateException(
                            "存在未完成的DQI评分（paramType=" + paramType
                                    + "），禁止运行模拟。请先在向导中获取建议分并提交评分。");
                }
                if ("AD".equals(paramType)) {
                    adParams.put(source.getId(), param);
                } else {
                    efParams.put(source.getId(), param);
                }
                allWarnings.addAll(param.getWarnings());

                UncertaintyParamResult row = new UncertaintyParamResult();
                row.setRunId(runId);
                row.setSourceMetaId(source.getId());
                row.setParamType(paramType);
                row.setRulesetVersion(ruleset.getRulesetVersion());
                row.setSumQW(param.getSumQW());
                row.setSumQMinW(param.getSumQMinW());
                row.setSumQMaxW(param.getSumQMaxW());
                row.setXPercent(param.getXPercent());
                row.setSdqi(param.getSdqi());
                row.setBetaAlpha(param.getBetaAlpha());
                row.setBetaBeta(param.getBetaBeta());
                row.setDeltaPercent(param.getDeltaPercent());
                row.setSupportLowFactor(param.getSupportLowFactor());
                row.setSupportHighFactor(param.getSupportHighFactor());
                row.setWarnings(param.getWarnings().isEmpty() ? null : String.join(",", param.getWarnings()));
                paramRows.add(row);
            }
        }
        uncertaintyParamResultRepository.saveAll(paramRows);

        // 步骤6：Scope 级完整性分量（5.13），落库 uncertainty_run_scope
        List<ScopeCompletenessResult> scopeResults = scopeCompletenessService.compute(
                run.getCalculationTemplateId(), ruleset);
        List<UncertaintyRunScope> scopeRows = new ArrayList<>();
        for (ScopeCompletenessResult scopeResult : scopeResults) {
            UncertaintyRunScope row = new UncertaintyRunScope();
            row.setRunId(runId);
            row.setScope(scopeResult.getScope());
            row.setScopeEmission(scopeResult.getScopeEmission());
            row.setBasis(scopeResult.getBasis());
            row.setBenchmarkQty(scopeResult.getBenchmarkQty());
            row.setBenchmarkSource(scopeResult.getBenchmarkSource());
            row.setRBenchmark(scopeResult.getRBenchmark());
            row.setRMeasured(scopeResult.getRMeasured());
            row.setPointRatioXn(scopeResult.getPointRatioXn());
            row.setDeltaCovPercent(scopeResult.getDeltaCovPercent());
            row.setEXiCov(scopeResult.getEXiCov());
            row.setDisclosure(scopeResult.getDisclosure());
            scopeRows.add(row);
            allWarnings.addAll(scopeResult.getWarnings());
        }
        uncertaintyRunScopeRepository.saveAll(scopeRows);

        // 步骤7（M4）：蒙特卡洛模拟
        double[] samples = runMonteCarlo(sources, adParams, efParams, scopeResults,
                ruleset, nIterations, randomSeed);

        // 步骤8（M5）：统计量、双基准点估计、验证规则与结论文本
        applyStatistics(run, samples, confidenceLevel, ePointRaw, scopeResults, ruleset, allWarnings);

        // 步骤9：更新运行记录为 SUCCESS
        run.setStatus("SUCCESS");
        run.setFinishedAt(LocalDateTime.now());
        uncertaintyRunRepository.save(run);
    }

    /**
     * 前置校验：每 source 的 AD/EF 参与维度（weight>0 且 enabled）final_score 均非空
     */
    private void validateScoresComplete(List<UncertaintySourceMeta> sources,
                                        Map<Long, List<UncertaintyScore>> scoresBySource,
                                        List<UncertaintyDimensionRule> dimRules) {
        // 按 paramType 收集参与维度 dimCode
        Map<String, List<String>> participatingDims = new HashMap<>();
        for (UncertaintyDimensionRule rule : dimRules) {
            if (rule.getEnabled() != null && rule.getEnabled() == 1
                    && rule.getWeight() != null && rule.getWeight().compareTo(BigDecimal.ZERO) > 0) {
                participatingDims.computeIfAbsent(rule.getAppliesTo().toUpperCase(),
                        k -> new ArrayList<>()).add(rule.getDimCode());
            }
        }
        for (UncertaintySourceMeta source : sources) {
            Map<String, Map<String, UncertaintyScore>> scoreIndex = new HashMap<>();
            for (UncertaintyScore score : scoresBySource.getOrDefault(source.getId(), new ArrayList<>())) {
                scoreIndex.computeIfAbsent(score.getParamType().toUpperCase(), k -> new HashMap<>())
                        .put(score.getDimCode(), score);
            }
            for (String paramType : new String[]{"AD", "EF"}) {
                Map<String, UncertaintyScore> byDim = scoreIndex.getOrDefault(paramType, new HashMap<>());
                for (String dimCode : participatingDims.getOrDefault(paramType, new ArrayList<>())) {
                    UncertaintyScore score = byDim.get(dimCode);
                    // final_score 为空但 suggested_score 有值：视为自动评分未被否决，允许运行
                    // （实际参数化时会 fallback 到 suggested 参与 SDQI 计算）
                    if (score == null
                            || (score.getFinalScore() == null && score.getSuggestedScore() == null)) {
                        throw new IllegalStateException(
                                "存在未完成的DQI评分，禁止运行模拟（缺失维度：" + paramType + "/" + dimCode
                                        + "）。请先在向导中提交 DQI 评分或重新获取建议分。");
                    }
                }
            }
        }
    }

    /**
     * M4 蒙特卡洛模拟（规范 5.4）
     * <p>
     * 性能优化：对每 source 预生成 AD/EF 各 n 个 ξ 样本数组，对每 scope 预生成
     * n 个 ξ_cov 样本（δ=0 时恒 1，跳过抽样）；逐迭代按下标取用，避免内层循环
     * 重复创建分布对象。
     *
     * @return 长度为 nIterations 的总排放量样本数组
     */
    private double[] runMonteCarlo(List<UncertaintySourceMeta> sources,
                                   Map<Long, ParamResultData> adParams,
                                   Map<Long, ParamResultData> efParams,
                                   List<ScopeCompletenessResult> scopeResults,
                                   UncertaintyRuleset ruleset,
                                   int nIterations, long randomSeed) {
        RandomGenerator rng = new Well19937c(randomSeed);

        // 预生成每 source 的 AD/EF 对称 Beta 扰动因子样本：ξ=L+(U−L)×B，B~Beta(α,β)，α=β=SDQI²
        int sourceCount = sources.size();
        double[][] adXi = new double[sourceCount][];
        double[][] efXi = new double[sourceCount][];
        double[] adNominal = new double[sourceCount];
        double[] efNominal = new double[sourceCount];
        for (int i = 0; i < sourceCount; i++) {
            UncertaintySourceMeta source = sources.get(i);
            adNominal[i] = source.getAdValue().doubleValue();
            efNominal[i] = source.getEfValue().doubleValue();
            adXi[i] = sampleSymmetricFactor(rng, adParams.get(source.getId()), nIterations);
            efXi[i] = sampleSymmetricFactor(rng, efParams.get(source.getId()), nIterations);
        }

        // 按与完整性计算一致的分组键归组 source 下标
        Map<String, List<Integer>> sourceIndexByScope = new LinkedHashMap<>();
        for (int i = 0; i < sourceCount; i++) {
            String scope = sources.get(i).getScope();
            String key = (scope == null || scope.isBlank()) ? UNGROUPED : scope;
            sourceIndexByScope.computeIfAbsent(key, k -> new ArrayList<>()).add(i);
        }

        // 预生成每 scope 的单侧完整性因子样本：ξ_cov=1+(δ/100)×B_cov，B_cov~Beta(1,α_cov)
        // 注意 Beta 参数顺序为 Beta(1, α_cov)，α_cov 默认 15（质量集中于 0，ξ_cov 贴近 1）
        BigDecimal coverageAlpha = ruleset.getCoverageAlpha() != null
                ? ruleset.getCoverageAlpha() : new BigDecimal("15");
        Map<String, double[]> covXiByScope = new HashMap<>();
        for (ScopeCompletenessResult scopeResult : scopeResults) {
            double deltaFraction = scopeResult.getDeltaCovPercent().doubleValue() / 100.0;
            double[] covXi = new double[nIterations];
            if (deltaFraction <= 0.0) {
                // δ=0 → ξ_cov≡1，跳过抽样
                Arrays.fill(covXi, 1.0);
            } else {
                BetaDistribution beta = new BetaDistribution(rng, 1.0, coverageAlpha.doubleValue());
                for (int k = 0; k < nIterations; k++) {
                    covXi[k] = 1.0 + deltaFraction * beta.sample();
                }
            }
            covXiByScope.put(scopeResult.getScope(), covXi);
        }

        // 逐迭代：E_i(k)=(ad_i×ξ_AD_i[k])×(ef_i×ξ_EF_i[k])，按 scope 汇总乘 ξ_cov_g[k]，E(k)=Σ_g
        double[] samples = new double[nIterations];
        for (int k = 0; k < nIterations; k++) {
            double total = 0.0;
            for (Map.Entry<String, List<Integer>> entry : sourceIndexByScope.entrySet()) {
                double scopeSum = 0.0;
                for (int i : entry.getValue()) {
                    scopeSum += (adNominal[i] * adXi[i][k]) * (efNominal[i] * efXi[i][k]);
                }
                double[] covXi = covXiByScope.get(entry.getKey());
                total += scopeSum * (covXi != null ? covXi[k] : 1.0);
            }
            samples[k] = total;
        }
        return samples;
    }

    /**
     * 生成单个参数（AD/EF）的 n 个对称 Beta 扰动因子样本
     */
    private double[] sampleSymmetricFactor(RandomGenerator rng, ParamResultData param, int n) {
        double low = param.getSupportLowFactor().doubleValue();
        double high = param.getSupportHighFactor().doubleValue();
        double[] xi = new double[n];
        if (high - low <= 0.0) {
            // δ=0 → 扰动因子恒 1（防御性分支，默认 δ 表最小为 5%）
            Arrays.fill(xi, 1.0);
            return xi;
        }
        BetaDistribution beta = new BetaDistribution(rng,
                param.getBetaAlpha().doubleValue(), param.getBetaBeta().doubleValue());
        for (int k = 0; k < n; k++) {
            xi[k] = low + (high - low) * beta.sample();
        }
        return xi;
    }

    /**
     * M5 统计量与验证（规范 5.5/5.6）
     * <p>
     * 分位数方法：对排序后样本采用线性插值（h=p×(n−1)，与 numpy 默认 type-7 一致）。
     */
    private void applyStatistics(UncertaintyRun run, double[] samples, BigDecimal confidenceLevel,
                                 BigDecimal ePointRaw, List<ScopeCompletenessResult> scopeResults,
                                 UncertaintyRuleset ruleset, List<String> allWarnings) throws Exception {
        int n = samples.length;
        double[] sorted = samples.clone();
        Arrays.sort(sorted);

        // 均值与样本标准差（分母 n−1）
        double sum = 0.0;
        for (double sample : samples) {
            sum += sample;
        }
        double mean = sum / n;
        double squareSum = 0.0;
        for (double sample : samples) {
            double diff = sample - mean;
            squareSum += diff * diff;
        }
        double std = Math.sqrt(squareSum / (n - 1));

        // 分位数：p5/p25/p50/p75/p95 与 CI 上下界 (1∓c)/2
        double c = confidenceLevel.doubleValue();
        double p5 = quantile(sorted, 0.05);
        double p25 = quantile(sorted, 0.25);
        double p50 = quantile(sorted, 0.50);
        double p75 = quantile(sorted, 0.75);
        double p95 = quantile(sorted, 0.95);
        double ciLower = quantile(sorted, (1.0 - c) / 2.0);
        double ciUpper = quantile(sorted, (1.0 + c) / 2.0);
        double cv = mean != 0.0 ? std / mean * 100.0 : 0.0;

        // 双基准点估计：E_point_cov=Σ_g(E[g]×E[ξ_cov_g])，可不经 MCS 解析算出
        BigDecimal ePointCov = BigDecimal.ZERO;
        for (ScopeCompletenessResult scopeResult : scopeResults) {
            ePointCov = ePointCov.add(scopeResult.getScopeEmission().multiply(scopeResult.getEXiCov()));
        }
        ePointCov = ePointCov.setScale(SCALE, RoundingMode.HALF_UP);

        // 上抬百分比（raw=0 时 uplift=0）
        BigDecimal uplift = BigDecimal.ZERO;
        if (ePointRaw.compareTo(BigDecimal.ZERO) > 0) {
            uplift = ePointCov.subtract(ePointRaw)
                    .divide(ePointRaw, SCALE, RoundingMode.HALF_UP)
                    .multiply(BigDecimal.valueOf(100)).setScale(SCALE, RoundingMode.HALF_UP);
        }

        // 验证规则（5.6）：均值/中位数偏差、区间包含性、下锚关系、CV 分级
        BigDecimal ePointCovD = ePointCov;
        double devMean = ePointCovD.doubleValue() != 0.0
                ? (mean - ePointCovD.doubleValue()) / ePointCovD.doubleValue() * 100.0 : 0.0;
        double devMedian = ePointCovD.doubleValue() != 0.0
                ? (p50 - ePointCovD.doubleValue()) / ePointCovD.doubleValue() * 100.0 : 0.0;
        boolean pointCovInCi = ePointCovD.doubleValue() >= ciLower && ePointCovD.doubleValue() <= ciUpper;
        boolean rawLeCov = ePointRaw.doubleValue() <= ePointCovD.doubleValue() + 1e-9;
        String uncertaintyLevel = cv <= 5.0 ? "低" : cv <= 15.0 ? "中" : cv <= 30.0 ? "较高" : "高";

        // 写回运行记录统计字段
        run.setEPointCov(ePointCov);
        run.setUpliftPercent(uplift);
        run.setTotalMean(BigDecimal.valueOf(mean).setScale(SCALE, RoundingMode.HALF_UP));
        run.setTotalMedian(BigDecimal.valueOf(p50).setScale(SCALE, RoundingMode.HALF_UP));
        run.setTotalStd(BigDecimal.valueOf(std).setScale(SCALE, RoundingMode.HALF_UP));
        run.setCvPercent(BigDecimal.valueOf(cv).setScale(SCALE, RoundingMode.HALF_UP));
        run.setCiLower(BigDecimal.valueOf(ciLower).setScale(SCALE, RoundingMode.HALF_UP));
        run.setCiUpper(BigDecimal.valueOf(ciUpper).setScale(SCALE, RoundingMode.HALF_UP));
        run.setDevMeanPercent(BigDecimal.valueOf(devMean).setScale(SCALE, RoundingMode.HALF_UP));
        run.setDevMedianPercent(BigDecimal.valueOf(devMedian).setScale(SCALE, RoundingMode.HALF_UP));
        run.setPointCovInCi(pointCovInCi);
        run.setRawLeCov(rawLeCov);
        run.setUncertaintyLevel(uncertaintyLevel);

        Map<String, Double> quantiles = new LinkedHashMap<>();
        quantiles.put("p5", p5);
        quantiles.put("p25", p25);
        quantiles.put("p50", p50);
        quantiles.put("p75", p75);
        quantiles.put("p95", p95);
        run.setQuantiles(objectMapper.writeValueAsString(quantiles));
        run.setWarnings(objectMapper.writeValueAsString(allWarnings));

        // 验证结论文本（O4）
        run.setVerificationConclusion(buildVerificationConclusion(run, ePointRaw, ePointCov, uplift,
                cv, uncertaintyLevel, devMean, pointCovInCi, rawLeCov, c, ciLower, ciUpper,
                scopeResults, ruleset));
    }

    /**
     * 分位数（线性插值法：h=p×(n−1)，与 numpy 默认 type-7 一致）
     *
     * @param sorted 已升序排序的样本数组
     * @param p      分位点（0-1）
     * @return 分位数值
     */
    private double quantile(double[] sorted, double p) {
        int n = sorted.length;
        if (n == 1) {
            return sorted[0];
        }
        double h = p * (n - 1);
        int lowerIndex = (int) Math.floor(h);
        int upperIndex = Math.min(lowerIndex + 1, n - 1);
        double fraction = h - lowerIndex;
        return sorted[lowerIndex] + fraction * (sorted[upperIndex] - sorted[lowerIndex]);
    }

    /**
     * 验证结论文本（O4 模板，含无基准 Scope 披露提示与 δ 表标定状态声明）
     */
    private String buildVerificationConclusion(UncertaintyRun run, BigDecimal ePointRaw,
                                               BigDecimal ePointCov, BigDecimal uplift,
                                               double cv, String uncertaintyLevel,
                                               double devMean, boolean pointCovInCi,
                                               boolean rawLeCov, double c,
                                               double ciLower, double ciUpper,
                                               List<ScopeCompletenessResult> scopeResults,
                                               UncertaintyRuleset ruleset) {
        StringBuilder sb = new StringBuilder();
        sb.append("经完整性修正后排放量为 E_point_cov=").append(ePointCov)
                .append("（较记录下锚 E_point_raw=").append(ePointRaw)
                .append(" 上抬 ").append(uplift).append("%）；");
        sb.append("该值").append(pointCovInCi ? "落入" : "未落入")
                .append(String.format(Locale.ROOT, " %.0f%%", c * 100))
                .append(" 置信区间 [").append(String.format(Locale.ROOT, "%.6f", ciLower))
                .append(", ").append(String.format(Locale.ROOT, "%.6f", ciUpper)).append("]，");
        sb.append("CV=").append(String.format(Locale.ROOT, "%.2f", cv)).append("%（")
                .append(uncertaintyLevel).append("），");
        sb.append("均值偏差 dev_mean=").append(String.format(Locale.ROOT, "%.4f", devMean))
                .append("%（|≤2%|为抽样无偏：").append(Math.abs(devMean) <= 2.0 ? "通过" : "未通过").append("），");
        sb.append("下锚关系 E_point_raw≤E_point_cov：").append(rawLeCov ? "成立" : "不成立").append("。");

        // 无基准 scope 披露提示
        List<String> disabledScopes = new ArrayList<>();
        List<String> measuredOnlyScopes = new ArrayList<>();
        for (ScopeCompletenessResult scopeResult : scopeResults) {
            if ("disabled".equals(scopeResult.getBasis())) {
                disabledScopes.add(scopeResult.getScope());
            } else if ("measured".equals(scopeResult.getBasis())) {
                measuredOnlyScopes.add(scopeResult.getScope());
            }
        }
        if (!disabledScopes.isEmpty()) {
            sb.append(" Scope ").append(String.join("、", disabledScopes))
                    .append(" 的完整性未经独立基准验证，未施加遗漏修正分量（E_point_cov=E_point_raw），"
                            + "须在报告'其他需要说明的情况'中强制披露该局限。");
        }
        if (!measuredOnlyScopes.isEmpty()) {
            sb.append(" Scope ").append(String.join("、", measuredOnlyScopes))
                    .append(" 的完整性仅反映已报数据中估算占比，不含遗漏风险。");
        }

        // δ表标定状态声明（5.3 第6条，未标定强制声明）
        if (ruleset.getCalibrationMeta() == null || ruleset.getCalibrationMeta().isBlank()) {
            sb.append(" 本报告不确定性分析所用 SDQI→δ 映射未经实证标定，CV 与置信区间仅供内部参考，"
                    + "不构成对不确定性量级的外部验证。");
        }
        return sb.toString();
    }

    /**
     * 规则库解析：指定版本号或取最新（按ID最大）
     */
    private UncertaintyRuleset resolveRuleset(String rulesetVersion) {
        if (rulesetVersion != null && !rulesetVersion.isBlank()) {
            return uncertaintyRulesetRepository.findByRulesetVersion(rulesetVersion)
                    .orElseThrow(() -> new IllegalStateException("规则库不存在：" + rulesetVersion));
        }
        return uncertaintyRulesetRepository.findAll().stream()
                .max(Comparator.comparing(UncertaintyRuleset::getId))
                .orElseThrow(() -> new IllegalStateException("规则库不存在，请先初始化规则库版本"));
    }

    @Override
    public List<UncertaintyRun> listRuns(Long calculationTemplateId) {
        return uncertaintyRunRepository.findByCalculationTemplateIdOrderByIdDesc(calculationTemplateId);
    }

    @Override
    public UncertaintyRunDetailDto getRunDetail(Long runId) {
        UncertaintyRun run = uncertaintyRunRepository.findById(runId)
                .orElseThrow(() -> new IllegalArgumentException("模拟运行记录不存在：id=" + runId));
        UncertaintyRunDetailDto dto = new UncertaintyRunDetailDto();
        dto.setRun(run);
        dto.setScopes(uncertaintyRunScopeRepository.findByRunId(runId));
        dto.setParams(uncertaintyParamResultRepository.findByRunId(runId));
        return dto;
    }
}
