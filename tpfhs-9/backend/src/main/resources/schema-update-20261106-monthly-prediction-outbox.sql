CREATE TABLE IF NOT EXISTS emission_monthly_prediction_outbox (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    company_dept_id BIGINT NOT NULL,
    template_id BIGINT NOT NULL,
    period DATE NOT NULL,
    operation_type TINYINT NOT NULL,
    snapshot JSON NOT NULL,
    request_payload JSON,
    delivery_status VARCHAR(24) NOT NULL,
    attempt_count INT NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    lease_until TIMESTAMP NULL,
    batch_id VARCHAR(64),
    last_error VARCHAR(512),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_monthly_outbox_version (company_dept_id, period, id),
    INDEX idx_monthly_outbox_due (delivery_status, next_attempt_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
