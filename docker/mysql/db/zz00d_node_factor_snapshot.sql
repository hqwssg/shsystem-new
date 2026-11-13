-- Clean incomplete legacy node overrides. A factor override is valid only when
-- value and unit are both present; otherwise the node inherits its template factor.
SET NAMES utf8mb4;

-- Preflight evidence: preserve this result with the deployment record before updating.
SELECT node_id,
       carbon_emission_factor,
       carbon_emission_factor_unit,
       carbon_emission_factor_description
FROM emission_node_config
WHERE (carbon_emission_factor IS NULL
       AND NULLIF(TRIM(carbon_emission_factor_unit), '') IS NOT NULL)
   OR (carbon_emission_factor IS NOT NULL
       AND NULLIF(TRIM(carbon_emission_factor_unit), '') IS NULL)
ORDER BY node_id;

UPDATE emission_node_config
SET carbon_emission_factor = NULL,
    carbon_emission_factor_unit = NULL,
    carbon_emission_factor_description = NULL
WHERE (carbon_emission_factor IS NULL
       AND NULLIF(TRIM(carbon_emission_factor_unit), '') IS NOT NULL)
   OR (carbon_emission_factor IS NOT NULL
       AND NULLIF(TRIM(carbon_emission_factor_unit), '') IS NULL);

UPDATE emission_node_config
SET carbon_emission_factor_unit = NULL
WHERE carbon_emission_factor IS NULL
  AND carbon_emission_factor_unit IS NOT NULL
  AND TRIM(carbon_emission_factor_unit) = '';

-- Postcondition: must return zero.
SELECT COUNT(*) AS incomplete_factor_snapshot_count
FROM emission_node_config
WHERE (carbon_emission_factor IS NULL
       AND NULLIF(TRIM(carbon_emission_factor_unit), '') IS NOT NULL)
   OR (carbon_emission_factor IS NOT NULL
       AND NULLIF(TRIM(carbon_emission_factor_unit), '') IS NULL);
