DELIMITER //
DROP PROCEDURE IF EXISTS import_ruoyi_business_history//
CREATE PROCEDURE import_ruoyi_business_history()
BEGIN
  DECLARE lock_result INT DEFAULT 0;
  DECLARE collection_record_id_base BIGINT DEFAULT 0;
  DECLARE collection_audit_id_base BIGINT DEFAULT 0;
  DECLARE report_task_id_base BIGINT DEFAULT 0;
  DECLARE node_id_base BIGINT DEFAULT 0;
  DECLARE detail_id_base BIGINT DEFAULT 0;
  DECLARE summary_id_base BIGINT DEFAULT 0;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    DO RELEASE_LOCK('ruoyi_business_history_import_v1');
    RESIGNAL;
  END;

  SELECT GET_LOCK('ruoyi_business_history_import_v1', 10) INTO lock_result;
  IF lock_result <> 1 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Could not acquire business history import lock';
  END IF;

  START TRANSACTION;

  IF EXISTS (
    SELECT 1 FROM stg_emission_calculation_template s
    LEFT JOIN emission_template t ON t.id=s.template_id WHERE t.id IS NULL
  ) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='A source emission template is missing on target'; END IF;

  -- emission_calculation_node is a historical snapshot. Its node_id is not a
  -- foreign key because source nodes may legitimately be removed or replaced
  -- after a calculation completes. Keep the snapshot instead of requiring the
  -- current emission_node tree to contain every historical source node.

  IF EXISTS (
    SELECT 1 FROM stg_report_task s
    LEFT JOIN sys_dept d ON d.dept_id=s.dept_id WHERE d.dept_id IS NULL
  ) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='A report department is missing on target'; END IF;

  IF EXISTS (
    SELECT 1 FROM stg_emission_calculation_template s JOIN emission_calculation_template t ON t.id=s.id
    WHERE NOT (t.template_id<=>s.template_id AND t.calculation_cycle_start_date<=>s.calculation_cycle_start_date
      AND t.calculation_cycle_end_date<=>s.calculation_cycle_end_date AND t.data_revision<=>s.data_revision)
  ) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Calculation task ID conflict; nothing imported'; END IF;

  IF EXISTS (
    SELECT 1 FROM stg_emission_calculation_template s JOIN emission_calculation_template t
      ON t.template_id=s.template_id AND t.calculation_cycle_start_date<=>s.calculation_cycle_start_date
      AND t.calculation_cycle_end_date<=>s.calculation_cycle_end_date AND t.data_revision=s.data_revision
    WHERE t.id<>s.id
  ) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Calculation task business-key conflict; nothing imported'; END IF;

  CREATE TEMPORARY TABLE map_collection_record (
    source_id BIGINT NOT NULL PRIMARY KEY,
    target_id BIGINT NOT NULL UNIQUE,
    is_existing TINYINT NOT NULL
  );
  INSERT INTO map_collection_record (source_id,target_id,is_existing)
    SELECT s.id,MIN(t.id),1 FROM stg_emission_collection_record s
    JOIN emission_collection_record t ON t.collection_point_type=s.collection_point_type
      AND t.collection_point_id=s.collection_point_id AND t.collection_time<=>s.collection_time
      AND t.billing_cycle_start_date<=>s.billing_cycle_start_date
      AND t.billing_cycle_end_date<=>s.billing_cycle_end_date AND t.created_at<=>s.created_at
      AND t.external_record_id<=>s.external_record_id
    GROUP BY s.id;
  INSERT IGNORE INTO map_collection_record (source_id,target_id,is_existing)
    SELECT s.id,s.id,0 FROM stg_emission_collection_record s
    LEFT JOIN emission_collection_record occupied ON occupied.id=s.id
    WHERE occupied.id IS NULL;
  SELECT GREATEST(COALESCE(MAX(id),0),(SELECT COALESCE(MAX(id),0) FROM stg_emission_collection_record))+1000
    INTO collection_record_id_base FROM emission_collection_record;
  INSERT IGNORE INTO map_collection_record (source_id,target_id,is_existing)
    SELECT s.id,collection_record_id_base+ROW_NUMBER() OVER (ORDER BY s.id),0
    FROM stg_emission_collection_record s;
  INSERT INTO emission_collection_record
    (id,collection_point_type,collection_point_id,reading_value,collection_time,collection_status,last_fetch_time,
     collection_point_name,emission_subcategory,measurement_unit,meter_reading_method,is_cumulative,
     billing_cycle_start_date,billing_cycle_end_date,created_at,created_by,updated_at,updated_by,review_comment,
     reviewed_at,reviewer_id,submitted_at,submitter_id,workflow_status,collection_failure_reason,external_quality,
     external_record_id)
    SELECT m.target_id,s.collection_point_type,s.collection_point_id,s.reading_value,s.collection_time,
      s.collection_status,s.last_fetch_time,s.collection_point_name,s.emission_subcategory,s.measurement_unit,
      s.meter_reading_method,s.is_cumulative,s.billing_cycle_start_date,s.billing_cycle_end_date,s.created_at,
      s.created_by,s.updated_at,s.updated_by,s.review_comment,s.reviewed_at,s.reviewer_id,s.submitted_at,
      s.submitter_id,s.workflow_status,s.collection_failure_reason,s.external_quality,s.external_record_id
    FROM stg_emission_collection_record s
    JOIN map_collection_record m ON m.source_id=s.id
    WHERE m.is_existing=0;

  CREATE TEMPORARY TABLE map_collection_audit (
    source_id BIGINT NOT NULL PRIMARY KEY,
    target_id BIGINT NOT NULL UNIQUE,
    is_existing TINYINT NOT NULL
  );
  INSERT INTO map_collection_audit (source_id,target_id,is_existing)
    SELECT s.id,MIN(t.id),1 FROM stg_emission_collection_record_audit s
    JOIN map_collection_record r ON r.source_id=s.record_id
    JOIN emission_collection_record_audit t ON t.record_id=r.target_id AND t.action=s.action
      AND t.from_status<=>s.from_status AND t.to_status<=>s.to_status AND t.operator_id<=>s.operator_id
      AND t.operated_at=s.operated_at
    GROUP BY s.id;
  INSERT IGNORE INTO map_collection_audit (source_id,target_id,is_existing)
    SELECT s.id,s.id,0 FROM stg_emission_collection_record_audit s
    LEFT JOIN emission_collection_record_audit occupied ON occupied.id=s.id
    WHERE occupied.id IS NULL;
  SELECT GREATEST(COALESCE(MAX(id),0),(SELECT COALESCE(MAX(id),0) FROM stg_emission_collection_record_audit))+1000
    INTO collection_audit_id_base FROM emission_collection_record_audit;
  INSERT IGNORE INTO map_collection_audit (source_id,target_id,is_existing)
    SELECT s.id,collection_audit_id_base+ROW_NUMBER() OVER (ORDER BY s.id),0
    FROM stg_emission_collection_record_audit s;
  INSERT INTO emission_collection_record_audit
    (id,record_id,action,from_status,to_status,operator_id,operator_name,comment,operated_at)
    SELECT a.target_id,r.target_id,s.action,s.from_status,s.to_status,s.operator_id,s.operator_name,s.comment,
      s.operated_at
    FROM stg_emission_collection_record_audit s
    JOIN map_collection_audit a ON a.source_id=s.id
    JOIN map_collection_record r ON r.source_id=s.record_id
    WHERE a.is_existing=0;
  INSERT INTO emission_calculation_template SELECT s.* FROM stg_emission_calculation_template s
    LEFT JOIN emission_calculation_template t ON t.id=s.id WHERE t.id IS NULL;
  INSERT INTO emission_calculation_data_state SELECT s.* FROM stg_emission_calculation_data_state s
    LEFT JOIN emission_calculation_data_state t ON t.calculation_template_id=s.calculation_template_id
    WHERE t.calculation_template_id IS NULL;

  CREATE TEMPORARY TABLE map_calculation_node (
    source_id BIGINT NOT NULL PRIMARY KEY,
    target_id BIGINT NOT NULL UNIQUE,
    is_existing TINYINT NOT NULL
  );
  INSERT INTO map_calculation_node (source_id,target_id,is_existing)
    SELECT s.id,MIN(t.id),1 FROM stg_emission_calculation_node s
    JOIN emission_calculation_node t ON t.calculation_template_id=s.calculation_template_id AND t.node_id=s.node_id
    GROUP BY s.id;
  INSERT IGNORE INTO map_calculation_node (source_id,target_id,is_existing)
    SELECT s.id,s.id,0 FROM stg_emission_calculation_node s
    LEFT JOIN emission_calculation_node occupied ON occupied.id=s.id
    WHERE occupied.id IS NULL;
  SELECT GREATEST(COALESCE(MAX(id),0),(SELECT COALESCE(MAX(id),0) FROM stg_emission_calculation_node))+1000
    INTO node_id_base FROM emission_calculation_node;
  INSERT IGNORE INTO map_calculation_node (source_id,target_id,is_existing)
    SELECT s.id,node_id_base+ROW_NUMBER() OVER (ORDER BY s.id),0
    FROM stg_emission_calculation_node s;
  CREATE TEMPORARY TABLE map_calculation_node_parent LIKE map_calculation_node;
  INSERT INTO map_calculation_node_parent SELECT * FROM map_calculation_node;
  INSERT INTO emission_calculation_node
    (id,calculation_template_id,node_id,name,type_id,parent_id,node_category,created_at,created_by,
     updated_at,updated_by,excluded_by_node_id,include_in_calculation)
    SELECT m.target_id,s.calculation_template_id,s.node_id,s.name,s.type_id,parent_map.target_id,s.node_category,
      s.created_at,s.created_by,s.updated_at,s.updated_by,s.excluded_by_node_id,s.include_in_calculation
    FROM stg_emission_calculation_node s
    JOIN map_calculation_node m ON m.source_id=s.id
    LEFT JOIN map_calculation_node_parent parent_map ON parent_map.source_id=s.parent_id
    WHERE m.is_existing=0;

  CREATE TEMPORARY TABLE map_calculation_detail (
    source_id BIGINT NOT NULL PRIMARY KEY,
    target_id BIGINT NOT NULL UNIQUE,
    is_existing TINYINT NOT NULL
  );
  INSERT INTO map_calculation_detail (source_id,target_id,is_existing)
    SELECT s.id,MIN(t.id),1 FROM stg_emission_collection_node_data s
    JOIN map_calculation_node n ON n.source_id=s.calculation_node_id
    JOIN emission_collection_node_data t ON t.calculation_node_id=n.target_id
      AND t.collection_point_type<=>s.collection_point_type AND t.collection_point_id<=>s.collection_point_id
    GROUP BY s.id;
  INSERT IGNORE INTO map_calculation_detail (source_id,target_id,is_existing)
    SELECT s.id,s.id,0 FROM stg_emission_collection_node_data s
    LEFT JOIN emission_collection_node_data occupied ON occupied.id=s.id
    WHERE occupied.id IS NULL;
  SELECT GREATEST(COALESCE(MAX(id),0),(SELECT COALESCE(MAX(id),0) FROM stg_emission_collection_node_data))+1000
    INTO detail_id_base FROM emission_collection_node_data;
  INSERT IGNORE INTO map_calculation_detail (source_id,target_id,is_existing)
    SELECT s.id,detail_id_base+ROW_NUMBER() OVER (ORDER BY s.id),0
    FROM stg_emission_collection_node_data s;
  INSERT INTO emission_collection_node_data
    (id,calculation_node_id,collection_point_type,collection_point_id,emission_category,emission_subcategory,
     carbon_emission_factor,is_cumulative,is_mobile_source,measurement_unit,energy_category_l1,energy_category_l2,
     energy_category_l3,energy_use_category,energy_measurement_value,carbon_emission,adjusted_energy_value,
     adjusted_carbon_emission,total_emission_calc_method,collection_record_start_date,collection_record_end_date,
     data_status,data_missing_description,created_at,created_by,updated_at,updated_by,carbon_emission_factor_unit,
     carbon_emission_unit,rollover_applied,rollover_threshold)
    SELECT d.target_id,n.target_id,s.collection_point_type,s.collection_point_id,s.emission_category,s.emission_subcategory,
      s.carbon_emission_factor,s.is_cumulative,s.is_mobile_source,s.measurement_unit,s.energy_category_l1,s.energy_category_l2,
      s.energy_category_l3,s.energy_use_category,s.energy_measurement_value,s.carbon_emission,s.adjusted_energy_value,
      s.adjusted_carbon_emission,s.total_emission_calc_method,s.collection_record_start_date,s.collection_record_end_date,
      s.data_status,s.data_missing_description,s.created_at,s.created_by,s.updated_at,s.updated_by,
      s.carbon_emission_factor_unit,s.carbon_emission_unit,s.rollover_applied,s.rollover_threshold
    FROM stg_emission_collection_node_data s
    JOIN map_calculation_detail d ON d.source_id=s.id
    JOIN map_calculation_node n ON n.source_id=s.calculation_node_id
    WHERE d.is_existing=0;

  CREATE TEMPORARY TABLE map_calculation_summary (
    source_id BIGINT NOT NULL PRIMARY KEY,
    target_id BIGINT NOT NULL UNIQUE,
    is_existing TINYINT NOT NULL
  );
  INSERT INTO map_calculation_summary (source_id,target_id,is_existing)
    SELECT s.id,MIN(t.id),1 FROM stg_emission_calc_node_summary s
    JOIN map_calculation_node n ON n.source_id=s.calculation_node_id
    JOIN emission_calc_node_summary t ON t.calculation_node_id=n.target_id
      AND t.energy_category_l1<=>s.energy_category_l1 AND t.energy_category_l2<=>s.energy_category_l2
      AND t.energy_category_l3<=>s.energy_category_l3 AND t.emission_subcategory<=>s.emission_subcategory
    GROUP BY s.id;
  INSERT IGNORE INTO map_calculation_summary (source_id,target_id,is_existing)
    SELECT s.id,s.id,0 FROM stg_emission_calc_node_summary s
    LEFT JOIN emission_calc_node_summary occupied ON occupied.id=s.id
    WHERE occupied.id IS NULL;
  SELECT GREATEST(COALESCE(MAX(id),0),(SELECT COALESCE(MAX(id),0) FROM stg_emission_calc_node_summary))+1000
    INTO summary_id_base FROM emission_calc_node_summary;
  INSERT IGNORE INTO map_calculation_summary (source_id,target_id,is_existing)
    SELECT s.id,summary_id_base+ROW_NUMBER() OVER (ORDER BY s.id),0
    FROM stg_emission_calc_node_summary s;
  INSERT INTO emission_calc_node_summary
    (id,calculation_template_id,calculation_node_id,source_node_id,parent_calc_node_id,node_level,is_leaf_calc_node,
     energy_category_l1,energy_category_l2,energy_category_l3,emission_category,emission_subcategory,direct_energy_value,
     direct_carbon_emission,subtotal_energy_value,subtotal_carbon_emission,calculation_unit_code,
     carbon_emission_factor,summary_source,created_at,created_by,updated_at,updated_by)
    SELECT sm.target_id,s.calculation_template_id,n.target_id,s.source_node_id,parent_map.target_id,s.node_level,
      s.is_leaf_calc_node,s.energy_category_l1,s.energy_category_l2,s.energy_category_l3,s.emission_category,
      s.emission_subcategory,s.direct_energy_value,s.direct_carbon_emission,s.subtotal_energy_value,
      s.subtotal_carbon_emission,s.calculation_unit_code,s.carbon_emission_factor,s.summary_source,
      s.created_at,s.created_by,s.updated_at,s.updated_by
    FROM stg_emission_calc_node_summary s
    JOIN map_calculation_summary sm ON sm.source_id=s.id
    JOIN map_calculation_node n ON n.source_id=s.calculation_node_id
    LEFT JOIN map_calculation_node_parent parent_map ON parent_map.source_id=s.parent_calc_node_id
    WHERE sm.is_existing=0;
  CREATE TEMPORARY TABLE map_report_task (
    source_id BIGINT NOT NULL PRIMARY KEY,
    target_id BIGINT NOT NULL UNIQUE,
    is_existing TINYINT NOT NULL
  );
  INSERT INTO map_report_task (source_id,target_id,is_existing)
    SELECT s.id,MIN(t.id),1 FROM stg_report_task s
    JOIN report_task t ON t.dept_id=s.dept_id AND t.title<=>s.title AND t.report_year=s.report_year
      AND t.report_month<=>s.report_month AND t.calculation_template_id<=>s.calculation_template_id
    GROUP BY s.id;
  INSERT IGNORE INTO map_report_task (source_id,target_id,is_existing)
    SELECT s.id,s.id,0 FROM stg_report_task s LEFT JOIN report_task occupied ON occupied.id=s.id
    WHERE occupied.id IS NULL;
  SELECT GREATEST(COALESCE(MAX(id),0),(SELECT COALESCE(MAX(id),0) FROM stg_report_task))+1000
    INTO report_task_id_base FROM report_task;
  INSERT IGNORE INTO map_report_task (source_id,target_id,is_existing)
    SELECT s.id,report_task_id_base+ROW_NUMBER() OVER (ORDER BY s.id),0 FROM stg_report_task s;
  INSERT INTO report_task
    (id,dept_id,title,template_code,period_type,report_year,report_month,period_start,period_end,subject_node_id,
     emission_template_id,calculation_template_id,factor_template_id,source_hash,status,current_step,version,
     deleted_flag,metadata_json,entity_profile_json,organization_boundary_json,emission_boundary_notes_json,
     activity_prose_json,prior_year_json,chapter6_json,last_validation_json,create_by,create_time,update_by,update_time)
    SELECT m.target_id,s.dept_id,s.title,s.template_code,s.period_type,s.report_year,s.report_month,s.period_start,
      s.period_end,s.subject_node_id,s.emission_template_id,s.calculation_template_id,s.factor_template_id,
      s.source_hash,s.status,s.current_step,s.version,s.deleted_flag,s.metadata_json,s.entity_profile_json,
      s.organization_boundary_json,s.emission_boundary_notes_json,s.activity_prose_json,s.prior_year_json,
      s.chapter6_json,s.last_validation_json,s.create_by,s.create_time,s.update_by,s.update_time
    FROM stg_report_task s JOIN map_report_task m ON m.source_id=s.id WHERE m.is_existing=0;

  UPDATE stg_report_emission_source s JOIN map_report_task m ON m.source_id=s.report_id SET s.report_id=m.target_id;
  UPDATE stg_report_activity_fuel s JOIN map_report_task m ON m.source_id=s.report_id SET s.report_id=m.target_id;
  UPDATE stg_report_activity_electricity s JOIN map_report_task m ON m.source_id=s.report_id SET s.report_id=m.target_id;
  UPDATE stg_report_activity_heat s JOIN map_report_task m ON m.source_id=s.report_id SET s.report_id=m.target_id;
  UPDATE stg_report_workload s JOIN map_report_task m ON m.source_id=s.report_id SET s.report_id=m.target_id;
  UPDATE stg_report_equipment s JOIN map_report_task m ON m.source_id=s.report_id SET s.report_id=m.target_id;
  UPDATE stg_report_monitoring_device s JOIN map_report_task m ON m.source_id=s.report_id SET s.report_id=m.target_id;
  UPDATE stg_report_import_batch s JOIN map_report_task m ON m.source_id=s.report_id SET s.report_id=m.target_id;
  UPDATE stg_report_file s JOIN map_report_task m ON m.source_id=s.report_id SET s.report_id=m.target_id;
  UPDATE stg_report_generation_job s JOIN map_report_task m ON m.source_id=s.report_id SET s.report_id=m.target_id;

  INSERT INTO report_emission_source SELECT s.* FROM stg_report_emission_source s
    LEFT JOIN report_emission_source t ON t.id=s.id WHERE t.id IS NULL;
  INSERT INTO report_activity_fuel SELECT s.* FROM stg_report_activity_fuel s
    LEFT JOIN report_activity_fuel t ON t.id=s.id WHERE t.id IS NULL;
  INSERT INTO report_activity_electricity
    (dept_id,report_id,scope,quantity_mwh,source_name,month,data_origin,source_table,source_id,source_value,
     source_unit,normalized_value,normalized_unit,source_hash,override_reason,sort_order,create_by,create_time,
     update_by,update_time)
    SELECT s.dept_id,s.report_id,s.scope,s.quantity_mwh,s.source_name,s.month,s.data_origin,s.source_table,
      s.source_id,s.source_value,s.source_unit,s.normalized_value,s.normalized_unit,s.source_hash,
      s.override_reason,s.sort_order,s.create_by,s.create_time,s.update_by,s.update_time
    FROM stg_report_activity_electricity s
    WHERE NOT EXISTS (SELECT 1 FROM report_activity_electricity t WHERE t.dept_id=s.dept_id
      AND t.report_id=s.report_id AND t.scope<=>s.scope AND t.month<=>s.month
      AND t.source_name<=>s.source_name AND t.source_table<=>s.source_table AND t.source_id<=>s.source_id
      AND t.quantity_mwh<=>s.quantity_mwh);
  INSERT INTO report_activity_heat SELECT s.* FROM stg_report_activity_heat s
    LEFT JOIN report_activity_heat t ON t.id=s.id WHERE t.id IS NULL;
  INSERT INTO report_workload
    (dept_id,report_id,metric_name,quantity,unit,data_origin,source_table,source_id,source_hash,override_reason,
     sort_order,create_by,create_time,update_by,update_time)
    SELECT s.dept_id,s.report_id,s.metric_name,s.quantity,s.unit,s.data_origin,s.source_table,s.source_id,
      s.source_hash,s.override_reason,s.sort_order,s.create_by,s.create_time,s.update_by,s.update_time
    FROM stg_report_workload s
    WHERE NOT EXISTS (SELECT 1 FROM report_workload t WHERE t.dept_id=s.dept_id AND t.report_id=s.report_id
      AND t.metric_name<=>s.metric_name AND t.source_table<=>s.source_table AND t.source_id<=>s.source_id
      AND t.quantity<=>s.quantity);
  INSERT INTO report_equipment
    (dept_id,report_id,name,category,quantity,unit,model,energy_type,remark,data_origin,source_id,sort_order,
     create_by,create_time,update_by,update_time)
    SELECT s.dept_id,s.report_id,s.name,s.category,s.quantity,s.unit,s.model,s.energy_type,s.remark,s.data_origin,
      s.source_id,s.sort_order,s.create_by,s.create_time,s.update_by,s.update_time
    FROM stg_report_equipment s
    WHERE NOT EXISTS (SELECT 1 FROM report_equipment t WHERE t.dept_id=s.dept_id AND t.report_id=s.report_id
      AND t.name<=>s.name AND t.model<=>s.model AND t.source_id<=>s.source_id);
  INSERT INTO report_monitoring_device
    (dept_id,report_id,name,model,accuracy,location,calibration_frequency,measurement_range,data_origin,
     source_table,source_id,sort_order,create_by,create_time,update_by,update_time)
    SELECT s.dept_id,s.report_id,s.name,s.model,s.accuracy,s.location,s.calibration_frequency,s.measurement_range,
      s.data_origin,s.source_table,s.source_id,s.sort_order,s.create_by,s.create_time,s.update_by,s.update_time
    FROM stg_report_monitoring_device s
    WHERE NOT EXISTS (SELECT 1 FROM report_monitoring_device t WHERE t.dept_id=s.dept_id
      AND t.report_id=s.report_id AND t.name<=>s.name AND t.model<=>s.model AND t.location<=>s.location
      AND t.source_id<=>s.source_id);
  INSERT INTO report_import_batch SELECT s.* FROM stg_report_import_batch s
    LEFT JOIN report_import_batch t ON t.id=s.id WHERE t.id IS NULL;
  INSERT INTO report_file (id,dept_id,report_id,kind,role,object_key,content,original_name,mime_type,size_bytes,
      sha256,snapshot_sha256,create_by,create_time,update_by,update_time)
    SELECT s.id,s.dept_id,s.report_id,s.kind,s.role,s.object_key,s.content,s.original_name,s.mime_type,s.size_bytes,
      s.sha256,s.snapshot_sha256,s.create_by,s.create_time,s.update_by,s.update_time
    FROM stg_report_file s LEFT JOIN report_file t ON t.id=s.id WHERE t.id IS NULL;
  INSERT INTO report_generation_job
    (dept_id,report_id,status,output_kind,progress,locked_by,heartbeat_at,attempt_count,input_snapshot_json,
     snapshot_sha256,ai_enabled,docx_file_id,pdf_file_id,error_message,llm_call_count,create_by,create_time,
     update_by,update_time)
    SELECT s.dept_id,s.report_id,s.status,s.output_kind,s.progress,s.locked_by,s.heartbeat_at,s.attempt_count,
      s.input_snapshot_json,s.snapshot_sha256,s.ai_enabled,s.docx_file_id,s.pdf_file_id,s.error_message,
      s.llm_call_count,s.create_by,s.create_time,s.update_by,s.update_time
    FROM stg_report_generation_job s
    WHERE NOT EXISTS (SELECT 1 FROM report_generation_job t WHERE t.dept_id=s.dept_id
      AND t.report_id=s.report_id AND t.output_kind<=>s.output_kind
      AND t.snapshot_sha256<=>s.snapshot_sha256 AND t.create_time<=>s.create_time);

  COMMIT;
  SELECT 'BUSINESS_HISTORY_INIT_OK' AS status, DATABASE() AS target_database;
  SELECT 'historical_collection_records' AS category,COUNT(*) AS source_rows FROM stg_emission_collection_record
  UNION ALL SELECT 'calculation_tasks',COUNT(*) FROM stg_emission_calculation_template
  UNION ALL SELECT 'calculation_nodes',COUNT(*) FROM stg_emission_calculation_node
  UNION ALL SELECT 'calculation_details',COUNT(*) FROM stg_emission_collection_node_data
  UNION ALL SELECT 'calculation_summaries',COUNT(*) FROM stg_emission_calc_node_summary
  UNION ALL SELECT 'report_tasks_with_body',COUNT(*) FROM stg_report_task
  UNION ALL SELECT 'report_generation_snapshots',COUNT(*) FROM stg_report_generation_job
  UNION ALL SELECT 'historical_report_files',COUNT(*) FROM stg_report_file;
  DO RELEASE_LOCK('ruoyi_business_history_import_v1');
END//
CALL import_ruoyi_business_history()//
DROP PROCEDURE import_ruoyi_business_history//
DELIMITER ;

