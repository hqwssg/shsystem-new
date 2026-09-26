-- 碳核算任务周期幂等及运行快照排除状态升级
-- 执行前必须备份数据库。本脚本不会删除或合并历史任务；发现异常历史数据时主动停止。
SET NAMES utf8mb4;

DELIMITER //
DROP PROCEDURE IF EXISTS migrate_20260921_validation_idempotency_exclusion//
CREATE PROCEDURE migrate_20260921_validation_idempotency_exclusion()
BEGIN
    DECLARE invalid_cycles BIGINT DEFAULT 0;
    DECLARE duplicate_cycles BIGINT DEFAULT 0;
    DECLARE column_exists INT DEFAULT 0;
    DECLARE index_exists INT DEFAULT 0;

    SELECT COUNT(*) INTO invalid_cycles
      FROM emission_calculation_template
     WHERE calculation_cycle_start_date IS NULL
        OR calculation_cycle_end_date IS NULL;
    IF invalid_cycles > 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '迁移停止：历史核算任务存在空周期，请人工核查后重试';
    END IF;

    SELECT COUNT(*) INTO duplicate_cycles
      FROM (
        SELECT template_id, calculation_cycle_start_date, calculation_cycle_end_date
          FROM emission_calculation_template
         GROUP BY template_id, calculation_cycle_start_date, calculation_cycle_end_date
        HAVING COUNT(*) > 1
      ) duplicates;
    IF duplicate_cycles > 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = '迁移停止：历史核算任务存在重复模板周期，请人工核查后重试';
    END IF;

    ALTER TABLE emission_calculation_template
        MODIFY calculation_cycle_start_date DATE NOT NULL COMMENT '核算周期起始日期（只保留日期部分）',
        MODIFY calculation_cycle_end_date DATE NOT NULL COMMENT '核算周期截止日期（只保留日期部分）';

    SELECT COUNT(*) INTO index_exists
      FROM information_schema.statistics
     WHERE table_schema = DATABASE()
       AND table_name = 'emission_calculation_template'
       AND index_name = 'uk_template_cycle';
    IF index_exists = 0 THEN
        ALTER TABLE emission_calculation_template
            ADD UNIQUE KEY uk_template_cycle
                (template_id, calculation_cycle_start_date, calculation_cycle_end_date);
    END IF;

    SELECT COUNT(*) INTO column_exists
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'emission_calculation_node'
       AND column_name = 'include_in_calculation';
    IF column_exists = 0 THEN
        ALTER TABLE emission_calculation_node
            ADD COLUMN include_in_calculation BOOLEAN NOT NULL DEFAULT TRUE
                COMMENT '本次任务中是否最终纳入核算（包含祖先排除规则）'
                AFTER node_category;
    END IF;

    SELECT COUNT(*) INTO column_exists
      FROM information_schema.columns
     WHERE table_schema = DATABASE()
       AND table_name = 'emission_calculation_node'
       AND column_name = 'excluded_by_node_id';
    IF column_exists = 0 THEN
        ALTER TABLE emission_calculation_node
            ADD COLUMN excluded_by_node_id BIGINT NULL
                COMMENT '导致本节点被排除的设计态节点ID，正常纳入时为空'
                AFTER include_in_calculation;
    END IF;
END//
CALL migrate_20260921_validation_idempotency_exclusion()//
DROP PROCEDURE migrate_20260921_validation_idempotency_exclusion//
DELIMITER ;
