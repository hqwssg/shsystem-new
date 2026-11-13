package com.example.carbon.emission.model.service.impl;

import com.example.carbon.emission.model.entity.EmissionNodeConfig;
import com.example.carbon.emission.model.security.CollectionScopeService;
import com.example.carbon.emission.model.security.CarbonSecurityContext;
import org.springframework.http.HttpStatus;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.*;
import java.util.function.Function;
import java.util.stream.Collectors;

/** Read-only statistics over approved collection records. */
@Service
public class EmissionStatisticsService {
    private static final int MAX_ROWS = 100_000;

    private final JdbcTemplate jdbc;
    private final CollectionScopeService scopes;
    private final FactorDimensionService factorDimensions;
    private final EffectiveFactorResolver factorResolver;

    public EmissionStatisticsService(JdbcTemplate jdbc, CollectionScopeService scopes,
                                     FactorDimensionService factorDimensions,
                                     EffectiveFactorResolver factorResolver) {
        this.jdbc = jdbc;
        this.scopes = scopes;
        this.factorDimensions = factorDimensions;
        this.factorResolver = factorResolver;
    }

    public Map<String, Object> query(Criteria criteria) {
        validate(criteria);
        List<Map<String, Object>> records = load(criteria);
        records.sort(comparator(criteria.sortBy, criteria.sortDirection));
        int from = Math.min(criteria.page * criteria.size, records.size());
        int to = Math.min(from + criteria.size, records.size());
        int pages = records.isEmpty() ? 0 : (records.size() + criteria.size - 1) / criteria.size;
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("content", records.subList(from, to));
        result.put("totalElements", records.size());
        result.put("totalPages", pages);
        result.put("size", criteria.size);
        result.put("number", criteria.page);
        result.put("first", criteria.page == 0);
        result.put("last", pages == 0 || criteria.page >= pages - 1);
        return result;
    }

    public Map<String, Object> dashboard(Criteria criteria) {
        validate(criteria);
        List<Map<String, Object>> records = load(criteria);
        records.sort(comparator("dataDate", "ASC"));

        BigDecimal totalEmission = sum(records, "calculatedValue");
        long factorMissing = records.stream().filter(row -> Boolean.TRUE.equals(row.get("factorMissing"))).count();
        double averageQuality = records.stream().map(row -> decimal(row.get("qualityScore")))
                .filter(Objects::nonNull).mapToDouble(BigDecimal::doubleValue).average().orElse(0D);

        Map<String, BigDecimal> activityByUnit = groupedSum(records, "activityUnit", "activityValue");
        Map<String, BigDecimal> emissionByEnergy = groupedSum(records, "energyTypeName", "calculatedValue");
        Map<String, BigDecimal> emissionBySource = groupedSum(records, "dataSourceName", "calculatedValue");
        Map<String, BigDecimal> emissionByNode = groupedSum(records, "nodeName", "calculatedValue");
        Map<String, BigDecimal> emissionByMonth = groupedSum(records, "month", "calculatedValue");

        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("recordCount", records.size());
        summary.put("totalEmission", totalEmission);
        summary.put("averageQuality", BigDecimal.valueOf(averageQuality).setScale(4, RoundingMode.HALF_UP));
        summary.put("factorMissingCount", factorMissing);
        summary.put("autoCount", records.stream().filter(row -> "AUTO".equals(row.get("dataSource"))).count());
        summary.put("manualCount", records.stream().filter(row -> "MANUAL".equals(row.get("dataSource"))).count());

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("summary", summary);
        result.put("activityByUnit", series(activityByUnit));
        result.put("trend", series(emissionByMonth, "period"));
        result.put("energyMix", series(emissionByEnergy));
        result.put("sourceMix", series(emissionBySource));
        result.put("topNodes", series(emissionByNode).stream()
                .sorted((a, b) -> decimal(b.get("value")).compareTo(decimal(a.get("value"))))
                .limit(10).toList());
        result.put("recentRecords", records.stream().sorted(comparator("dataDate", "DESC")).limit(10).toList());
        result.put("segmentEnergy", segmentEnergy());
        result.put("unit", "tCO2e");
        return result;
    }

