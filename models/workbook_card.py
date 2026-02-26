"""
WorkbookCard - metadata for an entire Excel workbook with multiple sheets.

A WorkbookCard is the parent container that groups together all TableCards
from a single Excel file. It tracks:
- Which sheets were ingested
- Cross-sheet relationships
- Overall workbook metadata
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import date


@dataclass
class SheetInfo:
    """Information about a single sheet in a workbook."""

    sheet_name: str
    """Original sheet name from Excel."""

    table_id: str
    """The table_id assigned to this sheet's TableCard."""

    data_range: str
    """Cell range that was extracted, e.g. 'A1:Z100'."""

    row_count: int
    """Number of data rows (excluding header)."""

    column_count: int
    """Number of columns."""

    was_ingested: bool = True
    """Whether this sheet was successfully ingested."""

    skip_reason: Optional[str] = None
    """If not ingested, why (e.g., 'empty', 'no data detected', 'user excluded')."""

    primary_entity: Optional[str] = None
    """The primary entity identified in this sheet (from TableCard)."""

    description_summary: Optional[str] = None
    """Brief description (first 100 chars of full description)."""


@dataclass
class CrossSheetRelationship:
    """A detected or confirmed relationship between two sheets."""

    source_sheet: str
    """Sheet name where the reference originates."""

    source_table_id: str
    """Table ID of the source sheet."""

    source_column: str
    """Column in source sheet that references the target."""

    target_sheet: str
    """Sheet name being referenced."""

    target_table_id: str
    """Table ID of the target sheet."""

    target_column: str
    """Column in target sheet being referenced."""

    match_quality: str
    """'exact', 'fuzzy', or 'inferred'."""

    confidence: float
    """Confidence score 0.0-1.0."""

    notes: str
    """Additional notes about this relationship."""


@dataclass
class WorkbookCard:
    """
    Metadata for an entire Excel workbook.

    Groups together all TableCards from sheets in a single Excel file,
    and tracks relationships between them.
    """

    # === IDENTITY ===
    workbook_id: str
    """Unique identifier for this workbook, e.g. 'wb_abc123'."""

    source_file: str
    """Original Excel filename, e.g. 'quarterly_report.xlsx'."""

    ingestion_date: str
    """ISO date when this workbook was ingested."""

    # === SHEET INVENTORY ===
    total_sheets: int
    """Total number of sheets in the original Excel file."""

    sheets_ingested: int
    """Number of sheets that were successfully ingested."""

    sheets_skipped: int
    """Number of sheets that were skipped."""

    sheets: list[SheetInfo]
    """Information about each sheet."""

    # === CROSS-SHEET RELATIONSHIPS ===
    cross_sheet_relationships: list[CrossSheetRelationship] = field(default_factory=list)
    """Detected relationships between sheets (potential JOINs)."""

    # === LLM-GENERATED SUMMARY ===
    workbook_description: str = ""
    """Overall description of what this workbook contains."""

    workbook_purpose: str = ""
    """What this workbook is used for."""

    # === STORAGE PATHS ===
    s3_base_path: Optional[str] = None
    """Base S3 path for all data from this workbook."""

    manifest_path: Optional[str] = None
    """Path to the manifest.json file."""

    @classmethod
    def create(
        cls,
        workbook_id: str,
        source_file: str,
        sheet_names: list[str],
    ) -> "WorkbookCard":
        """Create a new WorkbookCard with sheet placeholders."""
        return cls(
            workbook_id=workbook_id,
            source_file=source_file,
            ingestion_date=date.today().isoformat(),
            total_sheets=len(sheet_names),
            sheets_ingested=0,
            sheets_skipped=0,
            sheets=[],
        )

    def add_sheet(self, sheet_info: SheetInfo) -> None:
        """Add a sheet to the workbook."""
        self.sheets.append(sheet_info)
        if sheet_info.was_ingested:
            self.sheets_ingested += 1
        else:
            self.sheets_skipped += 1

    def get_sheet_by_name(self, sheet_name: str) -> Optional[SheetInfo]:
        """Get sheet info by name."""
        for sheet in self.sheets:
            if sheet.sheet_name == sheet_name:
                return sheet
        return None

    def get_table_ids(self) -> list[str]:
        """Get all table IDs from ingested sheets."""
        return [s.table_id for s in self.sheets if s.was_ingested]

    def add_relationship(self, relationship: CrossSheetRelationship) -> None:
        """Add a cross-sheet relationship."""
        self.cross_sheet_relationships.append(relationship)

    def get_relationships_for_sheet(self, sheet_name: str) -> list[CrossSheetRelationship]:
        """Get all relationships involving a specific sheet."""
        return [
            r for r in self.cross_sheet_relationships
            if r.source_sheet == sheet_name or r.target_sheet == sheet_name
        ]
