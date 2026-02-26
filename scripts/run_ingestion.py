#!/usr/bin/env python3
"""
Batch ingestion script.

Processes all files defined in config/table_configs.yaml, or a specific file by name.

Usage:
    # Process all configured files
    python scripts/run_ingestion.py

    # Process a specific config
    python scripts/run_ingestion.py --config financial_sample

    # Dry run (no storage, no LLM)
    python scripts/run_ingestion.py --dry-run

    # Skip LLM generation
    python scripts/run_ingestion.py --skip-llm

    # Verbose output
    python scripts/run_ingestion.py -v
"""

import argparse
import sys
import tempfile
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml
import boto3

from config.settings import get_settings, reset_settings
from ingestion.card_builder import build_card
from ingestion.excel_reader import list_sheets


def load_table_configs() -> dict:
    """Load table configurations from YAML."""
    config_path = Path(__file__).parent.parent / "config" / "table_configs.yaml"
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    return {}


def download_from_s3(bucket: str, key: str, local_path: Path, region: str) -> None:
    """Download a file from S3."""
    s3 = boto3.client('s3', region_name=region)
    s3.download_file(bucket, key, str(local_path))


def process_config(
    config_name: str,
    config: dict,
    settings,
    temp_dir: Path,
    verbose: bool = False,
    skip_llm: bool = False,
    skip_storage: bool = False,
) -> list[dict]:
    """Process a single configuration (may have multiple tables across sheets)."""
    results = []

    s3_key = config['s3_key']
    local_path = temp_dir / s3_key.split('/')[-1]

    # Download file
    if verbose:
        print(f"  Downloading: s3://{settings.s3_bucket_raw}/{s3_key}")
    download_from_s3(settings.s3_bucket_raw, s3_key, local_path, settings.aws_region)

    # Process each table (can be multiple tables per sheet)
    tables_config = config.get('tables', [])
    if not tables_config:
        # If no tables specified, auto-detect one table per sheet
        sheet_names = list_sheets(str(local_path))
        tables_config = [
            {'sheet': name, 'table_id': f"{config_name}_{name}".lower().replace(' ', '_'), 'start_cell': 'A1', 'end_cell': None}
            for name in sheet_names
        ]

    for table_config in tables_config:
        sheet_name = table_config['sheet']
        table_id = table_config.get('table_id') or f"{config_name}_{sheet_name}".lower().replace(' ', '_')
        start_cell = table_config.get('start_cell', 'A1')
        end_cell = table_config.get('end_cell')

        if verbose:
            print(f"  Processing table: {table_id} (sheet: {sheet_name}, {start_cell} -> {end_cell or 'auto'})")

        try:
            card = build_card(
                file_path=str(local_path),
                sheet_name=sheet_name,
                start_cell=start_cell,
                end_cell=end_cell,
                table_id=table_id,
                settings=settings,
                skip_llm=skip_llm,
                skip_storage=skip_storage,
            )

            results.append({
                'config': config_name,
                'sheet': sheet_name,
                'table_id': card.table_id,
                'rows': card.data_quality.row_count,
                'columns': card.data_quality.column_count,
                'status': 'success',
                'error': None,
            })

            if verbose:
                print(f"    -> Created: {card.table_id} ({card.data_quality.row_count} rows)")

        except Exception as e:
            results.append({
                'config': config_name,
                'sheet': sheet_name,
                'table_id': table_id,
                'rows': None,
                'columns': None,
                'status': 'error',
                'error': str(e),
            })
            print(f"    -> ERROR: {e}")

    return results


def main():
    parser = argparse.ArgumentParser(description='Batch ingestion from table_configs.yaml')
    parser.add_argument('--config', '-c', help='Process only this config name')
    parser.add_argument('--dry-run', action='store_true', help='Skip storage and LLM')
    parser.add_argument('--skip-llm', action='store_true', help='Skip LLM generation')
    parser.add_argument('--skip-storage', action='store_true', help='Skip saving to storage')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    args = parser.parse_args()

    # Load settings
    reset_settings()
    settings = get_settings()

    # Validate settings
    errors = settings.validate()
    if errors:
        print("Configuration errors:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    # Load configs
    table_configs = load_table_configs()
    if not table_configs:
        print("No configurations found in config/table_configs.yaml")
        sys.exit(1)

    # Filter to specific config if requested
    if args.config:
        if args.config not in table_configs:
            print(f"Config '{args.config}' not found. Available: {list(table_configs.keys())}")
            sys.exit(1)
        table_configs = {args.config: table_configs[args.config]}

    # Flags
    skip_llm = args.skip_llm or args.dry_run
    skip_storage = args.skip_storage or args.dry_run

    print("=" * 60)
    print("TAM Batch Ingestion")
    print("=" * 60)
    print(f"Storage mode: {settings.storage_mode}")
    print(f"Configs to process: {len(table_configs)}")
    print(f"Skip LLM: {skip_llm}")
    print(f"Skip storage: {skip_storage}")
    print("=" * 60)

    # Process
    all_results = []
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        for config_name, config in table_configs.items():
            print(f"\n[{config_name}]")
            results = process_config(
                config_name=config_name,
                config=config,
                settings=settings,
                temp_dir=temp_path,
                verbose=args.verbose,
                skip_llm=skip_llm,
                skip_storage=skip_storage,
            )
            all_results.extend(results)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    success = [r for r in all_results if r['status'] == 'success']
    failed = [r for r in all_results if r['status'] == 'error']

    print(f"Processed: {len(all_results)}")
    print(f"Success: {len(success)}")
    print(f"Failed: {len(failed)}")

    if success:
        print("\nSuccessful:")
        for r in success:
            print(f"  - {r['table_id']}: {r['rows']} rows, {r['columns']} cols")

    if failed:
        print("\nFailed:")
        for r in failed:
            print(f"  - {r['config']}/{r['sheet']}: {r['error']}")

    print("=" * 60)

    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(main())
