#!/usr/bin/env python3
"""
Excel-to-Queryable-Data Ingestion Pipeline

CLI tool for ingesting Excel tables and generating metadata cards.

Usage:
    python main.py ingest <excel_file> <sheet_name> <start_cell> <end_cell> [--table-id TABLE_ID]
    python main.py ingest-workbook <excel_file> [--workbook-id WORKBOOK_ID] [--skip-sheets SHEET1,SHEET2]
    python main.py list-sheets <excel_file>
    python main.py detect-range <excel_file> <sheet_name> [--start-cell A1]

Examples:
    python main.py ingest data.xlsx "Sheet1" B2 F45
    python main.py ingest data.xlsx "Sales Data" A1 Z100 --table-id sales_q1
    python main.py ingest-workbook quarterly_report.xlsx
    python main.py ingest-workbook data.xlsx --skip-sheets "Cover,Notes" --skip-llm
    python main.py list-sheets data.xlsx
    python main.py detect-range data.xlsx "Sheet1" --start-cell B2
"""

import argparse
import json
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.settings import get_settings, Settings
from ingestion.excel_reader import read_rectangle, list_sheets, detect_data_range
from ingestion.column_profiler import profile_columns, summarize_data_quality
from ingestion.card_builder import build_card
from ingestion.workbook_ingester import ingest_workbook
from models.serialization import table_card_to_json


def cmd_ingest(args):
    """Ingest an Excel file and create a TableCard."""
    settings = get_settings()

    print(f"Ingesting: {args.excel_file}")
    print(f"  Sheet: {args.sheet_name}")
    print(f"  Range: {args.start_cell}:{args.end_cell}")
    print(f"  Mode: {settings.storage_mode}")
    print()

    card = build_card(
        file_path=args.excel_file,
        sheet_name=args.sheet_name,
        start_cell=args.start_cell,
        end_cell=args.end_cell,
        table_id=args.table_id,
        settings=settings,
        skip_llm=args.skip_llm,
        skip_storage=args.skip_storage,
    )

    if args.output:
        with open(args.output, "w") as f:
            f.write(table_card_to_json(card))
        print(f"\nCard JSON saved to: {args.output}")

    return card


def cmd_ingest_workbook(args):
    """Ingest all sheets from an Excel workbook."""
    settings = get_settings()

    # Parse skip sheets from comma-separated string
    skip_sheets = []
    if args.skip_sheets:
        skip_sheets = [s.strip() for s in args.skip_sheets.split(",")]

    workbook_card, table_cards = ingest_workbook(
        file_path=args.excel_file,
        workbook_id=args.workbook_id,
        skip_sheets=skip_sheets,
        settings=settings,
        skip_llm=args.skip_llm,
        skip_storage=args.skip_storage,
        auto_detect_ranges=not args.no_auto_detect,
    )

    # Output summary
    print(f"\n{'='*60}")
    print("WORKBOOK INGESTION RESULTS")
    print(f"{'='*60}")
    print(f"Workbook ID: {workbook_card.workbook_id}")
    print(f"Total sheets: {workbook_card.total_sheets}")
    print(f"Ingested: {workbook_card.sheets_ingested}")
    print(f"Skipped: {workbook_card.sheets_skipped}")
    print(f"Cross-sheet relationships: {len(workbook_card.cross_sheet_relationships)}")

    if workbook_card.manifest_path:
        print(f"\nWorkbook card saved to: {workbook_card.manifest_path}")

    print(f"\nTable IDs created:")
    for table_id in workbook_card.get_table_ids():
        card = table_cards.get(table_id)
        if card:
            print(f"  - {table_id}: {card.row_count} rows, {card.column_count} cols")

    return workbook_card, table_cards


def cmd_list_sheets(args):
    """List sheets in an Excel file."""
    sheets = list_sheets(args.excel_file)
    print(f"Sheets in {args.excel_file}:")
    for i, sheet in enumerate(sheets, 1):
        print(f"  {i}. {sheet}")


def cmd_detect_range(args):
    """Detect the data range in a sheet."""
    start, end = detect_data_range(
        args.excel_file,
        args.sheet_name,
        args.start_cell,
    )
    print(f"Detected data range: {start}:{end}")


def cmd_profile(args):
    """Profile an Excel range without full ingestion."""
    print(f"Profiling: {args.excel_file} / {args.sheet_name} / {args.start_cell}:{args.end_cell}")

    df, header_metadata = read_rectangle(
        args.excel_file,
        args.sheet_name,
        args.start_cell,
        args.end_cell,
    )

    profiles = profile_columns(df, header_metadata=header_metadata)
    summary = summarize_data_quality(profiles)

    print(f"\n{'='*60}")
    print(f"DATA PROFILE")
    print(f"{'='*60}")
    print(f"Rows: {len(df)}")
    print(f"Columns: {len(df.columns)}")
    print(f"\n{'='*60}")
    print(f"DATA QUALITY SUMMARY")
    print(f"{'='*60}")
    print(f"Columns with warnings: {summary['columns_with_warnings']}/{summary['total_columns']}")
    print(f"Columns with nulls: {summary['columns_with_nulls']}/{summary['total_columns']}")
    print(f"Total warnings: {summary['total_warnings']}")

    if summary['mixed_type_columns']:
        print(f"Mixed-type columns: {summary['mixed_type_columns']}")

    if summary['warning_types']:
        print(f"\nWarning breakdown:")
        for warning_type, count in summary['warning_types'].items():
            print(f"  - {warning_type}: {count}")

    print(f"\n{'='*60}")
    print(f"COLUMN DETAILS")
    print(f"{'='*60}")

    for p in profiles:
        print(f"\n{p.name}")
        print(f"  Type: {p.data_type}")
        print(f"  Unique: {p.unique_values}, Nulls: {p.null_count}")
        if p.all_values:
            print(f"  Values: {p.all_values}")
        else:
            print(f"  Sample: {p.sample_values}")
        if p.min_value is not None:
            print(f"  Stats: min={p.min_value}, max={p.max_value}, mean={p.mean_value:.2f}")
        if p.format_warnings:
            print(f"  ⚠️  Warnings:")
            for w in p.format_warnings:
                print(f"      - {w}")


