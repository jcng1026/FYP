"""Database schema definitions and initialization."""

import sqlite3
from datetime import datetime, timezone

ALLOWED_ROLES = ("admin", "teacher", "student")

CREATE_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'teacher', 'student')),
    created_at TEXT NOT NULL,
    teacher_code TEXT,
    student_code TEXT,
    visible_temp_password TEXT,
    is_active INTEGER NOT NULL DEFAULT 1
);
"""

# teacher_code/student_code are separate, auto-generated formal display
# codes (TN0001.../TP0001...) - distinct from the internal user_id and, for
# students, from the manually-typed username. Both columns are nullable so
# non-teacher/non-student rows (and not-yet-backfilled rows) are unaffected;
# the partial unique indexes only constrain rows that actually have a code.
CREATE_USERS_TEACHER_CODE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_teacher_code
ON users(teacher_code) WHERE teacher_code IS NOT NULL;
"""

CREATE_USERS_STUDENT_CODE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_student_code
ON users(student_code) WHERE student_code IS NOT NULL;
"""

CREATE_CLASSES_TABLE = """
CREATE TABLE IF NOT EXISTS classes (
    class_id INTEGER PRIMARY KEY AUTOINCREMENT,
    class_name TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT 'English',
    teacher_id INTEGER,
    created_at TEXT NOT NULL,
    UNIQUE(class_name, subject),
    FOREIGN KEY (teacher_id) REFERENCES users(user_id)
);
"""

CREATE_CLASS_TRANSFER_REQUESTS_TABLE = """
CREATE TABLE IF NOT EXISTS class_transfer_requests (
    request_id INTEGER PRIMARY KEY AUTOINCREMENT,
    class_id INTEGER NOT NULL,
    requesting_teacher_id INTEGER NOT NULL,
    current_teacher_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
    request_reason TEXT,
    response_reason TEXT,
    responded_by_user_id INTEGER,
    created_at TEXT NOT NULL,
    responded_at TEXT,
    FOREIGN KEY (class_id) REFERENCES classes(class_id) ON DELETE CASCADE,
    FOREIGN KEY (requesting_teacher_id) REFERENCES users(user_id),
    FOREIGN KEY (current_teacher_id) REFERENCES users(user_id),
    FOREIGN KEY (responded_by_user_id) REFERENCES users(user_id)
);
"""

CREATE_CLASS_STUDENTS_TABLE = """
CREATE TABLE IF NOT EXISTS class_students (
    class_id INTEGER NOT NULL,
    student_id INTEGER NOT NULL,
    added_at TEXT NOT NULL,
    PRIMARY KEY (class_id, student_id),
    FOREIGN KEY (class_id) REFERENCES classes(class_id) ON DELETE CASCADE,
    FOREIGN KEY (student_id) REFERENCES users(user_id) ON DELETE CASCADE
);
"""

CREATE_STUDENT_TRANSFER_REQUESTS_TABLE = """
CREATE TABLE IF NOT EXISTS student_transfer_requests (
    request_id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    source_class_id INTEGER NOT NULL,
    target_class_id INTEGER NOT NULL,
    requesting_teacher_id INTEGER NOT NULL,
    current_teacher_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
    request_reason TEXT,
    response_reason TEXT,
    responded_by_user_id INTEGER,
    created_at TEXT NOT NULL,
    responded_at TEXT,
    FOREIGN KEY (student_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (source_class_id) REFERENCES classes(class_id) ON DELETE CASCADE,
    FOREIGN KEY (target_class_id) REFERENCES classes(class_id) ON DELETE CASCADE,
    FOREIGN KEY (requesting_teacher_id) REFERENCES users(user_id),
    FOREIGN KEY (current_teacher_id) REFERENCES users(user_id),
    FOREIGN KEY (responded_by_user_id) REFERENCES users(user_id)
);
"""

CREATE_REVISION_MATERIALS_TABLE = """
CREATE TABLE IF NOT EXISTS revision_materials (
    material_id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    paper_type TEXT NOT NULL CHECK (paper_type IN ('Kertas 1', 'Kertas 2', 'Both')),
    subject TEXT NOT NULL DEFAULT 'English',
    question_paper_path TEXT NOT NULL,
    marking_scheme_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (teacher_id) REFERENCES users(user_id)
);
"""

CREATE_REVISION_MATERIAL_CLASSES_TABLE = """
CREATE TABLE IF NOT EXISTS revision_material_classes (
    material_id INTEGER NOT NULL,
    class_id INTEGER NOT NULL,
    PRIMARY KEY (material_id, class_id),
    FOREIGN KEY (material_id) REFERENCES revision_materials(material_id) ON DELETE CASCADE,
    FOREIGN KEY (class_id) REFERENCES classes(class_id) ON DELETE CASCADE
);
"""

CREATE_STUDENT_EXTERNAL_REVISIONS_TABLE = """
CREATE TABLE IF NOT EXISTS student_external_revisions (
    external_revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    class_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    paper_type TEXT NOT NULL CHECK (paper_type IN ('Kertas 1', 'Kertas 2')),
    question_paper_path TEXT NOT NULL,
    marking_scheme_path TEXT NOT NULL,
    completed_answer_path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'uploaded',
    is_deleted_by_student INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (student_id) REFERENCES users(user_id),
    FOREIGN KEY (class_id) REFERENCES classes(class_id)
);
"""

CREATE_REVISION_ATTEMPTS_TABLE = """
CREATE TABLE IF NOT EXISTS revision_attempts (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id INTEGER NOT NULL,
    student_id INTEGER NOT NULL,
    class_id INTEGER NOT NULL,
    attempt_no INTEGER NOT NULL,
    completed_answer_path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'uploaded',
    submitted_at TEXT NOT NULL,
    is_deleted_by_student INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (material_id) REFERENCES revision_materials(material_id),
    FOREIGN KEY (student_id) REFERENCES users(user_id),
    FOREIGN KEY (class_id) REFERENCES classes(class_id)
);
"""

CREATE_ANSWER_TEMPLATES_TABLE = """
CREATE TABLE IF NOT EXISTS answer_templates (
    template_id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    paper_type TEXT NOT NULL CHECK (paper_type IN ('Kertas 1', 'Kertas 2')),
    sample_file_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (teacher_id) REFERENCES users(user_id)
);
"""

CREATE_TEMPLATE_REGIONS_TABLE = """
CREATE TABLE IF NOT EXISTS template_regions (
    region_id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    region_type TEXT,
    page_number INTEGER NOT NULL DEFAULT 1,
    x REAL NOT NULL CHECK (x >= 0 AND x <= 1),
    y REAL NOT NULL CHECK (y >= 0 AND y <= 1),
    width REAL NOT NULL CHECK (width > 0),
    height REAL NOT NULL CHECK (height > 0),
    order_index INTEGER NOT NULL,
    notes TEXT,
    shape_type TEXT NOT NULL DEFAULT 'rectangle',
    polygon_points_json TEXT,
    rotation_angle REAL NOT NULL DEFAULT 0.0,
    FOREIGN KEY (template_id) REFERENCES answer_templates(template_id) ON DELETE CASCADE
);
"""

CREATE_TEMPLATE_REGION_GROUPS_TABLE = """
CREATE TABLE IF NOT EXISTS template_region_groups (
    group_id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    region_type TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (template_id) REFERENCES answer_templates(template_id) ON DELETE CASCADE
);
"""

CREATE_TEMPLATE_REGION_GROUP_MEMBERS_TABLE = """
CREATE TABLE IF NOT EXISTS template_region_group_members (
    group_id INTEGER NOT NULL,
    region_id INTEGER NOT NULL,
    member_order INTEGER NOT NULL,
    PRIMARY KEY (group_id, region_id),
    FOREIGN KEY (group_id) REFERENCES template_region_groups(group_id) ON DELETE CASCADE,
    FOREIGN KEY (region_id) REFERENCES template_regions(region_id) ON DELETE CASCADE
);
"""

CREATE_MARKING_SETUPS_TABLE = """
CREATE TABLE IF NOT EXISTS marking_setups (
    setup_id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id INTEGER NOT NULL UNIQUE,
    teacher_id INTEGER NOT NULL,
    template_id INTEGER,
    paper_type TEXT NOT NULL CHECK (paper_type IN ('Kertas 1', 'Kertas 2')),
    spelling_deduction REAL NOT NULL DEFAULT -1,
    default_question_mark REAL NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (material_id) REFERENCES revision_materials(material_id),
    FOREIGN KEY (teacher_id) REFERENCES users(user_id),
    FOREIGN KEY (template_id) REFERENCES answer_templates(template_id)
);
"""

CREATE_MARKING_QUESTIONS_TABLE = """
CREATE TABLE IF NOT EXISTS marking_questions (
    question_id INTEGER PRIMARY KEY AUTOINCREMENT,
    setup_id INTEGER NOT NULL,
    question_no TEXT NOT NULL,
    correct_answer TEXT NOT NULL,
    max_mark REAL NOT NULL DEFAULT 1,
    explanation TEXT,
    question_type TEXT NOT NULL,
    region_id INTEGER,
    display_order INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (setup_id) REFERENCES marking_setups(setup_id) ON DELETE CASCADE,
    FOREIGN KEY (region_id) REFERENCES template_regions(region_id)
);
"""

CREATE_DOCUMENT_PREPROCESSING_JOBS_TABLE = """
CREATE TABLE IF NOT EXISTS document_preprocessing_jobs (
    job_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,
    source_id INTEGER,
    original_file_path TEXT NOT NULL,
    output_folder_path TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'completed', 'failed')),
    page_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
