"""
Column profiling functionality.

Analyzes DataFrame columns to extract statistics, detect data types,
and identify data quality issues.
"""

import re
from typing import Optional
from datetime import datetime

import pandas as pd
import numpy as np

from models.table_card import ColumnProfile
from config.settings import get_settings


# Patterns for detecting various formats
CURRENCY_PATTERN = re.compile(r"^[\$\€\£\¥]?\s*[\d,]+\.?\d*[KMBkmb]?\s*$")
PERCENTAGE_PATTERN = re.compile(r"^-?\d+\.?\d*\s*%$")
SUFFIX_NUMBER_PATTERN = re.compile(r"^[\$\€\£\¥]?\s*(\d+\.?\d*)\s*([KMBkmb])$", re.IGNORECASE)
PARENTHESES_NEGATIVE_PATTERN = re.compile(r"^\([\d,]+\.?\d*\)$")
SCIENTIFIC_PATTERN = re.compile(r"^-?\d+\.?\d*[eE][+-]?\d+$")

# Common date formats to try
DATE_FORMATS = [
    "%Y-%m-%d",      # 2024-01-15
    "%m/%d/%Y",      # 01/15/2024
    "%d/%m/%Y",      # 15/01/2024
    "%Y/%m/%d",      # 2024/01/15
    "%b %d, %Y",     # Jan 15, 2024
    "%B %d, %Y",     # January 15, 2024
    "%d %b %Y",      # 15 Jan 2024
    "%d %B %Y",      # 15 January 2024
    "%Y-%m-%d %H:%M:%S",  # 2024-01-15 10:30:00
    "%m-%d-%Y",      # 01-15-2024
]


def is_numeric_string(value: str) -> bool:
    """Check if a string represents a number (possibly with formatting)."""
    try:
        float(value.replace(",", "").replace(" ", ""))
        return True
    except (ValueError, AttributeError):
        pass

    # Check for suffix notation (2.5M, 900K, etc.)
    if SUFFIX_NUMBER_PATTERN.match(str(value).strip()):
        return True

    # Check for parentheses negative notation
    if PARENTHESES_NEGATIVE_PATTERN.match(str(value).strip()):
        return True

    return False


def is_date_string(value: str) -> bool:
    """Check if a string appears to be a date."""
    for fmt in DATE_FORMATS:
        try:
            datetime.strptime(str(value).strip(), fmt)
            return True
        except ValueError:
            continue
    return False


def is_boolean_like(value: str) -> bool:
    """Check if a string represents a boolean-like value."""
    bool_values = {
        "true", "false", "yes", "no", "y", "n",
        "1", "0", "on", "off", "enabled", "disabled"
    }
    return str(value).strip().lower() in bool_values


def detect_data_type(series: pd.Series, settings=None) -> str:
    """
    Detect the data type of a pandas Series.

    Returns one of: STRING, INTEGER, FLOAT, DATE, BOOLEAN, MIXED
    """
    if settings is None:
        settings = get_settings()

    # Get non-null values
    non_null = series.dropna()
    if len(non_null) == 0:
        return "STRING"  # Default for all-null columns

    clean_values = list(non_null)

    # Check native pandas dtype first
    if pd.api.types.is_integer_dtype(series):
        return "INTEGER"
    if pd.api.types.is_float_dtype(series):
        # Check if they're really integers stored as floats
        if all(float(v).is_integer() for v in clean_values if pd.notna(v)):
            return "INTEGER"
        return "FLOAT"
    if pd.api.types.is_bool_dtype(series):
        return "BOOLEAN"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "DATE"

    # For object dtype, analyze the actual values
    type_counts = {
        "integer": 0,
        "float": 0,
        "date": 0,
        "boolean": 0,
        "string": 0,
    }

    for value in clean_values:
        str_val = str(value).strip()

        # Check boolean first (most specific)
        if is_boolean_like(str_val):
            type_counts["boolean"] += 1
            continue

        # Check if it's a number
        try:
            num = float(str_val.replace(",", "").replace(" ", ""))
            if num.is_integer():
                type_counts["integer"] += 1
            else:
                type_counts["float"] += 1
            continue
        except (ValueError, AttributeError):
            pass

        # Check for suffix notation (2.5M, 900K)
        if SUFFIX_NUMBER_PATTERN.match(str_val):
            type_counts["float"] += 1  # These are usually floats
            continue

        # Check for date
        if is_date_string(str_val):
            type_counts["date"] += 1
            continue

        # Default to string
        type_counts["string"] += 1

    # Determine the dominant type
    total = sum(type_counts.values())
    if total == 0:
        return "STRING"

    # If any type is > 80%, use that type
    for dtype, count in type_counts.items():
        if count / total > 0.8:
            return dtype.upper()

    # If we have a mix, check if it's numbers vs strings
    numeric_count = type_counts["integer"] + type_counts["float"]
    if type_counts["string"] > 0 and numeric_count > 0:
        return "MIXED"

    # If mostly numeric with some integers and floats
    if numeric_count / total > 0.8:
        if type_counts["float"] > type_counts["integer"]:
            return "FLOAT"
        return "INTEGER"

    # If mostly dates
    if type_counts["date"] / total > 0.5:
        return "DATE"

    return "MIXED"


