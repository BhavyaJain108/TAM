# TAM Pipeline Documentation

> Excel-to-Queryable-Data Ingestion Pipeline

---

## Part 1: Excel Reader

### Purpose
Read a rectangular region from an Excel file and convert it to a pandas DataFrame for processing.

### Why This Matters
- Excel files are messy: merged cells, formulas, inconsistent formatting
- Users specify coordinates (e.g., `B2:F45`) because data often doesn't start at A1
- Need to extract clean, consistent data regardless of source formatting

### Key Functions

| Function | Purpose |
|----------|---------|
| `read_rectangle()` | Main entry point - reads specified range, returns DataFrame + header metadata |
| `list_sheets()` | List all sheet names in a workbook |
| `detect_data_range()` | Auto-detect where data ends (for unknown ranges) |
| `read_header_metadata()` | Extract category row above headers (handles merged cells) |

### Design Decisions

| Decision | Choice | Reasoning |
|----------|--------|-----------|
| Merged cells | Unmerge + fill with top-left value | Preserves user intent, each cell gets a value |
| Reversed ranges | Auto-normalize (`F10:B2` → `B2:F10`) | User convenience, no errors |
| Duplicate column names | Append `_2`, `_3`, etc. | Avoid downstream errors |
| Empty column names | Assign `column_N` | Must have valid identifiers |
| Header metadata | Read row above headers | Common Excel pattern for category labels |

### Tests

| Test | What It Validates |
|------|-------------------|
| `test_simple_cell` | Basic cell parsing: `A1` → (row=1, col=1) |
| `test_double_letter_column` | Excel columns beyond Z: `AA1` → col=27 |
| `test_triple_letter_column` | Large spreadsheets: `AAA1` → col=703 |
| `test_large_row_number` | Handle 100k+ rows |
| `test_lowercase` | Accept `a1` same as `A1` |
| `test_with_whitespace` | Trim ` B2 ` to `B2` |
| `test_invalid_reference` | Reject garbage input (`1A`, `A`, `123`) |
| `test_reversed_range` | `F10:B2` auto-corrects to `B2:F10` |
| `test_single_cell_range` | Edge case: `C3:C3` is valid (1 cell) |
| `test_file_not_found` | Clear error message |
| `test_invalid_file_format` | Reject fake `.xlsx` files |
| `test_sheet_not_found` | Error lists available sheets |
| `test_read_clean_data` | Correct row/column counts, header names |
| `test_read_messy_data` | Handles real-world messy data |

---

## Part 2: Column Profiler

### Purpose
Analyze each column in the DataFrame to determine data types, statistics, and quality observations.

### Why This Matters
- Need to understand data before querying it
- Data types affect what SQL operations are valid
- Statistics help users understand the data's shape
- Low-cardinality columns (< 20 unique values) are useful for filters

### Key Functions

| Function | Purpose |
|----------|---------|
| `profile_columns()` | Profile all columns in a DataFrame |
| `profile_column()` | Profile a single column |
| `detect_data_type()` | Determine column type (STRING, INTEGER, FLOAT, DATE, BOOLEAN, MIXED) |
| `detect_format_warnings()` | Identify formatting observations |

### Data Types Detected

| Type | Examples | Detection Logic |
|------|----------|-----------------|
| `INTEGER` | `1, 2, 3` | Whole numbers (even if stored as float) |
| `FLOAT` | `1.5, 2.7` | Decimal numbers |
| `STRING` | `"Alpha", "Beta"` | Text values |
| `DATE` | `2024-01-15` | Multiple date formats supported |
| `BOOLEAN` | `True/False, Yes/No` | Boolean-like values |
| `MIXED` | `1, 2, "three"` | Multiple types in same column |

### Column Profile Output