"""

CREATE_DOCUMENT_PREPROCESSING_PAGES_TABLE = """
CREATE TABLE IF NOT EXISTS document_preprocessing_pages (
    page_id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    page_number INTEGER NOT NULL,
    processed_image_path TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES document_preprocessing_jobs(job_id) ON DELETE CASCADE
);
"""

CREATE_OCR_JOBS_TABLE = """
CREATE TABLE IF NOT EXISTS ocr_jobs (
    ocr_job_id INTEGER PRIMARY KEY AUTOINCREMENT,
    preprocessing_job_id INTEGER NOT NULL,
    source_type TEXT NOT NULL,
    source_id INTEGER,
    status TEXT NOT NULL CHECK (status IN ('pending', 'completed', 'failed')),
    page_count INTEGER NOT NULL DEFAULT 0,
    full_text TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (preprocessing_job_id) REFERENCES document_preprocessing_jobs(job_id)
);
"""

CREATE_OCR_PAGE_RESULTS_TABLE = """
CREATE TABLE IF NOT EXISTS ocr_page_results (
    ocr_page_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ocr_job_id INTEGER NOT NULL,
    page_number INTEGER NOT NULL,
    text TEXT,
    average_confidence REAL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (ocr_job_id) REFERENCES ocr_jobs(ocr_job_id) ON DELETE CASCADE
);
"""

CREATE_OCR_TEXT_BLOCKS_TABLE = """
CREATE TABLE IF NOT EXISTS ocr_text_blocks (
    ocr_block_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ocr_page_id INTEGER NOT NULL,
    block_order INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL,
    confidence REAL,
    x1 REAL,
    y1 REAL,
    x2 REAL,
    y2 REAL,
    x3 REAL,
    y3 REAL,
    x4 REAL,
    y4 REAL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (ocr_page_id) REFERENCES ocr_page_results(ocr_page_id) ON DELETE CASCADE
);
"""

CREATE_EXTRACTION_JOBS_TABLE = """
CREATE TABLE IF NOT EXISTS extraction_jobs (
    extraction_job_id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id INTEGER NOT NULL,
    ocr_job_id INTEGER NOT NULL,
    template_id INTEGER NOT NULL,
    marking_setup_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'completed', 'failed')),
    region_count INTEGER NOT NULL DEFAULT 0,
    extracted_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (attempt_id) REFERENCES revision_attempts(attempt_id),
    FOREIGN KEY (ocr_job_id) REFERENCES ocr_jobs(ocr_job_id),
    FOREIGN KEY (template_id) REFERENCES answer_templates(template_id),
    FOREIGN KEY (marking_setup_id) REFERENCES marking_setups(setup_id)
);
"""

CREATE_EXTRACTED_REGION_RESULTS_TABLE = """
CREATE TABLE IF NOT EXISTS extracted_region_results (
    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
    extraction_job_id INTEGER NOT NULL,
    region_id INTEGER NOT NULL,
    page_number INTEGER NOT NULL,
    region_name TEXT NOT NULL,
    region_type TEXT NOT NULL,
    extracted_text TEXT,
    average_confidence REAL,
    matched_block_count INTEGER NOT NULL DEFAULT 0,
    extraction_status TEXT NOT NULL CHECK (
        extraction_status IN ('extracted', 'no_text', 'pending_detection', 'failed')
    ),
    created_at TEXT NOT NULL,
    FOREIGN KEY (extraction_job_id) REFERENCES extraction_jobs(extraction_job_id) ON DELETE CASCADE,
    FOREIGN KEY (region_id) REFERENCES template_regions(region_id)
);
"""

CREATE_EXTRACTED_REGION_BLOCKS_TABLE = """
CREATE TABLE IF NOT EXISTS extracted_region_blocks (
    extracted_block_id INTEGER PRIMARY KEY AUTOINCREMENT,
    result_id INTEGER NOT NULL,
    ocr_block_id INTEGER NOT NULL,
    block_order INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL,
    confidence REAL,
    FOREIGN KEY (result_id) REFERENCES extracted_region_results(result_id) ON DELETE CASCADE,
    FOREIGN KEY (ocr_block_id) REFERENCES ocr_text_blocks(ocr_block_id)
);
"""

CREATE_ANSWER_EXTRACTION_JOBS_TABLE = """
CREATE TABLE IF NOT EXISTS answer_extraction_jobs (
    answer_extraction_job_id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id INTEGER NOT NULL,
    extraction_job_id INTEGER NOT NULL,
    marking_setup_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'completed', 'failed')),
    question_count INTEGER NOT NULL DEFAULT 0,
    extracted_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (attempt_id) REFERENCES revision_attempts(attempt_id),
    FOREIGN KEY (extraction_job_id) REFERENCES extraction_jobs(extraction_job_id),
    FOREIGN KEY (marking_setup_id) REFERENCES marking_setups(setup_id)
);
"""

CREATE_EXTRACTED_ATTEMPT_ANSWERS_TABLE = """
CREATE TABLE IF NOT EXISTS extracted_attempt_answers (
    extracted_answer_id INTEGER PRIMARY KEY AUTOINCREMENT,
    answer_extraction_job_id INTEGER NOT NULL,
    question_id INTEGER NOT NULL,
    question_no TEXT NOT NULL,
    question_type TEXT NOT NULL,
    region_id INTEGER,
    region_name TEXT,
    raw_text TEXT,
    extracted_answer TEXT,
    confidence REAL,
    extraction_status TEXT NOT NULL CHECK (
        extraction_status IN ('extracted', 'no_text', 'no_region', 'pending_detection', 'failed')
    ),
    created_at TEXT NOT NULL,
    FOREIGN KEY (answer_extraction_job_id) REFERENCES answer_extraction_jobs(answer_extraction_job_id) ON DELETE CASCADE,
    FOREIGN KEY (question_id) REFERENCES marking_questions(question_id),
    FOREIGN KEY (region_id) REFERENCES template_regions(region_id)
);
"""

CREATE_MARKING_JOBS_TABLE = """
CREATE TABLE IF NOT EXISTS marking_jobs (
    marking_job_id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id INTEGER NOT NULL,
    answer_extraction_job_id INTEGER NOT NULL,
    marking_setup_id INTEGER NOT NULL,
    paper_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'completed', 'failed')),
    total_questions INTEGER NOT NULL DEFAULT 0,
    marked_count INTEGER NOT NULL DEFAULT 0,
    correct_count INTEGER NOT NULL DEFAULT 0,
    needs_review_count INTEGER NOT NULL DEFAULT 0,
    total_score REAL NOT NULL DEFAULT 0,
    max_score REAL NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (attempt_id) REFERENCES revision_attempts(attempt_id),
    FOREIGN KEY (answer_extraction_job_id) REFERENCES answer_extraction_jobs(answer_extraction_job_id),
    FOREIGN KEY (marking_setup_id) REFERENCES marking_setups(setup_id)
);
"""

CREATE_MARKING_QUESTION_RESULTS_TABLE = """
CREATE TABLE IF NOT EXISTS marking_question_results (
    marking_result_id INTEGER PRIMARY KEY AUTOINCREMENT,
    marking_job_id INTEGER NOT NULL,
    question_id INTEGER NOT NULL,
    extracted_answer_id INTEGER,
    question_no TEXT NOT NULL,
    question_type TEXT NOT NULL,
    correct_answer TEXT NOT NULL,
    extracted_answer TEXT,
    raw_text TEXT,
    is_correct INTEGER NOT NULL DEFAULT 0,
    needs_review INTEGER NOT NULL DEFAULT 0,
    score_awarded REAL NOT NULL DEFAULT 0,
    max_mark REAL NOT NULL DEFAULT 1,
    confidence REAL,
    reason TEXT,
    explanation TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (marking_job_id) REFERENCES marking_jobs(marking_job_id) ON DELETE CASCADE,
    FOREIGN KEY (question_id) REFERENCES marking_questions(question_id),
    FOREIGN KEY (extracted_answer_id) REFERENCES extracted_attempt_answers(extracted_answer_id)
);
"""

CREATE_MARKING_REVIEWS_TABLE = """
CREATE TABLE IF NOT EXISTS marking_reviews (
    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
    marking_job_id INTEGER NOT NULL UNIQUE,
    attempt_id INTEGER NOT NULL,
    teacher_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft', 'finalized')),
    auto_total_score REAL NOT NULL DEFAULT 0,
    final_total_score REAL NOT NULL DEFAULT 0,
    max_score REAL NOT NULL DEFAULT 0,
    teacher_overall_comment TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finalized_at TEXT,
    FOREIGN KEY (marking_job_id) REFERENCES marking_jobs(marking_job_id),
    FOREIGN KEY (attempt_id) REFERENCES revision_attempts(attempt_id),
    FOREIGN KEY (teacher_id) REFERENCES users(user_id)
);
"""

CREATE_MARKING_REVIEW_ITEMS_TABLE = """
CREATE TABLE IF NOT EXISTS marking_review_items (
    marking_review_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id INTEGER NOT NULL,
    marking_result_id INTEGER NOT NULL,
    question_no TEXT NOT NULL,
    auto_score_awarded REAL NOT NULL DEFAULT 0,
    final_score_awarded REAL NOT NULL DEFAULT 0,
    max_mark REAL NOT NULL DEFAULT 1,
    auto_is_correct INTEGER NOT NULL DEFAULT 0,
    final_is_correct INTEGER NOT NULL DEFAULT 0,
    needs_review INTEGER NOT NULL DEFAULT 0,
    teacher_comment TEXT,
    override_reason TEXT,
    review_status TEXT NOT NULL CHECK (
        review_status IN ('auto_accepted', 'overridden', 'needs_review')
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (review_id) REFERENCES marking_reviews(review_id) ON DELETE CASCADE,
    FOREIGN KEY (marking_result_id) REFERENCES marking_question_results(marking_result_id)
);
"""

CREATE_KERTAS2_AI_FEEDBACK_JOBS_TABLE = """
CREATE TABLE IF NOT EXISTS kertas2_ai_feedback_jobs (
    feedback_job_id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id INTEGER NOT NULL,
    answer_extraction_job_id INTEGER NOT NULL,
    marking_setup_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'completed', 'failed')),
    criterion_count INTEGER NOT NULL DEFAULT 0,
    generated_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    provider_backend TEXT,
    provider_model_path TEXT,
    provider_status TEXT,
    diagnostic_message TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (attempt_id) REFERENCES revision_attempts(attempt_id),
    FOREIGN KEY (answer_extraction_job_id) REFERENCES answer_extraction_jobs(answer_extraction_job_id),
    FOREIGN KEY (marking_setup_id) REFERENCES marking_setups(setup_id)
);
"""

CREATE_KERTAS2_AI_FEEDBACK_ITEMS_TABLE = """
CREATE TABLE IF NOT EXISTS kertas2_ai_feedback_items (
    feedback_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    feedback_job_id INTEGER NOT NULL,
    question_id INTEGER NOT NULL,
    extracted_answer_id INTEGER,
    criterion_name TEXT NOT NULL,
    question_type TEXT NOT NULL,
    student_answer TEXT,
    sample_answer TEXT,
    suggested_score REAL NOT NULL DEFAULT 0,
    max_mark REAL NOT NULL DEFAULT 1,
    feedback_text TEXT,
    reason TEXT,
    confidence REAL,
    feedback_status TEXT NOT NULL CHECK (
        feedback_status IN ('generated', 'no_answer', 'needs_review', 'failed')
    ),
    prompt_snapshot TEXT,
    raw_provider_output TEXT,
    parser_error TEXT,
    audit_status TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (feedback_job_id) REFERENCES kertas2_ai_feedback_jobs(feedback_job_id) ON DELETE CASCADE,
    FOREIGN KEY (question_id) REFERENCES marking_questions(question_id),
    FOREIGN KEY (extracted_answer_id) REFERENCES extracted_attempt_answers(extracted_answer_id)
);
"""

CREATE_KERTAS2_FEEDBACK_REVIEWS_TABLE = """
CREATE TABLE IF NOT EXISTS kertas2_feedback_reviews (
    kertas2_review_id INTEGER PRIMARY KEY AUTOINCREMENT,
    feedback_job_id INTEGER NOT NULL UNIQUE,
    attempt_id INTEGER NOT NULL,
    teacher_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft', 'finalized')),
    suggested_total_score REAL NOT NULL DEFAULT 0,
    final_total_score REAL NOT NULL DEFAULT 0,
    max_score REAL NOT NULL DEFAULT 1,
    teacher_overall_comment TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finalized_at TEXT,
    FOREIGN KEY (feedback_job_id) REFERENCES kertas2_ai_feedback_jobs(feedback_job_id),
    FOREIGN KEY (attempt_id) REFERENCES revision_attempts(attempt_id),
    FOREIGN KEY (teacher_id) REFERENCES users(user_id)
);
"""

CREATE_KERTAS2_FEEDBACK_REVIEW_ITEMS_TABLE = """
CREATE TABLE IF NOT EXISTS kertas2_feedback_review_items (
    kertas2_review_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    kertas2_review_id INTEGER NOT NULL,
    feedback_item_id INTEGER NOT NULL,
    criterion_name TEXT NOT NULL,
    question_type TEXT NOT NULL,
    student_answer TEXT,
    sample_answer TEXT,
    suggested_score REAL NOT NULL DEFAULT 0,
    final_score REAL NOT NULL DEFAULT 0,
    max_mark REAL NOT NULL DEFAULT 1,
    suggested_feedback TEXT,
    final_feedback TEXT,
    ai_reason TEXT,
    teacher_comment TEXT,
    review_status TEXT NOT NULL CHECK (review_status IN ('accepted', 'edited', 'needs_review')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (kertas2_review_id) REFERENCES kertas2_feedback_reviews(kertas2_review_id) ON DELETE CASCADE,
    FOREIGN KEY (feedback_item_id) REFERENCES kertas2_ai_feedback_items(feedback_item_id)
);
"""

CREATE_MAIN_MARKING_SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS main_marking_sessions (
    session_id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    paper_type TEXT NOT NULL CHECK (paper_type IN ('Kertas 1', 'Kertas 2', 'Both')),
    question_paper_path TEXT,
    answer_key_path TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    template_id INTEGER,
    subject_profile_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    FOREIGN KEY (teacher_id) REFERENCES users(user_id),
    FOREIGN KEY (template_id) REFERENCES answer_templates(template_id)
);
"""

# One row per uploaded student answer PDF - one PDF always belongs to
# exactly one session and represents exactly one student (Stage 11L). No
# class_id and no student-account link: this is a standalone workflow.
# detected_student_name/detected_student_code are reserved for a later
# auto-detection stage and are always NULL for now.
CREATE_MAIN_MARKING_ANSWER_FILES_TABLE = """
CREATE TABLE IF NOT EXISTS main_marking_answer_files (
    answer_file_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    original_filename TEXT,
    student_name TEXT,
    student_code TEXT,
    detected_student_name TEXT,
    detected_student_code TEXT,
    page_count INTEGER,
    processing_status TEXT NOT NULL DEFAULT 'uploaded',
    created_at TEXT NOT NULL,
    -- Stage 12G-1B: strictly binary attempt mode. 'standard' = the student
    -- answered on the original question paper (Subject Profile regions +
    -- Phase 2C overrides apply); 'separate_answer_paper' = the upload is a
    -- standalone answer paper whose answer geometry is mapped per attempt.
    attempt_mode TEXT NOT NULL DEFAULT 'standard'
        CHECK (attempt_mode IN ('standard', 'separate_answer_paper')),
    FOREIGN KEY (session_id) REFERENCES main_marking_sessions(session_id) ON DELETE CASCADE
);
"""

# Stage 11M: one row per "Run Preprocessing" click for a session - captures
# a run-level status/message so the teacher can see whether the last
# preprocessing pass succeeded, partially failed, or fully failed. No OCR,
# extraction, or marking happens here - this only converts uploaded student
# answer PDFs into cleaned page images.
CREATE_MAIN_MARKING_PROCESSING_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS main_marking_processing_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    message TEXT,
    FOREIGN KEY (session_id) REFERENCES main_marking_sessions(session_id) ON DELETE CASCADE
);
"""

# One row per preprocessed page produced from an answer file's PDF.
# preprocessed_image_path is NULL and message explains why whenever status
# is 'failed' for that page - other pages of the same file may still have
# succeeded.
CREATE_MAIN_MARKING_PREPROCESSED_PAGES_TABLE = """
CREATE TABLE IF NOT EXISTS main_marking_preprocessed_pages (
    page_id INTEGER PRIMARY KEY AUTOINCREMENT,
    answer_file_id INTEGER NOT NULL,
    page_number INTEGER NOT NULL,
    preprocessed_image_path TEXT,
    original_image_path TEXT,
    status TEXT NOT NULL CHECK (status IN ('preprocessed', 'failed')),
    message TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (answer_file_id) REFERENCES main_marking_answer_files(answer_file_id) ON DELETE CASCADE
);
"""

# Stage 11N: one row per "Run OCR" click for a session - mirrors
# main_marking_processing_runs. OCR is only ever run against Stage 11M's
# already-preprocessed page images (main_marking_preprocessed_pages), never
# against the original uploaded PDFs, and never performs answer extraction
# or marking.
CREATE_MAIN_MARKING_OCR_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS main_marking_ocr_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    message TEXT,
    FOREIGN KEY (session_id) REFERENCES main_marking_sessions(session_id) ON DELETE CASCADE
);
"""

# One row per OCR'd preprocessed page. A rerun (Stage 11N's "Run OCR"
# clicked again) deletes and recreates an answer file's rows so the latest
# visible results never duplicate - OCR run history itself still lives in
# main_marking_ocr_runs. ocr_blocks_json (Stage 11P) is a nullable snapshot
# of the OCR engine's per-block text/confidence/box output (discarded
# before Stage 11P), used for geometry-based answer extraction - NULL for
# any row that predates this column or whose engine/test double didn't
# supply block data.
CREATE_MAIN_MARKING_OCR_RESULTS_TABLE = """
CREATE TABLE IF NOT EXISTS main_marking_ocr_results (
    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
    answer_file_id INTEGER NOT NULL,
    page_number INTEGER NOT NULL,
    text TEXT,
    confidence REAL,
    status TEXT NOT NULL CHECK (status IN ('ocr_completed', 'ocr_failed')),
    message TEXT,
    created_at TEXT NOT NULL,
    ocr_blocks_json TEXT,
    FOREIGN KEY (answer_file_id) REFERENCES main_marking_answer_files(answer_file_id) ON DELETE CASCADE
);
"""

# Stage 11P: one row per "Run Extraction" click for a session - mirrors
# main_marking_processing_runs / main_marking_ocr_runs.
CREATE_MAIN_MARKING_ANSWER_EXTRACTION_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS main_marking_answer_extraction_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    message TEXT,
    FOREIGN KEY (session_id) REFERENCES main_marking_sessions(session_id) ON DELETE CASCADE
);
"""

# One row per extracted answer target (a single template region, or a
# region-group's combined output) for one answer file. region_id/group_id
# are informational references only (no FK) - deleting a template region
# or group in Template Editor must keep working even if extraction history
# mentions it. A rerun deletes and recreates an answer file's rows so the
# latest visible extraction never duplicates - run history itself still
# lives in main_marking_answer_extraction_runs. No scoring, no marking, no
# review, and no final-result data is ever stored here.
CREATE_MAIN_MARKING_EXTRACTED_ANSWERS_TABLE = """
CREATE TABLE IF NOT EXISTS main_marking_extracted_answers (
    extracted_answer_id INTEGER PRIMARY KEY AUTOINCREMENT,
    answer_file_id INTEGER NOT NULL,
    target_kind TEXT NOT NULL CHECK (target_kind IN ('region', 'group')),
    region_id INTEGER,
    group_id INTEGER,
    target_label TEXT NOT NULL,
    region_type TEXT,
    page_numbers_json TEXT NOT NULL,
    extracted_text TEXT,
    confidence REAL,
    status TEXT NOT NULL CHECK (status IN ('extracted', 'no_text', 'needs_review', 'failed')),
    message TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (answer_file_id) REFERENCES main_marking_answer_files(answer_file_id) ON DELETE CASCADE
);
"""

# Stage 11Q: one row per "Run Marking" click for a session - mirrors
# main_marking_answer_extraction_runs. Kertas 1 rule-based marking only;
# never Kertas 2, never a finalized result, never a teacher review.
CREATE_MAIN_MARKING_MARKING_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS main_marking_marking_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    message TEXT,
    FOREIGN KEY (session_id) REFERENCES main_marking_sessions(session_id) ON DELETE CASCADE
);
"""

# One row per draft-marked target (region or group) for one answer file.
# extracted_answer_id is an informational reference only (no FK) - a Stage
# 11P extraction rerun deletes/recreates extracted-answer rows, which must
# never break marking rows referencing an older run. A marking rerun
# deletes and recreates an answer file's rows so the latest visible marking
# never duplicates - run history itself still lives in
# main_marking_marking_runs. This table stores draft, rule-based marks only
# - it is never read by the Results page and never implies teacher review
# or finalization.
#
# Stage 11R adds teacher review/override columns (review_status,
# teacher_score, teacher_feedback, reviewed_at) - all nullable, so every
# pre-Stage-11R row defaults to review_status='pending_review' with no
# override yet. These are stored SEPARATELY from the machine-generated
# score/feedback/status/needs_review columns above, which are never
# overwritten by a teacher's review - mirroring the existing class-based
# marking_reviews/marking_review_items pattern of never mutating the
# original auto-marking result.
CREATE_MAIN_MARKING_MARKED_ANSWERS_TABLE = """
CREATE TABLE IF NOT EXISTS main_marking_marked_answers (
    marked_answer_id INTEGER PRIMARY KEY AUTOINCREMENT,
    answer_file_id INTEGER NOT NULL,
    extracted_answer_id INTEGER,
    target_kind TEXT NOT NULL CHECK (target_kind IN ('region', 'group')),
    target_label TEXT NOT NULL,
    region_type TEXT,
    student_answer_text TEXT,
    correct_answer_text TEXT,
    score REAL,
    max_score REAL NOT NULL DEFAULT 1.0,
    status TEXT NOT NULL CHECK (status IN ('marked', 'needs_review', 'failed')),
    feedback TEXT,
    needs_review INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'pending_review' CHECK (review_status IN ('pending_review', 'reviewed')),
    teacher_score REAL,
    teacher_feedback TEXT,
    reviewed_at TEXT,
    FOREIGN KEY (answer_file_id) REFERENCES main_marking_answer_files(answer_file_id) ON DELETE CASCADE
);
"""

