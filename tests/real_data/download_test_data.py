#!/usr/bin/env python3
"""
Download real-world Excel files for testing the ingestion pipeline.

These are public datasets that have characteristics of real messy business data.
"""

import urllib.request
import os
from pathlib import Path

# Directory for downloaded files
OUTPUT_DIR = Path(__file__).parent

# Public Excel datasets to download
DATASETS = [
    {
        "name": "financial_sample.xlsx",
        "url": "https://go.microsoft.com/fwlink/?LinkID=521962",
        "description": "Microsoft Power BI Financial Sample - sales data with segments, countries, products",
    },
    {
        "name": "superstore_sample.xlsx",
        "url": "https://github.com/tableau/tableau-gallery-files/raw/main/Sample%20-%20Superstore.xls",
        "description": "Tableau Superstore Sample - orders, returns, people tables",
    },
]

# Note: For Kaggle datasets, you need to use the Kaggle API
KAGGLE_DATASETS = [
    {
        "dataset": "shivavashishtha/dirty-excel-data",
        "description": "Dirty Excel Data - specifically designed for testing data cleaning",
    },
]


def download_file(url: str, filename: str, description: str) -> bool:
    """Download a file from URL."""
    filepath = OUTPUT_DIR / filename

    if filepath.exists():
        print(f"  [EXISTS] {filename}")
        return True

    print(f"  [DOWNLOADING] {filename}")
    print(f"    {description}")

    try:
        # Set a user agent to avoid 403 errors
        request = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            with open(filepath, 'wb') as f:
                f.write(response.read())
        print(f"    [OK] Downloaded to {filepath}")
        return True
    except Exception as e:
        print(f"    [FAILED] {e}")
        return False


def main():
    print("=" * 60)
    print("Downloading Real-World Test Excel Files")
    print("=" * 60)
    print()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Direct Downloads:")
    for dataset in DATASETS:
        download_file(
            dataset["url"],
            dataset["name"],
            dataset["description"],
        )

    print()
    print("=" * 60)
    print("Kaggle Datasets (Manual Download Required)")
    print("=" * 60)
    print()
    print("To download Kaggle datasets, you need to:")
    print("1. Install kaggle: pip install kaggle")
    print("2. Set up API credentials: ~/.kaggle/kaggle.json")
    print("3. Run the following commands:")
    print()

    for ds in KAGGLE_DATASETS:
        print(f"  kaggle datasets download -d {ds['dataset']} -p {OUTPUT_DIR}")
        print(f"    ({ds['description']})")

    print()
    print("=" * 60)
    print("Other Recommended Sources")
    print("=" * 60)
    print()
    print("1. Data.gov (data.gov)")
    print("   - Search for Excel downloads, filter by format")
    print("   - Good for government/public sector data")
    print()
    print("2. World Bank Open Data (data.worldbank.org)")
    print("   - Economic indicators, often in messy Excel format")
    print()
    print("3. Your Own Data!")
    print("   - The best test is with your actual business Excel files")
    print("   - Copy them to this directory for testing")
    print()
    print(f"Test files should be placed in: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
