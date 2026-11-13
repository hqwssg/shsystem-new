-- 补齐被旧版 schema.sql 注释掉的预置电表型号。按型号名称判断，重复执行安全，
-- 且不会覆盖用户已创建或修改的同名型号。
INSERT INTO emission_meter_model (model_name, model_type, description)
SELECT seed.model_name, seed.model_type, seed.description
FROM (
    SELECT 'DDZY2088' AS model_name, '单相' AS model_type, '单相电子式智能电能表，精度等级2.0级' AS description
    UNION ALL SELECT 'DDZY1980', '单相', '单相费控智能电能表，精度等级2.0级'
    UNION ALL SELECT 'DTZY2088', '三相四线', '三相四线电子式智能电能表，精度等级1.0级'
    UNION ALL SELECT 'DTZY1980', '三相四线', '三相四线费控智能电能表，精度等级1.0级'
    UNION ALL SELECT 'DTZ2088', '三相三线', '三相三线电子式智能电能表，精度等级1.0级'
    UNION ALL SELECT 'DTZY566', '三相四线', '三相四线智能电能表，精度等级0.5S级'
    UNION ALL SELECT 'DDZY866', '单相', '单相智能电能表，精度等级2.0级'
    UNION ALL SELECT 'DTZY866', '三相四线', '三相四线智能电能表，精度等级1.0级'
    UNION ALL SELECT 'DTZY217-Z', '三相四线', '三相四线智能电能表，精度等级1.0级'
    UNION ALL SELECT 'DDZY217-Z', '单相', '单相智能电能表，精度等级2.0级'
    UNION ALL SELECT 'DTZ188', '三相三线', '三相三线电能表，精度等级0.5级'
    UNION ALL SELECT 'DTZ88', '三相三线', '三相三线电能表，精度等级0.5级'
    UNION ALL SELECT 'DT5-GX2', '三相三线', '三相三线电能表'
    UNION ALL SELECT 'DSZY188-G', '三相四线', '三相四线智能电能表，精度等级1级'
    UNION ALL SELECT 'DSZ71', '三相四线', '三相四线电能表，精度等级0.5s级'
    UNION ALL SELECT 'DSZ178', '三相四线', '三相四线电能表，精度等级0.5s级'
    UNION ALL SELECT 'DTZ341', '三相三线', '三相三线电能表，精度等级0.2s级'
    UNION ALL SELECT 'DTZ1296', '三相三线', '三相三线电能表，精度等级0.2s级'
    UNION ALL SELECT 'DTZ178', '三相三线', '三相三线电能表，精度等级0.5s级'
    UNION ALL SELECT 'YD2040', '综合电力监测仪表', '三相电力监测仪表，可测量电压、电流、功率、电能等全量电参数，直连电压最高支持600V AC，适配多种接线方式，广泛用于工业电力监控场景'
    UNION ALL SELECT 'DTZ71', '三相三线', '三相三线电能表，精度等级0.5级'
    UNION ALL SELECT 'PD510-M14/R', '单相', '单相电能表，精度等级0.5级'
) seed
LEFT JOIN emission_meter_model existing
       ON existing.model_name = seed.model_name
WHERE existing.id IS NULL;