# Stage 11S: one row per finalized Main Marking answer file - a frozen
# SNAPSHOT of its reviewed marked answers at the moment of finalization,
# deliberately decoupled from the live main_marking_marked_answers rows
# (which Stage 11Q's "Run Marking" rerun already deletes/recreates). This
# is what the Results page reads for standalone Main Marking, kept
# entirely separate from the class-based marking_reviews/marking_review_
# items tables, which are never written to by this stage. Only one current
# result row is kept per answer_file_id (re-finalizing replaces it) - no
# duplicate visible results, but this is not a "final Results" in the
# class-based sense: it never touches those older tables.
CREATE_MAIN_MARKING_FINAL_RESULTS_TABLE = """
CREATE TABLE IF NOT EXISTS main_marking_final_results (
    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    answer_file_id INTEGER NOT NULL UNIQUE,
    teacher_id INTEGER NOT NULL,
    paper_type TEXT NOT NULL,
    student_name TEXT,
    student_code TEXT,
    answer_file_display_name TEXT NOT NULL,
    total_score REAL NOT NULL,
    max_score REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'finalized',
    finalized_at TEXT NOT NULL,
    message TEXT,
    FOREIGN KEY (session_id) REFERENCES main_marking_sessions(session_id) ON DELETE CASCADE,
    FOREIGN KEY (answer_file_id) REFERENCES main_marking_answer_files(answer_file_id) ON DELETE CASCADE,
    FOREIGN KEY (teacher_id) REFERENCES users(user_id)
);
"""

# One row per finalized target, snapshotting everything the Results page's
# detail view needs so it never has to re-join back to the (possibly since
# reset/recreated) live marked-answer rows.
CREATE_MAIN_MARKING_FINAL_RESULT_ITEMS_TABLE = """
CREATE TABLE IF NOT EXISTS main_marking_final_result_items (
    item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    result_id INTEGER NOT NULL,
    marked_answer_id INTEGER,
    target_label TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    region_type TEXT,
    student_answer_text TEXT,
    correct_answer_text TEXT,
    machine_score REAL,
    teacher_score REAL,
    final_score REAL NOT NULL,
    max_score REAL NOT NULL,
    machine_feedback TEXT,
    teacher_feedback TEXT,
    final_feedback TEXT,
    reviewed_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (result_id) REFERENCES main_marking_final_results(result_id) ON DELETE CASCADE
);
"""

# --- Stage 11V: Subject Profile marking workflow foundation -----------------
#
# A Subject Profile replaces the teacher-facing "choose a Template + paper
# type" workflow with a single, self-contained unit: a question paper PDF
# plus an answer scheme PDF, their OCR/extracted content, and teacher-
# defined regions/groups/answer-key entries - all owned by one profile row.
#
# Deliberately NOT built by reusing answer_templates/template_regions or
# marking_setups: answer_templates.paper_type and template_regions.
# region_type both have a CHECK constraint scoped to Kertas 1/Kertas 2's
# existing region-type vocabulary, and marking_setups.material_id is a
# NOT NULL UNIQUE foreign key into revision_materials - reusing either
# would require either a destructive CHECK-constraint table rebuild or a
# synthetic/placeholder revision_materials row. A brand-new, purpose-built
# set of tables (with their own region_type vocabulary, including the
# Stage 12 AI plan's future YOLO class names) avoids both risks entirely.
#
# Student answer PDF handling still REUSES main_marking_sessions /
# main_marking_answer_files / preprocessing / OCR (Stage 11L-11N) - those
# tables are generic (session/answer-file keyed, no template coupling), so
# a Subject Profile simply creates a main_marking_session under the hood
# (paper_type fixed to 'Kertas 1' internally - never shown to the teacher)
# linked back via the new nullable main_marking_sessions.subject_profile_id
# column below. Only extraction/marking are Subject-Profile-specific (they
# read subject_profile_regions/groups instead of template_regions).

# Stage 12E-fix: generic, paper-agnostic region vocabulary (Kertas 1/
# Kertas 2 no longer separated in the teacher-facing region type list) -
# see SUBJECT_PROFILE_REGION_TYPE_MIGRATION_MAP below for the old->new
# value mapping applied to existing Subject Profiles.
SUBJECT_PROFILE_REGION_TYPES_SQL = (
    "'question_area', 'question_number_box', 'answer_region', 'answer_box', "
    "'bubble_area', 'letter_box', 'underline_answer', 'student_info_area', "
    "'extra_page_label', 'ignore_region'"
)

# Old (pre-Stage-12E-fix) region_type value -> new generic value. Applied
# by _migrate_subject_profile_regions_rename_generic_labels/_migrate_
# subject_profile_region_groups_rename_generic_labels when rebuilding
# those tables for the new CHECK constraint above - any value not listed
# here (already-generic labels) passes through unchanged.
SUBJECT_PROFILE_REGION_TYPE_MIGRATION_MAP = {
    "k1_bubble_area": "bubble_area",
    "k1_letter_box": "letter_box",
    "k1_underline_answer": "underline_answer",
    "k2_question_number_box": "question_number_box",
    "k2_answer_box": "answer_box",
}

CREATE_SUBJECT_PROFILES_TABLE = f"""
CREATE TABLE IF NOT EXISTS subject_profiles (
    profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL,
    profile_name TEXT NOT NULL,
    question_paper_path TEXT,
    answer_scheme_path TEXT,
    question_paper_ocr_json TEXT,
    answer_scheme_ocr_json TEXT,
    question_paper_extracted_json TEXT,
    answer_scheme_extracted_json TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    updated_at TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (teacher_id) REFERENCES users(user_id)
);
"""

CREATE_SUBJECT_PROFILE_REGIONS_TABLE = f"""
CREATE TABLE IF NOT EXISTS subject_profile_regions (
    region_id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('question_paper', 'answer_scheme')),
    label TEXT NOT NULL,
    region_type TEXT NOT NULL CHECK (region_type IN ({SUBJECT_PROFILE_REGION_TYPES_SQL})),
    page_number INTEGER NOT NULL DEFAULT 1,
    x REAL NOT NULL CHECK (x >= 0 AND x <= 1),
    y REAL NOT NULL CHECK (y >= 0 AND y <= 1),
    width REAL NOT NULL CHECK (width > 0),
    height REAL NOT NULL CHECK (height > 0),
    shape_type TEXT NOT NULL DEFAULT 'rectangle',
    polygon_points_json TEXT,
    rotation_angle REAL NOT NULL DEFAULT 0.0,
    order_index INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (profile_id) REFERENCES subject_profiles(profile_id) ON DELETE CASCADE
);
"""

CREATE_SUBJECT_PROFILE_REGION_GROUPS_TABLE = f"""
CREATE TABLE IF NOT EXISTS subject_profile_region_groups (
    group_id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    region_type TEXT NOT NULL CHECK (region_type IN ({SUBJECT_PROFILE_REGION_TYPES_SQL})),
    notes TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (profile_id) REFERENCES subject_profiles(profile_id) ON DELETE CASCADE
);
"""

CREATE_SUBJECT_PROFILE_REGION_GROUP_MEMBERS_TABLE = """
CREATE TABLE IF NOT EXISTS subject_profile_region_group_members (
    group_id INTEGER NOT NULL,
    region_id INTEGER NOT NULL,
    member_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (group_id, region_id),
    FOREIGN KEY (group_id) REFERENCES subject_profile_region_groups(group_id) ON DELETE CASCADE,
    FOREIGN KEY (region_id) REFERENCES subject_profile_regions(region_id) ON DELETE CASCADE
);
"""

# Teacher-confirmed/edited answer-scheme content, doubling as the marking
# scheme (question_no/correct_answer/max_mark/comment) - one row per
# region OR group target defined on the profile.
CREATE_SUBJECT_PROFILE_ANSWER_KEY_ENTRIES_TABLE = """
CREATE TABLE IF NOT EXISTS subject_profile_answer_key_entries (
    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL,
    target_label TEXT NOT NULL,
    target_kind TEXT NOT NULL CHECK (target_kind IN ('region', 'group')),
    question_no TEXT,
    correct_answer TEXT,
    max_mark REAL NOT NULL DEFAULT 1.0,
    comment TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    FOREIGN KEY (profile_id) REFERENCES subject_profiles(profile_id) ON DELETE CASCADE
);
"""

# One row per subject-profile-region/group target extracted from one
# student answer_file (main_marking_answer_files, reused) - mirrors
# main_marking_extracted_answers but keyed to subject_profile_regions
# instead of template_regions, so no FK conflict with the older table.
CREATE_SUBJECT_PROFILE_EXTRACTED_ANSWERS_TABLE = """
CREATE TABLE IF NOT EXISTS subject_profile_extracted_answers (
    extracted_answer_id INTEGER PRIMARY KEY AUTOINCREMENT,
    answer_file_id INTEGER NOT NULL,
    target_label TEXT NOT NULL,
    target_kind TEXT NOT NULL CHECK (target_kind IN ('region', 'group')),
    region_type TEXT,
    extracted_text TEXT,
    confidence REAL,
    status TEXT NOT NULL DEFAULT 'extracted',
    message TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (answer_file_id) REFERENCES main_marking_answer_files(answer_file_id) ON DELETE CASCADE
);
"""

CREATE_SUBJECT_PROFILE_MARKED_ANSWERS_TABLE = """
CREATE TABLE IF NOT EXISTS subject_profile_marked_answers (
    marked_answer_id INTEGER PRIMARY KEY AUTOINCREMENT,
    answer_file_id INTEGER NOT NULL,
    target_label TEXT NOT NULL,
    target_kind TEXT NOT NULL CHECK (target_kind IN ('region', 'group')),
    region_type TEXT,
    student_answer_text TEXT,
    correct_answer_text TEXT,
    score REAL,
    max_score REAL NOT NULL DEFAULT 1.0,
    is_correct INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'marked',
    feedback TEXT,
    created_at TEXT NOT NULL,
    -- Stage 12G-1A teacher-review + raw-extraction-provenance columns. The
    -- machine-generated columns above are NEVER overwritten by a teacher
    -- correction; the teacher's values live here (see subject_profile_
    -- review_service). raw_ocr_text preserves the raw OCR for audit even
    -- after the teacher corrects the answer text.
    raw_ocr_text TEXT,
    extraction_confidence REAL,
    extraction_method TEXT,
    extraction_timestamp TEXT,
    corrected_answer_text TEXT,
    teacher_score REAL,
    teacher_status TEXT,
    teacher_feedback TEXT,
    private_comment TEXT,
    reviewed_by INTEGER,
    reviewed_at TEXT,
    updated_at TEXT,
    -- Stage 12G-1A (Part 3 finalisation integrity): the Kertas 2 Part 3
    -- answer box records which Part 3 question (3/4/5) the student chose.
    -- extracted_* is the machine-detected number (from the non-gradeable
    -- question_number_field region); teacher_* is the teacher's confirmed/
    -- corrected choice. Both NULL on every other target and on legacy rows.
    extracted_selected_question_number TEXT,
    teacher_selected_question_number TEXT,
    -- Stage 12G-1A Phase 2C: set when an attempt region override changes this
    -- target's effective extraction, so the teacher's existing K1/K2 review is
    -- flagged stale and finalisation is blocked until they reconfirm.
    extraction_review_stale INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (answer_file_id) REFERENCES main_marking_answer_files(answer_file_id) ON DELETE CASCADE
);
"""

# Tick/X/percentage overlay marks (Stage 11V) - persisted per answer_file so
# a move/resize/rotate/delete survives reopening the marking editor for
# that student result. x/y/rotation are editable after creation (unlike
# template_regions, which only supports redraw-to-reposition).
CREATE_SUBJECT_PROFILE_OVERLAYS_TABLE = """
CREATE TABLE IF NOT EXISTS subject_profile_overlays (
    overlay_id INTEGER PRIMARY KEY AUTOINCREMENT,
    answer_file_id INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('tick', 'cross', 'percentage', 'feedback')),
    page_number INTEGER NOT NULL DEFAULT 1,
    x REAL NOT NULL,
    y REAL NOT NULL,
    width REAL NOT NULL DEFAULT 0.04,
    height REAL NOT NULL DEFAULT 0.04,
    rotation_angle REAL NOT NULL DEFAULT 0.0,
    text_value TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    is_hidden INTEGER NOT NULL DEFAULT 0,
    is_teacher_adjusted INTEGER NOT NULL DEFAULT 0,
    original_x REAL,
    original_y REAL,
    -- Stage 12G-1A Phase 2B: link a status marker to its logical answer
    -- target (NULL for the headline summary overlay) so the editable overlay
    -- workspace shows one row per target and regeneration preserves teacher
    -- edits by target. teacher_symbol_override + use_auto_symbol hold an
    -- explicit teacher symbol choice separately from the generated `kind`
    -- (which is preserved for audit); use_auto_symbol=1 means Auto mode.
    target_label TEXT,
    teacher_symbol_override TEXT,
    use_auto_symbol INTEGER NOT NULL DEFAULT 1,
    -- Optional manual font size (in PDF points) for a 'feedback' note; NULL
    -- means the size is chosen automatically to fit the note's box.
    font_size INTEGER,
    FOREIGN KEY (answer_file_id) REFERENCES main_marking_answer_files(answer_file_id) ON DELETE CASCADE
);
"""


# --- Stage 12G-1A: Teacher Review & Marking Correction Workspace ------------
#
# A production-grade teacher review layer over one student attempt's marked
# answers (main_marking_answer_files.answer_file_id) - the persistence
# foundation for later Core AI 1 dataset export (Stage 12G-2). Deliberately
# ADDITIVE and non-destructive: the original machine-generated columns on
# subject_profile_marked_answers (student_answer_text/correct_answer_text/
# score/status/feedback/is_correct/max_score) are NEVER overwritten by a
# teacher correction - the teacher's values live in separate teacher_*
# columns and the raw OCR in raw_ocr_text, so a finalised training label
# always retains its full provenance (raw OCR -> automated result -> teacher
# correction). See app/services/subject_profile_review_service.py.

# One review header per student attempt (answer_file). review_state
# separates the ATTEMPT-level workflow position (draft/needs_review/
# finalised) from each answer's own MARKING status (correct/wrong/...),
# per the "do not overload one field" rule. Cascade-deletes with the
# answer file, matching the existing hard-delete policy (see delete_
# student_marking).
CREATE_SUBJECT_PROFILE_ATTEMPT_REVIEWS_TABLE = """
CREATE TABLE IF NOT EXISTS subject_profile_attempt_reviews (
    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
    answer_file_id INTEGER NOT NULL UNIQUE,
    profile_id INTEGER,
    review_state TEXT NOT NULL DEFAULT 'draft'
        CHECK (review_state IN ('draft', 'needs_review', 'finalised')),
    reviewed_by INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    reviewed_at TEXT,
    finalised_at TEXT,
    -- Stage 12G-1A Phase 2B: paths of the last published FINAL reviewed
    -- outputs (marked PDF + student-facing comments). NULL until the attempt
    -- is finalised; the dashboard download uses these when present.
    final_marked_pdf_path TEXT,
    final_comments_path TEXT,
    final_output_generated_at TEXT,
    -- Phase 2B consistency fix: the active published output VERSION id. The
    -- marked PDF + comments both live in result_versions/<version>/ so a
    -- download always resolves a matched pair.
    final_output_version TEXT,
    FOREIGN KEY (answer_file_id) REFERENCES main_marking_answer_files(answer_file_id) ON DELETE CASCADE,
    FOREIGN KEY (reviewed_by) REFERENCES users(user_id)
);
"""

# Structured, expandable feedback-category catalogue (seeded once with the
# Stage 12G-1A initial list). A separate link table records each answer's
# selected categories - never a comma-separated display string - so a
# future category-management UI and the Core AI 1 dataset export can query
# them structurally. is_active lets a category be retired without deleting
# historical selections that reference it.
CREATE_SUBJECT_PROFILE_FEEDBACK_CATEGORIES_TABLE = """
CREATE TABLE IF NOT EXISTS subject_profile_feedback_categories (
    category_id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_key TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    display_order INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
"""

CREATE_SUBJECT_PROFILE_ANSWER_FEEDBACK_CATEGORIES_TABLE = """
CREATE TABLE IF NOT EXISTS subject_profile_answer_feedback_categories (
    marked_answer_id INTEGER NOT NULL,
    category_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (marked_answer_id, category_id),
    FOREIGN KEY (marked_answer_id) REFERENCES subject_profile_marked_answers(marked_answer_id) ON DELETE CASCADE,
    FOREIGN KEY (category_id) REFERENCES subject_profile_feedback_categories(category_id)
);
"""

