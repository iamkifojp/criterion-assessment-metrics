"""
Art Criterion Metrics — backend data-processing engine.

This package contains the core (UI-free) logic for tracking, aggregating, and
reporting IB MYP Visual Arts grades across a multi-term school year.

Modules
-------
models        : dataclasses for the domain (students, records, scores).
docx_parser   : extracts unit metadata from an MYP unit-plan .docx.
ingestion     : reads grading CSVs into the student gradebook.
criterion_d   : manual-entry schema for Criterion D reflection scores.
aggregation   : recency-weighted scoring + context-filtering pipeline.
persistence   : JSON database I/O and per-class term-summary files.
"""

from .models import (
    MYP_CRITERIA,
    Criterion,
    UnitPlan,
    CriterionScore,
    ExamResult,
    Student,
    Assignment,
    Gradebook,
)
from .docx_parser import UnitPlanParser, parse_unit_plan
from .ingestion import (
    IngestionPipeline,
    detect_criterion_in_header,
    map_criterion_columns,
    parse_classroom_roster,
    parse_iso_date,
    parse_date_from_filename,
    student_id_from_email,
    clean_assignment_name,
    is_exam_csv,
    exam_question_columns,
)
from .collation import gojuon_sort_key
from .criterion_d import CriterionDInitializer
from .persistence import (
    DEFAULT_DB_FILENAME,
    serialize_gradebook,
    deserialize_gradebook,
    unit_plan_to_dict,
    unit_plan_from_dict,
    save_database,
    load_database,
    term_summary_path,
    save_term_summary,
    load_term_summaries,
)
from .aggregation import (
    recency_weighted_score,
    aggregate_student_criterion,
    CALCULATION_METHODS,
    DEFAULT_CALCULATION_METHOD,
    METHOD_LABELS,
    MYP_GRADE_BOUNDS,
    SCHOOL_GRADE_BOUNDS,
    myp_grade,
    school_grade,
    calculate_final_grade,
    method_score,
    RecencyWeightConfig,
    AggregationResult,
    Evidence,
    select_evidence,
    TrendInfo,
    trend_for_series,
    format_trend_sentence,
)

__all__ = [
    "MYP_CRITERIA",
    "Criterion",
    "UnitPlan",
    "CriterionScore",
    "ExamResult",
    "Student",
    "Assignment",
    "Gradebook",
    "is_exam_csv",
    "exam_question_columns",
    "UnitPlanParser",
    "parse_unit_plan",
    "IngestionPipeline",
    "detect_criterion_in_header",
    "map_criterion_columns",
    "parse_classroom_roster",
    "parse_iso_date",
    "parse_date_from_filename",
    "student_id_from_email",
    "clean_assignment_name",
    "gojuon_sort_key",
    "CriterionDInitializer",
    "recency_weighted_score",
    "aggregate_student_criterion",
    "CALCULATION_METHODS",
    "DEFAULT_CALCULATION_METHOD",
    "METHOD_LABELS",
    "MYP_GRADE_BOUNDS",
    "SCHOOL_GRADE_BOUNDS",
    "myp_grade",
    "school_grade",
    "calculate_final_grade",
    "method_score",
    "RecencyWeightConfig",
    "AggregationResult",
    "Evidence",
    "select_evidence",
    "TrendInfo",
    "trend_for_series",
    "format_trend_sentence",
    "DEFAULT_DB_FILENAME",
    "serialize_gradebook",
    "deserialize_gradebook",
    "unit_plan_to_dict",
    "unit_plan_from_dict",
    "save_database",
    "load_database",
    "term_summary_path",
    "save_term_summary",
    "load_term_summaries",
]
