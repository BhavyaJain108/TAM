"""Ingestion pipeline components."""

from .excel_reader import read_rectangle, list_sheets, detect_data_range
from .column_profiler import profile_columns
from .athena_loader import create_athena_table
from .card_builder import build_card
from .workbook_ingester import ingest_workbook

__all__ = [
    # Excel reading
    "read_rectangle",
    "list_sheets",
    "detect_data_range",
    # Column profiling
    "profile_columns",
    # Storage
    "create_athena_table",
    # Single-sheet ingestion
    "build_card",
    # Multi-sheet workbook ingestion
    "ingest_workbook",
]