# Attempt-specific answer-region geometry correction - stored ENTIRELY
# separately from the shared subject_profile_regions row it overrides, so
# correcting one student's region never mutates the Subject Profile other
# attempts share (the guarded "apply back to profile" action is a separate,
# explicit route - see the review service). profile_region_id is an
# informational reference only (no FK) so deleting/editing a shared region
# never breaks an attempt's historical override. One override per (answer
# file, target label).
CREATE_SUBJECT_PROFILE_ATTEMPT_REGION_OVERRIDES_TABLE = """
CREATE TABLE IF NOT EXISTS subject_profile_attempt_region_overrides (
    override_id INTEGER PRIMARY KEY AUTOINCREMENT,
    answer_file_id INTEGER NOT NULL,
    profile_region_id INTEGER,
    source TEXT NOT NULL DEFAULT 'question_paper',
    label TEXT NOT NULL,
    region_type TEXT,
    page_number INTEGER NOT NULL DEFAULT 1,
    x REAL NOT NULL,
    y REAL NOT NULL,
    width REAL NOT NULL,
    height REAL NOT NULL,
    shape_type TEXT NOT NULL DEFAULT 'rectangle',
    polygon_points_json TEXT,
    rotation_angle REAL NOT NULL DEFAULT 0.0,
    corrected_text TEXT,
    correction_reason TEXT,
    corrected_by INTEGER,
    corrected_at TEXT,
    created_at TEXT NOT NULL,
    -- Stage 12G-1A Phase 2C: snapshot of the ORIGINAL (shared Subject Profile)
    -- region geometry at override time (for original-vs-effective comparison
    -- and Restore Original Region); the rerun-OCR lineage kept SEPARATE from
    -- the original OCR (on the marked answer) and the teacher-corrected text;
    -- and crop checksums proving the crop actually changed.
    original_x REAL,
    original_y REAL,
    original_width REAL,
    original_height REAL,
    rerun_ocr_text TEXT,
    rerun_ocr_confidence REAL,
    rerun_ocr_at TEXT,
    crop_checksum TEXT,
    original_crop_checksum TEXT,
    UNIQUE (answer_file_id, label),
    FOREIGN KEY (answer_file_id) REFERENCES main_marking_answer_files(answer_file_id) ON DELETE CASCADE,
    FOREIGN KEY (corrected_by) REFERENCES users(user_id)
);
"""

# Immutable audit trail of review workflow actions (save_draft / finalise /
# reopen / apply_region_to_profile) on one attempt - who did what, when, and
# the state transition. Cascade-deletes with the answer file (consistent
# with the existing hard-delete policy: a deleted attempt retains no
# records). A future audit-retention policy can change this cascade.
CREATE_SUBJECT_PROFILE_REVIEW_AUDIT_TABLE = """
CREATE TABLE IF NOT EXISTS subject_profile_review_audit (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    answer_file_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT,
    acted_by INTEGER,
    acted_at TEXT NOT NULL,
    note TEXT,
    FOREIGN KEY (answer_file_id) REFERENCES main_marking_answer_files(answer_file_id) ON DELETE CASCADE,
    FOREIGN KEY (acted_by) REFERENCES users(user_id)
);
"""

# --- Stage 12G-1B: Manual Separate Answer Paper mode ------------------------
#
# A separate-answer-paper attempt uploads standalone answer pages. Those pages
# are NOT Subject Profile pages: they get their own attempt-scoped page rows,
# and every answer's geometry is mapped per attempt. The shared Subject
# Profile is never modified by any of this.

CREATE_SEPARATE_PAPER_PAGES_TABLE = """
CREATE TABLE IF NOT EXISTS separate_answer_paper_pages (
    sap_page_id INTEGER PRIMARY KEY AUTOINCREMENT,
    answer_file_id INTEGER NOT NULL,
    page_number INTEGER NOT NULL,          -- 1-based teacher-visible order
    source_file_path TEXT NOT NULL,        -- original uploaded file (preserved)
    source_original_filename TEXT,
    source_page_index INTEGER NOT NULL DEFAULT 0,  -- page inside a multi-page PDF
    source_kind TEXT NOT NULL DEFAULT 'pdf' CHECK (source_kind IN ('pdf', 'image')),
    file_checksum TEXT,
    width_px INTEGER,
    height_px INTEGER,
    original_image_path TEXT,
    preview_image_path TEXT,
    status TEXT NOT NULL DEFAULT 'uploaded',
    message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    UNIQUE (answer_file_id, page_number),
    FOREIGN KEY (answer_file_id) REFERENCES main_marking_answer_files(answer_file_id) ON DELETE CASCADE
);
"""

# One row per REQUIRED logical target for a separate-paper attempt, holding the
# teacher-owned state. The target list itself is derived from the Subject
# Profile; this table only stores the per-attempt decision/state.
CREATE_SEPARATE_PAPER_TARGET_STATES_TABLE = """
CREATE TABLE IF NOT EXISTS separate_paper_target_states (
    target_state_id INTEGER PRIMARY KEY AUTOINCREMENT,
    answer_file_id INTEGER NOT NULL,
    target_label TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'unresolved'
        CHECK (state IN ('unresolved', 'mapped', 'explicitly_blank')),
    blank_confirmed INTEGER NOT NULL DEFAULT 0,
    review_stale INTEGER NOT NULL DEFAULT 0,
    teacher_final_answer TEXT,             -- K1 teacher's final answer (precedence 1)
    note TEXT,
    updated_by INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    UNIQUE (answer_file_id, target_label),
    FOREIGN KEY (answer_file_id) REFERENCES main_marking_answer_files(answer_file_id) ON DELETE CASCADE,
    FOREIGN KEY (updated_by) REFERENCES users(user_id)
);
"""

# One row per mapped rectangle. A target may have several (main + ordered
# continuation regions); reading_order is unique per target.
CREATE_SEPARATE_PAPER_MAPPINGS_TABLE = """
CREATE TABLE IF NOT EXISTS separate_paper_mappings (
    mapping_id INTEGER PRIMARY KEY AUTOINCREMENT,
    answer_file_id INTEGER NOT NULL,
    target_label TEXT NOT NULL,
    paper TEXT,
    part TEXT,
    question_no TEXT,
    mapping_type TEXT NOT NULL CHECK (mapping_type IN (
        'k1_answer_block', 'k1_individual_answer', 'k2_part1', 'k2_part2', 'k2_part3',
        'part3_selected_question', 'continuation')),
    sap_page_id INTEGER NOT NULL,
    x REAL NOT NULL, y REAL NOT NULL, width REAL NOT NULL, height REAL NOT NULL,
    page_width_px INTEGER, page_height_px INTEGER,
    reading_order INTEGER NOT NULL DEFAULT 1,
    is_continuation INTEGER NOT NULL DEFAULT 0,
    -- OCR lineage: original (first) OCR, rerun OCR and teacher-corrected text
    -- are kept in three separate columns.
    original_ocr_text TEXT,
    original_ocr_confidence REAL,
    rerun_ocr_text TEXT,
    rerun_ocr_confidence REAL,
    rerun_ocr_at TEXT,
    corrected_text TEXT,
    crop_checksum TEXT,
    -- JSON list of the OCR engine's recognised line boxes for this crop, each
    -- normalised to the MAPPING rectangle: {"text", "x", "y", "width",
    -- "height"}. Used to anchor a per-question marker on the real line the
    -- answer was read from; NULL when the engine returned no geometry.
    ocr_line_boxes_json TEXT,
    confirmed INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    UNIQUE (answer_file_id, target_label, reading_order),
    FOREIGN KEY (answer_file_id) REFERENCES main_marking_answer_files(answer_file_id) ON DELETE CASCADE,
    FOREIGN KEY (sap_page_id) REFERENCES separate_answer_paper_pages(sap_page_id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES users(user_id)
);
"""

# One row per (question_no, answer) pair parsed out of a K1 numbered-answer
# block, plus its warnings/conflicts and the teacher's correction.
CREATE_SEPARATE_PAPER_PARSED_ANSWERS_TABLE = """
CREATE TABLE IF NOT EXISTS separate_paper_parsed_answers (
    parsed_id INTEGER PRIMARY KEY AUTOINCREMENT,
    answer_file_id INTEGER NOT NULL,
    mapping_id INTEGER,                    -- the k1_answer_block mapping it came from
    question_no TEXT,
    parsed_answer TEXT,
    source_text TEXT,
    confidence REAL,
    reason TEXT,
    warning TEXT,
    has_conflict INTEGER NOT NULL DEFAULT 0,
    teacher_answer TEXT,
    state TEXT NOT NULL DEFAULT 'unconfirmed'
        CHECK (state IN ('unconfirmed', 'confirmed', 'blank', 'unresolved')),
    -- Anchor is BLOCK-RELATIVE (0-1 within the parsed block mapping).
    anchor_x REAL, anchor_y REAL, anchor_width REAL, anchor_height REAL,
    -- Which geometry the anchor came from: a real recognised OCR line box, or
    -- the parser's approximate line/character estimate. Never presented as
    -- exact when it is only approximate.
    anchor_source TEXT NOT NULL DEFAULT 'approximate_block_row'
        CHECK (anchor_source IN ('ocr_line_geometry', 'approximate_block_row')),
    created_at TEXT NOT NULL,
    updated_at TEXT,
    FOREIGN KEY (answer_file_id) REFERENCES main_marking_answer_files(answer_file_id) ON DELETE CASCADE,
    FOREIGN KEY (mapping_id) REFERENCES separate_paper_mappings(mapping_id) ON DELETE CASCADE
);
"""


# Stage 12G-1A seed list - inserted once (idempotent via INSERT OR IGNORE on
# the unique category_key) by _seed_feedback_categories. Order = display order.
FEEDBACK_CATEGORY_SEED = (
    ("task_fulfilment", "Task Fulfilment"),
    ("content", "Content"),
    ("organisation", "Organisation"),
    ("language", "Language"),
    ("grammar", "Grammar"),
    ("vocabulary", "Vocabulary"),
    ("spelling", "Spelling"),
    ("relevance", "Relevance"),
    ("coherence", "Coherence"),
    ("mechanics", "Mechanics"),
    ("needs_improvement", "Needs Improvement"),
    ("strength", "Strength"),
)


CREATE_TEACHER_MARKING_SETTINGS_TABLE = """
CREATE TABLE IF NOT EXISTS teacher_marking_settings (
    setting_id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL UNIQUE,
    spelling_deduction_enabled INTEGER NOT NULL DEFAULT 1,
    spelling_deduction_points REAL NOT NULL DEFAULT 1.0,
    kertas2_partial_mark_default REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (teacher_id) REFERENCES users(user_id)
);
"""

CREATE_LOCAL_AI_SETTINGS_TABLE = """
CREATE TABLE IF NOT EXISTS local_ai_settings (
    setting_id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER,
    provider_name TEXT NOT NULL DEFAULT 'local',
    backend_name TEXT NOT NULL DEFAULT 'none',
    model_path TEXT,
    is_enabled INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (teacher_id) REFERENCES users(user_id)
);
"""

# teacher_id is nullable so pre-Stage-10B rows (created before per-teacher
# settings existed) survive migration untouched as a legacy/global fallback
# row (teacher_id IS NULL). The partial unique index only constrains rows
# that DO have a teacher_id, so each teacher can have at most one settings
# row while still allowing the single legacy row to coexist.
CREATE_LOCAL_AI_SETTINGS_TEACHER_ID_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_local_ai_settings_teacher_id
ON local_ai_settings(teacher_id) WHERE teacher_id IS NOT NULL;
"""

# --- Stage 12A: AI Models page / model registry foundation ------------------
#
# Deliberately separate from local_ai_settings above: local_ai_settings
# configures the teacher's LOCAL AI BACKEND for Kertas 2 draft feedback
# generation (which pluggable backend to call and its model file path) -
# it does not track trained model versions. The tables below are this
# project's OWN model registry: trained model versions (Core AI 1's
# Cross-Encoder and Core AI 2's YOLO detector), their training jobs/
# progress/logs, and which version is
# "active" per teacher per model_key. No training happens in Stage 12A -
# these tables only give future stages (12B+) a safe place to record
# versions/jobs once real training exists.

AI_MODEL_KEYS_SQL = "'k2_short_answer_scoring', 'answer_region_detection'"
AI_MODEL_TYPES_SQL = "'cross_encoder', 'yolo_detector'"
AI_TRAINING_JOB_STATUSES_SQL = "'queued', 'running', 'completed', 'failed', 'cancelled'"

CREATE_AI_MODEL_VERSIONS_TABLE = f"""
CREATE TABLE IF NOT EXISTS ai_model_versions (
    model_id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL,
    model_key TEXT NOT NULL CHECK (model_key IN ({AI_MODEL_KEYS_SQL})),
    model_name TEXT NOT NULL,
    model_type TEXT NOT NULL CHECK (model_type IN ({AI_MODEL_TYPES_SQL})),
    version_label TEXT NOT NULL,
    model_path TEXT,
    metrics_json TEXT,
    config_json TEXT,
    notes TEXT,
    is_active INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (teacher_id) REFERENCES users(user_id)
);
"""

# Only one row per (teacher_id, model_key) may have is_active = 1 - enforced
# at the database level (in addition to the service layer explicitly
# deactivating any other active version for that teacher/model_key before
# activating a new one) via this partial unique index.
CREATE_AI_MODEL_VERSIONS_ACTIVE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_model_versions_active_per_teacher_key
ON ai_model_versions(teacher_id, model_key) WHERE is_active = 1;
"""

CREATE_AI_TRAINING_JOBS_TABLE = f"""
CREATE TABLE IF NOT EXISTS ai_training_jobs (
    job_id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL,
    model_key TEXT NOT NULL CHECK (model_key IN ({AI_MODEL_KEYS_SQL})),
    model_type TEXT NOT NULL CHECK (model_type IN ({AI_MODEL_TYPES_SQL})),
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ({AI_TRAINING_JOB_STATUSES_SQL})),
    progress_percent REAL NOT NULL DEFAULT 0 CHECK (progress_percent >= 0 AND progress_percent <= 100),
    current_step TEXT,
    log_path TEXT,
    output_model_id INTEGER,
    config_json TEXT,
    metrics_json TEXT,
    message TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (teacher_id) REFERENCES users(user_id),
    FOREIGN KEY (output_model_id) REFERENCES ai_model_versions(model_id)
);
"""

# --- Stage 12B: Kertas 2 training dataset export foundation -----------------
#
# Prepares Core AI 1's training source (see docs/stage12_ai_plan.md): an
# exported CSV/JSONL snapshot of teacher-reviewed (finalized only - never
# draft AI feedback) Kertas 2 examples. This table only records metadata
# about each export (paths, row count, summary) - the actual dataset rows
# live in the CSV/JSONL files under data/ai_training_datasets/, never in
# the database itself.
#
# Stage 12E reuses this same table for Answer Region Detection's YOLO-style
# image/label dataset exports (model_key='answer_region_detection' was
# already an allowed AI_MODEL_KEYS_SQL value - no CHECK constraint change
# needed) rather than a parallel table, since the metadata shape (teacher,
# name, format, row_count, summary, timestamps) is identical. The one
# genuine mismatch is that csv_path/jsonl_path name specific TEXT dataset
# files that don't make sense for a folder of images/labels/yaml/manifest -
# dataset_folder_path (added below, nullable) covers that case instead of
# overloading csv_path/jsonl_path with the wrong meaning. dataset_format
# distinguishes the two: 'csv_jsonl' (Kertas 2) vs 'yolo_image_dataset'
# (Answer Region Detection) - no CHECK constraint restricts this column,
# so no migration was needed to add the new value.
CREATE_AI_TRAINING_DATASETS_TABLE = f"""
CREATE TABLE IF NOT EXISTS ai_training_datasets (
    dataset_id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL,
    model_key TEXT NOT NULL CHECK (model_key IN ({AI_MODEL_KEYS_SQL})),
    dataset_name TEXT NOT NULL,
    dataset_format TEXT NOT NULL DEFAULT 'csv_jsonl',
    row_count INTEGER NOT NULL DEFAULT 0,
    csv_path TEXT,
    jsonl_path TEXT,
    dataset_folder_path TEXT,
    summary_json TEXT,
    source_filter_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (teacher_id) REFERENCES users(user_id)
);
"""

