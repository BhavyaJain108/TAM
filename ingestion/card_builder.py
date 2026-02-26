"""
Card builder - orchestrates the full ingestion pipeline.

Combines all steps: Excel reading, column profiling, storage, and LLM generation
to produce a complete TableCard.
"""

from datetime import date
from typing import Optional
import uuid

import pandas as pd

from models.table_card import TableCard
from models.serialization import table_card_to_json
from config.settings import Settings, get_settings
from .excel_reader import read_rectangle
from .column_profiler import profile_columns
from .athena_loader import create_athena_table, save_card
from llm.bedrock_client import LLMClient, get_llm_client
from llm.description_generator import generate_description, extract_initial_tags
from llm.entity_extractor import extract_entities
from llm.pattern_generator import generate_query_patterns


class CardBuildError(Exception):
    """Raised when card building fails."""
    pass


def generate_table_id(prefix: str = "tbl") -> str:
    """Generate a unique table ID."""
    short_uuid = uuid.uuid4().hex[:8]
    return f"{prefix}_{short_uuid}"


def build_card(
    file_path: str,
    sheet_name: str,
    start_cell: str,
    end_cell: str,
    table_id: Optional[str] = None,
    settings: Optional[Settings] = None,
    llm_client: Optional[LLMClient] = None,
    skip_llm: bool = False,
    skip_storage: bool = False,
) -> TableCard:
    """
    Build a complete TableCard from an Excel file.

    This is the main orchestration function that:
    1. Reads the Excel rectangle
    2. Profiles all columns
    3. Stores data (Parquet + Athena table or local)
    4. Generates LLM descriptions
    5. Extracts entities
    6. Generates query patterns
    7. Assembles and saves the TableCard

    Args:
        file_path: Path to the Excel file
        sheet_name: Name of the sheet to read
        start_cell: Top-left cell of the data range (e.g., 'B2')
        end_cell: Bottom-right cell of the data range (e.g., 'F45')
        table_id: Optional table identifier (auto-generated if not provided)
        settings: Optional Settings object
        llm_client: Optional LLM client (for testing with mocks)
        skip_llm: If True, skip all LLM calls (faster, but incomplete card)
        skip_storage: If True, skip Parquet/Athena storage (for testing)

    Returns:
        Complete TableCard

    Raises:
        CardBuildError: If any critical step fails
    """
    if settings is None:
        settings = get_settings()

    if table_id is None:
        table_id = generate_table_id(settings.table_id_prefix)

    # Ensure local directories exist
    if settings.storage_mode == "local":
        settings.ensure_local_dirs()

    # Get LLM client if needed
    if not skip_llm and llm_client is None:
        llm_client = get_llm_client(settings)

    # Extract source file name
    import os
    source_file = os.path.basename(file_path)

    print(f"[1/7] Reading Excel: {source_file} / {sheet_name} / {start_cell}:{end_cell}")

    # Step 1: Read the Excel data
    try:
        df, header_metadata = read_rectangle(file_path, sheet_name, start_cell, end_cell)
    except Exception as e:
        raise CardBuildError(f"Failed to read Excel file: {e}")

    if len(df) == 0:
        raise CardBuildError("No data rows found in the specified range")

    print(f"    Read {len(df)} rows, {len(df.columns)} columns")
    if header_metadata:
        print(f"    Found header metadata for {len(header_metadata)} columns")

    # Step 2: Profile columns
    print(f"[2/7] Profiling columns...")
    try:
        profiles = profile_columns(df, settings, header_metadata)
    except Exception as e:
        raise CardBuildError(f"Failed to profile columns: {e}")

    # Step 3: Store data (Parquet + Athena)
    parquet_path = None
    card_path = None

    if not skip_storage:
        print(f"[3/7] Storing data...")
        try:
            parquet_path, _ = create_athena_table(df, table_id, profiles, settings)
            print(f"    Stored at: {parquet_path}")
        except Exception as e:
            print(f"    Warning: Storage failed: {e}")
            # Continue without storage - card can still be useful
    else:
        print(f"[3/7] Skipping storage (skip_storage=True)")

    # Steps 4-6: LLM generation
    if skip_llm:
        print(f"[4/7] Skipping LLM description (skip_llm=True)")
        description = "Description not generated (LLM skipped)"
        purpose = "Purpose not generated (LLM skipped)"
        caveats = "Caveats not analyzed (LLM skipped)"

        print(f"[5/7] Skipping entity extraction (skip_llm=True)")
        entities = []
        cross_references = []

        print(f"[6/7] Skipping query pattern generation (skip_llm=True)")
        query_patterns = []

        tags_initial = []
    else:
        # Step 4: Generate description
        print(f"[4/7] Generating description with LLM...")
        try:
            description, purpose, caveats = generate_description(
                df, profiles, source_file, sheet_name, f"{start_cell}:{end_cell}",
                client=llm_client, settings=settings
            )
        except Exception as e:
            print(f"    Warning: Description generation failed: {e}")
            description = f"Description generation failed: {e}"
            purpose = "Unknown"
            caveats = "Unable to analyze"

        # Step 5: Extract entities
        print(f"[5/7] Extracting entities with LLM...")
        try:
            entities, cross_references = extract_entities(
                df, profiles, description, purpose, caveats,
                client=llm_client, settings=settings
            )
        except Exception as e:
            print(f"    Warning: Entity extraction failed: {e}")
            entities = []
            cross_references = []

        # Step 6: Generate query patterns
        print(f"[6/7] Generating query patterns with LLM...")
        try:
            query_patterns = generate_query_patterns(
                table_id, profiles, description, purpose, caveats, entities,
                client=llm_client, settings=settings
            )
        except Exception as e:
            print(f"    Warning: Query pattern generation failed: {e}")
            query_patterns = []

        # Extract tags
        tags_initial = extract_initial_tags(description, purpose)

    # Step 7: Assemble the TableCard
    print(f"[7/7] Assembling TableCard...")

    card = TableCard(
        table_id=table_id,
        source_file=source_file,
        source_sheet=sheet_name,
        source_range=f"{start_cell}:{end_cell}",
        ingestion_date=date.today().isoformat(),
        row_count=len(df),
        column_count=len(df.columns),
        columns=profiles,
        description=description,
        purpose=purpose,
        caveats=caveats,
        entities=entities,
        cross_references=cross_references,
        query_patterns=query_patterns,
        tags_initial=tags_initial,
        s3_parquet_path=parquet_path,
    )

    # Save the card
    if not skip_storage:
        try:
            card_json = table_card_to_json(card)
            card_path = save_card(card_json, table_id, settings)
            card.s3_card_path = card_path
            print(f"    Card saved to: {card_path}")
        except Exception as e:
            print(f"    Warning: Failed to save card: {e}")

    print(f"\n✓ Card built successfully: {table_id}")
    print(f"  - {len(profiles)} columns profiled")
    print(f"  - {len(entities)} entities identified")
    print(f"  - {len(query_patterns)} query patterns generated")

    return card


def build_card_minimal(
    df: pd.DataFrame,
    table_id: str,
    source_file: str = "unknown.xlsx",
    source_sheet: str = "Sheet1",
    source_range: str = "A1:Z100",
    settings: Optional[Settings] = None,
) -> TableCard:
    """
    Build a minimal TableCard from an existing DataFrame.

    Useful for testing or when you already have the data loaded.
    Skips LLM and storage steps.

    Args:
        df: pandas DataFrame
        table_id: Table identifier
        source_file: Source file name (metadata only)
        source_sheet: Source sheet name (metadata only)
        source_range: Source range (metadata only)
        settings: Optional Settings object

    Returns:
        TableCard with column profiles but no LLM-generated fields
    """
    if settings is None:
        settings = get_settings()

    profiles = profile_columns(df, settings)

    return TableCard(
        table_id=table_id,
        source_file=source_file,
        source_sheet=source_sheet,
        source_range=source_range,
        ingestion_date=date.today().isoformat(),
        row_count=len(df),
        column_count=len(df.columns),
        columns=profiles,
        description="Minimal card - LLM description not generated",
        purpose="General data analysis",
        caveats="No automated quality analysis performed",
        entities=[],
        cross_references=[],
        query_patterns=[],
        tags_initial=[],
    )
