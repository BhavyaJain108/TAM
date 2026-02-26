"""
Configuration settings for the ingestion pipeline.

Supports both AWS deployment and local development modes.
"""

import os
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path


@dataclass
class Settings:
    """
    Configuration settings loaded from environment variables.

    For local development, set STORAGE_MODE=local to use filesystem instead of S3.
    For AWS deployment, set STORAGE_MODE=aws and configure the S3/Athena settings.
    """

    # === STORAGE MODE ===
    storage_mode: str = "local"
    """'local' for filesystem, 'aws' for S3/Athena."""

    # === LOCAL MODE SETTINGS ===
    local_data_dir: str = "./data"
    """Directory for local data storage (Parquet files, metadata cards)."""

    local_raw_dir: str = "./data/raw"
    """Directory for raw Excel files in local mode."""

    local_processed_dir: str = "./data/processed"
    """Directory for processed Parquet files in local mode."""

    local_metadata_dir: str = "./data/metadata"
    """Directory for metadata cards (JSON) in local mode."""

    # === AWS S3 SETTINGS ===
    s3_bucket_raw: str = ""
    """S3 bucket for raw Excel uploads."""

    s3_bucket_processed: str = ""
    """S3 bucket for processed Parquet files and metadata cards."""

    s3_prefix_processed: str = "processed"
    """S3 prefix for Parquet files."""

    s3_prefix_metadata: str = "metadata"
    """S3 prefix for metadata cards."""

    # === AWS ATHENA SETTINGS ===
    athena_database: str = "table_cards"
    """Glue catalog database name for Athena tables."""

    athena_workgroup: str = "primary"
    """Athena workgroup to use for queries."""

    athena_output_location: str = ""
    """S3 location for Athena query results."""

    # === AWS REGION ===
    aws_region: str = "us-east-1"
    """AWS region for all services."""

    # === LLM SETTINGS ===
    llm_provider: str = "bedrock"
    """LLM provider: 'bedrock', 'anthropic', or 'mock'."""

    bedrock_model_id: str = "anthropic.claude-3-sonnet-20240229-v1:0"
    """Bedrock model ID for Claude."""

    anthropic_api_key: str = ""
    """Anthropic API key (if using 'anthropic' provider)."""

    anthropic_model: str = "claude-3-sonnet-20240229"
    """Anthropic model name (if using 'anthropic' provider)."""

    llm_max_tokens: int = 4096
    """Maximum tokens for LLM responses."""

    llm_temperature: float = 0.0
    """Temperature for LLM responses (0.0 = deterministic)."""

    # === TABLE ID SETTINGS ===
    table_id_prefix: str = "tbl"
    """Prefix for auto-generated table IDs."""

    # === PROFILING SETTINGS ===
    cardinality_threshold: int = 20
    """Max unique values to include in all_values field."""

    sample_values_count: int = 10
    """Number of sample values to include for high-cardinality columns."""

    sample_rows_for_llm: int = 20
    """Number of rows to send to LLM for analysis."""

    # === PLACEHOLDER DETECTION ===
    placeholder_values: list[str] = field(
        default_factory=lambda: [
            "???",
            "N/A",
            "n/a",
            "NA",
            "TBD",
            "tbd",
            "-",
            "--",
            "NULL",
            "null",
            "None",
            "none",
            "#N/A",
            "#REF!",
            "#VALUE!",
            "#DIV/0!",
            "PENDING",
            "pending",
            "UNKNOWN",
            "unknown",
        ]
    )
    """Values to detect as placeholders in data."""

    @classmethod
    def from_env(cls) -> "Settings":
        """Load settings from environment variables."""
        return cls(
            # Storage mode
            storage_mode=os.getenv("STORAGE_MODE", "local"),
            # Local paths
            local_data_dir=os.getenv("LOCAL_DATA_DIR", "./data"),
            local_raw_dir=os.getenv("LOCAL_RAW_DIR", "./data/raw"),
            local_processed_dir=os.getenv("LOCAL_PROCESSED_DIR", "./data/processed"),
            local_metadata_dir=os.getenv("LOCAL_METADATA_DIR", "./data/metadata"),
            # S3
            s3_bucket_raw=os.getenv("S3_BUCKET_RAW", ""),
            s3_bucket_processed=os.getenv("S3_BUCKET_PROCESSED", ""),
            s3_prefix_processed=os.getenv("S3_PREFIX_PROCESSED", "processed"),
            s3_prefix_metadata=os.getenv("S3_PREFIX_METADATA", "metadata"),
            # Athena
            athena_database=os.getenv("ATHENA_DATABASE", "table_cards"),
            athena_workgroup=os.getenv("ATHENA_WORKGROUP", "primary"),
            athena_output_location=os.getenv("ATHENA_OUTPUT_LOCATION", ""),
            # AWS
            aws_region=os.getenv("AWS_REGION", "us-east-1"),
            # LLM
            llm_provider=os.getenv("LLM_PROVIDER", "bedrock"),
            bedrock_model_id=os.getenv(
                "BEDROCK_MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0"
            ),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-3-sonnet-20240229"),
            llm_max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4096")),
            llm_temperature=float(os.getenv("LLM_TEMPERATURE", "0.0")),
            # Table ID
            table_id_prefix=os.getenv("TABLE_ID_PREFIX", "tbl"),
            # Profiling
            cardinality_threshold=int(os.getenv("CARDINALITY_THRESHOLD", "20")),
            sample_values_count=int(os.getenv("SAMPLE_VALUES_COUNT", "10")),
            sample_rows_for_llm=int(os.getenv("SAMPLE_ROWS_FOR_LLM", "20")),
        )

    def ensure_local_dirs(self) -> None:
        """Create local directories if they don't exist (local mode only)."""
        if self.storage_mode == "local":
            Path(self.local_data_dir).mkdir(parents=True, exist_ok=True)
            Path(self.local_raw_dir).mkdir(parents=True, exist_ok=True)
            Path(self.local_processed_dir).mkdir(parents=True, exist_ok=True)
            Path(self.local_metadata_dir).mkdir(parents=True, exist_ok=True)

    def get_parquet_path(self, table_id: str) -> str:
        """Get the storage path for a table's Parquet file."""
        if self.storage_mode == "local":
            return str(Path(self.local_processed_dir) / table_id / f"{table_id}.parquet")
        else:
            return f"s3://{self.s3_bucket_processed}/{self.s3_prefix_processed}/{table_id}/{table_id}.parquet"

    def get_card_path(self, table_id: str) -> str:
        """Get the storage path for a table's metadata card."""
        if self.storage_mode == "local":
            return str(Path(self.local_metadata_dir) / table_id / "card.json")
        else:
            return f"s3://{self.s3_bucket_processed}/{self.s3_prefix_metadata}/{table_id}/card.json"

    def validate(self) -> list[str]:
        """Validate settings and return list of errors (empty if valid)."""
        errors = []

        if self.storage_mode == "aws":
            if not self.s3_bucket_processed:
                errors.append("S3_BUCKET_PROCESSED is required in AWS mode")
            if not self.athena_output_location:
                errors.append("ATHENA_OUTPUT_LOCATION is required in AWS mode")

        if self.llm_provider == "anthropic" and not self.anthropic_api_key:
            errors.append("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")

        return errors


# Global settings instance (lazy loaded)
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get the global settings instance, loading from environment if needed."""
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings


def reset_settings() -> None:
    """Reset settings (useful for testing)."""
    global _settings
    _settings = None