```python
ColumnProfile(
    name="Revenue",           # Column header
    data_type="FLOAT",        # Detected type
    unique_values=150,        # Cardinality
    sample_values=[...],      # 10 examples (or all if < 20 unique)
    null_count=5,             # Missing values
    all_values=[...],         # Full list if cardinality < 20
    min_value=1000.0,         # For numeric columns
    max_value=500000.0,
    mean_value=75000.0,
    format_warnings=[...],    # Observations about formatting
    header_metadata="Financial Data"  # From row above header (if present)
)
```

### Format Observations Detected

| Observation | Example | Why It Matters |
|-------------|---------|----------------|
| Leading whitespace | `" Acme"` | Can cause join failures |
| Trailing whitespace | `"Acme "` | Can cause join failures |
| Inconsistent casing | `Active`, `ACTIVE`, `active` | May need normalization |
| Currency symbols | `$1,000` | Cannot aggregate directly |
| Suffix notation | `2.5M`, `900K` | Needs conversion for math |
| Percentage format | `50%` | Stored as text, not number |
| Empty strings | `""` | Different from null |

### Design Decisions

| Decision | Choice | Reasoning |
|----------|--------|-----------|
| Cardinality threshold | 20 unique values | Balance between useful filters and JSON size |
| Sample size | 10 values | Enough to understand the data |
| Type detection | 80% threshold | Allow some noise, detect dominant type |
| N/A, blanks | Not flagged as issues | These are valid data values |

### Tests

| Test | What It Validates |
|------|-------------------|
| `test_clean_integers` | Detect `[1, 2, 3]` as INTEGER |
| `test_clean_floats` | Detect `[1.5, 2.7]` as FLOAT |
| `test_integers_as_floats` | `[1.0, 2.0]` should be INTEGER, not FLOAT |
| `test_clean_strings` | Detect text as STRING |
| `test_mixed_types` | `[1, 2, "three"]` detected as MIXED |
| `test_all_nulls` | All-empty column defaults to STRING |
| `test_numeric_strings` | Numbers stored as text |
| `test_boolean_native` | `[True, False]` as BOOLEAN |
| `test_leading_whitespace` | Detect `" Acme"` |
| `test_trailing_whitespace` | Detect `"Acme "` |
| `test_inconsistent_casing` | Detect `Active` vs `ACTIVE` |
| `test_currency_symbols` | Detect `$1,000` |
| `test_suffix_notation` | Detect `2.5M`, `900K` |
| `test_no_warnings_for_clean_data` | Clean data has zero warnings |
| `test_basic_profile` | Stats: name, type, unique count, min/max/mean |
| `test_with_nulls` | Null count tracked correctly |
| `test_low_cardinality_all_values` | < 20 unique → store all values |
| `test_high_cardinality_no_all_values` | 25+ unique → only store samples |
| `test_profile_dataframe` | Profile entire DataFrame at once |
| `test_summary_structure` | Data quality summary has expected fields |

---

## Part 3: Storage / Athena Loader

### Connection from Previous Part (Column Profiler)

**Input received:**
- `DataFrame` - the actual data to store
- `list[ColumnProfile]` - column metadata including detected types

**Why this connection matters:**
- Column profiles contain the detected data types (`INTEGER`, `FLOAT`, `STRING`, etc.)
- These types are mapped to Athena types (`BIGINT`, `DOUBLE`, `STRING`, etc.)
- The storage layer uses profiles to generate correct DDL, not raw DataFrame dtypes
- This ensures the Athena table schema matches what the profiler determined, not pandas' interpretation

```
Column Profiler                    Storage Layer
     |                                  |
     | ColumnProfile.data_type -------> | ATHENA_TYPE_MAP
     | (INTEGER, FLOAT, STRING...)      | (BIGINT, DOUBLE, STRING...)
     |                                  |
     | DataFrame -------------------->  | Parquet file
```

### Purpose

Store the DataFrame as queryable data and save the TableCard metadata.

### Why This Matters

