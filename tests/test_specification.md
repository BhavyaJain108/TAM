# Test Specification — Edge Cases & Scenarios

## 1. Excel Reading (`read_rectangle`)

### 1.1 Cell Content Edge Cases

| Test Case | Input | Expected Behavior |
|-----------|-------|-------------------|
| **Merged cells** | Header spans B2:D2 | Unmerge and use value in top-left cell only |
| **Formulas** | `=SUM(A1:A10)` | Return computed value, not formula string |
| **Empty cells** | Blank cells in data | Return `None`/`NaN`, not empty string |
| **Very long text** | 10,000+ character cell | Truncate or handle gracefully |
| **Unicode/emoji** | "客户名称", "Status ✓" | Preserve exactly |
| **Newlines in cells** | "Line1\nLine2" | Preserve or normalize consistently |
| **Leading/trailing whitespace** | " Acme Corp " | Preserve (profiler will flag) |
| **HTML/Rich text** | Bold/italic formatting | Strip formatting, keep text |

### 1.2 Range Specification Edge Cases

| Test Case | Input | Expected Behavior |
|-----------|-------|-------------------|
| **Invalid range** | "ZZ999:AAA1000" | Raise clear error |
| **Reversed range** | "F45:B2" (end before start) | Normalize to B2:F45 or raise error |
| **Single cell** | "B2:B2" | Return 1x1 DataFrame (edge case: is this header or data?) |
| **Single row** | "B2:F2" | Return DataFrame with headers only, no data rows |
| **Single column** | "B2:B45" | Return single-column DataFrame |
| **Range exceeds data** | "B2:Z100" but data ends at F45 | Return only cells with data, or pad with nulls? |
| **Range starts mid-table** | Header in row 1, range starts row 5 | First row of range becomes header (may be data) |

### 1.3 Sheet Edge Cases

| Test Case | Input | Expected Behavior |
|-----------|-------|-------------------|
| **Sheet doesn't exist** | sheet_name="FakeSheet" | Raise clear error with available sheet names |
| **Sheet name with spaces** | "Q1 2024 Data" | Handle correctly |
| **Sheet name with special chars** | "Data (Final)" | Handle correctly |
| **Hidden sheet** | Sheet is hidden in Excel | Still accessible |
| **Very long sheet name** | 100+ characters | Handle or truncate |

### 1.4 File Edge Cases

| Test Case | Input | Expected Behavior |
|-----------|-------|-------------------|
| **File not found** | path doesn't exist | Raise clear error |
| **Not an Excel file** | .csv renamed to .xlsx | Raise clear error |
| **Password protected** | Encrypted workbook | Raise clear error (not supported) |
| **Corrupted file** | Partial/damaged .xlsx | Raise clear error |
| **.xls (old format)** | Excel 97-2003 | Support or raise "use .xlsx" error |
| **.xlsm (macros)** | Excel with macros | Read data, ignore macros |
| **Very large file** | 100MB+ Excel | Handle without OOM (streaming?) |

---

## 2. Column Profiling (`profile_columns`)

### 2.1 Data Type Detection

| Test Case | Column Values | Expected `data_type` | Notes |
|-----------|---------------|---------------------|-------|
| **Clean integers** | [1, 2, 3, 4, 5] | INTEGER | |
| **Clean floats** | [1.5, 2.7, 3.14] | FLOAT | |
| **Integers as floats** | [1.0, 2.0, 3.0] | INTEGER | Detect whole numbers stored as float |
| **Clean strings** | ["A", "B", "C"] | STRING | |
| **Clean dates** | ["2024-01-15", "2024-02-20"] | DATE | ISO format |
| **Mixed date formats** | ["2024-01-15", "01/15/2024", "Jan 15, 2024"] | DATE or MIXED? | Need to decide |
| **Booleans** | [True, False, True] | BOOLEAN | |
| **Boolean-like strings** | ["Yes", "No", "Yes"] | STRING + note | Flag as boolean-like |
| **Mixed int/string** | [1, 2, "three", 4] | MIXED | |
| **Numbers as strings** | ["1", "2", "3"] | STRING (but flag) | Detect "numeric strings" |
| **All nulls** | [None, None, None] | STRING (default) | Flag as "all null" |
| **Single value + nulls** | ["Active", None, None] | STRING | |

