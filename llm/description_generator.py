"""
Generate table descriptions using LLM with Pydantic validation.

Produces the description, purpose, and caveats fields of the TableCard.
"""

from typing import Optional

import pandas as pd

from models.table_card import ColumnProfile
from config.settings import Settings, get_settings
from .bedrock_client import LLMClient, get_llm_client
from .schemas import TableDescriptionResponse


DESCRIPTION_SYSTEM_PROMPT = """You are a data analyst examining a table extracted from an Excel file.
Your job is to understand what this table contains and describe it clearly.

Be HONEST about data quality. If there are issues, say so explicitly. Don't assume the data is clean.
Focus on what the data actually shows, not what it ideally might show."""


def format_column_info(profiles: list[ColumnProfile]) -> str:
    """Format column profiles as text for the LLM prompt."""
    lines = []
    for p in profiles:
        line = f"- {p.name} ({p.data_type}): {p.unique_values} unique values"
        if p.null_count > 0:
            line += f", {p.null_count} nulls"
        if p.all_values:
            line += f"\n  All values: {p.all_values}"
        elif p.sample_values:
            line += f"\n  Sample values: {p.sample_values}"
        if p.format_warnings:
            line += f"\n  WARNINGS: {p.format_warnings}"
        lines.append(line)
    return "\n".join(lines)


def format_sample_data(df: pd.DataFrame, max_rows: int = 20) -> str:
    """Format sample rows as text for the LLM prompt."""
    sample = df.head(max_rows)
    return sample.to_string(index=False)


def generate_description(
    df: pd.DataFrame,
    profiles: list[ColumnProfile],
    source_file: str,
    source_sheet: str,
    source_range: str,
    client: Optional[LLMClient] = None,
    settings: Optional[Settings] = None,
) -> tuple[str, str, str]:
    """
    Generate description, purpose, and caveats for a table.

    Args:
        df: The DataFrame (first N rows will be used)
        profiles: Column profiles from profiling step
        source_file: Original Excel filename
        source_sheet: Sheet name
        source_range: Cell range extracted
        client: Optional LLM client (creates one if not provided)
        settings: Optional settings (uses global if not provided)

    Returns:
        Tuple of (description, purpose, caveats)
    """
    if settings is None:
        settings = get_settings()

    if client is None:
        client = get_llm_client(settings)

    # Build the prompt
    column_info = format_column_info(profiles)
    sample_data = format_sample_data(df, settings.sample_rows_for_llm)

    prompt = f"""Analyze this table extracted from Excel.

Source: {source_file}, Sheet: "{source_sheet}", Range: {source_range}
Rows: {len(df)} (excluding header)
Columns: {len(df.columns)}

COLUMN PROFILES:
{column_info}

SAMPLE DATA (first {min(len(df), settings.sample_rows_for_llm)} rows):
{sample_data}

Based on this information, provide a description, purpose, and caveats for this table."""

    try:
        # Use Pydantic-validated response
        response, _ = client.invoke_with_schema(
            prompt=prompt,
            response_schema=TableDescriptionResponse,
            system=DESCRIPTION_SYSTEM_PROMPT,
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
        )

        return response.description, response.purpose, response.caveats

    except ValueError as e:
        # Schema validation failed after retries
        return (
            f"Table description could not be generated: {str(e)}",
            "General data analysis",
            "Unable to analyze data quality automatically",
        )
    except Exception as e:
        # LLM call failed entirely
        return (
            f"Table description could not be generated: {str(e)}",
            "General data analysis",
            "Unable to analyze data quality automatically",
        )


def extract_initial_tags(description: str, purpose: str) -> list[str]:
    """
    Extract initial tags from the description and purpose.

    Simple keyword extraction - finds likely category words.
    """
    # Common business/data terms to look for
    tag_candidates = [
        "client", "clients", "customer", "customers",
        "deal", "deals", "opportunity", "opportunities", "pipeline",
        "revenue", "sales", "financial", "finance",
        "employee", "employees", "staff", "hr", "personnel",
        "product", "products", "inventory", "sku",
        "project", "projects", "task", "tasks",
        "partner", "partners", "vendor", "vendors",
        "industry", "segment", "region", "geography",
        "status", "stage", "active", "dormant",
        "date", "time", "timeline", "schedule",
        "contact", "contacts", "email", "phone",
        "marketing", "campaign", "lead", "leads",
        "support", "ticket", "tickets", "issue", "issues",
    ]

    combined = (description + " " + purpose).lower()
    found_tags = []

    for tag in tag_candidates:
        if tag in combined:
            # Use singular form for consistency
            singular = tag.rstrip("s") if tag.endswith("s") and len(tag) > 3 else tag
            if singular not in found_tags:
                found_tags.append(singular)

    # Limit to most relevant
    return found_tags[:10]