- **Parquet format**: Columnar storage, efficient for analytics queries
- **Dual-mode storage**: Local filesystem for development, S3/Athena for production
- **Athena integration**: Makes data queryable via standard SQL without a database server
- **Idempotent**: Re-ingestion overwrites existing table (DROP IF EXISTS + CREATE)

### Key Functions

| Function | Purpose |
|----------|---------|
| `create_athena_table()` | Main entry - stores data + creates Athena table (or local Parquet) |
| `save_parquet_local()` | Write DataFrame to local Parquet file |
| `save_parquet_s3()` | Write DataFrame to S3 as Parquet |
| `create_athena_table_ddl()` | Generate CREATE EXTERNAL TABLE SQL |
| `execute_athena_query()` | Run DDL/queries in Athena |
| `save_card()` | Save TableCard JSON to storage |
| `load_card()` | Load TableCard JSON from storage |

### Type Mapping

| Profiler Type | Athena Type | Reasoning |
|---------------|-------------|-----------|
| `STRING` | `STRING` | Direct mapping |
| `INTEGER` | `BIGINT` | Safe for large integers |
| `FLOAT` | `DOUBLE` | Double precision for decimals |
| `DATE` | `STRING` | Preserve original format, parse at query time |
| `BOOLEAN` | `BOOLEAN` | Direct mapping |
| `MIXED` | `STRING` | Mixed types stored as text |

**Why DATE stays as STRING:**
- Excel dates come in many formats (`2024-01-15`, `01/15/2024`, `Jan 15, 2024`)
- Converting could lose information or fail
- Safer to keep original format, parse at query time

### Storage Modes

**Local Mode** (development):
```
data/
├── processed/
│   └── {table_id}/
│       └── {table_id}.parquet
└── metadata/
    └── {table_id}/
        └── card.json
```

**AWS Mode** (production):
```
s3://{bucket}/
├── processed/
│   └── {table_id}/
│       └── {table_id}.parquet    <- Athena reads from here
└── metadata/
    └── {table_id}/
        └── card.json
```

### Design Decisions

| Decision | Choice | Reasoning |
|----------|--------|-----------|
| Parquet format | Yes | Columnar, compressed, Athena-native |
| Column names | Quote with `"name"` in SQL | Preserves special chars, spaces |
| Table exists | DROP + CREATE | Idempotent re-ingestion |
| Date storage | Keep as STRING | Preserve original format |
| Local mode | Full feature parity | Develop without AWS costs |
| Save BEFORE LLM | Yes | If LLM fails, data is still queryable |

### Connection to Next Part (LLM Integration)

**What storage provides to LLM:**

1. **`table_id`** - The Athena table name (e.g., `tbl_abc123`)
   - LLM uses this in generated SQL: `SELECT * FROM tbl_abc123`
   - Queries reference a table that actually exists

2. **`parquet_path`** - Where data lives (stored in final TableCard)

**The sequence matters:**
```
[Storage]
    Creates table_id = "tbl_abc123"
    Saves parquet file
         ↓
[LLM - Query Patterns]
    Generates: SELECT SUM("Revenue") FROM tbl_abc123 WHERE "Region" = 'North'
                                          ↑
                                    Uses real table name
```

### Tests

**Currently: No dedicated tests (Athena not integrated yet)**

Tests needed when Athena is connected:

| Test | What It Should Validate |
|------|-------------------------|
| `test_sanitize_column_name` | Special chars → underscores |
| `test_quote_column_name` | Proper quoting for SQL |
| `test_type_mapping` | Profiler types → Athena types |
| `test_ddl_generation` | Valid CREATE TABLE syntax |
| `test_save_load_parquet_local` | Round-trip Parquet locally |
| `test_save_load_card_local` | Round-trip JSON locally |

---

## Part 4: LLM Integration

### Connection from Previous Parts

**The full journey to LLM:**

```
Excel File
    ↓
[Excel Reader] → DataFrame + column headers
    ↓
[Column Profiler] → Adds types, stats, all_values for low-cardinality
    ↓
[Storage] → Saves data, creates table_id
    ↓
[LLM] → Sees: sample rows + column profiles + source info
    ↓
Generates: description, entities, SQL queries
```

