"""
Athena/S3 storage functionality.

Handles converting DataFrames to Parquet and storing in S3 (AWS mode)
or local filesystem (local mode). Also creates Athena tables.
"""

import re
from pathlib import Path
from typing import Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from config.settings import Settings, get_settings
from models.table_card import ColumnProfile


class StorageError(Exception):
    """Base exception for storage errors."""
    pass


class AthenaError(StorageError):
    """Raised when Athena operations fail."""
    pass


class S3Error(StorageError):
    """Raised when S3 operations fail."""
    pass


# Mapping from detected data types to Athena types
ATHENA_TYPE_MAP = {
    "STRING": "STRING",
    "INTEGER": "BIGINT",
    "FLOAT": "DOUBLE",
    "DATE": "STRING",  # Keep as string to preserve format
    "BOOLEAN": "BOOLEAN",
    "MIXED": "STRING",  # Mixed types become strings
}


def sanitize_column_name(name: str) -> str:
    """
    Sanitize a column name for use in Athena.

    Athena column names:
    - Must start with a letter or underscore
    - Can contain letters, digits, underscores
    - Are case-insensitive

    We'll preserve the original name but quote it in SQL.
    This function just validates it's usable.
    """
    if not name:
        return "unnamed_column"

    # Replace problematic characters with underscores for the Parquet schema
    # but we'll use the original name (quoted) in Athena
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", str(name))

    # Ensure it starts with a letter or underscore
    if sanitized[0].isdigit():
        sanitized = "_" + sanitized

    return sanitized


def quote_column_name(name: str) -> str:
    """
    Quote a column name for use in SQL.

    Uses double quotes, which is ANSI SQL standard and works in Athena.
    """
    # Escape any existing double quotes
    escaped = str(name).replace('"', '""')
    return f'"{escaped}"'


def get_athena_column_type(profile: ColumnProfile) -> str:
    """Get the Athena data type for a column based on its profile."""
    return ATHENA_TYPE_MAP.get(profile.data_type, "STRING")


def dataframe_to_parquet_bytes(df: pd.DataFrame) -> bytes:
    """Convert a DataFrame to Parquet format bytes."""
    table = pa.Table.from_pandas(df)
    buf = pa.BufferOutputStream()
    pq.write_table(table, buf)
    return buf.getvalue().to_pybytes()


def save_parquet_local(df: pd.DataFrame, file_path: str) -> str:
    """
    Save a DataFrame as a Parquet file locally.

    Args:
        df: DataFrame to save
        file_path: Local file path

    Returns:
        The file path where data was saved
    """
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    table = pa.Table.from_pandas(df)
    pq.write_table(table, str(path))

    return str(path)


def save_parquet_s3(
    df: pd.DataFrame,
    bucket: str,
    key: str,
    settings: Settings,
) -> str:
    """
    Save a DataFrame as a Parquet file in S3.

    Args:
        df: DataFrame to save
        bucket: S3 bucket name
        key: S3 object key
        settings: Settings object with AWS config

    Returns:
        S3 URI where data was saved
    """
    import boto3

    s3_client = boto3.client("s3", region_name=settings.aws_region)

    parquet_bytes = dataframe_to_parquet_bytes(df)
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=parquet_bytes,
    )

    return f"s3://{bucket}/{key}"


def create_athena_table_ddl(
    table_id: str,
    profiles: list[ColumnProfile],
    s3_location: str,
    database: str = "default",
) -> str:
    """
    Generate the CREATE EXTERNAL TABLE DDL for Athena.

    Args:
        table_id: Table identifier (becomes the table name)
        profiles: Column profiles with type information
        s3_location: S3 URI where the Parquet data is stored
        database: Athena database name

    Returns:
        DDL statement string
    """
    # Build column definitions
    columns = []
    for profile in profiles:
        col_name = quote_column_name(profile.name)
        col_type = get_athena_column_type(profile)
        columns.append(f"  {col_name} {col_type}")

    columns_str = ",\n".join(columns)

    # Remove the filename from s3_location to get the directory
    s3_dir = "/".join(s3_location.rstrip("/").rsplit("/", 1)[:-1]) + "/"

    ddl = f"""CREATE EXTERNAL TABLE IF NOT EXISTS {database}.{table_id} (
{columns_str}
)
STORED AS PARQUET
LOCATION '{s3_dir}'
TBLPROPERTIES ('parquet.compression'='SNAPPY');"""

    return ddl


