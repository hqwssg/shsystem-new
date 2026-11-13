-- Remove historical successful runs that were fabricated by the retired Java
-- compatibility mode. Child result rows are deleted through foreign keys.
SET NAMES utf8mb4;
USE carbon_emissions;

DELETE FROM energy_run
WHERE run_id IN (
    '11111111-1111-1111-1111-111111111111',
    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
    'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
    'cccccccc-cccc-cccc-cccc-cccccccccccc',
    'dddddddd-dddd-dddd-dddd-dddddddddddd'
)
  AND (worker_id IN ('fixture-worker', 'builtin-compatibility')
       OR code_version = 'builtin-compatibility');