**What LLM receives:**

| From | Data | Example |
|------|------|---------|
| Excel Reader | Source info | `quarterly_report.xlsx`, sheet `Sales`, range `B2:G700` |
| Excel Reader | DataFrame | Raw data (first 20 rows shown to LLM) |
| Column Profiler | Column types | `Revenue` is `FLOAT`, `Region` is `STRING` |
| Column Profiler | Statistics | `Revenue`: min=5000, max=500000, mean=75000 |
| Column Profiler | All values (low cardinality) | `Region`: `["North", "South", "East", "West", "Central"]` |
| Storage | Table ID | `tbl_abc123` (used in generated SQL) |

### How Entity Extraction Works (Key Concept)

**Q: How can entities be extracted from only sample data?**

**A: We don't only use sample data.** The LLM sees ColumnProfiles computed from ALL rows:

```
Example: 700-row sales table

ColumnProfile("Client Name"):
    unique_values: 700          ← computed from ALL rows
    all_values: None            ← too many (>20), not stored
    sample_values: ["Acme Corp", "Beta Inc", ...]

ColumnProfile("Region"):
    unique_values: 5            ← computed from ALL rows
    all_values: ["North", "South", "East", "West", "Central"]  ← ALL values stored

ColumnProfile("Status"):
    unique_values: 2
    all_values: ["Active", "Dormant"]   ← ALL values stored
```

**What LLM sees in the prompt:**

```
COLUMNS:
- Client Name (STRING): 700 unique values
  Sample: ["Acme Corp", "Beta Inc", "Gamma LLC", ...]

- Region (STRING): 5 unique values
  All values: ["North", "South", "East", "West", "Central"]

- Status (STRING): 2 unique values
  All values: ["Active", "Dormant"]

SAMPLE DATA (first 20 rows):
  Client Name    Region   Status    Revenue
  Acme Corp      North    Active    50000
  ...
```

**How LLM reasons:**

| Column | Observation | Conclusion |
|--------|-------------|------------|
| Client Name | 700 unique in 700 rows | **PRIMARY ENTITY** (one per row) |
| Region | 5 unique in 700 rows | **SECONDARY ENTITY** (grouping dimension) |
| Status | 2 unique in 700 rows | Flag/state field |
| Revenue | High cardinality numeric | Measure (not an entity) |

Even if sample rows only showed "North" and "South", the LLM knows "Central" exists from `all_values`.

### Purpose

Use Claude to generate human-readable metadata:
1. **Description** - What is this table?
2. **Purpose** - What questions can it answer?
3. **Caveats** - What are the data quality concerns?
4. **Entities** - What real-world things does it describe?
5. **Query Patterns** - Example SQL queries

### The Three LLM Calls

**Call 1: `generate_description()`**

```python
# Input: Column profiles + sample rows
# Output:
TableDescriptionResponse(
    description="This table contains client account data with revenue
                 figures across geographic regions and industries...",
    purpose="Analyze revenue by region, identify top clients,
             track active vs dormant accounts...",
    caveats="No significant data quality issues detected."
)
```

**Call 2: `extract_entities()`**

```python
# Input: Description from Call 1 + column profiles + sample data
# Output:
EntityExtractionResponse(
    entities=[
        EntityProfile(
            name="Client",
            is_primary=True,
            identified_by="Client Name",
            cardinality="one per row",
            attributes=["Revenue", "Status"],
            description="Business customer account"
        ),
        EntityProfile(
            name="Region",
            is_primary=False,
            identified_by="Region",
            cardinality="one to many",
            attributes=[],
            description="Geographic sales territory"
        ),
    ],
    cross_references=[
        CrossReference(
            column="Industry",
            likely_entity_type="Industry",
            match_quality="exact",
            notes="Could join with industry reference table"
        ),
    ]
)
```