### 2.2 Numeric Format Variations

| Test Case | Column Values | Expected Handling |
|-----------|---------------|-------------------|
| **Currency symbols** | ["$1,000", "$2,500", "€3,000"] | STRING + warning: "Currency values with symbols" |
| **K/M/B suffixes** | ["2.5M", "900K", "1.2B"] | STRING + warning: "Abbreviated numbers (K/M/B)" |
| **Percentages** | ["50%", "75%", "100%"] | STRING + warning: "Percentage format" |
| **Parentheses = negative** | ["100", "(50)", "200"] | STRING + warning: "Negative values in parentheses" |
| **Scientific notation** | ["1.5e6", "2.3e-4"] | FLOAT | Should parse correctly |
| **Comma separators** | ["1,000", "2,500,000"] | STRING or INTEGER? | Locale-dependent |
| **Mixed formats same column** | ["2.5M", "1,200,000", "$500K"] | STRING + warning: "Inconsistent number formats" |

### 2.3 String Quality Issues

| Test Case | Column Values | Expected Warning |
|-----------|---------------|-----------------|
| **Leading whitespace** | [" Acme", "Beta"] | "Some values have leading whitespace" |
| **Trailing whitespace** | ["Acme ", "Beta"] | "Some values have trailing whitespace" |
| **Inconsistent casing** | ["Active", "ACTIVE", "active"] | "Inconsistent casing for same values" |
| **Common placeholders** | ["Acme", "???", "N/A", "TBD"] | "Contains placeholder values: ???, N/A, TBD" |
| **Empty strings vs null** | ["Acme", "", None, "Beta"] | "Contains empty strings (different from null)" |
| **Abbreviations** | ["CW", "Neg", "Prop"] | Detected by LLM, not profiler |

### 2.4 Cardinality Edge Cases

| Test Case | Column Profile | Expected Behavior |
|-----------|----------------|-------------------|
| **All unique** | 1000 rows, 1000 unique values | `all_values = None`, sample only |
| **All identical** | 1000 rows, 1 unique value | `all_values = ["Active"]`, flag as "constant column" |
| **High cardinality ID** | UUIDs or sequential IDs | Detect as likely identifier |
| **Low cardinality categorical** | 5 values across 1000 rows | `all_values` populated, good for GROUP BY |
| **Boundary: exactly 20 unique** | 20 distinct values | Include in `all_values` (boundary test) |
| **Boundary: 21 unique** | 21 distinct values | `all_values = None` |

### 2.5 Statistical Edge Cases

| Test Case | Values | Expected Stats |
|-----------|--------|----------------|
| **Single value** | [42] | min=42, max=42, mean=42 |
| **All nulls** | [None, None] | min=None, max=None, mean=None |
| **One value + nulls** | [42, None, None] | min=42, max=42, mean=42 |
| **Extreme outliers** | [1, 2, 3, 1000000] | Accurate stats (consider flagging outlier?) |
| **Negative numbers** | [-100, -50, 0, 50] | Correct handling of negatives |
| **Very small floats** | [0.0001, 0.0002] | Preserve precision |
| **Very large numbers** | [1e15, 2e15] | No overflow |

---

## 3. Athena/Parquet Storage (`create_athena_table`)

### 3.1 Column Name Edge Cases

