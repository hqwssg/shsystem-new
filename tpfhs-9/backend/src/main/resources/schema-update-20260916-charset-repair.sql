-- Repair one-time UTF-8 -> latin1 -> UTF-8 mojibake introduced by the
-- original Windows/Docker import command. This migration is intentionally
-- limited to carbon-accounting seed/configuration data. Historical audit
-- tables (for example sys_oper_log) are immutable and are not changed.
--
-- Idempotency: after a value is repaired its UTF-8 bytes no longer match
-- @mojibake_hex, so a second execution updates zero rows.

SET NAMES utf8mb4;
USE `carbon_emissions`;

-- A one-level corruption of Chinese UTF-8 always contains the UTF-8 form of
-- latin1/cp1252 characters such as ä/å/æ/ç/è/é/â/Â/Ã. Do not match E280xx
-- alone because a valid Chinese description may legitimately contain — or “”.
SET @mojibake_hex = 'C3(A[2-9F]|8[23])';

START TRANSACTION;

-- Data dictionaries and node types.
UPDATE emission_data_dict
SET dict_name = CONVERT(CAST(CONVERT(dict_name USING latin1) AS BINARY) USING utf8mb4)
WHERE HEX(dict_name) REGEXP @mojibake_hex;
UPDATE emission_data_dict
SET description = CONVERT(CAST(CONVERT(description USING latin1) AS BINARY) USING utf8mb4)
WHERE description IS NOT NULL AND HEX(description) REGEXP @mojibake_hex;

UPDATE emission_data_dict_item
SET item_value = CONVERT(CAST(CONVERT(item_value USING latin1) AS BINARY) USING utf8mb4)
WHERE HEX(item_value) REGEXP @mojibake_hex;

UPDATE emission_node_type
SET type_name = CONVERT(CAST(CONVERT(type_name USING latin1) AS BINARY) USING utf8mb4)
WHERE HEX(type_name) REGEXP @mojibake_hex;
UPDATE emission_node_type
SET description = CONVERT(CAST(CONVERT(description USING latin1) AS BINARY) USING utf8mb4)
WHERE description IS NOT NULL AND HEX(description) REGEXP @mojibake_hex;

UPDATE emission_energy_category
SET category_name = CONVERT(CAST(CONVERT(category_name USING latin1) AS BINARY) USING utf8mb4)
WHERE HEX(category_name) REGEXP @mojibake_hex;
UPDATE emission_energy_category
SET remark = CONVERT(CAST(CONVERT(remark USING latin1) AS BINARY) USING utf8mb4)
WHERE remark IS NOT NULL AND HEX(remark) REGEXP @mojibake_hex;

-- Emission factor seed libraries. created_by IS NULL identifies the
-- repository-provided baseline and avoids rewriting user-created factors.
UPDATE emission_electricity_carbon_emission_factor
SET factor_name = CONVERT(CAST(CONVERT(factor_name USING latin1) AS BINARY) USING utf8mb4)
WHERE created_by IS NULL AND HEX(factor_name) REGEXP @mojibake_hex;
UPDATE emission_electricity_carbon_emission_factor
SET unit = CONVERT(CAST(CONVERT(unit USING latin1) AS BINARY) USING utf8mb4)
WHERE created_by IS NULL AND HEX(unit) REGEXP @mojibake_hex;
UPDATE emission_electricity_carbon_emission_factor
SET description = CONVERT(CAST(CONVERT(description USING latin1) AS BINARY) USING utf8mb4)
WHERE created_by IS NULL AND description IS NOT NULL AND HEX(description) REGEXP @mojibake_hex;

