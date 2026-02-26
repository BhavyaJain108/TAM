"""
Core data models for the TableCard metadata system.

TableCard is the central data structure that describes an ingested table.
It has two halves:
- Static half: Set at ingestion, never modified
- Dynamic half: Grows over time with usage
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import date


@dataclass
class ColumnProfile:
    """Statistical profile of a single column."""

    name: str
    """The exact column header as it appears in the Excel file."""

    data_type: str
    """One of: STRING, INTEGER, FLOAT, DATE, BOOLEAN, MIXED."""

    unique_values: int
    """How many distinct values exist in this column."""

    sample_values: list[str]
    """Example values (5-10 for high cardinality, all for low cardinality)."""

    null_count: int
    """How many cells in this column are empty/null."""

    all_values: Optional[list[str]] = None
    """Complete list of distinct values if unique_values < 20, else None."""

    min_value: Optional[float] = None
    """Minimum value (only for INTEGER/FLOAT columns)."""

    max_value: Optional[float] = None
    """Maximum value (only for INTEGER/FLOAT columns)."""

    mean_value: Optional[float] = None
    """Mean value (only for INTEGER/FLOAT columns)."""

    format_warnings: Optional[list[str]] = None
    """Warnings about data quality issues in this column."""

    header_metadata: Optional[str] = None
    """Value from the row above the header (if present) - often contains descriptions or categories."""


@dataclass
class EntityProfile:
    """Description of a real-world entity represented in the table."""

    name: str
    """The entity name, e.g. 'Client', 'Deal', 'Partner'."""

    is_primary: bool
    """True if this entity has one row per instance (primary entity)."""

    identified_by: str
    """Which column identifies this entity, e.g. 'Client Name'."""

    cardinality: str
    """How the entity maps to rows: 'one per row' or 'one to many'."""

    attributes: list[str]
    """Which other columns describe this entity."""

    description: str
    """LLM-generated note about this entity in context of this table."""


@dataclass
class CrossReference:
    """A potential connection to another table."""

    column: str
    """Which column in THIS table might connect to other tables."""

    likely_entity_type: str
    """What kind of entity this column refers to, e.g. 'Client'."""

    match_quality: str
    """How reliable a join would be: 'exact', 'fuzzy', or 'unknown'."""

    notes: str
    """Any caveats about matching."""


@dataclass
class QueryPattern:
    """A pre-generated example SQL query for this table."""

    natural_language: str
    """The kind of question this query answers, in plain English."""

    sql: str
    """The actual SQL query using this table's real column names."""

    warnings: Optional[str] = None
    """Any caveats about this query."""


@dataclass
class UsageEntry:
    """Log entry for when this table was considered for a query."""

    date: str
    """When this entry was created (ISO format)."""

    user_query: str
    """What the user asked, in natural language."""

    was_selected: bool
    """Whether this table was selected as relevant for the query."""

    selection_reason: str
    """Why the table was selected (or why it wasn't)."""

    sql_generated: Optional[str] = None
    """The SQL query that was generated (only if was_selected=True)."""

    query_succeeded: Optional[bool] = None
    """Whether the SQL ran without error in Athena."""

    user_feedback: Optional[str] = None
    """'thumbs_up', 'thumbs_down', or None."""


@dataclass
class VocabularyMapping:
    """A learned mapping from user terminology to column values."""

    user_term: str
    """What the user said, e.g. 'fintech'."""

    maps_to_column: str
    """Which column this maps to, e.g. 'Industry'."""

    maps_to_values: list[str]
    """Which column values match, e.g. ['Financial Technology', 'Fintech']."""

    confidence: str
    """'high' (confirmed multiple times), 'medium' (confirmed once), 'low' (inferred)."""

    times_confirmed: int
    """How many successful queries have used this mapping."""


@dataclass
class ConfirmedRelationship:
    """A verified cross-table join that has been tested and works."""

    this_column: str
    """Column in this table, e.g. 'Client Name'."""

    other_table_id: str
    """The table_id of the other table, e.g. 'tbl_00058'."""

    other_column: str
    """Column in the other table, e.g. 'Acct'."""

    join_type: str
    """'exact' (values match directly) or 'fuzzy' (need approximate matching)."""

    match_rate: float
    """What percentage of values in this column found a match (0.0 to 1.0)."""

    mapping_examples: list[dict]
    """Concrete examples: [{'this': 'Acme Corp', 'other': 'Acme'}, ...]."""

    times_used: int
    """How many queries have used this join successfully."""