# Stage 12G-2: sanitized audit trail for global AI-admin actions (AI Models
# registry access/denials, dataset freeze/conversion, model activation/
# rollback, proposal accept/reject, Local-AI fallback). Deliberately separate
# from subject_profile_review_audit (which is answer-file scoped). Notes are
# sanitized JSON - never full essays, prompts, raw OCR or secrets.
CREATE_AI_ADMIN_AUDIT_TABLE = """
CREATE TABLE IF NOT EXISTS ai_admin_audit (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_user_id INTEGER,
    actor_role TEXT,
    action TEXT NOT NULL,
    target TEXT,
    outcome TEXT NOT NULL DEFAULT 'ok'
        CHECK (outcome IN ('ok', 'denied', 'failed')),
    note TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (actor_user_id) REFERENCES users(user_id)
);
"""

CREATE_AI_ADMIN_AUDIT_ACTION_INDEX = """
CREATE INDEX IF NOT EXISTS idx_ai_admin_audit_action_time
ON ai_admin_audit(action, created_at);
"""

# Stage 12G-4: Core AI 2 answer-region PROPOSALS (teacher-facing). A proposal
# is never an automatic region/mapping - it is teacher-reviewed. One table
# serves both workflows: Subject Profile region proposals (profile_id set) and
# Separate Answer Paper attempt proposals (answer_file_id set). Source geometry
# (the model's) and final geometry (the teacher's) are both preserved. Only
# geometry/class metadata is stored - never raw essays, prompts or OCR.
CREATE_CORE_AI2_PROPOSALS_TABLE = """
CREATE TABLE IF NOT EXISTS core_ai2_region_proposals (
    proposal_id TEXT PRIMARY KEY,
    workflow_context TEXT NOT NULL
        CHECK (workflow_context IN ('subject_profile', 'separate_answer_paper')),
    profile_id INTEGER,
    answer_file_id INTEGER,
    source TEXT,                       -- question_paper / answer_scheme (profile) or NULL
    page_number INTEGER,
    sap_page_id INTEGER,               -- separate-paper page (attempt workflow)
    model_family TEXT NOT NULL,
    model_version TEXT,
    model_checksum TEXT,
    input_page_checksum TEXT,
    proposed_class TEXT,               -- region_class (profile) / mapping_type (attempt)
    proposed_target_label TEXT,        -- logical target when the model suggests one
    confidence REAL,
    rationale TEXT,
    source_x REAL, source_y REAL, source_width REAL, source_height REAL,
    final_x REAL, final_y REAL, final_width REAL, final_height REAL,
    status TEXT NOT NULL DEFAULT 'proposed'
        CHECK (status IN ('proposed', 'accepted', 'rejected', 'edited', 'deferred')),
    decision_reason TEXT,
    accepted_region_id INTEGER,        -- created Subject Profile region (accept)
    accepted_mapping_id INTEGER,       -- created attempt mapping (accept)
    actor_user_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    FOREIGN KEY (profile_id) REFERENCES subject_profiles(profile_id) ON DELETE CASCADE,
    FOREIGN KEY (answer_file_id) REFERENCES main_marking_answer_files(answer_file_id) ON DELETE CASCADE,
    FOREIGN KEY (actor_user_id) REFERENCES users(user_id)
);
"""

CREATE_CORE_AI2_PROPOSALS_PROFILE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_core_ai2_proposals_profile
ON core_ai2_region_proposals(profile_id, status);
"""

CREATE_CORE_AI2_PROPOSALS_ATTEMPT_INDEX = """
CREATE INDEX IF NOT EXISTS idx_core_ai2_proposals_attempt
ON core_ai2_region_proposals(answer_file_id, status);
"""

# Stage 12G-7: the local natural-language feedback runtime the teacher points
# at is configured per teacher, alongside the existing Stage 10B provider
# fields. Every column is nullable or defaulted, so this is a plain additive
# ALTER TABLE ADD COLUMN on an existing database - no rewrite, no data loss,
# and a teacher who has configured nothing keeps working exactly as before.
LOCAL_AI_RUNTIME_COLUMNS = (
    ("feedback_adapter", "TEXT NOT NULL DEFAULT 'none'"),
    ("feedback_endpoint", "TEXT"),
    ("feedback_model_name", "TEXT"),
    ("feedback_timeout_seconds", "REAL NOT NULL DEFAULT 15"),
    ("feedback_max_output_tokens", "INTEGER NOT NULL DEFAULT 180"),
    ("feedback_temperature", "REAL NOT NULL DEFAULT 0.2"),
    ("feedback_response_size_limit", "INTEGER NOT NULL DEFAULT 8192"),
    ("feedback_requested_length", "INTEGER NOT NULL DEFAULT 500"),
    ("feedback_allow_private_network", "INTEGER NOT NULL DEFAULT 0"),
)


def _migrate_attempts_add_marked_link_columns(conn: sqlite3.Connection) -> None:
    """Marking-bridge columns: a student attempt / external revision marked
    through the Subject Profile pipeline remembers which answer file and
    profile carry its marking, so the student's pages can surface the
    finalised marked PDF. Same additive ALTER TABLE pattern as the other
    column migrations - no rewrite, no data loss."""
    for table in ("revision_attempts", "student_external_revisions"):
        existing = {info[1] for info in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        added = False
        for name in ("marked_answer_file_id", "marked_profile_id"):
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} INTEGER")
                added = True
        if added:
            conn.commit()


def _migrate_local_ai_settings_add_runtime_columns(conn: sqlite3.Connection) -> None:
    existing = {info[1] for info in conn.execute("PRAGMA table_info(local_ai_settings)").fetchall()}
    added = False
    for name, definition in LOCAL_AI_RUNTIME_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE local_ai_settings ADD COLUMN {name} {definition}")
            added = True
    if added:
        conn.commit()


CREATE_CORE_AI1_DRAFTS_TABLE = """
CREATE TABLE IF NOT EXISTS core_ai1_answer_drafts (
    draft_id TEXT PRIMARY KEY,
    marked_answer_id INTEGER NOT NULL,
    answer_file_id INTEGER NOT NULL,
    profile_id INTEGER,
    status TEXT NOT NULL
        CHECK (status IN ('completed', 'skipped', 'attention_required', 'failed')),
    draft_score REAL,                  -- proposed_application_score (never final)
    draft_raw_score REAL,
    normalized_score REAL,
    draft_feedback_category TEXT,
    category_confidence REAL,
    score_confidence REAL,
    rounding_policy_version TEXT,
    model_version TEXT,
    model_checksum TEXT,
    dataset_lineage TEXT,
    input_template_version TEXT,
    input_checksum TEXT NOT NULL,      -- staleness: compared to the current input
    truncation_warning INTEGER NOT NULL DEFAULT 0,
    missing_scheme_warning INTEGER NOT NULL DEFAULT 0,
    clamped INTEGER NOT NULL DEFAULT 0,
    warnings TEXT,                     -- JSON list
    failure_code TEXT,
    device TEXT,
    runtime_duration_seconds REAL,
    generated_by_user_id INTEGER,
    generated_at TEXT NOT NULL,
    applied_at TEXT,                   -- when a teacher copied it into their own entry
    dismissed_at TEXT,
    FOREIGN KEY (marked_answer_id) REFERENCES subject_profile_marked_answers(marked_answer_id)
        ON DELETE CASCADE,
    FOREIGN KEY (answer_file_id) REFERENCES main_marking_answer_files(answer_file_id)
        ON DELETE CASCADE,
    FOREIGN KEY (generated_by_user_id) REFERENCES users(user_id)
);
"""

CREATE_CORE_AI1_DRAFTS_ANSWER_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_core_ai1_drafts_marked_answer
ON core_ai1_answer_drafts(marked_answer_id);
"""

CREATE_CORE_AI1_DRAFTS_FILE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_core_ai1_drafts_answer_file
ON core_ai1_answer_drafts(answer_file_id);
"""

# Stage 12G-11: a superseded draft is never destroyed - it is archived here so
# the lineage of what the model suggested, and when, survives regeneration.
CREATE_CORE_AI1_DRAFT_HISTORY_TABLE = """
CREATE TABLE IF NOT EXISTS core_ai1_draft_history (
    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id TEXT NOT NULL,
    marked_answer_id INTEGER NOT NULL,
    answer_file_id INTEGER NOT NULL,
    status TEXT,
    draft_score REAL,
    draft_feedback_category TEXT,
    model_version TEXT,
    model_checksum TEXT,
    dataset_lineage TEXT,
    input_checksum TEXT,
    generated_at TEXT,
    applied_at TEXT,
    superseded_at TEXT NOT NULL,
    superseded_reason TEXT
);
"""

CREATE_CORE_AI1_DRAFT_HISTORY_INDEX = """
CREATE INDEX IF NOT EXISTS idx_core_ai1_draft_history_answer
ON core_ai1_draft_history(marked_answer_id);
"""

# Persisted staleness. A draft produced by a model that is no longer active is
# marked stale at activation/rollback time, not only inferred at read time.
CORE_AI1_DRAFT_STALE_COLUMNS = (
    ("stale_reason", "TEXT"),
    ("stale_marked_at", "TEXT"),
)


def _migrate_core_ai1_drafts_add_stale_columns(conn: sqlite3.Connection) -> None:
    existing = {info[1] for info in
                conn.execute("PRAGMA table_info(core_ai1_answer_drafts)").fetchall()}
    added = False
    for name, definition in CORE_AI1_DRAFT_STALE_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE core_ai1_answer_drafts ADD COLUMN {name} {definition}")
            added = True
    if added:
        conn.commit()


_LEGACY_ADMIN_ROLE = "developer_admin"


def _users_table_needs_role_migration(conn: sqlite3.Connection) -> bool:
    """Detect a pre-existing users table still built with the old CHECK constraint."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'users'"
    ).fetchone()
    if row is None:
        return False
    sql = row[0] or ""
    return _LEGACY_ADMIN_ROLE in sql


def _migrate_legacy_admin_role(conn: sqlite3.Connection) -> None:
    """Rebuild the users table so 'developer_admin' becomes 'admin'.

    SQLite cannot alter an existing CHECK constraint in place, so the table
    is renamed, recreated with the new constraint, and its rows are copied
    back across (preserving user_id so classes.teacher_id stays valid).
    """
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")
    try:
        conn.execute("ALTER TABLE users RENAME TO users_role_migration_old")
        conn.execute(CREATE_USERS_TABLE)
        conn.execute(
            f"""
            INSERT INTO users (user_id, username, password_hash, full_name, role, created_at)
            SELECT user_id, username, password_hash, full_name,
                   CASE WHEN role = '{_LEGACY_ADMIN_ROLE}' THEN 'admin' ELSE role END,
                   created_at
            FROM users_role_migration_old
            """
        )
        conn.execute("DROP TABLE users_role_migration_old")
        conn.commit()
    finally:
        conn.execute("PRAGMA legacy_alter_table = OFF")
        conn.execute("PRAGMA foreign_keys = ON")


def _classes_table_needs_teacher_nullable_migration(conn: sqlite3.Connection) -> bool:
    """Detect a pre-existing classes table still built with teacher_id NOT NULL."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'classes'"
    ).fetchone()
    if row is None:
        return False
    sql = row[0] or ""
    return "teacher_id INTEGER NOT NULL" in sql


def _migrate_classes_teacher_nullable(conn: sqlite3.Connection) -> None:
    """Rebuild the classes table so teacher_id allows NULL (unassigned classes).

    SQLite cannot drop a NOT NULL constraint in place, so the table is
    renamed, recreated with the new (nullable) definition, and its rows are
    copied back across (preserving class_id so class_transfer_requests.class_id
    stays valid).
    """
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")
    try:
        conn.execute("ALTER TABLE classes RENAME TO classes_teacher_nullable_migration_old")
        conn.execute(CREATE_CLASSES_TABLE)
        conn.execute(
            """
            INSERT INTO classes (class_id, class_name, subject, teacher_id, created_at)
            SELECT class_id, class_name, subject, teacher_id, created_at
            FROM classes_teacher_nullable_migration_old
            """
        )
        conn.execute("DROP TABLE classes_teacher_nullable_migration_old")
        conn.commit()
    finally:
        conn.execute("PRAGMA legacy_alter_table = OFF")
        conn.execute("PRAGMA foreign_keys = ON")


def _overlays_needs_feedback_kind_migration(conn: sqlite3.Connection) -> bool:
    """Detect a pre-existing subject_profile_overlays table whose kind CHECK
    constraint predates the 'feedback' overlay kind (the draggable red
    natural-language feedback note)."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'subject_profile_overlays'"
    ).fetchone()
    if row is None:
        return False
    sql = row[0] or ""
    return "'feedback'" not in sql


def _migrate_overlays_allow_feedback_kind(conn: sqlite3.Connection) -> None:
    """Rebuild subject_profile_overlays so its kind CHECK constraint also allows
    'feedback'. SQLite cannot alter a CHECK constraint in place, so the table is
    renamed, recreated with the new definition, and every row copied back
    (preserving overlay_id and all edit state - positions, hidden flags, teacher
    symbol overrides - so nothing about existing marked attempts is lost)."""
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")
    try:
        conn.execute("ALTER TABLE subject_profile_overlays RENAME TO subject_profile_overlays_feedback_kind_migration_old")
        conn.execute(CREATE_SUBJECT_PROFILE_OVERLAYS_TABLE)
        conn.execute(
            """
            INSERT INTO subject_profile_overlays
                (overlay_id, answer_file_id, kind, page_number, x, y, width, height,
                 rotation_angle, text_value, created_at, updated_at, is_hidden,
                 is_teacher_adjusted, original_x, original_y, target_label,
                 teacher_symbol_override, use_auto_symbol)
            SELECT overlay_id, answer_file_id, kind, page_number, x, y, width, height,
                   rotation_angle, text_value, created_at, updated_at, is_hidden,
                   is_teacher_adjusted, original_x, original_y, target_label,
                   teacher_symbol_override, use_auto_symbol
            FROM subject_profile_overlays_feedback_kind_migration_old
            """
        )
        conn.execute("DROP TABLE subject_profile_overlays_feedback_kind_migration_old")
        conn.commit()
    finally:
        conn.execute("PRAGMA legacy_alter_table = OFF")
        conn.execute("PRAGMA foreign_keys = ON")


def _overlays_needs_font_size_migration(conn: sqlite3.Connection) -> bool:
    """Detect a pre-existing subject_profile_overlays table built before the
    optional per-overlay font_size column (manual feedback-note font size)."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'subject_profile_overlays'"
    ).fetchone()
    if row is None:
        return False
    columns = {info[1] for info in conn.execute("PRAGMA table_info(subject_profile_overlays)").fetchall()}
    return "font_size" not in columns


def _migrate_overlays_add_font_size(conn: sqlite3.Connection) -> None:
    """Add the nullable font_size column. It is nullable (NULL = auto), so a
    plain ALTER TABLE ADD COLUMN is enough - no rename/recreate needed."""
    conn.execute("ALTER TABLE subject_profile_overlays ADD COLUMN font_size INTEGER")
    conn.commit()


def _revision_materials_needs_both_paper_type_migration(conn: sqlite3.Connection) -> bool:
    """Detect a pre-existing revision_materials table whose CHECK constraint
    predates the 'Both' paper type (Stage 10F)."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'revision_materials'"
    ).fetchone()
    if row is None:
        return False
    sql = row[0] or ""
    return "'Both'" not in sql


