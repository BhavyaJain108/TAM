"""
Workbook ingestion - handles Excel files with multiple sheets.

Ingests an entire Excel workbook, creating:
- One WorkbookCard for the file
- One TableCard per sheet (or per detected table)
- Cross-sheet relationship detection
"""

import os
import uuid
from typing import Optional
from pathlib import Path

import pandas as pd

from models.workbook_card import WorkbookCard, SheetInfo, CrossSheetRelationship
from models.table_card import TableCard
from models.serialization import table_card_to_json
from config.settings import Settings, get_settings
from .excel_reader import list_sheets, read_rectangle, detect_data_range
from .column_profiler import profile_columns
from .athena_loader import create_athena_table, save_card
from llm.bedrock_client import LLMClient, get_llm_client
from llm.description_generator import generate_description, extract_initial_tags
from llm.entity_extractor import extract_entities
from llm.pattern_generator import generate_query_patterns


class WorkbookIngestionError(Exception):
    """Raised when workbook ingestion fails."""
    pass


def generate_workbook_id(prefix: str = "wb") -> str:
    """Generate a unique workbook ID."""
    short_uuid = uuid.uuid4().hex[:8]
    return f"{prefix}_{short_uuid}"


def generate_table_id_for_sheet(workbook_id: str, sheet_name: str) -> str:
    """Generate a table ID for a sheet within a workbook."""
    # Clean sheet name for use in ID
    clean_name = "".join(c if c.isalnum() else "_" for c in sheet_name)
    clean_name = clean_name.lower()[:20]  # Limit length
    return f"{workbook_id}_{clean_name}"


def should_skip_sheet(sheet_name: str, skip_patterns: Optional[list[str]] = None) -> tuple[bool, str]:
    """
    Determine if a sheet should be skipped based on naming patterns.

    Returns (should_skip, reason)
    """
    skip_patterns = skip_patterns or []

    # Default patterns to skip
    default_skip = [
        "template",
        "instructions",
        "readme",
        "cover",
        "toc",
        "table of contents",
        "index",
        "blank",
        "empty",
        "notes",
        "scratch",
    ]

    all_patterns = [p.lower() for p in skip_patterns + default_skip]
    sheet_lower = sheet_name.lower()

    for pattern in all_patterns:
        if pattern in sheet_lower:
            return True, f"Sheet name matches skip pattern: '{pattern}'"

    return False, ""


def detect_cross_sheet_relationships(
    workbook_card: WorkbookCard,
    table_cards: dict[str, TableCard],
) -> list[CrossSheetRelationship]:
    """
    Detect potential relationships between sheets based on column names and values.

    Looks for:
    - Columns with matching names across sheets
    - Columns whose values appear in other sheets (FK relationships)
    """
    relationships = []

    sheets_with_cards = [s for s in workbook_card.sheets if s.was_ingested]

    for i, source_sheet in enumerate(sheets_with_cards):
        source_card = table_cards.get(source_sheet.table_id)
        if not source_card:
            continue

        for target_sheet in sheets_with_cards[i + 1:]:
            target_card = table_cards.get(target_sheet.table_id)
            if not target_card:
                continue

            # Check for matching column names
            source_cols = {c.name.lower(): c for c in source_card.columns}
            target_cols = {c.name.lower(): c for c in target_card.columns}

            for col_name_lower, source_col in source_cols.items():
                if col_name_lower in target_cols:
                    target_col = target_cols[col_name_lower]

                    # Columns with same name - likely a relationship
                    # Check if it looks like an ID/key column
                    is_key_column = any(
                        k in col_name_lower
                        for k in ["id", "key", "code", "name", "number"]
                    )

                    if is_key_column or (source_col.unique_values == target_col.unique_values):
                        relationships.append(
                            CrossSheetRelationship(
                                source_sheet=source_sheet.sheet_name,
                                source_table_id=source_sheet.table_id,
                                source_column=source_col.name,
                                target_sheet=target_sheet.sheet_name,
                                target_table_id=target_sheet.table_id,
                                target_column=target_col.name,
                                match_quality="exact" if source_col.unique_values == target_col.unique_values else "inferred",
                                confidence=0.8 if is_key_column else 0.5,
                                notes=f"Matching column name: {source_col.name}",
                            )
                        )

            # Check cross-references identified by entity extraction
            for xref in source_card.cross_references:
                for target_col in target_card.columns:
                    if xref.likely_entity_type.lower() in target_col.name.lower():
                        relationships.append(
                            CrossSheetRelationship(
                                source_sheet=source_sheet.sheet_name,
                                source_table_id=source_sheet.table_id,
                                source_column=xref.column,
                                target_sheet=target_sheet.sheet_name,
                                target_table_id=target_sheet.table_id,
                                target_column=target_col.name,
                                match_quality=xref.match_quality,
                                confidence=0.6,
                                notes=f"Cross-reference: {xref.notes}",
                            )
                        )

    return relationships