def cmd_view_card(args):
    """View a saved TableCard."""
    from ingestion.athena_loader import load_card
    from models.serialization import table_card_from_json

    card_json = load_card(args.table_id)
    if card_json is None:
        print(f"Card not found: {args.table_id}")
        sys.exit(1)

    if args.raw:
        print(card_json)
    else:
        card = table_card_from_json(card_json)
        print(f"Table: {card.table_id}")
        print(f"Source: {card.source_file} / {card.source_sheet} / {card.source_range}")
        print(f"Ingested: {card.ingestion_date}")
        print(f"Size: {card.row_count} rows x {card.column_count} columns")
        print(f"\nDescription: {card.description}")
        print(f"\nPurpose: {card.purpose}")
        print(f"\nCaveats: {card.caveats}")
        print(f"\nTags: {card.tags_initial}")

        if card.entities:
            print(f"\nEntities:")
            for e in card.entities:
                primary = "(PRIMARY)" if e.is_primary else ""
                print(f"  - {e.name} {primary}: {e.description}")

        if card.query_patterns:
            print(f"\nExample Queries:")
            for q in card.query_patterns:
                print(f"\n  {q.natural_language}")
                print(f"  {q.sql}")
                if q.warnings:
                    print(f"  ⚠️  {q.warnings}")


def main():
    parser = argparse.ArgumentParser(
        description="Excel-to-Queryable-Data Ingestion Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # ingest command (single sheet)
    ingest_parser = subparsers.add_parser("ingest", help="Ingest a single sheet from Excel file")
    ingest_parser.add_argument("excel_file", help="Path to Excel file")
    ingest_parser.add_argument("sheet_name", help="Sheet name")
    ingest_parser.add_argument("start_cell", help="Start cell (e.g., B2)")
    ingest_parser.add_argument("end_cell", help="End cell (e.g., F45)")
    ingest_parser.add_argument("--table-id", dest="table_id", help="Custom table ID")
    ingest_parser.add_argument("--output", "-o", help="Output JSON file path")
    ingest_parser.add_argument("--skip-llm", action="store_true", help="Skip LLM calls")
    ingest_parser.add_argument("--skip-storage", action="store_true", help="Skip storage")

    # ingest-workbook command (all sheets)
    wb_parser = subparsers.add_parser("ingest-workbook", help="Ingest all sheets from Excel workbook")
    wb_parser.add_argument("excel_file", help="Path to Excel file")
    wb_parser.add_argument("--workbook-id", dest="workbook_id", help="Custom workbook ID")
    wb_parser.add_argument("--skip-sheets", dest="skip_sheets", help="Comma-separated list of sheets to skip")
    wb_parser.add_argument("--skip-llm", action="store_true", help="Skip LLM calls")
    wb_parser.add_argument("--skip-storage", action="store_true", help="Skip storage")
    wb_parser.add_argument("--no-auto-detect", action="store_true", help="Disable auto-detection of data ranges")

    # list-sheets command
    sheets_parser = subparsers.add_parser("list-sheets", help="List sheets in Excel file")
    sheets_parser.add_argument("excel_file", help="Path to Excel file")

    # detect-range command
    detect_parser = subparsers.add_parser("detect-range", help="Detect data range")
    detect_parser.add_argument("excel_file", help="Path to Excel file")
    detect_parser.add_argument("sheet_name", help="Sheet name")
    detect_parser.add_argument("--start-cell", default="A1", help="Start cell for detection")

    # profile command
    profile_parser = subparsers.add_parser("profile", help="Profile data without full ingestion")
    profile_parser.add_argument("excel_file", help="Path to Excel file")
    profile_parser.add_argument("sheet_name", help="Sheet name")
    profile_parser.add_argument("start_cell", help="Start cell")
    profile_parser.add_argument("end_cell", help="End cell")

    # view command
    view_parser = subparsers.add_parser("view", help="View a saved TableCard")
    view_parser.add_argument("table_id", help="Table ID to view")
    view_parser.add_argument("--raw", action="store_true", help="Output raw JSON")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    try:
        if args.command == "ingest":
            cmd_ingest(args)
        elif args.command == "ingest-workbook":
            cmd_ingest_workbook(args)
        elif args.command == "list-sheets":
            cmd_list_sheets(args)
        elif args.command == "detect-range":
            cmd_detect_range(args)
        elif args.command == "profile":
            cmd_profile(args)
        elif args.command == "view":
            cmd_view_card(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