def _migrate_revision_materials_allow_both_paper_type(conn: sqlite3.Connection) -> None:
    """Rebuild revision_materials so its paper_type CHECK constraint also
    allows 'Both'. SQLite cannot alter a CHECK constraint in place, so the
    table is renamed, recreated with the new definition, and its rows
    (including existing Kertas 1/Kertas 2 materials) are copied back across,
    preserving material_id so revision_material_classes stays valid."""
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")
    try:
        conn.execute("ALTER TABLE revision_materials RENAME TO revision_materials_both_paper_type_migration_old")
        conn.execute(CREATE_REVISION_MATERIALS_TABLE)
        conn.execute(
            """
            INSERT INTO revision_materials
                (material_id, teacher_id, title, paper_type, subject,
                 question_paper_path, marking_scheme_path, created_at)
            SELECT material_id, teacher_id, title, paper_type, subject,
                   question_paper_path, marking_scheme_path, created_at
            FROM revision_materials_both_paper_type_migration_old
            """
        )
        conn.execute("DROP TABLE revision_materials_both_paper_type_migration_old")
        conn.commit()
    finally:
        conn.execute("PRAGMA legacy_alter_table = OFF")
        conn.execute("PRAGMA foreign_keys = ON")


def _template_regions_needs_region_type_migration(conn: sqlite3.Connection) -> bool:
    """Detect a pre-existing template_regions table built before region_type/notes existed."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'template_regions'"
    ).fetchone()
    if row is None:
        return False
    columns = {info[1] for info in conn.execute("PRAGMA table_info(template_regions)").fetchall()}
    return "region_type" not in columns


def _migrate_template_regions_add_region_type(conn: sqlite3.Connection) -> None:
    """Add the region_type and notes columns to a pre-existing template_regions table.

    Both columns are nullable, so a plain ALTER TABLE ADD COLUMN is enough -
    no need for the rename/recreate/copy dance used for constraint changes.
    """
    conn.execute("ALTER TABLE template_regions ADD COLUMN region_type TEXT")
    conn.execute("ALTER TABLE template_regions ADD COLUMN notes TEXT")
    conn.commit()


def _template_regions_needs_shape_type_migration(conn: sqlite3.Connection) -> bool:
    """Detect a pre-existing template_regions table built before Stage 11G's
    polygon region support (shape_type/polygon_points_json)."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'template_regions'"
    ).fetchone()
    if row is None:
        return False
    columns = {info[1] for info in conn.execute("PRAGMA table_info(template_regions)").fetchall()}
    return "shape_type" not in columns


def _migrate_template_regions_add_shape_type(conn: sqlite3.Connection) -> None:
    """Add shape_type and polygon_points_json to a pre-existing
    template_regions table (Stage 11G).

    shape_type has a constant string default, so every existing row
    (previously rectangle-only) becomes 'rectangle' automatically.
    polygon_points_json is nullable and stays NULL for those rows. Both are
    plain ALTER TABLE ADD COLUMN operations - no rename/recreate/copy dance
    needed, and no existing region data is touched.
    """
    conn.execute("ALTER TABLE template_regions ADD COLUMN shape_type TEXT NOT NULL DEFAULT 'rectangle'")
    conn.execute("ALTER TABLE template_regions ADD COLUMN polygon_points_json TEXT")
    conn.commit()


def _template_regions_needs_rotation_angle_migration(conn: sqlite3.Connection) -> bool:
    """Detect a pre-existing template_regions table built before Stage 11J's
    manual per-region rotation support (rotation_angle)."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'template_regions'"
    ).fetchone()
    if row is None:
        return False
    columns = {info[1] for info in conn.execute("PRAGMA table_info(template_regions)").fetchall()}
    return "rotation_angle" not in columns


def _migrate_template_regions_add_rotation_angle(conn: sqlite3.Connection) -> None:
    """Add rotation_angle to a pre-existing template_regions table (Stage
    11J). It has a constant numeric default, so every existing row
    (previously unrotated) becomes 0.0 automatically - a plain ALTER TABLE
    ADD COLUMN, no rename/recreate/copy dance needed, and no existing
    region geometry is touched."""
    conn.execute("ALTER TABLE template_regions ADD COLUMN rotation_angle REAL NOT NULL DEFAULT 0.0")
    conn.commit()


def _main_marking_sessions_needs_template_id_migration(conn: sqlite3.Connection) -> bool:
    """Detect a pre-existing main_marking_sessions table built before Stage
    11O's optional template link (template_id)."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'main_marking_sessions'"
    ).fetchone()
    if row is None:
        return False
    columns = {info[1] for info in conn.execute("PRAGMA table_info(main_marking_sessions)").fetchall()}
    return "template_id" not in columns


def _migrate_main_marking_sessions_add_template_id(conn: sqlite3.Connection) -> None:
    """Add template_id to a pre-existing main_marking_sessions table (Stage
    11O). It is nullable, so every existing session (previously unlinked)
    becomes template_id = NULL automatically - a plain ALTER TABLE ADD
    COLUMN, no rename/recreate/copy dance needed, and no existing session/
    answer-file/preprocessing/OCR data is touched."""
    conn.execute("ALTER TABLE main_marking_sessions ADD COLUMN template_id INTEGER")
    conn.commit()


def _main_marking_sessions_needs_subject_profile_id_migration(conn: sqlite3.Connection) -> bool:
    """Detect a pre-existing main_marking_sessions table built before Stage
    11V's optional Subject Profile link (subject_profile_id)."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'main_marking_sessions'"
    ).fetchone()
    if row is None:
        return False
    columns = {info[1] for info in conn.execute("PRAGMA table_info(main_marking_sessions)").fetchall()}
    return "subject_profile_id" not in columns


def _migrate_main_marking_sessions_add_subject_profile_id(conn: sqlite3.Connection) -> None:
    """Add subject_profile_id to a pre-existing main_marking_sessions table
    (Stage 11V). It is nullable, so every existing session (created before
    Subject Profiles existed) becomes subject_profile_id = NULL
    automatically - a plain ALTER TABLE ADD COLUMN, no rename/recreate/copy
    dance needed, and no existing session/answer-file/preprocessing/OCR
    data is touched."""
    conn.execute("ALTER TABLE main_marking_sessions ADD COLUMN subject_profile_id INTEGER")
    conn.commit()


def _main_marking_preprocessed_pages_needs_original_image_path_migration(conn: sqlite3.Connection) -> bool:
    """Detect a pre-existing main_marking_preprocessed_pages table built
    before Stage 11W's original_image_path column (the clean, un-degraded
    rendered page, kept alongside the CLAHE/denoise/threshold-processed
    image used for OCR)."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'main_marking_preprocessed_pages'"
    ).fetchone()
    if row is None:
        return False
    columns = {info[1] for info in conn.execute("PRAGMA table_info(main_marking_preprocessed_pages)").fetchall()}
    return "original_image_path" not in columns


def _migrate_main_marking_preprocessed_pages_add_original_image_path(conn: sqlite3.Connection) -> None:
    """Add original_image_path to a pre-existing main_marking_preprocessed_
    pages table (Stage 11W). Nullable, so every pre-existing row (whose
    original render was never kept) becomes original_image_path = NULL and
    falls back to preprocessed_image_path for preview - a plain ALTER TABLE
    ADD COLUMN, no rename/recreate/copy dance needed."""
    conn.execute("ALTER TABLE main_marking_preprocessed_pages ADD COLUMN original_image_path TEXT")
    conn.commit()


def _subject_profile_regions_needs_generic_label_migration(conn: sqlite3.Connection) -> bool:
    """Detect a pre-existing subject_profile_regions table whose stored
    CHECK constraint still mentions an old Kertas-specific region type
    (Stage 12E-fix) - i.e. it hasn't been rebuilt with the new generic
    vocabulary yet. Checked independently of the question_area migration
    below so it correctly detects old databases regardless of whether
    that migration has already run."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'subject_profile_regions'"
    ).fetchone()
    if row is None:
        return False
    sql = row[0] or ""
    return "'k1_bubble_area'" in sql


def _migrate_subject_profile_regions_rename_generic_labels(conn: sqlite3.Connection) -> None:
    """Rebuild subject_profile_regions with the new generic region_type
    CHECK constraint (Stage 12E-fix), renaming every existing row's
    old Kertas-specific region_type value to its new generic equivalent
    (SUBJECT_PROFILE_REGION_TYPE_MIGRATION_MAP) in the same pass - values
    not in that map (already-generic labels) pass through unchanged.
    Existing Subject Profiles are never deleted, only relabelled. Runs
    BEFORE _migrate_subject_profile_regions_add_question_area below so an
    old database with old region_type values is remapped while the
    table's CHECK constraint still allows them - inserting into a table
    already rebuilt with the new-only CHECK constraint would otherwise
    reject the old values outright. Same rename/recreate/copy technique as
    _migrate_subject_profile_regions_add_question_area."""
    case_expression = "CASE region_type " + " ".join(
        f"WHEN '{old}' THEN '{new}'" for old, new in SUBJECT_PROFILE_REGION_TYPE_MIGRATION_MAP.items()
    ) + " ELSE region_type END"
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")
    try:
        conn.execute("ALTER TABLE subject_profile_regions RENAME TO subject_profile_regions_generic_label_migration_old")
        conn.execute(CREATE_SUBJECT_PROFILE_REGIONS_TABLE)
        conn.execute(
            f"""
            INSERT INTO subject_profile_regions
                (region_id, profile_id, source, label, region_type, page_number, x, y, width, height,
                 shape_type, polygon_points_json, rotation_angle, order_index, notes, created_at)
            SELECT region_id, profile_id, source, label, {case_expression}, page_number, x, y, width, height,
                   shape_type, polygon_points_json, rotation_angle, order_index, notes, created_at
            FROM subject_profile_regions_generic_label_migration_old
            """
        )
        conn.execute("DROP TABLE subject_profile_regions_generic_label_migration_old")
        conn.commit()
    finally:
        conn.execute("PRAGMA legacy_alter_table = OFF")
        conn.execute("PRAGMA foreign_keys = ON")


def _subject_profile_region_groups_needs_generic_label_migration(conn: sqlite3.Connection) -> bool:
    """Detect a pre-existing subject_profile_region_groups table whose
    stored CHECK constraint still mentions an old Kertas-specific region
    type (Stage 12E-fix)."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'subject_profile_region_groups'"
    ).fetchone()
    if row is None:
        return False
    sql = row[0] or ""
    return "'k1_bubble_area'" in sql


def _migrate_subject_profile_region_groups_rename_generic_labels(conn: sqlite3.Connection) -> None:
    """Rebuild subject_profile_region_groups with the new generic
    region_type CHECK constraint (Stage 12E-fix), renaming every existing
    row's region_type the same way as _migrate_subject_profile_regions_
    rename_generic_labels - see that function for the full rationale."""
    case_expression = "CASE region_type " + " ".join(
        f"WHEN '{old}' THEN '{new}'" for old, new in SUBJECT_PROFILE_REGION_TYPE_MIGRATION_MAP.items()
    ) + " ELSE region_type END"
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")
    try:
        conn.execute(
            "ALTER TABLE subject_profile_region_groups RENAME TO subject_profile_region_groups_generic_label_migration_old"
        )
        conn.execute(CREATE_SUBJECT_PROFILE_REGION_GROUPS_TABLE)
        conn.execute(
            f"""
            INSERT INTO subject_profile_region_groups (group_id, profile_id, label, region_type, notes, created_at)
            SELECT group_id, profile_id, label, {case_expression}, notes, created_at
            FROM subject_profile_region_groups_generic_label_migration_old
            """
        )
        conn.execute("DROP TABLE subject_profile_region_groups_generic_label_migration_old")
        conn.commit()
    finally:
        conn.execute("PRAGMA legacy_alter_table = OFF")
        conn.execute("PRAGMA foreign_keys = ON")


def _subject_profile_regions_needs_question_area_migration(conn: sqlite3.Connection) -> bool:
    """Detect a pre-existing subject_profile_regions table whose region_type
    CHECK constraint predates the 'question_area' region type (Stage 11W)."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'subject_profile_regions'"
    ).fetchone()
    if row is None:
        return False
    sql = row[0] or ""
    return "'question_area'" not in sql


def _migrate_subject_profile_regions_add_question_area(conn: sqlite3.Connection) -> None:
    """Rebuild subject_profile_regions so its region_type CHECK constraint
    also allows 'question_area'. SQLite cannot alter a CHECK constraint in
    place, so the table is renamed, recreated with the new definition, and
    its rows are copied back across, preserving region_id so
    subject_profile_region_group_members (FK'd to region_id) stays valid -
    exactly the same technique already used for
    _migrate_revision_materials_allow_both_paper_type (Stage 10F)."""
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")
    try:
        conn.execute("ALTER TABLE subject_profile_regions RENAME TO subject_profile_regions_question_area_migration_old")
        conn.execute(CREATE_SUBJECT_PROFILE_REGIONS_TABLE)
        conn.execute(
            """
            INSERT INTO subject_profile_regions
                (region_id, profile_id, source, label, region_type, page_number, x, y, width, height,
                 shape_type, polygon_points_json, rotation_angle, order_index, notes, created_at)
            SELECT region_id, profile_id, source, label, region_type, page_number, x, y, width, height,
                   shape_type, polygon_points_json, rotation_angle, order_index, notes, created_at
            FROM subject_profile_regions_question_area_migration_old
            """
        )
        conn.execute("DROP TABLE subject_profile_regions_question_area_migration_old")
        conn.commit()
    finally:
        conn.execute("PRAGMA legacy_alter_table = OFF")
        conn.execute("PRAGMA foreign_keys = ON")


def _subject_profile_region_groups_needs_question_area_migration(conn: sqlite3.Connection) -> bool:
    """Detect a pre-existing subject_profile_region_groups table whose
    region_type CHECK constraint predates 'question_area' (Stage 11W)."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'subject_profile_region_groups'"
    ).fetchone()
    if row is None:
        return False
    sql = row[0] or ""
    return "'question_area'" not in sql


def _migrate_subject_profile_region_groups_add_question_area(conn: sqlite3.Connection) -> None:
    """Rebuild subject_profile_region_groups so its region_type CHECK
    constraint also allows 'question_area', preserving group_id so
    subject_profile_region_group_members (FK'd to group_id) stays valid -
    same technique as _migrate_subject_profile_regions_add_question_area."""
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")
    try:
        conn.execute(
            "ALTER TABLE subject_profile_region_groups RENAME TO subject_profile_region_groups_question_area_migration_old"
        )
        conn.execute(CREATE_SUBJECT_PROFILE_REGION_GROUPS_TABLE)
        conn.execute(
            """
            INSERT INTO subject_profile_region_groups (group_id, profile_id, label, region_type, notes, created_at)
            SELECT group_id, profile_id, label, region_type, notes, created_at
            FROM subject_profile_region_groups_question_area_migration_old
            """
        )
        conn.execute("DROP TABLE subject_profile_region_groups_question_area_migration_old")
        conn.commit()
    finally:
        conn.execute("PRAGMA legacy_alter_table = OFF")
        conn.execute("PRAGMA foreign_keys = ON")


def _ai_training_datasets_needs_dataset_folder_path_migration(conn: sqlite3.Connection) -> bool:
    """Detect a pre-existing ai_training_datasets table built before Stage
    12E's dataset_folder_path column (added for Answer Region Detection's
    folder-of-files YOLO dataset exports, which csv_path/jsonl_path can't
    represent)."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'ai_training_datasets'"
    ).fetchone()
    if row is None:
        return False
    columns = {info[1] for info in conn.execute("PRAGMA table_info(ai_training_datasets)").fetchall()}
    return "dataset_folder_path" not in columns


def _migrate_ai_training_datasets_add_dataset_folder_path(conn: sqlite3.Connection) -> None:
    """Add dataset_folder_path to a pre-existing ai_training_datasets table
    (Stage 12E). Nullable, so every pre-existing (Kertas 2 CSV/JSONL) row
    becomes dataset_folder_path = NULL - a plain ALTER TABLE ADD COLUMN, no
    rename/recreate/copy dance needed."""
    conn.execute("ALTER TABLE ai_training_datasets ADD COLUMN dataset_folder_path TEXT")
    conn.commit()


def _main_marking_marked_answers_needs_review_columns_migration(conn: sqlite3.Connection) -> bool:
    """Detect a pre-existing main_marking_marked_answers table built before
    Stage 11R's teacher review/override columns."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'main_marking_marked_answers'"
    ).fetchone()
    if row is None:
        return False
    columns = {info[1] for info in conn.execute("PRAGMA table_info(main_marking_marked_answers)").fetchall()}
    return "review_status" not in columns


