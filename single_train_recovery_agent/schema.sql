CREATE TABLE IF NOT EXISTS single_dept_project (
 dept_id BIGINT NOT NULL, project_code VARCHAR(100) NOT NULL,
 enabled TINYINT NOT NULL DEFAULT 1, PRIMARY KEY(dept_id,project_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS single_version (
 version_id CHAR(36) PRIMARY KEY, target_module VARCHAR(20) NOT NULL,
 project_code VARCHAR(100) NOT NULL, version_code VARCHAR(100) NOT NULL,
 version_name VARCHAR(200) NOT NULL, route_name VARCHAR(200) NOT NULL,
 status VARCHAR(20) NOT NULL DEFAULT 'draft', data_status VARCHAR(50) NOT NULL,
 files_json LONGTEXT NOT NULL, parameters_json LONGTEXT NOT NULL,
 provenance_json LONGTEXT NOT NULL, content_sha256 CHAR(64) NOT NULL,
 created_by VARCHAR(100) NOT NULL, created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 UNIQUE KEY single_version_code(target_module,project_code,version_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS single_run (
 run_id CHAR(36) PRIMARY KEY, version_id CHAR(36) NOT NULL,
 project_code VARCHAR(100) NOT NULL, dept_id BIGINT NULL,
 requested_by VARCHAR(100) NOT NULL, run_type VARCHAR(20) NOT NULL,
 status VARCHAR(20) NOT NULL, idempotency_key VARCHAR(100) NOT NULL,
 request_sha256 CHAR(64) NOT NULL, snapshot_json LONGTEXT NOT NULL,
 parameters_json LONGTEXT NOT NULL, code_sha256 CHAR(64) NOT NULL,
 total_cases INT NOT NULL DEFAULT 0, completed_cases INT NOT NULL DEFAULT 0,
 current_case VARCHAR(300) NULL, error_message TEXT NULL,
 cancel_requested TINYINT NOT NULL DEFAULT 0,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 started_at DATETIME(6) NULL, heartbeat_at DATETIME(6) NULL, finished_at DATETIME(6) NULL,
 UNIQUE KEY single_run_idempotency(requested_by,idempotency_key),
 KEY single_run_queue(status,created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS single_case (
 case_id CHAR(36) PRIMARY KEY, run_id CHAR(36) NOT NULL,
 scenario_key VARCHAR(150) NOT NULL, scenario_name VARCHAR(300) NOT NULL,
 controller_key VARCHAR(100) NOT NULL, controller_name VARCHAR(300) NOT NULL,
 status VARCHAR(20) NOT NULL, eligible TINYINT NOT NULL DEFAULT 0,
 metrics_json LONGTEXT NOT NULL, audit_json LONGTEXT NOT NULL,
 error_message TEXT NULL, UNIQUE KEY single_case_identity(run_id,scenario_key,controller_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS single_artifact (
 artifact_id CHAR(36) PRIMARY KEY, run_id CHAR(36) NOT NULL, case_id CHAR(36) NULL,
 relative_path VARCHAR(300) NOT NULL, kind VARCHAR(20) NOT NULL,
 size_bytes BIGINT NOT NULL, content_sha256 CHAR(64) NOT NULL,
 UNIQUE KEY single_artifact_path(run_id,relative_path)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