    public List<Map<String, Object>> segmentEnergy() {
        try {
            return jdbc.queryForList("""
                select p.project_code projectCode, v.version_code versionCode,
                       s.segment_code segmentCode, s.start_km startKm, s.end_km endKm,
                       a.window_start windowStart, a.window_end windowEnd, a.direction,
                       a.train_count trainCount, a.sample_count sampleCount,
                       a.traction_consumption_kwh tractionConsumptionKwh,
                       a.regenerative_energy_kwh regenerativeEnergyKwh,
                       a.net_energy_kwh netEnergyKwh,
                       a.energy_intensity_kwh_per_train_km energyIntensityKwhPerTrainKm,
                       a.energy_level energyLevel, a.source_type sourceType
                from energy_segment_consumption_summary a
                join energy_route_segment s on s.segment_id = a.segment_id
                join energy_project_version v on v.version_id = a.version_id
                join energy_project p on p.project_id = v.project_id
                where a.window_end = (
                    select max(latest.window_end)
                    from energy_segment_consumption_summary latest
                    where latest.version_id = a.version_id and latest.segment_id = a.segment_id
                )
                order by s.start_km, s.segment_code
                limit 2000
                    """);
        } catch (DataAccessException ignored) {
            return List.of();
        }
    }

    public Map<String, Object> surface(Criteria criteria, String granularity) {
        if (!"month".equals(granularity) && !"quarter".equals(granularity)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "granularity仅支持month或quarter");
        }
        List<Map<String, Object>> records = load(criteria);
        SortedSet<Integer> years = records.stream().map(row -> (LocalDate) row.get("dataDate"))
                .filter(Objects::nonNull).map(LocalDate::getYear).collect(Collectors.toCollection(TreeSet::new));
        int periodCount = "quarter".equals(granularity) ? 4 : 12;
        List<String> labels = new ArrayList<>();
        for (int i = 1; i <= periodCount; i++) labels.add("quarter".equals(granularity) ? "Q" + i : i + "月");
        List<List<BigDecimal>> matrix = new ArrayList<>();
        for (Integer year : years) {
            List<BigDecimal> row = new ArrayList<>(Collections.nCopies(periodCount, BigDecimal.ZERO));
            for (Map<String, Object> record : records) {
                LocalDate date = (LocalDate) record.get("dataDate");
                BigDecimal emission = decimal(record.get("calculatedValue"));
                if (date == null || emission == null || date.getYear() != year) continue;
                int index = "quarter".equals(granularity) ? (date.getMonthValue() - 1) / 3 : date.getMonthValue() - 1;
                row.set(index, row.get(index).add(emission));
            }
            matrix.add(row.stream().map(value -> value.setScale(6, RoundingMode.HALF_UP)).toList());
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("scope", criteria.templateId == null ? "overall" : "template");
        result.put("scopeName", "朔黄铁路碳排放");
        result.put("granularity", granularity);
        result.put("unit", "tCO2e");
        result.put("periodLabels", labels);
        result.put("years", years);
        result.put("matrix", matrix);
        return result;
    }

    private List<Map<String, Object>> load(Criteria criteria) {
        if ("CALCULATED".equals(criteria.dataSource)) {
            return loadCalculated(criteria);
        }
        List<Map<String, Object>> records = loadCollectionRecords(criteria);
        // A successful calculation stores an immutable snapshot in
        // emission_collection_node_data.  Older deployments may have that
        // snapshot but no approved raw collection record, so do not present a
        // valid template as an empty statistics result.
        if (records.isEmpty() && criteria.templateId != null && criteria.dataSource == null) {
            List<Map<String, Object>> calculated = loadCalculated(criteria);
            if (!calculated.isEmpty()) return calculated;
        }
        return records;
    }

