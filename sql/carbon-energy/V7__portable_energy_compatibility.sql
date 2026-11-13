-- Portable fallback storage for online energy-version editing.
-- Idempotent and safe for existing databases.

CREATE TABLE IF NOT EXISTS energy_version_edit_sheet (
    sheet_id bigint(20) NOT NULL AUTO_INCREMENT,
    version_id char(36) NOT NULL,
    topic_code varchar(64) NOT NULL,
    sheet_name varchar(128) NOT NULL,
    columns_json json NOT NULL,
    rows_json json NOT NULL,
    source_note text,
    updated_by varchar(64),
    created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT uq_energy_edit_sheet UNIQUE (version_id, topic_code, sheet_name),
    PRIMARY KEY (sheet_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