UPDATE emission_fossil_fuel_emission_factor
SET emission_factor_name = CONVERT(CAST(CONVERT(emission_factor_name USING latin1) AS BINARY) USING utf8mb4)
WHERE created_by IS NULL AND emission_factor_name IS NOT NULL AND HEX(emission_factor_name) REGEXP @mojibake_hex;
UPDATE emission_fossil_fuel_emission_factor
SET fuel_type = CONVERT(CAST(CONVERT(fuel_type USING latin1) AS BINARY) USING utf8mb4)
WHERE created_by IS NULL AND HEX(fuel_type) REGEXP @mojibake_hex;
UPDATE emission_fossil_fuel_emission_factor
SET source = CONVERT(CAST(CONVERT(source USING latin1) AS BINARY) USING utf8mb4)
WHERE created_by IS NULL AND source IS NOT NULL AND HEX(source) REGEXP @mojibake_hex;
UPDATE emission_fossil_fuel_emission_factor
SET unit = CONVERT(CAST(CONVERT(unit USING latin1) AS BINARY) USING utf8mb4)
WHERE created_by IS NULL AND HEX(unit) REGEXP @mojibake_hex;
UPDATE emission_fossil_fuel_emission_factor
SET factor_unit = CONVERT(CAST(CONVERT(factor_unit USING latin1) AS BINARY) USING utf8mb4)
WHERE created_by IS NULL AND factor_unit IS NOT NULL AND HEX(factor_unit) REGEXP @mojibake_hex;
UPDATE emission_fossil_fuel_emission_factor
SET description = CONVERT(CAST(CONVERT(description USING latin1) AS BINARY) USING utf8mb4)
WHERE created_by IS NULL AND description IS NOT NULL AND HEX(description) REGEXP @mojibake_hex;

UPDATE emission_thermal_emission_factor
SET emission_factor_name = CONVERT(CAST(CONVERT(emission_factor_name USING latin1) AS BINARY) USING utf8mb4)
WHERE created_by IS NULL AND emission_factor_name IS NOT NULL AND HEX(emission_factor_name) REGEXP @mojibake_hex;
UPDATE emission_thermal_emission_factor
SET unit = CONVERT(CAST(CONVERT(unit USING latin1) AS BINARY) USING utf8mb4)
WHERE created_by IS NULL AND unit IS NOT NULL AND HEX(unit) REGEXP @mojibake_hex;
UPDATE emission_thermal_emission_factor
SET source = CONVERT(CAST(CONVERT(source USING latin1) AS BINARY) USING utf8mb4)
WHERE created_by IS NULL AND source IS NOT NULL AND HEX(source) REGEXP @mojibake_hex;
UPDATE emission_thermal_emission_factor
SET description = CONVERT(CAST(CONVERT(description USING latin1) AS BINARY) USING utf8mb4)
WHERE created_by IS NULL AND description IS NOT NULL AND HEX(description) REGEXP @mojibake_hex;

UPDATE emission_wastewater_treatment_factor
SET emission_factor_name = CONVERT(CAST(CONVERT(emission_factor_name USING latin1) AS BINARY) USING utf8mb4)
WHERE created_by IS NULL AND emission_factor_name IS NOT NULL AND HEX(emission_factor_name) REGEXP @mojibake_hex;
UPDATE emission_wastewater_treatment_factor
SET wastewater_type = CONVERT(CAST(CONVERT(wastewater_type USING latin1) AS BINARY) USING utf8mb4)
WHERE created_by IS NULL AND wastewater_type IS NOT NULL AND HEX(wastewater_type) REGEXP @mojibake_hex;
UPDATE emission_wastewater_treatment_factor
SET unit = CONVERT(CAST(CONVERT(unit USING latin1) AS BINARY) USING utf8mb4)
WHERE created_by IS NULL AND unit IS NOT NULL AND HEX(unit) REGEXP @mojibake_hex;
UPDATE emission_wastewater_treatment_factor
SET source = CONVERT(CAST(CONVERT(source USING latin1) AS BINARY) USING utf8mb4)
WHERE created_by IS NULL AND source IS NOT NULL AND HEX(source) REGEXP @mojibake_hex;
UPDATE emission_wastewater_treatment_factor
SET description = CONVERT(CAST(CONVERT(description USING latin1) AS BINARY) USING utf8mb4)
WHERE created_by IS NULL AND description IS NOT NULL AND HEX(description) REGEXP @mojibake_hex;