def detect_format_warnings(series: pd.Series, data_type: str, settings=None) -> list[str]:
    """
    Detect data quality issues and format warnings for a column.
    """
    if settings is None:
        settings = get_settings()

    warnings = []
    non_null = series.dropna()

    if len(non_null) == 0:
        warnings.append("Column is entirely null/empty")
        return warnings

    string_values = [str(v) for v in non_null]

    # Check for whitespace issues
    leading_ws = sum(1 for v in string_values if v != v.lstrip())
    trailing_ws = sum(1 for v in string_values if v != v.rstrip())
    if leading_ws > 0:
        warnings.append(f"Some values have leading whitespace ({leading_ws} values)")
    if trailing_ws > 0:
        warnings.append(f"Some values have trailing whitespace ({trailing_ws} values)")

    # Check for inconsistent casing
    unique_lower = set(v.lower() for v in string_values)
    unique_original = set(string_values)
    if len(unique_lower) < len(unique_original):
        # Find examples of inconsistent casing
        casing_groups = {}
        for v in string_values:
            key = v.lower()
            if key not in casing_groups:
                casing_groups[key] = set()
            casing_groups[key].add(v)
        inconsistent = [variants for variants in casing_groups.values() if len(variants) > 1]
        if inconsistent:
            example = list(inconsistent[0])[:3]
            warnings.append(f"Inconsistent casing detected: {example}")

    # Check for number format issues (if it looks numeric)
    if data_type in ["STRING", "MIXED"]:
        # Check for currency symbols
        currency_values = [v for v in string_values if re.match(r"^[\$\€\£\¥]", v)]
        if currency_values:
            warnings.append("Values contain currency symbols (cannot aggregate directly)")

        # Check for K/M/B suffixes
        suffix_values = [v for v in string_values if SUFFIX_NUMBER_PATTERN.match(v)]
        if suffix_values:
            warnings.append("Values use K/M/B suffixes (e.g., '2.5M', '900K') - cannot aggregate directly")

        # Check for percentage format
        pct_values = [v for v in string_values if PERCENTAGE_PATTERN.match(v)]
        if pct_values:
            warnings.append("Values are in percentage format (e.g., '50%')")

        # Check for parentheses negative notation
        paren_neg = [v for v in string_values if PARENTHESES_NEGATIVE_PATTERN.match(v)]
        if paren_neg:
            warnings.append("Some values use parentheses for negatives: (100) = -100")

        # Check for comma-formatted numbers
        comma_nums = [v for v in string_values if re.match(r"^\d{1,3}(,\d{3})+(\.\d+)?$", v)]
        if comma_nums:
            warnings.append("Values use comma separators (e.g., '1,000,000')")

    # Check for mixed date formats
    if data_type == "DATE" or data_type == "MIXED":
        date_formats_found = set()
        for v in string_values:
            for fmt in DATE_FORMATS:
                try:
                    datetime.strptime(v.strip(), fmt)
                    date_formats_found.add(fmt)
                    break
                except ValueError:
                    continue
        if len(date_formats_found) > 1:
            warnings.append(f"Mixed date formats detected ({len(date_formats_found)} different formats)")

    # Check for empty strings (different from null)
    empty_strings = sum(1 for v in non_null if str(v).strip() == "")
    if empty_strings > 0:
        warnings.append(f"Contains {empty_strings} empty strings (different from null)")

    return warnings


