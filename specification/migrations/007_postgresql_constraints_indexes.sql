ALTER TABLE quality_inspectionsession
    ADD CONSTRAINT inspection_session_status_check
        CHECK (status IN ('open', 'closed'));

ALTER TABLE quality_inspectiontarget
    ADD CONSTRAINT inspection_target_issue_status_check
        CHECK (issue_status IN ('not_required', 'pending', 'issued', 'missing_file', 'skipped'));

ALTER TABLE quality_history
    ADD CONSTRAINT history_time_slot_check
        CHECK (time_slot IN ('A', 'B', 'C', 'D'));

ALTER TABLE quality_job
    ADD CONSTRAINT quality_job_type_check
        CHECK (job_type IN ('master_update', 'plans_import', 'inspection_sheet_issue', 'daily_report_generate')),
    ADD CONSTRAINT quality_job_status_check
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed'));

ALTER TABLE quality_machine
    ADD CONSTRAINT machine_class_check
        CHECK (machine_class IS NULL OR machine_class IN (1, 2, 3, 4, 5, 6, 10)),
    ADD CONSTRAINT machine_shape_type_check
        CHECK (shape_type IN ('circle', 'ellipse', 'rectangle'));

ALTER TABLE quality_layoutobjecttype
    ADD CONSTRAINT layout_object_type_code_check
        CHECK (code IN ('machine', 'wall', 'path', 'area', 'stairs', 'entrance'));

CREATE INDEX IF NOT EXISTS history_date_idx ON quality_history(date);
CREATE INDEX IF NOT EXISTS history_master_id_idx ON quality_history(master_id);
CREATE INDEX IF NOT EXISTS history_class_override_idx ON quality_history(class_override);
CREATE INDEX IF NOT EXISTS history_date_class_override_idx ON quality_history(date, class_override);

CREATE INDEX IF NOT EXISTS inspection_target_normalized_code_idx ON quality_inspectiontarget(normalized_code);
CREATE INDEX IF NOT EXISTS inspection_target_master_id_idx ON quality_inspectiontarget(master_id);
CREATE INDEX IF NOT EXISTS inspection_target_session_id_idx ON quality_inspectiontarget(session_id);