@dataclass
class TableCard:
    """
    The central metadata structure for an ingested table.

    Static half (set at ingestion, never modified):
    - Identity fields (table_id, source_*, ingestion_date, row/column counts)
    - Column definitions (columns)
    - LLM-generated description, purpose, caveats
    - Entities and cross-references
    - Query patterns

    Dynamic half (grows over time with usage):
    - Usage log
    - Learned tags
    - Reliability scores
    - Vocabulary mappings
    - Confirmed relationships
    """

    # === IDENTITY (Static) ===
    table_id: str
    """Unique identifier, e.g. 'tbl_00042'. Used as Athena table name."""

    source_file: str
    """Original Excel filename, e.g. 'client_data.xlsx'."""

    source_sheet: str
    """Sheet name within the Excel file, e.g. 'Sheet1'."""

    source_range: str
    """Cell range that was extracted, e.g. 'B2:F45'."""

    ingestion_date: str
    """ISO date when this table was ingested, e.g. '2026-02-25'."""

    row_count: int
    """Number of data rows (excluding header)."""

    column_count: int
    """Number of columns."""

    # === COLUMN DEFINITIONS (Static) ===
    columns: list[ColumnProfile]
    """Statistical profile of each column."""

    # === LLM-GENERATED DESCRIPTION (Static) ===
    description: str
    """Plain English explanation of what this table is."""

    purpose: str
    """What kinds of questions this table can answer."""

    caveats: str
    """Warnings about data quality, inconsistencies, limitations."""

    # === ENTITIES (Static) ===
    entities: list[EntityProfile]
    """Real-world things this table describes."""

    # === CROSS-REFERENCE HINTS (Static) ===
    cross_references: list[CrossReference]
    """Columns that might connect to other tables."""

    # === QUERY PATTERNS (Static) ===
    query_patterns: list[QueryPattern]
    """Pre-generated example SQL queries."""

    # === INITIAL TAGS (Static) ===
    tags_initial: list[str]
    """Tags set at ingestion, e.g. ['clients', 'revenue', 'industry']."""

    # === DYNAMIC HALF ===
    usage_log: list[UsageEntry] = field(default_factory=list)
    """Every query consideration is logged here."""

    tags_learned: list[str] = field(default_factory=list)
    """Tags added over time from successful queries."""

    query_success_rate: float = 0.0
    """Percentage of generated SQL that ran without errors (0.0 to 1.0)."""

    user_satisfaction_rate: float = 0.0
    """Percentage of results with positive/neutral feedback (0.0 to 1.0)."""

    total_queries: int = 0
    """How many times this table has been used in a query."""

    learned_mappings: list[VocabularyMapping] = field(default_factory=list)
    """User vocabulary → column value mappings."""

    confirmed_relationships: list[ConfirmedRelationship] = field(default_factory=list)
    """Verified cross-table joins."""

    # === S3 LOCATION (set after storage) ===
    s3_parquet_path: Optional[str] = None
    """S3 path to the Parquet file, e.g. 's3://bucket/processed/tbl_00042/tbl_00042.parquet'."""

    s3_card_path: Optional[str] = None
    """S3 path to this card's JSON, e.g. 's3://bucket/metadata/tbl_00042/card.json'."""

    @classmethod
    def create_empty(
        cls,
        table_id: str,
        source_file: str,
        source_sheet: str,
        source_range: str,
    ) -> "TableCard":
        """Create a TableCard with minimal identity info, ready to be populated."""
        return cls(
            table_id=table_id,
            source_file=source_file,
            source_sheet=source_sheet,
            source_range=source_range,
            ingestion_date=date.today().isoformat(),
            row_count=0,
            column_count=0,
            columns=[],
            description="",
            purpose="",
            caveats="",
            entities=[],
            cross_references=[],
            query_patterns=[],
            tags_initial=[],
        )

    def update_reliability_scores(self) -> None:
        """Recalculate reliability scores from usage log."""
        if not self.usage_log:
            return

        selected_entries = [e for e in self.usage_log if e.was_selected]
        if not selected_entries:
            return

        self.total_queries = len(selected_entries)

        # Query success rate
        queries_with_result = [e for e in selected_entries if e.query_succeeded is not None]
        if queries_with_result:
            successful = sum(1 for e in queries_with_result if e.query_succeeded)
            self.query_success_rate = successful / len(queries_with_result)

        # User satisfaction rate
        queries_with_feedback = [e for e in selected_entries if e.user_feedback is not None]
        if queries_with_feedback:
            positive = sum(1 for e in queries_with_feedback if e.user_feedback == "thumbs_up")
            neutral = sum(1 for e in queries_with_feedback if e.user_feedback is None)
            self.user_satisfaction_rate = (positive + neutral) / len(queries_with_feedback)

    def add_usage_entry(self, entry: UsageEntry) -> None:
        """Add a usage log entry and update reliability scores."""
        self.usage_log.append(entry)
        self.update_reliability_scores()

    def add_learned_tag(self, tag: str) -> None:
        """Add a learned tag if not already present."""
        tag_lower = tag.lower()
        if tag_lower not in [t.lower() for t in self.tags_learned]:
            self.tags_learned.append(tag)

    def add_vocabulary_mapping(self, mapping: VocabularyMapping) -> None:
        """Add or update a vocabulary mapping."""
        # Check if mapping for this term already exists
        for existing in self.learned_mappings:
            if existing.user_term.lower() == mapping.user_term.lower():
                # Update existing mapping
                existing.maps_to_values = list(set(existing.maps_to_values + mapping.maps_to_values))
                existing.times_confirmed += 1
                if existing.times_confirmed >= 3:
                    existing.confidence = "high"
                elif existing.times_confirmed >= 1:
                    existing.confidence = "medium"
                return

        # Add new mapping
        self.learned_mappings.append(mapping)

    def promote_cross_reference(
        self,
        column: str,
        other_table_id: str,
        other_column: str,
        match_rate: float,
        mapping_examples: list[dict],
        join_type: str = "exact",
    ) -> None:
        """Promote a cross-reference hint to a confirmed relationship."""
        # Check if already confirmed
        for existing in self.confirmed_relationships:
            if (
                existing.this_column == column
                and existing.other_table_id == other_table_id
                and existing.other_column == other_column
            ):
                # Update existing
                existing.times_used += 1
                existing.match_rate = match_rate  # Update with latest
                return

        # Create new confirmed relationship
        self.confirmed_relationships.append(
            ConfirmedRelationship(
                this_column=column,
                other_table_id=other_table_id,
                other_column=other_column,
                join_type=join_type,
                match_rate=match_rate,
                mapping_examples=mapping_examples,
                times_used=1,
            )
        )