| Test Case | Column Name | Expected Handling |
|-----------|-------------|-------------------|
| **Spaces** | "Client Name" | Quote in SQL: `"Client Name"` |
| **Special chars** | "$ Val" | Quote in SQL: `"$ Val"` |
| **Slashes** | "Client Vertical / Industry" | Quote in SQL |
| **Parentheses** | "Revenue (USD)" | Quote in SQL |
| **Leading numbers** | "2024 Revenue" | Quote in SQL (invalid unquoted) |
| **SQL reserved word** | "Select", "From", "Table" | Quote in SQL |
| **Very long name** | 200+ characters | Truncate or error? Athena limit is 255 |
| **Duplicate names** | ["Name", "Name"] | Rename to "Name", "Name_2" |
| **Empty name** | "" (blank header) | Assign "column_1", "column_2", etc. |
| **Unicode** | "客户" | Verify Athena/Parquet support |

### 3.2 Data Type Mapping

| Python/Pandas Type | Parquet Type | Athena Type |
|-------------------|--------------|-------------|
| int64 | INT64 | BIGINT |
| float64 | DOUBLE | DOUBLE |
| object (string) | STRING | STRING |
| datetime64 | TIMESTAMP | TIMESTAMP |
| bool | BOOLEAN | BOOLEAN |
| mixed (object) | STRING | STRING |

### 3.3 S3/Athena Edge Cases

| Test Case | Scenario | Expected Handling |
|-----------|----------|-------------------|
| **S3 path exists** | Table already ingested | Overwrite or version? |
| **Athena table exists** | Re-ingesting same table_id | DROP and recreate, or error? |
| **Special chars in table_id** | "tbl-00001" (hyphen) | Use underscores only |
| **Very large DataFrame** | 10M+ rows | Partition? Multiple Parquet files? |
| **Empty DataFrame** | 0 data rows | Create table with schema only, or error? |

---

## 4. LLM Generation Functions

### 4.1 `generate_description` Edge Cases

| Test Case | Table Content | Challenge |
|-----------|---------------|-----------|
| **Ambiguous purpose** | Generic column names: "Col1", "Col2", "Value" | LLM must say "purpose unclear" |
| **Very small table** | 2 rows of data | Limited context for inference |
| **Very wide table** | 50+ columns | Token limits, prioritize important columns |
| **Pivot table layout** | Months as columns, products as rows | Recognize time-series pivot structure |
| **Foreign language** | Chinese/Spanish column names and values | Handle or flag language |
| **Sensitive data** | SSN, credit cards visible | Flag as PII, warn in caveats |
| **All numeric** | No text columns for context | Harder to infer purpose |
| **Contradictory data** | Column "Active" with value "Closed" | Flag data quality issue |

### 4.2 `extract_entities` Edge Cases

| Test Case | Table Structure | Challenge |
|-----------|-----------------|-----------|
| **No clear primary entity** | Aggregated summary table | May have no "one per row" entity |
| **Multiple primary candidates** | Both "Deal ID" and "Opp Name" unique | Pick one, note the other |
| **Composite key** | Uniqueness requires 2+ columns | Identify composite identifier |
| **Self-referential** | "Manager ID" refers to "Employee ID" in same table | Detect hierarchy |
| **Junction table** | Many-to-many mapping (Client-Product) | Both entities are "one to many" |
| **Denormalized** | Client info repeated on every deal row | Client is secondary entity |

### 4.3 `generate_query_patterns` Edge Cases

| Test Case | Column Situation | Expected Pattern Handling |
|-----------|------------------|---------------------------|
| **Non-aggregatable values** | "$ Val" = "2.5M" | Include WARNING comment |
| **Date with placeholders** | "Exp Close" has "???" | WHERE clause excludes placeholder |
| **Abbreviations** | "Stage" = "CW", "Neg" | Note meaning in query comment |
| **No numeric columns** | All text/categorical | Skip SUM/AVG patterns |
| **No categorical columns** | All unique values | Skip GROUP BY patterns |
| **All columns problematic** | Every column has issues | Still generate useful patterns with warnings |

---

## 5. Integration Test Scenarios

### 5.1 Real-World Messy Data Patterns