def ingest_workbook(
    file_path: str,
    workbook_id: Optional[str] = None,
    sheet_configs: Optional[dict[str, dict]] = None,
    skip_sheets: Optional[list[str]] = None,
    settings: Optional[Settings] = None,
    llm_client: Optional[LLMClient] = None,
    skip_llm: bool = False,
    skip_storage: bool = False,
    auto_detect_ranges: bool = True,
) -> tuple[WorkbookCard, dict[str, TableCard]]:
    """
    Ingest an entire Excel workbook with multiple sheets.

    Args:
        file_path: Path to the Excel file
        workbook_id: Optional ID (auto-generated if not provided)
        sheet_configs: Optional dict of sheet_name -> config dict with:
            - start_cell: Start of data range (default: auto-detect)
            - end_cell: End of data range (default: auto-detect)
            - skip: If True, skip this sheet
        skip_sheets: List of sheet names to skip
        settings: Optional Settings object
        llm_client: Optional LLM client
        skip_llm: Skip all LLM calls
        skip_storage: Skip storage (for testing)
        auto_detect_ranges: Auto-detect data ranges if not specified

    Returns:
        Tuple of (WorkbookCard, dict of table_id -> TableCard)
    """
    if settings is None:
        settings = get_settings()

    if workbook_id is None:
        workbook_id = generate_workbook_id(settings.table_id_prefix.replace("tbl", "wb"))

    if settings.storage_mode == "local":
        settings.ensure_local_dirs()

    if not skip_llm and llm_client is None:
        llm_client = get_llm_client(settings)

    source_file = os.path.basename(file_path)
    sheet_configs = sheet_configs or {}
    skip_sheets = skip_sheets or []

    print(f"{'='*60}")
    print(f"WORKBOOK INGESTION: {source_file}")
    print(f"Workbook ID: {workbook_id}")
    print(f"{'='*60}")

    # Get all sheet names
    all_sheets = list_sheets(file_path)
    print(f"\nFound {len(all_sheets)} sheets: {all_sheets}")

    # Create workbook card
    workbook_card = WorkbookCard.create(
        workbook_id=workbook_id,
        source_file=source_file,
        sheet_names=all_sheets,
    )

    table_cards: dict[str, TableCard] = {}

    # Process each sheet
    for sheet_idx, sheet_name in enumerate(all_sheets, 1):
        print(f"\n[Sheet {sheet_idx}/{len(all_sheets)}] {sheet_name}")
        print("-" * 40)

        # Check if should skip
        if sheet_name in skip_sheets:
            print(f"  SKIPPED (user excluded)")
            workbook_card.add_sheet(SheetInfo(
                sheet_name=sheet_name,
                table_id="",
                data_range="",
                row_count=0,
                column_count=0,
                was_ingested=False,
                skip_reason="User excluded",
            ))
            continue

        sheet_config = sheet_configs.get(sheet_name, {})
        if sheet_config.get("skip", False):
            print(f"  SKIPPED (config)")
            workbook_card.add_sheet(SheetInfo(
                sheet_name=sheet_name,
                table_id="",
                data_range="",
                row_count=0,
                column_count=0,
                was_ingested=False,
                skip_reason="Skipped in config",
            ))
            continue

        # Check naming patterns
        should_skip, skip_reason = should_skip_sheet(sheet_name)
        if should_skip:
            print(f"  SKIPPED ({skip_reason})")
            workbook_card.add_sheet(SheetInfo(
                sheet_name=sheet_name,
                table_id="",
                data_range="",
                row_count=0,
                column_count=0,
                was_ingested=False,
                skip_reason=skip_reason,
            ))
            continue

        # Determine data range
        start_cell = sheet_config.get("start_cell", "A1")
        end_cell = sheet_config.get("end_cell")

        if end_cell is None and auto_detect_ranges:
            try:
                _, end_cell = detect_data_range(file_path, sheet_name, start_cell)
                print(f"  Auto-detected range: {start_cell}:{end_cell}")
            except Exception as e:
                print(f"  SKIPPED (range detection failed: {e})")
                workbook_card.add_sheet(SheetInfo(
                    sheet_name=sheet_name,
                    table_id="",
                    data_range="",
                    row_count=0,
                    column_count=0,
                    was_ingested=False,
                    skip_reason=f"Range detection failed: {e}",
                ))
                continue

        if end_cell is None:
            end_cell = "Z1000"  # Default fallback

        data_range = f"{start_cell}:{end_cell}"

        # Read the data
        try:
            df, header_metadata = read_rectangle(file_path, sheet_name, start_cell, end_cell)
        except Exception as e:
            print(f"  SKIPPED (read failed: {e})")
            workbook_card.add_sheet(SheetInfo(
                sheet_name=sheet_name,
                table_id="",
                data_range=data_range,
                row_count=0,
                column_count=0,
                was_ingested=False,
                skip_reason=f"Read failed: {e}",
            ))
            continue

        if len(df) == 0:
            print(f"  SKIPPED (no data rows)")
            workbook_card.add_sheet(SheetInfo(
                sheet_name=sheet_name,
                table_id="",
                data_range=data_range,
                row_count=0,
                column_count=0,
                was_ingested=False,
                skip_reason="No data rows",
            ))
            continue

        print(f"  Read {len(df)} rows, {len(df.columns)} columns")

        # Generate table ID for this sheet
        table_id = generate_table_id_for_sheet(workbook_id, sheet_name)

        # Profile columns
        profiles = profile_columns(df, settings, header_metadata)

        # Store data
        parquet_path = None
        if not skip_storage:
            try:
                parquet_path, _ = create_athena_table(df, table_id, profiles, settings)
                print(f"  Stored: {parquet_path}")
            except Exception as e:
                print(f"  Storage warning: {e}")

        # LLM generation
        description = f"Sheet '{sheet_name}' from {source_file}"
        purpose = "Data analysis"
        caveats = "No automated analysis"
        entities = []
        cross_refs = []
        query_patterns = []
        tags_initial = []

        if not skip_llm:
            try:
                print(f"  Generating description...")
                description, purpose, caveats = generate_description(
                    df, profiles, source_file, sheet_name, data_range,
                    client=llm_client, settings=settings
                )
            except Exception as e:
                print(f"  Description failed: {e}")

            try:
                print(f"  Extracting entities...")
                entities, cross_refs = extract_entities(
                    df, profiles, description, purpose, caveats,
                    client=llm_client, settings=settings
                )
            except Exception as e:
                print(f"  Entity extraction failed: {e}")

            try:
                print(f"  Generating query patterns...")
                query_patterns = generate_query_patterns(
                    table_id, profiles, description, purpose, caveats, entities,
                    client=llm_client, settings=settings
                )
            except Exception as e:
                print(f"  Pattern generation failed: {e}")

            tags_initial = extract_initial_tags(description, purpose)

        # Create TableCard
        from datetime import date
        table_card = TableCard(
            table_id=table_id,
            source_file=source_file,
            source_sheet=sheet_name,
            source_range=data_range,
            ingestion_date=date.today().isoformat(),
            row_count=len(df),
            column_count=len(df.columns),
            columns=profiles,
            description=description,
            purpose=purpose,
            caveats=caveats,
            entities=entities,
            cross_references=cross_refs,
            query_patterns=query_patterns,
            tags_initial=tags_initial,
            s3_parquet_path=parquet_path,
        )

        # Save card
        if not skip_storage:
            try:
                card_json = table_card_to_json(table_card)
                card_path = save_card(card_json, table_id, settings)
                table_card.s3_card_path = card_path
                print(f"  Card saved: {card_path}")
            except Exception as e:
                print(f"  Card save warning: {e}")

        table_cards[table_id] = table_card

        # Add sheet info to workbook
        primary_entity = None
        if entities:
            primary = next((e for e in entities if e.is_primary), None)
            if primary:
                primary_entity = primary.name

        workbook_card.add_sheet(SheetInfo(
            sheet_name=sheet_name,
            table_id=table_id,
            data_range=data_range,
            row_count=len(df),
            column_count=len(df.columns),
            was_ingested=True,
            primary_entity=primary_entity,
            description_summary=description[:100] if description else None,
        ))

        print(f"  ✓ Ingested as {table_id}")

    # Detect cross-sheet relationships
    print(f"\n{'='*60}")
    print("DETECTING CROSS-SHEET RELATIONSHIPS")
    print(f"{'='*60}")

    relationships = detect_cross_sheet_relationships(workbook_card, table_cards)
    for rel in relationships:
        workbook_card.add_relationship(rel)
        print(f"  {rel.source_sheet}.{rel.source_column} -> {rel.target_sheet}.{rel.target_column} ({rel.match_quality})")

    if not relationships:
        print("  No relationships detected")

    # Save workbook card
    if not skip_storage:
        import json
        from dataclasses import asdict

        if settings.storage_mode == "local":
            workbook_dir = Path(settings.local_metadata_dir) / workbook_id
            workbook_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = workbook_dir / "workbook_card.json"
            # Set path BEFORE serializing
            workbook_card.manifest_path = str(manifest_path)
            workbook_json = json.dumps(asdict(workbook_card), indent=2, default=str)
            with open(manifest_path, "w") as f:
                f.write(workbook_json)
            print(f"\nWorkbook card saved: {manifest_path}")

    # Summary
    print(f"\n{'='*60}")
    print("INGESTION COMPLETE")
    print(f"{'='*60}")
    print(f"Workbook ID: {workbook_id}")
    print(f"Sheets ingested: {workbook_card.sheets_ingested}/{workbook_card.total_sheets}")
    print(f"Sheets skipped: {workbook_card.sheets_skipped}")
    print(f"Relationships found: {len(workbook_card.cross_sheet_relationships)}")
    print(f"Table IDs: {workbook_card.get_table_ids()}")

    return workbook_card, table_cards
