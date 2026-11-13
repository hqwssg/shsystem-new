USE carbon_emissions;

CREATE TABLE IF NOT EXISTS prediction_monthly_source_head (
  org_id VARCHAR(16) NOT NULL,
  period DATE NOT NULL,
  source_version BIGINT NOT NULL DEFAULT 0,
  awaiting_source TINYINT(1) NOT NULL DEFAULT 0,
  batch_id VARCHAR(40),
  PRIMARY KEY (org_id, period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS prediction_monthly_source_receipt (
  idempotency_key VARCHAR(64) NOT NULL,
  org_id VARCHAR(16) NOT NULL,
  period DATE NOT NULL,
  source_version BIGINT NOT NULL,
  request_hash CHAR(64) NOT NULL,
  payload JSON NOT NULL,
  response JSON NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (idempotency_key),
  UNIQUE KEY uk_prediction_source_version (org_id, period, source_version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
