-- Manual collection review workflow migration. Safe to run repeatedly.
SET NAMES utf8mb4;
SET @db := DATABASE();

SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=@db AND table_name='emission_collection_record' AND column_name='workflow_status')=0,
  'ALTER TABLE emission_collection_record ADD COLUMN workflow_status VARCHAR(20) NOT NULL DEFAULT ''APPROVED'' COMMENT ''manual review status'' AFTER collection_status', 'SELECT 1'); PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=@db AND table_name='emission_collection_record' AND column_name='submitter_id')=0,
  'ALTER TABLE emission_collection_record ADD COLUMN submitter_id BIGINT NULL COMMENT ''submitter id'' AFTER workflow_status', 'SELECT 1'); PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=@db AND table_name='emission_collection_record' AND column_name='submitted_at')=0,
  'ALTER TABLE emission_collection_record ADD COLUMN submitted_at TIMESTAMP NULL COMMENT ''submitted time'' AFTER submitter_id', 'SELECT 1'); PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=@db AND table_name='emission_collection_record' AND column_name='reviewer_id')=0,
  'ALTER TABLE emission_collection_record ADD COLUMN reviewer_id BIGINT NULL COMMENT ''reviewer id'' AFTER submitted_at', 'SELECT 1'); PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=@db AND table_name='emission_collection_record' AND column_name='reviewed_at')=0,
  'ALTER TABLE emission_collection_record ADD COLUMN reviewed_at TIMESTAMP NULL COMMENT ''reviewed time'' AFTER reviewer_id', 'SELECT 1'); PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
SET @sql := IF((SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=@db AND table_name='emission_collection_record' AND column_name='review_comment')=0,
  'ALTER TABLE emission_collection_record ADD COLUMN review_comment VARCHAR(500) NULL COMMENT ''review comment'' AFTER reviewed_at', 'SELECT 1'); PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;
SET @sql := IF((SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=@db AND table_name='emission_collection_record' AND index_name='idx_workflow_status')=0,
  'ALTER TABLE emission_collection_record ADD INDEX idx_workflow_status (workflow_status)', 'SELECT 1'); PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

INSERT INTO sys_config (config_key, config_value, config_name, remark)
SELECT 'carbon.collection.manual.auto-approve', 'false', '具有审核权限的人在提交人工采集数据后自动审核通过', '开启后，具有碳排放数据审核权限的人员提交人工采集数据时自动审核通过；关闭后进入待审核状态。'
WHERE NOT EXISTS (SELECT 1 FROM sys_config WHERE config_key = 'carbon.collection.manual.auto-approve');

CREATE TABLE IF NOT EXISTS emission_collection_record_audit (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    record_id BIGINT NOT NULL,
    action VARCHAR(30) NOT NULL,
    from_status VARCHAR(20),
    to_status VARCHAR(20),
    operator_id BIGINT,
    operator_name VARCHAR(100),
    comment VARCHAR(500),
    operated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_collection_audit_record (record_id),
    INDEX idx_collection_audit_time (operated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='采集记录审核流水';