def _migrate_main_marking_marked_answers_add_review_columns(conn: sqlite3.Connection) -> None:
    """Add review_status/teacher_score/teacher_feedback/reviewed_at to a
    pre-existing main_marking_marked_answers table (Stage 11R). Every
    existing row (previously un-reviewed) becomes review_status =
    'pending_review' with teacher_score/teacher_feedback/reviewed_at = NULL
    automatically - plain ALTER TABLE ADD COLUMN operations, no rename/
    recreate/copy dance needed, and no existing machine-marking data
    (score/feedback/status/needs_review) is touched."""
    conn.execute(
        "ALTER TABLE main_marking_marked_answers ADD COLUMN review_status TEXT NOT NULL DEFAULT 'pending_review' "
        "CHECK (review_status IN ('pending_review', 'reviewed'))"
    )
    conn.execute("ALTER TABLE main_marking_marked_answers ADD COLUMN teacher_score REAL")
    conn.execute("ALTER TABLE main_marking_marked_answers ADD COLUMN teacher_feedback TEXT")
    conn.execute("ALTER TABLE main_marking_marked_answers ADD COLUMN reviewed_at TEXT")
    conn.commit()


def _main_marking_ocr_results_needs_blocks_json_migration(conn: sqlite3.Connection) -> bool:
    """Detect a pre-existing main_marking_ocr_results table built before
    Stage 11P's OCR block/coordinate storage (ocr_blocks_json)."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'main_marking_ocr_results'"
    ).fetchone()
    if row is None:
        return False
    columns = {info[1] for info in conn.execute("PRAGMA table_info(main_marking_ocr_results)").fetchall()}
    return "ocr_blocks_json" not in columns


def _migrate_main_marking_ocr_results_add_blocks_json(conn: sqlite3.Connection) -> None:
    """Add ocr_blocks_json to a pre-existing main_marking_ocr_results table
    (Stage 11P). It is nullable, so every existing OCR result row (from
    before block data was stored) becomes ocr_blocks_json = NULL
    automatically - a plain ALTER TABLE ADD COLUMN, no rename/recreate/copy
    dance needed, and no existing OCR text/confidence/status data is
    touched. Answer extraction treats a NULL value as "block coordinates
    unavailable" and falls back to page-level text instead of crashing."""
    conn.execute("ALTER TABLE main_marking_ocr_results ADD COLUMN ocr_blocks_json TEXT")
    conn.commit()


def _kertas2_ai_feedback_jobs_needs_audit_columns_migration(conn: sqlite3.Connection) -> bool:
    """Detect a pre-existing kertas2_ai_feedback_jobs table built before the
    Stage 8C audit columns existed."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'kertas2_ai_feedback_jobs'"
    ).fetchone()
    if row is None:
        return False
    columns = {info[1] for info in conn.execute("PRAGMA table_info(kertas2_ai_feedback_jobs)").fetchall()}
    return "provider_backend" not in columns


def _migrate_kertas2_ai_feedback_jobs_add_audit_columns(conn: sqlite3.Connection) -> None:
    """Add the Stage 8C provider/diagnostic audit columns to a pre-existing
    kertas2_ai_feedback_jobs table. All columns are nullable, so a plain
    ALTER TABLE ADD COLUMN is enough."""
    conn.execute("ALTER TABLE kertas2_ai_feedback_jobs ADD COLUMN provider_backend TEXT")
    conn.execute("ALTER TABLE kertas2_ai_feedback_jobs ADD COLUMN provider_model_path TEXT")
    conn.execute("ALTER TABLE kertas2_ai_feedback_jobs ADD COLUMN provider_status TEXT")
    conn.execute("ALTER TABLE kertas2_ai_feedback_jobs ADD COLUMN diagnostic_message TEXT")
    conn.commit()


def _kertas2_ai_feedback_items_needs_audit_columns_migration(conn: sqlite3.Connection) -> bool:
    """Detect a pre-existing kertas2_ai_feedback_items table built before the
    Stage 8C audit columns existed."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'kertas2_ai_feedback_items'"
    ).fetchone()
    if row is None:
        return False
    columns = {info[1] for info in conn.execute("PRAGMA table_info(kertas2_ai_feedback_items)").fetchall()}
    return "prompt_snapshot" not in columns


def _migrate_kertas2_ai_feedback_items_add_audit_columns(conn: sqlite3.Connection) -> None:
    """Add the Stage 8C prompt/output audit columns to a pre-existing
    kertas2_ai_feedback_items table. All columns are nullable, so a plain
    ALTER TABLE ADD COLUMN is enough."""
    conn.execute("ALTER TABLE kertas2_ai_feedback_items ADD COLUMN prompt_snapshot TEXT")
    conn.execute("ALTER TABLE kertas2_ai_feedback_items ADD COLUMN raw_provider_output TEXT")
    conn.execute("ALTER TABLE kertas2_ai_feedback_items ADD COLUMN parser_error TEXT")
    conn.execute("ALTER TABLE kertas2_ai_feedback_items ADD COLUMN audit_status TEXT")
    conn.commit()


def _local_ai_settings_needs_teacher_id_migration(conn: sqlite3.Connection) -> bool:
    """Detect a pre-existing local_ai_settings table built before Stage 10B's
    per-teacher teacher_id column existed."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'local_ai_settings'"
    ).fetchone()
    if row is None:
        return False
    columns = {info[1] for info in conn.execute("PRAGMA table_info(local_ai_settings)").fetchall()}
    return "teacher_id" not in columns


def _migrate_local_ai_settings_add_teacher_id(conn: sqlite3.Connection) -> None:
    """Add the Stage 10B teacher_id column to a pre-existing local_ai_settings
    table. It is nullable, so a plain ALTER TABLE ADD COLUMN is enough - any
    existing row is preserved untouched (teacher_id NULL) as the legacy/
    global fallback row."""
    conn.execute("ALTER TABLE local_ai_settings ADD COLUMN teacher_id INTEGER")
    conn.commit()


def _users_table_needs_formal_code_columns_migration(conn: sqlite3.Connection) -> bool:
    """Detect a pre-existing users table built before Stage 10C's
    teacher_code/student_code/visible_temp_password columns existed."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'users'"
    ).fetchone()
    if row is None:
        return False
    columns = {info[1] for info in conn.execute("PRAGMA table_info(users)").fetchall()}
    return "teacher_code" not in columns


def _migrate_users_table_add_formal_code_columns(conn: sqlite3.Connection) -> None:
    """Add the Stage 10C formal-code and visible-temp-password columns to a
    pre-existing users table. All are nullable, so a plain ALTER TABLE ADD
    COLUMN is enough - existing rows are preserved with these columns NULL
    until backfilled (see app/services/user_service.py,
    app/services/student_service.py)."""
    conn.execute("ALTER TABLE users ADD COLUMN teacher_code TEXT")
    conn.execute("ALTER TABLE users ADD COLUMN student_code TEXT")
    conn.execute("ALTER TABLE users ADD COLUMN visible_temp_password TEXT")
    conn.commit()


def _users_table_needs_is_active_column_migration(conn: sqlite3.Connection) -> bool:
    """Detect a pre-existing users table built before Stage 10D's is_active
    column existed."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'users'"
    ).fetchone()
    if row is None:
        return False
    columns = {info[1] for info in conn.execute("PRAGMA table_info(users)").fetchall()}
    return "is_active" not in columns


def _migrate_users_table_add_is_active_column(conn: sqlite3.Connection) -> None:
    """Add the Stage 10D is_active column to a pre-existing users table.
    SQLite applies the DEFAULT to every existing row, so every current
    account (any role) becomes active immediately - no one is locked out
    by this migration."""
    conn.execute("ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
    conn.commit()


def _subject_profile_marked_answers_needs_review_columns_migration(conn: sqlite3.Connection) -> bool:
    """Detect a pre-existing subject_profile_marked_answers table built
    before Stage 12G-1A's teacher-review columns."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'subject_profile_marked_answers'"
    ).fetchone()
    if row is None:
        return False
    columns = {info[1] for info in conn.execute("PRAGMA table_info(subject_profile_marked_answers)").fetchall()}
    return "corrected_answer_text" not in columns


def _migrate_subject_profile_marked_answers_add_review_columns(conn: sqlite3.Connection) -> None:
    """Stage 12G-1A: add teacher-review + raw-extraction-provenance columns
    to a pre-existing subject_profile_marked_answers table. Every existing
    row keeps its original machine-generated columns untouched and gets NULL
    teacher/raw values (i.e. "not yet reviewed, no correction") automatically -
    plain ALTER TABLE ADD COLUMN operations, no rename/recreate/copy dance,
    and no historical marking data is lost."""
    for column_sql in (
        "raw_ocr_text TEXT",
        "extraction_confidence REAL",
        "extraction_method TEXT",
        "extraction_timestamp TEXT",
        "corrected_answer_text TEXT",
        "teacher_score REAL",
        "teacher_status TEXT",
        "teacher_feedback TEXT",
        "private_comment TEXT",
        "reviewed_by INTEGER",
        "reviewed_at TEXT",
        "updated_at TEXT",
    ):
        conn.execute(f"ALTER TABLE subject_profile_marked_answers ADD COLUMN {column_sql}")
    conn.commit()


def _main_marking_answer_files_needs_attempt_mode_migration(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'main_marking_answer_files'"
    ).fetchone()
    if row is None:
        return False
    columns = {info[1] for info in conn.execute("PRAGMA table_info(main_marking_answer_files)").fetchall()}
    return "attempt_mode" not in columns


def _migrate_main_marking_answer_files_add_attempt_mode(conn: sqlite3.Connection) -> None:
    """Stage 12G-1B: add the binary attempt mode. EVERY existing attempt
    migrates to 'standard' (it was answered on the question paper), so historic
    marking behaviour is unchanged - plain ALTER TABLE ADD COLUMN with a
    default, no data loss."""
    conn.execute(
        "ALTER TABLE main_marking_answer_files ADD COLUMN attempt_mode TEXT NOT NULL DEFAULT 'standard'")
    conn.commit()


def _separate_paper_mappings_needs_line_boxes_migration(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'separate_paper_mappings'"
    ).fetchone()
    if row is None:
        return False
    columns = {info[1] for info in conn.execute("PRAGMA table_info(separate_paper_mappings)").fetchall()}
    return "ocr_line_boxes_json" not in columns


def _migrate_separate_paper_mappings_add_line_boxes(conn: sqlite3.Connection) -> None:
    """Stage 12G-1B follow-up: store the OCR engine's per-line geometry for a
    mapped crop so each parsed K1 answer can be anchored on the line it was
    actually read from. Additive and nullable - existing mappings keep working
    with the approximate block-row anchor."""
    conn.execute("ALTER TABLE separate_paper_mappings ADD COLUMN ocr_line_boxes_json TEXT")
    conn.commit()


def _separate_paper_parsed_answers_needs_anchor_source_migration(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'separate_paper_parsed_answers'"
    ).fetchone()
    if row is None:
        return False
    columns = {info[1] for info in conn.execute("PRAGMA table_info(separate_paper_parsed_answers)").fetchall()}
    return "anchor_source" not in columns


def _migrate_separate_paper_parsed_answers_add_anchor_source(conn: sqlite3.Connection) -> None:
    """Stage 12G-1B follow-up: label where each parsed answer's anchor came
    from. Existing rows were derived from the parser's line/character estimate,
    so they migrate to 'approximate_block_row' - the honest value."""
    conn.execute(
        "ALTER TABLE separate_paper_parsed_answers ADD COLUMN anchor_source TEXT NOT NULL "
        "DEFAULT 'approximate_block_row'")
    conn.commit()


def _subject_profile_region_overrides_needs_phase2c_columns_migration(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'subject_profile_attempt_region_overrides'"
    ).fetchone()
    if row is None:
        return False
    columns = {info[1] for info in conn.execute("PRAGMA table_info(subject_profile_attempt_region_overrides)").fetchall()}
    return "rerun_ocr_text" not in columns


def _migrate_subject_profile_region_overrides_add_phase2c_columns(conn: sqlite3.Connection) -> None:
    """Stage 12G-1A Phase 2C: add original-geometry snapshot, rerun-OCR lineage
    (kept separate from original OCR + teacher text), and crop checksums to a
    pre-existing region-override table. Existing rows get NULL - plain ALTER
    TABLE ADD COLUMN, no data loss."""
    for column_sql in (
        "original_x REAL", "original_y REAL", "original_width REAL", "original_height REAL",
        "rerun_ocr_text TEXT", "rerun_ocr_confidence REAL", "rerun_ocr_at TEXT",
        "crop_checksum TEXT", "original_crop_checksum TEXT",
    ):
        conn.execute(f"ALTER TABLE subject_profile_attempt_region_overrides ADD COLUMN {column_sql}")
    conn.commit()


def _subject_profile_marked_answers_needs_stale_column_migration(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'subject_profile_marked_answers'"
    ).fetchone()
    if row is None:
        return False
    columns = {info[1] for info in conn.execute("PRAGMA table_info(subject_profile_marked_answers)").fetchall()}
    return "extraction_review_stale" not in columns


def _migrate_subject_profile_marked_answers_add_stale_column(conn: sqlite3.Connection) -> None:
    """Stage 12G-1A Phase 2C: add the extraction-review-stale flag. Existing
    rows get 0 (not stale) - plain ALTER TABLE ADD COLUMN, no data loss."""
    conn.execute("ALTER TABLE subject_profile_marked_answers ADD COLUMN extraction_review_stale INTEGER NOT NULL DEFAULT 0")
    conn.commit()