    private List<Map<String, Object>> loadCollectionRecords(Criteria criteria) {
        StringBuilder configFilter = new StringBuilder();
        List<Object> args = new ArrayList<>();
        if (criteria.nodeId != null) {
            configFilter.append(" and candidate.node_id=?");
            args.add(criteria.nodeId);
        }
        if (criteria.templateId != null) {
            configFilter.append(" and candidate_node.template_id=?");
            args.add(criteria.templateId);
        }
        StringBuilder sql = new StringBuilder("""
                select r.id,r.collection_point_type,r.collection_point_id,r.reading_value,
                       r.collection_time,r.external_quality,r.collection_point_name,
                       r.emission_subcategory,r.measurement_unit,r.meter_reading_method,r.is_cumulative,
                       r.review_comment,nc.node_id,nc.carbon_emission_factor,
                       nc.carbon_emission_factor_unit,n.name node_name,n.template_id,t.factor_template_id,
                       (select previous.reading_value from emission_collection_record previous
                         where previous.collection_point_type=r.collection_point_type
                           and previous.collection_point_id=r.collection_point_id
                           and previous.collection_status=1 and previous.workflow_status='APPROVED'
                           and previous.reading_value is not null and previous.collection_time is not null
                           and (previous.collection_time<r.collection_time
                                or (previous.collection_time=r.collection_time and previous.id<r.id))
                         order by previous.collection_time desc,previous.id desc limit 1) previous_reading
                from emission_collection_record r
                left join emission_node_config nc on nc.id=(
                    select min(candidate.id) from emission_node_config candidate
                    join emission_node candidate_node on candidate_node.id=candidate.node_id
                    where candidate.collection_point_type=r.collection_point_type
                      and candidate.collection_point_id=r.collection_point_id
                """ + configFilter + ") left join emission_node n on n.id=nc.node_id "
                + "left join emission_template t on t.id=n.template_id where r.collection_status=1 "
                + "and r.workflow_status='APPROVED' and r.reading_value is not null and r.collection_time is not null");
        if (criteria.nodeId != null || criteria.templateId != null) sql.append(" and nc.id is not null");
        if (criteria.startDate != null) { sql.append(" and r.collection_time>=?"); args.add(criteria.startDate.atStartOfDay()); }
        if (criteria.endDate != null) { sql.append(" and r.collection_time<?"); args.add(criteria.endDate.plusDays(1).atStartOfDay()); }
        if (criteria.energyType != null) { sql.append(" and r.collection_point_type=?"); args.add(criteria.energyType); }
        if ("AUTO".equals(criteria.dataSource)) sql.append(" and r.meter_reading_method=1");
        if ("MANUAL".equals(criteria.dataSource)) sql.append(" and r.meter_reading_method=0");
        sql.append(" order by r.collection_time asc,r.id asc limit ").append(MAX_ROWS + 1);

        List<RawRecord> raw = jdbc.query(sql.toString(), this::mapRaw, args.toArray());
        if (raw.size() > MAX_ROWS) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "统计结果超过100000条，请缩小日期或节点范围");
        }
        Map<String, Boolean> scopeCache = new HashMap<>();
        Map<FactorKey, ResolvedFactor> factorCache = new HashMap<>();
        List<Map<String, Object>> result = new ArrayList<>();
        for (RawRecord item : raw) {
            String pointKey = item.collectionPointType + ":" + item.collectionPointId;
            boolean visible = scopeCache.computeIfAbsent(pointKey, ignored -> {
                try {
                    return scopes.canView(scopeType(item.collectionPointType), "meter", item.collectionPointId);
                } catch (ResponseStatusException ex) {
                    // Historical records can reference a meter that was removed or
                    // replaced. A stale record must not make the whole statistics
                    // endpoint return 404; it is simply outside the current scope.
                    if (ex.getStatusCode() == HttpStatus.NOT_FOUND) return false;
                    throw ex;
                }
            });
            if (!visible) continue;
            BigDecimal activity = activity(item);
            FactorKey factorKey = new FactorKey(item.factorTemplateId, item.emissionSubcategory,
                    item.measurementUnit, item.factor, item.factorUnit);
            ResolvedFactor factor = factorCache.computeIfAbsent(factorKey, this::resolveFactor);
            BigDecimal emission = factor.coefficient() == null ? null
                    : activity.multiply(factor.coefficient()).setScale(9, RoundingMode.HALF_UP);
            LocalDate date = item.collectionTime.toLocalDate();
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("id", item.id);
            row.put("templateId", item.templateId);
            row.put("nodeId", item.nodeId);
            row.put("nodeName", item.nodeName == null ? item.collectionPointName : item.nodeName);
            row.put("collectionPointType", item.collectionPointType);
            row.put("collectionPointId", item.collectionPointId);
            row.put("collectionPointName", item.collectionPointName);
            row.put("dataDate", date);
            row.put("month", date.toString().substring(0, 7));
            row.put("activityValue", activity);
            row.put("activityUnit", item.measurementUnit);
            row.put("actualValue", emission);
            row.put("calculatedValue", emission);
            row.put("emissionFactor", factor.value());
            row.put("factorUnit", factor.unit());
            row.put("factorMissing", emission == null);
            row.put("dataSource", item.meterReadingMethod != null && item.meterReadingMethod == 0 ? "MANUAL" : "AUTO");
            row.put("dataSourceName", item.meterReadingMethod != null && item.meterReadingMethod == 0 ? "人工采集" : "自动采集");
            row.put("qualityScore", quality(item, emission != null));
            row.put("energyType", energyTypeCode(item.collectionPointType));
            row.put("energyTypeName", energyTypeName(item.collectionPointType));
            row.put("emissionSubcategory", item.emissionSubcategory);
            row.put("isCumulative", item.isCumulative);
            row.put("remarks", item.reviewComment);
            result.add(row);
        }
        return result;
    }

    private List<Map<String, Object>> loadCalculated(Criteria criteria) {
        if (criteria.templateId == null) return List.of();
        List<Object> args = new ArrayList<>();
        StringBuilder sql = new StringBuilder("""
                select d.id,d.collection_point_type,d.collection_point_id,
                       d.emission_subcategory,d.measurement_unit,
                       d.carbon_emission_factor,d.carbon_emission_factor_unit,
                       d.is_cumulative,d.energy_measurement_value,d.adjusted_energy_value,
                       d.carbon_emission,d.adjusted_carbon_emission,d.data_status,
                       d.collection_record_start_date,d.collection_record_end_date,
                       cn.node_id,n.name node_name,ct.id calculation_task_id,
                       ct.template_id,ct.calculation_cycle_start_date,ct.calculation_cycle_end_date
                from emission_collection_node_data d
                join emission_calculation_node cn on cn.id=d.calculation_node_id
                join emission_calculation_template ct on ct.id=cn.calculation_template_id
                left join emission_node n on n.id=cn.node_id
                where ct.template_id=? and ct.status=2
                  and (d.data_status is null or d.data_status in (1,3,4,5))
                  and (d.energy_measurement_value is not null or d.adjusted_energy_value is not null)
                  and (d.carbon_emission is not null or d.adjusted_carbon_emission is not null)
                  and not exists (
                      select 1 from emission_calculation_template newer
                      where newer.template_id=ct.template_id and newer.status=2
                        and newer.calculation_cycle_start_date=ct.calculation_cycle_start_date
                        and newer.calculation_cycle_end_date=ct.calculation_cycle_end_date
                        and newer.id>ct.id)
                """);
        args.add(criteria.templateId);
        if (criteria.nodeId != null) {
            sql.append(" and cn.node_id=?");
            args.add(criteria.nodeId);
        }
        if (criteria.startDate != null) {
            sql.append(" and ct.calculation_cycle_end_date>=?");
            args.add(criteria.startDate);
        }
        if (criteria.endDate != null) {
            sql.append(" and ct.calculation_cycle_start_date<=?");
            args.add(criteria.endDate);
        }
        if (criteria.energyType != null) {
            sql.append(" and d.collection_point_type=?");
            args.add(criteria.energyType);
        }
        sql.append(" order by coalesce(d.collection_record_end_date,ct.calculation_cycle_end_date) asc,d.id asc limit ")
                .append(MAX_ROWS + 1);

        List<Map<String, Object>> rows = jdbc.queryForList(sql.toString(), args.toArray());
        if (rows.size() > MAX_ROWS) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY,
                    "统计结果超过100000条，请缩小日期或节点范围");
        }
        CarbonSecurityContext context = CarbonSecurityContext.current();
        List<Map<String, Object>> result = new ArrayList<>();
        for (Map<String, Object> source : rows) {
            Integer pointType = integerValue(source.get("collection_point_type"));
            Long pointId = longValue(source.get("collection_point_id"));
            if (pointType != null && pointId != null) {
                if (!scopes.canView(scopeType(pointType), "meter", pointId)) continue;
            } else if (!context.allData()) {
                // A virtual node has no physical collection scope.  It is only
                // safe to expose it to the all-data role until node-scope
                // filtering is explicitly available for snapshot rows.
                continue;
            }
            LocalDate date = toLocalDate(source.get("collection_record_end_date"));
            if (date == null) date = toLocalDate(source.get("calculation_cycle_end_date"));
            BigDecimal activity = decimal(source.get("adjusted_energy_value"));
            if (activity == null) activity = decimal(source.get("energy_measurement_value"));
            BigDecimal emission = decimal(source.get("adjusted_carbon_emission"));
            if (emission == null) emission = decimal(source.get("carbon_emission"));
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("id", longValue(source.get("id")));
            row.put("templateId", longValue(source.get("template_id")));
            row.put("nodeId", longValue(source.get("node_id")));
            row.put("nodeName", source.get("node_name"));
            row.put("collectionPointType", pointType);
            row.put("collectionPointId", pointId);
            row.put("collectionPointName", "核算结果");
            row.put("dataDate", date);
            row.put("month", date == null ? "" : date.toString().substring(0, 7));
            row.put("activityValue", activity);
            row.put("activityUnit", source.get("measurement_unit"));
            row.put("actualValue", emission);
            row.put("calculatedValue", emission);
            row.put("emissionFactor", decimal(source.get("carbon_emission_factor")));
            row.put("factorUnit", source.get("carbon_emission_factor_unit"));
            row.put("factorMissing", emission == null);
            row.put("dataSource", "CALCULATED");
            row.put("dataSourceName", "核算结果");
            row.put("qualityScore", Integer.valueOf(1).equals(integerValue(source.get("data_status")))
                    ? new BigDecimal("0.95") : new BigDecimal("0.60"));
            row.put("energyType", pointType == null ? "UNKNOWN" : energyTypeCode(pointType));
            row.put("energyTypeName", pointType == null ? "核算结果" : energyTypeName(pointType));
            row.put("emissionSubcategory", source.get("emission_subcategory"));
            row.put("isCumulative", integerValue(source.get("is_cumulative")));
            row.put("remarks", "核算任务 #" + text(source.get("calculation_task_id")));
            result.add(row);
        }
        return result;
    }

    private RawRecord mapRaw(ResultSet rs, int rowNum) throws SQLException {
        RawRecord item = new RawRecord();
        item.id = rs.getLong("id");
        item.collectionPointType = rs.getInt("collection_point_type");
        item.collectionPointId = rs.getLong("collection_point_id");
        item.reading = rs.getBigDecimal("reading_value");
        item.previousReading = rs.getBigDecimal("previous_reading");
        Timestamp time = rs.getTimestamp("collection_time");
        item.collectionTime = time.toLocalDateTime();
        item.externalQuality = rs.getString("external_quality");
        item.collectionPointName = rs.getString("collection_point_name");
        item.emissionSubcategory = rs.getString("emission_subcategory");
        item.measurementUnit = rs.getString("measurement_unit");
        item.meterReadingMethod = nullableInt(rs, "meter_reading_method");
        item.isCumulative = nullableInt(rs, "is_cumulative");
        item.reviewComment = rs.getString("review_comment");
        item.nodeId = nullableLong(rs, "node_id");
        item.factor = rs.getBigDecimal("carbon_emission_factor");
        item.factorUnit = rs.getString("carbon_emission_factor_unit");
        item.nodeName = rs.getString("node_name");
        item.templateId = nullableLong(rs, "template_id");
        item.factorTemplateId = nullableLong(rs, "factor_template_id");
        return item;
    }

    private ResolvedFactor resolveFactor(FactorKey key) {
        EmissionNodeConfig override = new EmissionNodeConfig();
        override.setCarbonEmissionFactor(key.overrideValue());
        override.setCarbonEmissionFactorUnit(key.overrideUnit());
        EffectiveFactorResolver.FactorSnapshot snapshot;
        try {
            snapshot = factorResolver.resolve(override, key.factorTemplateId(), key.subcategory());
        } catch (IllegalStateException ex) {
            return new ResolvedFactor(null, null, null);
        }

        BigDecimal coefficient;
        try {
            coefficient = factorDimensions.calculate(key.subcategory(), BigDecimal.ONE,
                    key.activityUnit(), snapshot.value(), snapshot.unit()).carbonTco2e();
        } catch (IllegalStateException | IllegalArgumentException ex) {
            coefficient = null;
        }
        return new ResolvedFactor(snapshot.value(), snapshot.unit(), coefficient);
    }

    private BigDecimal activity(RawRecord item) {
        if (!Integer.valueOf(1).equals(item.isCumulative)) return item.reading;
        if (item.previousReading == null) return BigDecimal.ZERO;
        BigDecimal delta = item.reading.subtract(item.previousReading);
        return delta.signum() >= 0 ? delta : item.reading;
    }

    private BigDecimal quality(RawRecord item, boolean factorValid) {
        if (!factorValid) return new BigDecimal("0.60");
        String quality = nullSafe(item.externalQuality).toUpperCase(Locale.ROOT);
        if (quality.contains("LOW") || quality.contains("差")) return new BigDecimal("0.70");
        if (quality.contains("NORMAL") || quality.contains("一般")) return new BigDecimal("0.85");
        if (quality.contains("HIGH") || quality.contains("GOOD") || quality.contains("优")) return BigDecimal.ONE;
        return Integer.valueOf(0).equals(item.meterReadingMethod) ? new BigDecimal("0.95") : new BigDecimal("0.98");
    }

    private void validate(Criteria criteria) {
        if (criteria.page < 0 || criteria.size < 1 || criteria.size > 5000) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "分页参数非法，size必须在1到5000之间");
        }
        if (criteria.startDate != null && criteria.endDate != null && criteria.startDate.isAfter(criteria.endDate)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "开始日期不能晚于结束日期");
        }
        if (criteria.energyType != null && (criteria.energyType < 1 || criteria.energyType > 3)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "能源类型仅支持1、2、3");
        }
        if (criteria.dataSource != null && !Set.of("AUTO", "MANUAL", "CALCULATED").contains(criteria.dataSource)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "数据来源仅支持AUTO、MANUAL或CALCULATED");
        }
    }

    private Comparator<Map<String, Object>> comparator(String field, String direction) {
        Function<Map<String, Object>, Comparable<?>> extractor = switch (field == null ? "dataDate" : field) {
            case "nodeName" -> row -> nullSafe(row.get("nodeName"));
            case "activityValue" -> row -> decimal(row.get("activityValue"));
            case "calculatedValue", "actualValue" -> row -> decimal(row.get("calculatedValue"));
            default -> row -> (LocalDate) row.get("dataDate");
        };
        Comparator<Map<String, Object>> comparator = (left, right) -> compareNullable(extractor.apply(left), extractor.apply(right));
        return "ASC".equalsIgnoreCase(direction) ? comparator : comparator.reversed();
    }

    @SuppressWarnings({"rawtypes", "unchecked"})
    private int compareNullable(Comparable left, Comparable right) {
        if (left == null && right == null) return 0;
        if (left == null) return -1;
        if (right == null) return 1;
        return left.compareTo(right);
    }

    private Map<String, BigDecimal> groupedSum(List<Map<String, Object>> rows, String group, String value) {
        Map<String, BigDecimal> result = new TreeMap<>();
        for (Map<String, Object> row : rows) {
            String key = nullSafe(row.get(group));
            if (key.isBlank()) key = "未配置";
            BigDecimal amount = decimal(row.get(value));
            if (amount != null) result.merge(key, amount, BigDecimal::add);
        }
        return result;
    }

    private BigDecimal sum(List<Map<String, Object>> rows, String field) {
        return rows.stream().map(row -> decimal(row.get(field))).filter(Objects::nonNull)
                .reduce(BigDecimal.ZERO, BigDecimal::add).setScale(9, RoundingMode.HALF_UP);
    }

    private List<Map<String, Object>> series(Map<String, BigDecimal> values) { return series(values, "name"); }

    private List<Map<String, Object>> series(Map<String, BigDecimal> values, String keyName) {
        return values.entrySet().stream().map(entry -> {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put(keyName, entry.getKey());
            item.put("value", entry.getValue().setScale(9, RoundingMode.HALF_UP));
            return item;
        }).toList();
    }

    private Integer nullableInt(ResultSet rs, String column) throws SQLException { int value = rs.getInt(column); return rs.wasNull() ? null : value; }
    private Long nullableLong(ResultSet rs, String column) throws SQLException { long value = rs.getLong(column); return rs.wasNull() ? null : value; }
    private Integer integerValue(Object value) {
        if (value instanceof Number number) return number.intValue();
        if (value == null) return null;
        try { return Integer.valueOf(value.toString()); } catch (NumberFormatException ignored) { return null; }
    }
    private Long longValue(Object value) {
        if (value instanceof Number number) return number.longValue();
        if (value == null) return null;
        try { return Long.valueOf(value.toString()); } catch (NumberFormatException ignored) { return null; }
    }
    private LocalDate toLocalDate(Object value) {
        if (value instanceof LocalDate date) return date;
        if (value instanceof java.sql.Date date) return date.toLocalDate();
        if (value instanceof Timestamp timestamp) return timestamp.toLocalDateTime().toLocalDate();
        if (value == null) return null;
        try { return LocalDate.parse(value.toString().substring(0, 10)); }
        catch (RuntimeException ignored) { return null; }
    }
    private BigDecimal decimal(Object value) { if (value instanceof BigDecimal decimal) return decimal; if (value instanceof Number number) return BigDecimal.valueOf(number.doubleValue()); return null; }
    private String text(Object value) { return value == null ? "" : String.valueOf(value); }
    private String nullSafe(Object value) { return value == null ? "" : String.valueOf(value); }
    private String scopeType(int type) { return switch (type) { case 1 -> "electricity"; case 2 -> "fossil"; case 3 -> "heat"; default -> ""; }; }
    private String energyTypeCode(int type) { return switch (type) { case 1 -> "ELECTRICITY"; case 2 -> "FOSSIL"; case 3 -> "HEAT"; default -> "UNKNOWN"; }; }
    private String energyTypeName(int type) { return switch (type) { case 1 -> "购入电力"; case 2 -> "化石燃料"; case 3 -> "外购热力"; default -> "未知"; }; }

    public static class Criteria {
        public Long templateId;
        public Long nodeId;
        public LocalDate startDate;
        public LocalDate endDate;
        public Integer energyType;
        public String dataSource;
        public int page = 0;
        public int size = 20;
        public String sortBy = "dataDate";
        public String sortDirection = "DESC";
    }

    private record FactorKey(Long factorTemplateId, String subcategory, String activityUnit,
                             BigDecimal overrideValue, String overrideUnit) {
    }

    private record ResolvedFactor(BigDecimal value, String unit, BigDecimal coefficient) {
    }

    private static class RawRecord {
        long id;
        int collectionPointType;
        long collectionPointId;
        BigDecimal reading;
        BigDecimal previousReading;
        LocalDateTime collectionTime;
        String externalQuality;
        String collectionPointName;
        String emissionSubcategory;
        String measurementUnit;
        Integer meterReadingMethod;
        Integer isCumulative;
        String reviewComment;
        Long nodeId;
        BigDecimal factor;
        String factorUnit;
        String nodeName;
        Long templateId;
        Long factorTemplateId;
    }
}
