"""Tests for the column profiler module."""

import pytest
import pandas as pd
import numpy as np
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.column_profiler import (
    detect_data_type,
    detect_format_warnings,
    profile_column,
    profile_columns,
    summarize_data_quality,
)
from config.settings import Settings


@pytest.fixture
def default_settings():
    """Create default settings for testing."""
    return Settings()


class TestDetectDataType:
    """Tests for data type detection."""

    def test_clean_integers(self, default_settings):
        series = pd.Series([1, 2, 3, 4, 5])
        assert detect_data_type(series, default_settings) == "INTEGER"

    def test_clean_floats(self, default_settings):
        series = pd.Series([1.5, 2.7, 3.14, 4.0, 5.5])
        assert detect_data_type(series, default_settings) == "FLOAT"

    def test_integers_as_floats(self, default_settings):
        """Whole numbers stored as floats should be detected as INTEGER."""
        series = pd.Series([1.0, 2.0, 3.0, 4.0])
        assert detect_data_type(series, default_settings) == "INTEGER"

    def test_clean_strings(self, default_settings):
        series = pd.Series(["Alpha", "Beta", "Gamma"])
        assert detect_data_type(series, default_settings) == "STRING"

    def test_mixed_types(self, default_settings):
        """Mix of numbers and strings should be MIXED."""
        series = pd.Series([1, 2, "three", 4])
        assert detect_data_type(series, default_settings) == "MIXED"

    def test_all_nulls(self, default_settings):
        """All null column should default to STRING."""
        series = pd.Series([None, None, None])
        assert detect_data_type(series, default_settings) == "STRING"

    def test_numeric_strings(self, default_settings):
        """Numbers stored as strings."""
        series = pd.Series(["1", "2", "3", "4"])
        # These could be detected as INTEGER, STRING, or MIXED depending on implementation
        dtype = detect_data_type(series, default_settings)
        assert dtype in ["INTEGER", "STRING", "MIXED"]  # Implementation may vary

    def test_boolean_native(self, default_settings):
        series = pd.Series([True, False, True, False])
        assert detect_data_type(series, default_settings) == "BOOLEAN"


class TestDetectFormatWarnings:
    """Tests for format warning detection."""

    def test_leading_whitespace(self, default_settings):
        series = pd.Series([" Acme", "Beta", " Gamma"])
        warnings = detect_format_warnings(series, "STRING", default_settings)
        assert any("leading whitespace" in w.lower() for w in warnings)

    def test_trailing_whitespace(self, default_settings):
        series = pd.Series(["Acme ", "Beta", "Gamma "])
        warnings = detect_format_warnings(series, "STRING", default_settings)
        assert any("trailing whitespace" in w.lower() for w in warnings)

    def test_inconsistent_casing(self, default_settings):
        series = pd.Series(["Active", "ACTIVE", "active", "Inactive"])
        warnings = detect_format_warnings(series, "STRING", default_settings)
        assert any("casing" in w.lower() for w in warnings)

    def test_currency_symbols(self, default_settings):
        series = pd.Series(["$1,000", "$2,500", "$3,000"])
        warnings = detect_format_warnings(series, "STRING", default_settings)
        assert any("currency" in w.lower() for w in warnings)

    def test_suffix_notation(self, default_settings):
        series = pd.Series(["2.5M", "900K", "1.2B"])
        warnings = detect_format_warnings(series, "STRING", default_settings)
        assert any("suffix" in w.lower() or "k/m/b" in w.lower() for w in warnings)

    def test_no_warnings_for_clean_data(self, default_settings):
        series = pd.Series(["Alpha", "Beta", "Gamma", "Delta"])
        warnings = detect_format_warnings(series, "STRING", default_settings)
        # Clean data should have no warnings
        assert len(warnings) == 0


class TestProfileColumn:
    """Tests for single column profiling."""

    def test_basic_profile(self, default_settings):
        series = pd.Series([1, 2, 3, 4, 5], name="Numbers")
        profile = profile_column(series, default_settings)

        assert profile.name == "Numbers"
        assert profile.data_type == "INTEGER"
        assert profile.unique_values == 5
        assert profile.null_count == 0
        assert profile.min_value == 1.0
        assert profile.max_value == 5.0
        assert profile.mean_value == 3.0

    def test_with_nulls(self, default_settings):
        series = pd.Series([1, None, 3, None, 5], name="WithNulls")
        profile = profile_column(series, default_settings)

        assert profile.null_count == 2
        assert profile.unique_values == 3  # 1, 3, 5

    def test_low_cardinality_all_values(self, default_settings):
        """Low cardinality columns should have all_values populated."""
        series = pd.Series(["A", "B", "C", "A", "B"], name="Category")
        profile = profile_column(series, default_settings)

        assert profile.all_values is not None
        assert set(profile.all_values) == {"A", "B", "C"}

    def test_high_cardinality_no_all_values(self, default_settings):
        """High cardinality columns should not have all_values."""
        # Create 25 unique values (above threshold of 20)
        series = pd.Series([f"Val_{i}" for i in range(25)], name="HighCard")
        profile = profile_column(series, default_settings)

        assert profile.all_values is None
        assert len(profile.sample_values) <= default_settings.sample_values_count


class TestProfileColumns:
    """Tests for profiling multiple columns."""

    def test_profile_dataframe(self, default_settings):
        df = pd.DataFrame({
            "Name": ["Alice", "Bob", "Charlie"],
            "Age": [25, 30, 35],
            "Score": [85.5, 90.0, 88.5],
        })

        profiles = profile_columns(df, default_settings)

        assert len(profiles) == 3
        assert profiles[0].name == "Name"
        assert profiles[0].data_type == "STRING"
        assert profiles[1].name == "Age"
        assert profiles[1].data_type == "INTEGER"
        assert profiles[2].name == "Score"
        assert profiles[2].data_type == "FLOAT"


class TestSummarizeDataQuality:
    """Tests for data quality summary."""

    def test_summary_structure(self, default_settings):
        df = pd.DataFrame({
            "Clean": ["A", "B", "C"],
            "WithNulls": [1, None, 3],
            "Messy": ["  x", "y ", "???"],
        })

        profiles = profile_columns(df, default_settings)
        summary = summarize_data_quality(profiles)

        assert "total_columns" in summary
        assert "columns_with_warnings" in summary
        assert "columns_with_nulls" in summary
        assert summary["total_columns"] == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