def _subject_profile_marked_answers_needs_part3_columns_migration(conn: sqlite3.Connection) -> bool:
    """Detect a subject_profile_marked_answers table built before the Stage
    12G-1A Part 3 selected-question-number columns."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'subject_profile_marked_answers'"
    ).fetchone()
    if row is None:
        return False
    columns = {info[1] for info in conn.execute("PRAGMA table_info(subject_profile_marked_answers)").fetchall()}
    return "extracted_selected_question_number" not in columns


def _migrate_subject_profile_marked_answers_add_part3_columns(conn: sqlite3.Connection) -> None:
    """Stage 12G-1A Part 3 integrity: add the selected-question-number columns
    (machine-extracted + teacher-corrected) to a pre-existing marked-answers
    table. Every existing row gets NULL for both - plain ALTER TABLE ADD
    COLUMN, no data loss, no denominator or overlay impact."""
    conn.execute("ALTER TABLE subject_profile_marked_answers ADD COLUMN extracted_selected_question_number TEXT")
    conn.execute("ALTER TABLE subject_profile_marked_answers ADD COLUMN teacher_selected_question_number TEXT")
    conn.commit()


def _subject_profile_overlays_needs_review_columns_migration(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'subject_profile_overlays'"
    ).fetchone()
    if row is None:
        return False
    columns = {info[1] for info in conn.execute("PRAGMA table_info(subject_profile_overlays)").fetchall()}
    return "is_hidden" not in columns


def _migrate_subject_profile_overlays_add_review_columns(conn: sqlite3.Connection) -> None:
    """Stage 12G-1A: add teacher overlay-editing columns (is_hidden /
    is_teacher_adjusted / original_x / original_y) to a pre-existing
    subject_profile_overlays table. Every existing overlay becomes visible
    (is_hidden=0), not-yet-teacher-adjusted, with NULL original position -
    plain ALTER TABLE ADD COLUMN, no data loss."""
    conn.execute("ALTER TABLE subject_profile_overlays ADD COLUMN is_hidden INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE subject_profile_overlays ADD COLUMN is_teacher_adjusted INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE subject_profile_overlays ADD COLUMN original_x REAL")
    conn.execute("ALTER TABLE subject_profile_overlays ADD COLUMN original_y REAL")
    conn.commit()


def _subject_profile_attempt_reviews_needs_final_output_columns_migration(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'subject_profile_attempt_reviews'"
    ).fetchone()
    if row is None:
        return False
    columns = {info[1] for info in conn.execute("PRAGMA table_info(subject_profile_attempt_reviews)").fetchall()}
    return "final_marked_pdf_path" not in columns


def _migrate_subject_profile_attempt_reviews_add_final_output_columns(conn: sqlite3.Connection) -> None:
    """Stage 12G-1A Phase 2B: record the published final reviewed-output paths
    on the attempt review. Every existing review row gets NULL (no final
    output published yet) - plain ALTER TABLE ADD COLUMN, no data loss."""
    conn.execute("ALTER TABLE subject_profile_attempt_reviews ADD COLUMN final_marked_pdf_path TEXT")
    conn.execute("ALTER TABLE subject_profile_attempt_reviews ADD COLUMN final_comments_path TEXT")
    conn.execute("ALTER TABLE subject_profile_attempt_reviews ADD COLUMN final_output_generated_at TEXT")
    conn.commit()


def _subject_profile_attempt_reviews_needs_final_version_migration(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'subject_profile_attempt_reviews'"
    ).fetchone()
    if row is None:
        return False
    columns = {info[1] for info in conn.execute("PRAGMA table_info(subject_profile_attempt_reviews)").fetchall()}
    return "final_marked_pdf_path" in columns and "final_output_version" not in columns


def _migrate_subject_profile_attempt_reviews_add_final_version_column(conn: sqlite3.Connection) -> None:
    """Phase 2B consistency fix: add the active output-version id. Existing
    finalised rows get NULL (their paths still resolve; the next re-finalise
    publishes a versioned pair) - plain ALTER TABLE ADD COLUMN, no data loss."""
    conn.execute("ALTER TABLE subject_profile_attempt_reviews ADD COLUMN final_output_version TEXT")
    conn.commit()


def _subject_profile_overlays_needs_symbol_override_migration(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'subject_profile_overlays'"
    ).fetchone()
    if row is None:
        return False
    columns = {info[1] for info in conn.execute("PRAGMA table_info(subject_profile_overlays)").fetchall()}
    return "teacher_symbol_override" not in columns


def _migrate_subject_profile_overlays_add_symbol_override_columns(conn: sqlite3.Connection) -> None:
    """Stage 12G-1A Phase 2B: add the logical-target link + explicit teacher
    symbol-override columns to a pre-existing subject_profile_overlays table.
    Every existing overlay migrates safely to Auto mode (use_auto_symbol=1,
    no override) with NULL target_label - plain ALTER TABLE ADD COLUMN, no
    data loss, generated `kind` untouched."""
    conn.execute("ALTER TABLE subject_profile_overlays ADD COLUMN target_label TEXT")
    conn.execute("ALTER TABLE subject_profile_overlays ADD COLUMN teacher_symbol_override TEXT")
    conn.execute("ALTER TABLE subject_profile_overlays ADD COLUMN use_auto_symbol INTEGER NOT NULL DEFAULT 1")
    conn.commit()


def _seed_feedback_categories(conn: sqlite3.Connection) -> None:
    """Insert the Stage 12G-1A initial feedback-category list once. Idempotent
    via INSERT OR IGNORE on the unique category_key, so re-running init_schema
    never duplicates or resurrects a category an admin later deactivated."""
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for order, (key, label) in enumerate(FEEDBACK_CATEGORY_SEED):
        conn.execute(
            "INSERT OR IGNORE INTO subject_profile_feedback_categories "
            "(category_key, label, display_order, is_active, created_at) VALUES (?, ?, ?, 1, ?)",
            (key, label, order, now),
        )
    conn.commit()


def init_schema(conn: sqlite3.Connection) -> None:
    """Create all tables if they do not already exist, migrating legacy data."""
    if _users_table_needs_role_migration(conn):
        _migrate_legacy_admin_role(conn)

    if _users_table_needs_formal_code_columns_migration(conn):
        _migrate_users_table_add_formal_code_columns(conn)

    if _users_table_needs_is_active_column_migration(conn):
        _migrate_users_table_add_is_active_column(conn)

    if _classes_table_needs_teacher_nullable_migration(conn):
        _migrate_classes_teacher_nullable(conn)

    if _revision_materials_needs_both_paper_type_migration(conn):
        _migrate_revision_materials_allow_both_paper_type(conn)

    if _overlays_needs_feedback_kind_migration(conn):
        _migrate_overlays_allow_feedback_kind(conn)

    if _overlays_needs_font_size_migration(conn):
        _migrate_overlays_add_font_size(conn)

    if _template_regions_needs_region_type_migration(conn):
        _migrate_template_regions_add_region_type(conn)

    if _template_regions_needs_shape_type_migration(conn):
        _migrate_template_regions_add_shape_type(conn)

    if _template_regions_needs_rotation_angle_migration(conn):
        _migrate_template_regions_add_rotation_angle(conn)

    if _kertas2_ai_feedback_jobs_needs_audit_columns_migration(conn):
        _migrate_kertas2_ai_feedback_jobs_add_audit_columns(conn)

    if _kertas2_ai_feedback_items_needs_audit_columns_migration(conn):
        _migrate_kertas2_ai_feedback_items_add_audit_columns(conn)

    if _local_ai_settings_needs_teacher_id_migration(conn):
        _migrate_local_ai_settings_add_teacher_id(conn)

    if _main_marking_sessions_needs_template_id_migration(conn):
        _migrate_main_marking_sessions_add_template_id(conn)

    if _main_marking_ocr_results_needs_blocks_json_migration(conn):
        _migrate_main_marking_ocr_results_add_blocks_json(conn)

    if _main_marking_marked_answers_needs_review_columns_migration(conn):
        _migrate_main_marking_marked_answers_add_review_columns(conn)

    if _main_marking_sessions_needs_subject_profile_id_migration(conn):
        _migrate_main_marking_sessions_add_subject_profile_id(conn)

    if _main_marking_preprocessed_pages_needs_original_image_path_migration(conn):
        _migrate_main_marking_preprocessed_pages_add_original_image_path(conn)

    # Stage 12E-fix: must run BEFORE the question_area migrations below -
    # both rebuild these tables using the SAME (current) CREATE_SUBJECT_
    # PROFILE_REGIONS_TABLE/CREATE_SUBJECT_PROFILE_REGION_GROUPS_TABLE
    # constants, which already only allow the new generic vocabulary. If
    # the question_area migration ran first on a genuinely old database,
    # it would try to copy old Kertas-specific region_type values into a
    # table whose CHECK constraint no longer allows them.
    if _subject_profile_regions_needs_generic_label_migration(conn):
        _migrate_subject_profile_regions_rename_generic_labels(conn)

    if _subject_profile_region_groups_needs_generic_label_migration(conn):
        _migrate_subject_profile_region_groups_rename_generic_labels(conn)

    if _subject_profile_regions_needs_question_area_migration(conn):
        _migrate_subject_profile_regions_add_question_area(conn)

    if _subject_profile_region_groups_needs_question_area_migration(conn):
        _migrate_subject_profile_region_groups_add_question_area(conn)

    if _ai_training_datasets_needs_dataset_folder_path_migration(conn):
        _migrate_ai_training_datasets_add_dataset_folder_path(conn)

    if _subject_profile_marked_answers_needs_review_columns_migration(conn):
        _migrate_subject_profile_marked_answers_add_review_columns(conn)

    if _subject_profile_marked_answers_needs_part3_columns_migration(conn):
        _migrate_subject_profile_marked_answers_add_part3_columns(conn)

    if _subject_profile_marked_answers_needs_stale_column_migration(conn):
        _migrate_subject_profile_marked_answers_add_stale_column(conn)

    if _subject_profile_region_overrides_needs_phase2c_columns_migration(conn):
        _migrate_subject_profile_region_overrides_add_phase2c_columns(conn)

    if _main_marking_answer_files_needs_attempt_mode_migration(conn):
        _migrate_main_marking_answer_files_add_attempt_mode(conn)

    if _separate_paper_mappings_needs_line_boxes_migration(conn):
        _migrate_separate_paper_mappings_add_line_boxes(conn)

    if _separate_paper_parsed_answers_needs_anchor_source_migration(conn):
        _migrate_separate_paper_parsed_answers_add_anchor_source(conn)

    if _subject_profile_overlays_needs_review_columns_migration(conn):
        _migrate_subject_profile_overlays_add_review_columns(conn)

    if _subject_profile_overlays_needs_symbol_override_migration(conn):
        _migrate_subject_profile_overlays_add_symbol_override_columns(conn)

    if _subject_profile_attempt_reviews_needs_final_output_columns_migration(conn):
        _migrate_subject_profile_attempt_reviews_add_final_output_columns(conn)

    if _subject_profile_attempt_reviews_needs_final_version_migration(conn):
        _migrate_subject_profile_attempt_reviews_add_final_version_column(conn)

    conn.execute(CREATE_USERS_TABLE)
    conn.execute(CREATE_USERS_TEACHER_CODE_INDEX)
    conn.execute(CREATE_USERS_STUDENT_CODE_INDEX)
    conn.execute(CREATE_CLASSES_TABLE)
    conn.execute(CREATE_CLASS_TRANSFER_REQUESTS_TABLE)
    conn.execute(CREATE_CLASS_STUDENTS_TABLE)
    conn.execute(CREATE_STUDENT_TRANSFER_REQUESTS_TABLE)
    conn.execute(CREATE_REVISION_MATERIALS_TABLE)
    conn.execute(CREATE_REVISION_MATERIAL_CLASSES_TABLE)
    conn.execute(CREATE_STUDENT_EXTERNAL_REVISIONS_TABLE)
    conn.execute(CREATE_REVISION_ATTEMPTS_TABLE)
    conn.execute(CREATE_ANSWER_TEMPLATES_TABLE)
    conn.execute(CREATE_TEMPLATE_REGIONS_TABLE)
    conn.execute(CREATE_TEMPLATE_REGION_GROUPS_TABLE)
    conn.execute(CREATE_TEMPLATE_REGION_GROUP_MEMBERS_TABLE)
    conn.execute(CREATE_MARKING_SETUPS_TABLE)
    conn.execute(CREATE_MARKING_QUESTIONS_TABLE)
    conn.execute(CREATE_DOCUMENT_PREPROCESSING_JOBS_TABLE)
    conn.execute(CREATE_DOCUMENT_PREPROCESSING_PAGES_TABLE)
    conn.execute(CREATE_OCR_JOBS_TABLE)
    conn.execute(CREATE_OCR_PAGE_RESULTS_TABLE)
    conn.execute(CREATE_OCR_TEXT_BLOCKS_TABLE)
    conn.execute(CREATE_EXTRACTION_JOBS_TABLE)
    conn.execute(CREATE_EXTRACTED_REGION_RESULTS_TABLE)
    conn.execute(CREATE_EXTRACTED_REGION_BLOCKS_TABLE)
    conn.execute(CREATE_ANSWER_EXTRACTION_JOBS_TABLE)
    conn.execute(CREATE_EXTRACTED_ATTEMPT_ANSWERS_TABLE)
    conn.execute(CREATE_MARKING_JOBS_TABLE)
    conn.execute(CREATE_MARKING_QUESTION_RESULTS_TABLE)
    conn.execute(CREATE_MARKING_REVIEWS_TABLE)
    conn.execute(CREATE_MARKING_REVIEW_ITEMS_TABLE)
    conn.execute(CREATE_KERTAS2_AI_FEEDBACK_JOBS_TABLE)
    conn.execute(CREATE_KERTAS2_AI_FEEDBACK_ITEMS_TABLE)
    conn.execute(CREATE_KERTAS2_FEEDBACK_REVIEWS_TABLE)
    conn.execute(CREATE_KERTAS2_FEEDBACK_REVIEW_ITEMS_TABLE)
    conn.execute(CREATE_MAIN_MARKING_SESSIONS_TABLE)
    conn.execute(CREATE_MAIN_MARKING_ANSWER_FILES_TABLE)
    conn.execute(CREATE_MAIN_MARKING_PROCESSING_RUNS_TABLE)
    conn.execute(CREATE_MAIN_MARKING_PREPROCESSED_PAGES_TABLE)
    conn.execute(CREATE_MAIN_MARKING_OCR_RUNS_TABLE)
    conn.execute(CREATE_MAIN_MARKING_OCR_RESULTS_TABLE)
    conn.execute(CREATE_MAIN_MARKING_ANSWER_EXTRACTION_RUNS_TABLE)
    conn.execute(CREATE_MAIN_MARKING_EXTRACTED_ANSWERS_TABLE)
    conn.execute(CREATE_MAIN_MARKING_MARKING_RUNS_TABLE)
    conn.execute(CREATE_MAIN_MARKING_MARKED_ANSWERS_TABLE)
    conn.execute(CREATE_MAIN_MARKING_FINAL_RESULTS_TABLE)
    conn.execute(CREATE_MAIN_MARKING_FINAL_RESULT_ITEMS_TABLE)
    conn.execute(CREATE_SUBJECT_PROFILES_TABLE)
    conn.execute(CREATE_SUBJECT_PROFILE_REGIONS_TABLE)
    conn.execute(CREATE_SUBJECT_PROFILE_REGION_GROUPS_TABLE)
    conn.execute(CREATE_SUBJECT_PROFILE_REGION_GROUP_MEMBERS_TABLE)
    conn.execute(CREATE_SUBJECT_PROFILE_ANSWER_KEY_ENTRIES_TABLE)
    conn.execute(CREATE_SUBJECT_PROFILE_EXTRACTED_ANSWERS_TABLE)
    conn.execute(CREATE_SUBJECT_PROFILE_MARKED_ANSWERS_TABLE)
    conn.execute(CREATE_SUBJECT_PROFILE_OVERLAYS_TABLE)
    conn.execute(CREATE_SUBJECT_PROFILE_ATTEMPT_REVIEWS_TABLE)
    conn.execute(CREATE_SUBJECT_PROFILE_FEEDBACK_CATEGORIES_TABLE)
    conn.execute(CREATE_SUBJECT_PROFILE_ANSWER_FEEDBACK_CATEGORIES_TABLE)
    conn.execute(CREATE_SUBJECT_PROFILE_ATTEMPT_REGION_OVERRIDES_TABLE)
    conn.execute(CREATE_SUBJECT_PROFILE_REVIEW_AUDIT_TABLE)
    # Stage 12G-1B: separate answer paper pages / target states / mappings / parsed answers
    conn.execute(CREATE_SEPARATE_PAPER_PAGES_TABLE)
    conn.execute(CREATE_SEPARATE_PAPER_TARGET_STATES_TABLE)
    conn.execute(CREATE_SEPARATE_PAPER_MAPPINGS_TABLE)
    conn.execute(CREATE_SEPARATE_PAPER_PARSED_ANSWERS_TABLE)
    conn.execute(CREATE_TEACHER_MARKING_SETTINGS_TABLE)
    conn.execute(CREATE_LOCAL_AI_SETTINGS_TABLE)
    conn.execute(CREATE_LOCAL_AI_SETTINGS_TEACHER_ID_INDEX)
    _migrate_local_ai_settings_add_runtime_columns(conn)
    _migrate_attempts_add_marked_link_columns(conn)
    conn.execute(CREATE_AI_MODEL_VERSIONS_TABLE)
    conn.execute(CREATE_AI_MODEL_VERSIONS_ACTIVE_INDEX)
    conn.execute(CREATE_AI_TRAINING_JOBS_TABLE)
    conn.execute(CREATE_AI_TRAINING_DATASETS_TABLE)
    conn.execute(CREATE_AI_ADMIN_AUDIT_TABLE)
    conn.execute(CREATE_CORE_AI2_PROPOSALS_TABLE)
    conn.execute(CREATE_CORE_AI2_PROPOSALS_PROFILE_INDEX)
    conn.execute(CREATE_CORE_AI2_PROPOSALS_ATTEMPT_INDEX)
    conn.execute(CREATE_CORE_AI1_DRAFTS_TABLE)
    conn.execute(CREATE_CORE_AI1_DRAFTS_ANSWER_INDEX)
    conn.execute(CREATE_CORE_AI1_DRAFTS_FILE_INDEX)
    conn.execute(CREATE_CORE_AI1_DRAFT_HISTORY_TABLE)
    conn.execute(CREATE_CORE_AI1_DRAFT_HISTORY_INDEX)
    _migrate_core_ai1_drafts_add_stale_columns(conn)
    conn.execute(CREATE_AI_ADMIN_AUDIT_ACTION_INDEX)
    conn.commit()

    _seed_feedback_categories(conn)