| Scenario | Characteristics | Test Focus |
|----------|-----------------|------------|
| **Sales Pipeline** | Abbreviated stages, currency suffixes, partial dates | Full ingestion flow |
| **Client Master** | Duplicate names (casing), missing industry, mixed regions | Entity detection, deduplication hints |
| **Financial Report** | Pivot layout, merged headers, formula results | Pivot detection, merged cell handling |
| **HR Export** | PII (SSN, salary), dates in multiple formats | PII flagging, date normalization |
| **Inventory List** | SKUs, quantities, mixed units (ea, box, case) | Unit detection, numeric extraction |

### 5.2 End-to-End Test Cases

```
Test E2E-1: Clean Data Happy Path
├── Input: Well-formatted 20-row table, clear headers, consistent types
├── Expected: All functions succeed, card generated with no warnings
└── Verify: Card can be used to generate working SQL

Test E2E-2: Maximum Mess
├── Input: Mixed types, placeholders, merged cells, abbreviations, whitespace
├── Expected: All issues captured in warnings/caveats
└── Verify: Caveats mention every issue, query patterns include warnings

Test E2E-3: Re-ingestion
├── Input: Same Excel file ingested twice
├── Expected: Defined behavior (overwrite vs version vs error)
└── Verify: No orphaned S3 files or Athena tables

Test E2E-4: Multiple Tables Same File
├── Input: Excel with 3 separate tables on different sheets
├── Expected: 3 independent TableCards, potential cross-references detected
└── Verify: Cross-reference hints between related tables

Test E2E-5: Query Feedback Loop
├── Input: Ingest table, run query, provide feedback
├── Expected: Dynamic half updated (usage_log, satisfaction_rate)
└── Verify: Learned mappings captured from successful queries
```

---

## 6. Test Data Files Needed

| File | Purpose | Contents |
|------|---------|----------|
| `test_clean.xlsx` | Happy path | 20 rows, 6 columns, clean data |
| `test_messy.xlsx` | Edge cases | Mixed formats, placeholders, whitespace |
| `test_merged.xlsx` | Merged cells | Headers spanning multiple columns |
| `test_pivot.xlsx` | Pivot layout | Time periods as columns |
| `test_formulas.xlsx` | Formula handling | Cells with =SUM(), =VLOOKUP() |
| `test_large.xlsx` | Scale testing | 100K+ rows |
| `test_unicode.xlsx` | International | Chinese, Arabic, emoji in cells |
| `test_types.xlsx` | Type detection | One column per type edge case |
| `test_multi_table.xlsx` | Multiple tables | 3 tables across sheets |

---

## 7. Decision Points (Need Resolution)

These edge cases require explicit design decisions:

| Question | Options | Recommendation |
|----------|---------|----------------|
| Mixed date formats in one column? | A) MIXED type, B) DATE + warning | **B** — try to parse, warn about formats |
| Merged cells in data (not header)? | A) Unmerge + fill, B) Unmerge + null | **A** — fill with merged value |
| Numbers with commas "1,000"? | A) STRING, B) Parse as INTEGER | **A** — STRING + warning (locale issues) |
| Reversed range "F45:B2"? | A) Normalize, B) Error | **A** — normalize silently |
| Duplicate column names? | A) Rename "_2", B) Error | **A** — rename with suffix |
| Empty column name? | A) "column_N", B) Error | **A** — assign default name |
| Table already exists? | A) Overwrite, B) Version, C) Error | **A** — overwrite with backup |
| 0-row table (headers only)? | A) Create anyway, B) Error | **B** — error (no data to profile) |

---

## 8. Non-Functional Tests

| Category | Test | Acceptance Criteria |
|----------|------|---------------------|
| **Performance** | Profile 100K-row table | < 30 seconds |
| **Performance** | Generate description for 50-column table | < 10 seconds |
| **Memory** | Ingest 100MB Excel file | < 2GB RAM peak |
| **Cost** | LLM tokens per table | < 10K tokens input, < 2K output |
| **Reliability** | Partial failure recovery | If LLM fails, still save what we have |
| **Idempotency** | Run same ingestion twice | Identical output |
