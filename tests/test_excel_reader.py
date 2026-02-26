"""Tests for the Excel reader module."""

import pytest
import pandas as pd
from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.excel_reader import (
    parse_cell_reference,
    normalize_range,
    read_rectangle,
    list_sheets,
    InvalidRangeError,
    SheetNotFoundError,
    FileReadError,
)


class TestParseCellReference:
    """Tests for parse_cell_reference function."""

    def test_simple_cell(self):
        assert parse_cell_reference("A1") == (1, 1)
        assert parse_cell_reference("B2") == (2, 2)
        assert parse_cell_reference("Z26") == (26, 26)

    def test_double_letter_column(self):
        assert parse_cell_reference("AA1") == (1, 27)
        assert parse_cell_reference("AB1") == (1, 28)
        assert parse_cell_reference("AZ1") == (1, 52)

    def test_triple_letter_column(self):
        assert parse_cell_reference("AAA1") == (1, 703)

    def test_large_row_number(self):
        assert parse_cell_reference("A1000") == (1000, 1)
        assert parse_cell_reference("A99999") == (99999, 1)

    def test_lowercase(self):
        assert parse_cell_reference("a1") == (1, 1)
        assert parse_cell_reference("aa1") == (1, 27)

    def test_with_whitespace(self):
        assert parse_cell_reference(" B2 ") == (2, 2)

    def test_invalid_reference(self):
        with pytest.raises(InvalidRangeError):
            parse_cell_reference("1A")  # Number before letter

        with pytest.raises(InvalidRangeError):
            parse_cell_reference("A")  # No row number

        with pytest.raises(InvalidRangeError):
            parse_cell_reference("123")  # No column letter

        with pytest.raises(InvalidRangeError):
            parse_cell_reference("")  # Empty string


class TestNormalizeRange:
    """Tests for normalize_range function."""

    def test_normal_range(self):
        start, end = normalize_range("B2", "F10")
        assert start == (2, 2)
        assert end == (10, 6)

    def test_reversed_range(self):
        """Reversed ranges should be normalized."""
        start, end = normalize_range("F10", "B2")
        assert start == (2, 2)
        assert end == (10, 6)

    def test_single_cell_range(self):
        start, end = normalize_range("C3", "C3")
        assert start == (3, 3)
        assert end == (3, 3)


class TestReadRectangle:
    """Tests for read_rectangle function."""

    @pytest.fixture
    def test_files_dir(self):
        return Path(__file__).parent / "fixtures"

    def test_file_not_found(self):
        with pytest.raises(FileReadError):
            read_rectangle("/nonexistent/file.xlsx", "Sheet1", "A1", "B2")

    def test_invalid_file_format(self, tmp_path):
        # Create a text file with .xlsx extension
        fake_xlsx = tmp_path / "fake.xlsx"
        fake_xlsx.write_text("not an excel file")

        with pytest.raises(FileReadError):
            read_rectangle(str(fake_xlsx), "Sheet1", "A1", "B2")

    def test_sheet_not_found(self, test_files_dir):
        """Test that non-existent sheet raises error with available sheets listed."""
        test_file = test_files_dir / "test_clean.xlsx"
        if not test_file.exists():
            pytest.skip("Test file not generated yet")

        with pytest.raises(SheetNotFoundError) as exc_info:
            read_rectangle(str(test_file), "NonexistentSheet", "A1", "B2")

        # Error message should include available sheets
        assert "Available sheets" in str(exc_info.value)


class TestReadRectangleWithData:
    """Tests that require actual Excel files."""

    @pytest.fixture
    def test_files_dir(self):
        return Path(__file__).parent / "fixtures"

    def test_read_clean_data(self, test_files_dir):
        """Test reading clean, well-formatted data."""
        test_file = test_files_dir / "test_clean.xlsx"
        if not test_file.exists():
            pytest.skip("Test file not generated yet - run generate_test_files.py")

        df, header_metadata = read_rectangle(str(test_file), "Clients", "B2", "G12")

        # Should have 10 data rows (excluding header)
        assert len(df) == 10

        # Should have 6 columns
        assert len(df.columns) == 6

        # Check column names
        expected_cols = ["Client Name", "Industry", "Region", "Annual Revenue", "Status", "Start Date"]
        assert list(df.columns) == expected_cols

        # Header metadata should be a dict (may be empty)
        assert isinstance(header_metadata, dict)

    def test_read_messy_data(self, test_files_dir):
        """Test reading messy data with various issues."""
        test_file = test_files_dir / "test_messy.xlsx"
        if not test_file.exists():
            pytest.skip("Test file not generated yet - run generate_test_files.py")

        df, header_metadata = read_rectangle(str(test_file), "Deals", "B2", "G11")

        # Should have data
        assert len(df) > 0

        # Check for expected columns
        assert "Acct" in df.columns
        assert "$ Val" in df.columns


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