def execute_athena_query(
    query: str,
    settings: Settings,
    wait: bool = True,
) -> Optional[str]:
    """
    Execute a query in Athena.

    Args:
        query: SQL query to execute
        settings: Settings object with Athena config
        wait: Whether to wait for query completion

    Returns:
        Query execution ID
    """
    import boto3
    import time

    athena_client = boto3.client("athena", region_name=settings.aws_region)

    response = athena_client.start_query_execution(
        QueryString=query,
        QueryExecutionContext={"Database": settings.athena_database},
        WorkGroup=settings.athena_workgroup,
        ResultConfiguration={
            "OutputLocation": settings.athena_output_location,
        },
    )

    execution_id = response["QueryExecutionId"]

    if wait:
        while True:
            result = athena_client.get_query_execution(QueryExecutionId=execution_id)
            state = result["QueryExecution"]["Status"]["State"]

            if state in ["SUCCEEDED", "FAILED", "CANCELLED"]:
                if state != "SUCCEEDED":
                    reason = result["QueryExecution"]["Status"].get(
                        "StateChangeReason", "Unknown error"
                    )
                    raise AthenaError(f"Query {state}: {reason}")
                break

            time.sleep(0.5)

    return execution_id


def create_athena_table(
    df: pd.DataFrame,
    table_id: str,
    profiles: list[ColumnProfile],
    settings: Optional[Settings] = None,
) -> tuple[str, str]:
    """
    Store a DataFrame and create an Athena table.

    In local mode: saves Parquet to local filesystem.
    In AWS mode: saves to S3 and creates Athena table.

    Args:
        df: DataFrame to store
        table_id: Unique table identifier
        profiles: Column profiles from profiling step
        settings: Settings object (uses global if not provided)

    Returns:
        Tuple of (parquet_path, ddl_or_local_path)
    """
    if settings is None:
        settings = get_settings()

    if settings.storage_mode == "local":
        # Local mode: just save Parquet file
        parquet_path = settings.get_parquet_path(table_id)
        save_parquet_local(df, parquet_path)
        return parquet_path, parquet_path

    else:
        # AWS mode: save to S3 and create Athena table
        s3_key = f"{settings.s3_prefix_processed}/{table_id}/{table_id}.parquet"
        s3_uri = save_parquet_s3(
            df,
            settings.s3_bucket_processed,
            s3_key,
            settings,
        )

        # Generate and execute DDL
        ddl = create_athena_table_ddl(
            table_id,
            profiles,
            s3_uri,
            settings.athena_database,
        )

        # Drop table if exists, then create
        drop_ddl = f"DROP TABLE IF EXISTS {settings.athena_database}.{table_id}"
        try:
            execute_athena_query(drop_ddl, settings)
        except AthenaError:
            pass  # Table might not exist

        execute_athena_query(ddl, settings)

        return s3_uri, ddl


def save_card_local(card_json: str, file_path: str) -> str:
    """Save a card JSON to local filesystem."""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        f.write(card_json)

    return str(path)


def save_card_s3(
    card_json: str,
    bucket: str,
    key: str,
    settings: Settings,
) -> str:
    """Save a card JSON to S3."""
    import boto3

    s3_client = boto3.client("s3", region_name=settings.aws_region)

    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=card_json.encode("utf-8"),
        ContentType="application/json",
    )

    return f"s3://{bucket}/{key}"


def save_card(
    card_json: str,
    table_id: str,
    settings: Optional[Settings] = None,
) -> str:
    """
    Save a TableCard JSON to storage.

    Args:
        card_json: JSON string of the card
        table_id: Table identifier
        settings: Settings object (uses global if not provided)

    Returns:
        Path/URI where card was saved
    """
    if settings is None:
        settings = get_settings()

    if settings.storage_mode == "local":
        card_path = settings.get_card_path(table_id)
        return save_card_local(card_json, card_path)
    else:
        s3_key = f"{settings.s3_prefix_metadata}/{table_id}/card.json"
        return save_card_s3(
            card_json,
            settings.s3_bucket_processed,
            s3_key,
            settings,
        )


def load_card_local(file_path: str) -> str:
    """Load a card JSON from local filesystem."""
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


def load_card_s3(
    bucket: str,
    key: str,
    settings: Settings,
) -> str:
    """Load a card JSON from S3."""
    import boto3

    s3_client = boto3.client("s3", region_name=settings.aws_region)

    response = s3_client.get_object(Bucket=bucket, Key=key)
    return response["Body"].read().decode("utf-8")


def load_card(
    table_id: str,
    settings: Optional[Settings] = None,
) -> Optional[str]:
    """
    Load a TableCard JSON from storage.

    Args:
        table_id: Table identifier
        settings: Settings object (uses global if not provided)

    Returns:
        JSON string of the card, or None if not found
    """
    if settings is None:
        settings = get_settings()

    try:
        if settings.storage_mode == "local":
            card_path = settings.get_card_path(table_id)
            return load_card_local(card_path)
        else:
            s3_key = f"{settings.s3_prefix_metadata}/{table_id}/card.json"
            return load_card_s3(
                settings.s3_bucket_processed,
                s3_key,
                settings,
            )
    except FileNotFoundError:
        return None
    except Exception:
        return None