def profile_column(series: pd.Series, settings=None, header_metadata: str = None) -> ColumnProfile:
    """
    Generate a complete profile for a single column.
    """
    if settings is None:
        settings = get_settings()

    name = series.name if series.name else "unnamed"
    name = str(name)

    # Count nulls
    null_count = series.isna().sum()

    # Get non-null values
    non_null = series.dropna()

    # Count unique values
    unique_values = non_null.nunique()

    # Detect data type
    data_type = detect_data_type(series, settings)

    # Get sample values
    unique_list = non_null.unique().tolist()
    unique_str = [str(v) for v in unique_list]

    # Determine sample vs all values
    if unique_values <= settings.cardinality_threshold:
        all_values = unique_str
        sample_values = unique_str
    else:
        all_values = None
        sample_values = unique_str[: settings.sample_values_count]

    # Compute numeric stats if applicable
    min_value = None
    max_value = None
    mean_value = None

    if data_type in ["INTEGER", "FLOAT"] and len(non_null) > 0:
        try:
            # Try to convert to numeric
            numeric = pd.to_numeric(non_null, errors="coerce")
            numeric = numeric.dropna()
            if len(numeric) > 0:
                min_value = float(numeric.min())
                max_value = float(numeric.max())
                mean_value = float(numeric.mean())
        except Exception:
            pass  # Can't compute stats, leave as None

    # Detect format warnings
    format_warnings = detect_format_warnings(series, data_type, settings)
    if not format_warnings:
        format_warnings = None

    return ColumnProfile(
        name=name,
        data_type=data_type,
        unique_values=unique_values,
        sample_values=sample_values,
        null_count=null_count,
        all_values=all_values,
        min_value=min_value,
        max_value=max_value,
        mean_value=mean_value,
        format_warnings=format_warnings,
        header_metadata=header_metadata,
    )


def profile_columns(
    df: pd.DataFrame,
    settings=None,
    header_metadata: dict[int, str] = None,
) -> list[ColumnProfile]:
    """
    Generate profiles for all columns in a DataFrame.

    Args:
        df: pandas DataFrame to profile
        settings: Optional Settings object (uses global settings if not provided)
        header_metadata: Optional dict mapping column index (0-based) to metadata
                        string from the row above headers

    Returns:
        List of ColumnProfile objects, one per column
    """
    if settings is None:
        settings = get_settings()

    header_metadata = header_metadata or {}

    profiles = []
    for col_idx, column in enumerate(df.columns):
        col_metadata = header_metadata.get(col_idx)
        profile = profile_column(df[column], settings, col_metadata)
        profiles.append(profile)

    return profiles


def summarize_data_quality(profiles: list[ColumnProfile]) -> dict:
    """
    Generate a summary of data quality issues across all columns.

    Returns a dict with:
    - total_columns: int
    - columns_with_warnings: int
    - columns_with_nulls: int
    - total_warnings: int
    - warning_types: dict of warning pattern -> count
    - mixed_type_columns: list of column names with MIXED type
    """
    total_warnings = 0
    columns_with_warnings = 0
    columns_with_nulls = 0
    warning_types = {}
    mixed_type_columns = []

    for profile in profiles:
        if profile.null_count > 0:
            columns_with_nulls += 1

        if profile.data_type == "MIXED":
            mixed_type_columns.append(profile.name)

        if profile.format_warnings:
            columns_with_warnings += 1
            total_warnings += len(profile.format_warnings)
            for warning in profile.format_warnings:
                # Extract warning type (first few words)
                warning_key = warning.split(":")[0].strip()
                warning_types[warning_key] = warning_types.get(warning_key, 0) + 1

    return {
        "total_columns": len(profiles),
        "columns_with_warnings": columns_with_warnings,
        "columns_with_nulls": columns_with_nulls,
        "total_warnings": total_warnings,
        "warning_types": warning_types,
        "mixed_type_columns": mixed_type_columns,
    }