**Call 3: `generate_query_patterns()`**

```python
# Input: table_id + column profiles + entities + description
# Output:
QueryPatternResponse(
    patterns=[
        QueryPattern(
            natural_language="Total revenue by region",
            sql='SELECT "Region", SUM("Revenue") FROM tbl_abc123 GROUP BY "Region"',
            warnings=None
        ),
        QueryPattern(
            natural_language="Top 10 clients by revenue",
            sql='SELECT "Client Name", "Revenue" FROM tbl_abc123 ORDER BY "Revenue" DESC LIMIT 10',
            warnings=None
        ),
        QueryPattern(
            natural_language="Active vs dormant client count",
            sql='SELECT "Status", COUNT(*) FROM tbl_abc123 GROUP BY "Status"',
            warnings=None
        ),
        # ... 5-8 patterns total
    ]
)
```

**Notice:**
- SQL uses `tbl_abc123` (the real table_id from storage)
- Column names are quoted: `"Client Name"`, `"Revenue"`
- Filter values come from `all_values`: `'Dormant'` not guessed

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    LLM Client Layer                      │
├─────────────────────────────────────────────────────────┤
│  BedrockClient    AnthropicClient    MockLLMClient      │
│  (AWS Bedrock)    (Direct API)       (Testing)          │
└────────────────────────┬────────────────────────────────┘
                         │
                         │ invoke_with_schema()
                         ▼
┌─────────────────────────────────────────────────────────┐
│                  Pydantic Validation                     │
├─────────────────────────────────────────────────────────┤
│  TableDescriptionResponse                                │
│  EntityExtractionResponse                                │
│  QueryPatternResponse                                    │
└─────────────────────────────────────────────────────────┘
```

### Key Principle: Always Use Pydantic

Every LLM call uses `invoke_with_schema()`:
1. System prompt includes the JSON schema
2. LLM returns structured JSON
3. Response is validated against Pydantic model
4. Retries automatically if validation fails

### Future: Natural Language to SQL

The query patterns generated now are just **examples**. The real value comes at **query time**:

```
Stage 1 (Ingestion - current):
    Excel → Profile → Store → LLM generates examples → TableCard

Stage 2 (Query Time - future):
    User: "What's the total revenue by region?"
                    ↓
            Uses TableCard metadata:
            - Knows "Revenue" is FLOAT
            - Knows "Region" has 5 values
            - Knows table_id = tbl_abc123
                    ↓
            Generates: SELECT "Region", SUM("Revenue")
                       FROM tbl_abc123
                       GROUP BY "Region"
```

The TableCard becomes a **knowledge base** that powers query generation.

### LLM Configuration (Ready to Use)

```bash
# AWS Bedrock
export LLM_PROVIDER=bedrock
export AWS_REGION=us-east-1

# Anthropic Direct
export LLM_PROVIDER=anthropic
export ANTHROPIC_API_KEY=sk-ant-...

# Testing (no API needed)
export LLM_PROVIDER=mock
```

### Design Decisions

| Decision | Choice | Reasoning |
|----------|--------|-----------|
| Schema validation | Pydantic + retries | Guarantees structured output |
| LLM provider | Configurable | Bedrock/Anthropic/Mock flexibility |
| Failure handling | Continue with defaults | Don't block ingestion on LLM failure |
| Temperature | 0.0 | Deterministic output |
| Sample rows | 20 | Enough context without token bloat |

### Connection to Next Part (Card Builder)

**What LLM produces:**

```
description: str
purpose: str
caveats: str
entities: list[EntityProfile]
cross_references: list[CrossReference]
query_patterns: list[QueryPattern]
tags_initial: list[str]
```

**Card Builder assembles everything into TableCard** - it's the final step that combines all outputs from the pipeline.

### Tests

**Currently: No dedicated tests (LLM not connected yet)**

The `MockLLMClient` enables testing without API:

```python
mock_client = MockLLMClient()
mock_client.set_response_for_schema(
    TableDescriptionResponse,
    {"description": "Test", "purpose": "Test", "caveats": "None"}
)
```

---

## Part 5: Card Builder & Workbook Ingester

### Connection from Previous Part (LLM)

**Everything is ready to assemble:**

```
From Excel Reader:
    source_file         = "quarterly_report.xlsx"
    source_sheet        = "Sales"
    source_range        = "B2:G700"