UPDATE emission_waste_incineration_factor
SET emission_factor_name = CONVERT(CAST(CONVERT(emission_factor_name USING latin1) AS BINARY) USING utf8mb4)
WHERE created_by IS NULL AND emission_factor_name IS NOT NULL AND HEX(emission_factor_name) REGEXP @mojibake_hex;
UPDATE emission_waste_incineration_factor
SET waste_type = CONVERT(CAST(CONVERT(waste_type USING latin1) AS BINARY) USING utf8mb4)
WHERE created_by IS NULL AND waste_type IS NOT NULL AND HEX(waste_type) REGEXP @mojibake_hex;
UPDATE emission_waste_incineration_factor
SET unit = CONVERT(CAST(CONVERT(unit USING latin1) AS BINARY) USING utf8mb4)
WHERE created_by IS NULL AND unit IS NOT NULL AND HEX(unit) REGEXP @mojibake_hex;
UPDATE emission_waste_incineration_factor
SET source = CONVERT(CAST(CONVERT(source USING latin1) AS BINARY) USING utf8mb4)
WHERE created_by IS NULL AND source IS NOT NULL AND HEX(source) REGEXP @mojibake_hex;
UPDATE emission_waste_incineration_factor
SET description = CONVERT(CAST(CONVERT(description USING latin1) AS BINARY) USING utf8mb4)
WHERE created_by IS NULL AND description IS NOT NULL AND HEX(description) REGEXP @mojibake_hex;

-- Unit dictionaries and conversion descriptions. Codes remain unchanged.
UPDATE emission_calc_unit_default
SET subcategory_name = CONVERT(CAST(CONVERT(subcategory_name USING latin1) AS BINARY) USING utf8mb4)
WHERE HEX(subcategory_name) REGEXP @mojibake_hex;
UPDATE emission_calc_unit_default
SET remark = CONVERT(CAST(CONVERT(remark USING latin1) AS BINARY) USING utf8mb4)
WHERE remark IS NOT NULL AND HEX(remark) REGEXP @mojibake_hex;

UPDATE emission_unit_conversion
SET remark = CONVERT(CAST(CONVERT(remark USING latin1) AS BINARY) USING utf8mb4)
WHERE remark IS NOT NULL AND HEX(remark) REGEXP @mojibake_hex;

UPDATE emission_unit_standard
SET unit_name = CONVERT(CAST(CONVERT(unit_name USING latin1) AS BINARY) USING utf8mb4)
WHERE HEX(unit_name) REGEXP @mojibake_hex;

UPDATE emission_ghg_unit
SET ghg_name = CONVERT(CAST(CONVERT(ghg_name USING latin1) AS BINARY) USING utf8mb4)
WHERE HEX(ghg_name) REGEXP @mojibake_hex;

UPDATE emission_factor_unit
SET factor_unit_name = CONVERT(CAST(CONVERT(factor_unit_name USING latin1) AS BINARY) USING utf8mb4)
WHERE HEX(factor_unit_name) REGEXP @mojibake_hex;

-- Only the repository-provided default template/root are repaired here.
UPDATE emission_template
SET name = CONVERT(CAST(CONVERT(name USING latin1) AS BINARY) USING utf8mb4),
    description = CONVERT(CAST(CONVERT(description USING latin1) AS BINARY) USING utf8mb4)
WHERE id = 1
  AND (HEX(name) REGEXP @mojibake_hex OR HEX(description) REGEXP @mojibake_hex);

UPDATE emission_node
SET name = CONVERT(CAST(CONVERT(name USING latin1) AS BINARY) USING utf8mb4)
WHERE id = 1 AND HEX(name) REGEXP @mojibake_hex;

COMMIT;

-- The result set is intentionally small and contains no credentials.
SELECT item_code, item_value
FROM emission_data_dict_item
WHERE item_code IN ('PE_PF', 'FF_D', 'FF_NG')
ORDER BY item_code;