From Column Profiler:
    columns             = [ColumnProfile(...), ...]
    row_count           = 699
    column_count        = 6

From Storage:
    table_id            = "tbl_abc123"
    s3_parquet_path     = "data/processed/tbl_abc123/..."

From LLM:
    description         = "This table contains..."
    purpose             = "Analyze revenue..."
    caveats             = "No issues..."
    entities            = [EntityProfile(...), ...]
    cross_references    = [CrossReference(...), ...]
    query_patterns      = [QueryPattern(...), ...]
    tags_initial        = ["client", "revenue", "region"]
```

### Purpose

**Card Builder** = Orchestrator that runs each pipeline step and assembles the final TableCard.

**Workbook Ingester** = Handles multi-sheet Excel files, creates one TableCard per sheet plus a WorkbookCard wrapper.

### Card Builder Pipeline

```
[1/7] Reading Excel...
[2/7] Profiling columns...
[3/7] Storing data...
[4/7] Generating description with LLM...
[5/7] Extracting entities with LLM...
[6/7] Generating query patterns with LLM...
[7/7] Assembling TableCard...
```

### Workbook Ingester

For Excel files with multiple sheets:

```
quarterly_report.xlsx
├── Sheet: "Clients"    → TableCard (wb_abc123_clients)
├── Sheet: "Deals"      → TableCard (wb_abc123_deals)
└── Sheet: "Contacts"   → TableCard (wb_abc123_contacts)
        ↓
    WorkbookCard (parent container)
```

### TableCard vs WorkbookCard

**TableCard** = the real content (per sheet)
- Column profiles, stats, all_values
- LLM-generated description, entities, queries
- Storage paths
- Usage tracking (dynamic half)

**WorkbookCard** = thin wrapper (per Excel file)
- List of sheet names + their table_ids
- Which sheets were ingested vs skipped (and why)
- Cross-sheet relationships (which columns could JOIN)
- Source file name

```
WorkbookCard
├── workbook_id: "wb_abc123"
├── source_file: "quarterly_report.xlsx"
├── sheets: [
│     { sheet_name: "Clients", table_id: "wb_abc123_clients", was_ingested: true },
│     { sheet_name: "Deals", table_id: "wb_abc123_deals", was_ingested: true },
│     { sheet_name: "Notes", table_id: "", was_ingested: false, skip_reason: "No data" },
│   ]
├── cross_sheet_relationships: [
│     { source: "Clients.Client Name" → target: "Deals.Client Name" }
│   ]
│
└── Actual data lives in separate TableCards
```

### Cross-Sheet Relationship Detection

Automatically finds columns that could be JOINed:
- Same column name across sheets
- Matching values (exact or fuzzy)
- Key-like column names (contains "id", "name", "code")

### Connection to Next Part (Data Models)

Card Builder creates instances of:
- `TableCard` - main output
- `ColumnProfile` - one per column
- `EntityProfile` - from LLM
- `CrossReference` - from LLM
- `QueryPattern` - from LLM

Workbook Ingester creates:
- `WorkbookCard` - wrapper
- `SheetInfo` - one per sheet
- `CrossSheetRelationship` - detected JOINs

### Tests

Card Builder is tested implicitly through integration tests (full pipeline runs).

Workbook Ingester tested with `test_multi_table.xlsx` (3 sheets: Clients, Deals, Contacts).

---

## Part 6: Data Models

*To be documented...*

---

## Part 7: CLI Commands

*To be documented...*
