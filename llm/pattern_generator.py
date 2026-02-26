"""
Generate SQL query patterns for tables using LLM with Pydantic validation.

Creates example queries that demonstrate how to use the table effectively.
"""

from typing import Optional

from models.table_card import ColumnProfile, EntityProfile, QueryPattern
from config.settings import Settings, get_settings
from .bedrock_client import LLMClient, get_llm_client
from .schemas import QueryPatternResponse


PATTERN_SYSTEM_PROMPT = """You are a SQL expert writing example queries for a data table.

Your task is to write 5-8 realistic SQL queries that someone might run against this table.

CRITICAL RULES:
1. Use the EXACT column names provided - don't rename or modify them
2. ALWAYS quote column names with double quotes (Athena SQL standard): SELECT "Column Name" FROM table
3. Use the exact table name provided
4. Include a mix of query types: SELECT, WHERE filters, GROUP BY, COUNT, etc.
5. If a column has data quality issues (noted in warnings), ADD A WARNING COMMENT in the SQL
6. Each query should answer a realistic business question

If you can't aggregate a column, say so! Don't write queries that will fail."""


def format_for_pattern_generation(
    table_id: str,
    profiles: list[ColumnProfile],
    description: str,
    purpose: str,
    caveats: str,
    entities: list[EntityProfile],
) -> str:
    """Format information for query pattern generation."""
    # Column details with warnings
    columns_info = []
    for p in profiles:
        info = f'- "{p.name}" ({p.data_type})'
        if p.all_values:
            info += f"\n  Possible values: {p.all_values}"
        if p.format_warnings:
            info += f"\n  WARNING: {p.format_warnings}"
        columns_info.append(info)

    # Entity summary
    entity_info = []
    for e in entities:
        if e.is_primary:
            entity_info.append(f'Primary entity: {e.name} (identified by "{e.identified_by}")')
        else:
            entity_info.append(f"Secondary entity: {e.name}")

    return f"""TABLE NAME: {table_id}

DESCRIPTION: {description}

PURPOSE: {purpose}

CAVEATS: {caveats}

ENTITIES:
{chr(10).join(entity_info) if entity_info else "No entities identified"}

COLUMNS (use these exact names with double quotes):
{chr(10).join(columns_info)}

Write 5-8 SQL queries that would be useful for analyzing this data."""


def generate_query_patterns(
    table_id: str,
    profiles: list[ColumnProfile],
    description: str,
    purpose: str,
    caveats: str,
    entities: list[EntityProfile],
    client: Optional[LLMClient] = None,
    settings: Optional[Settings] = None,
) -> list[QueryPattern]:
    """
    Generate example SQL query patterns for a table.

    Args:
        table_id: The table identifier (used as table name in SQL)
        profiles: Column profiles
        description: Generated description
        purpose: Generated purpose
        caveats: Generated caveats
        entities: Extracted entities
        client: Optional LLM client
        settings: Optional settings

    Returns:
        List of QueryPattern objects
    """
    if settings is None:
        settings = get_settings()

    if client is None:
        client = get_llm_client(settings)

    prompt = format_for_pattern_generation(
        table_id, profiles, description, purpose, caveats, entities
    )

    try:
        # Use Pydantic-validated response
        response, _ = client.invoke_with_schema(
            prompt=prompt,
            response_schema=QueryPatternResponse,
            system=PATTERN_SYSTEM_PROMPT,
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
        )

        # Convert Pydantic models to our dataclasses
        patterns = [
            QueryPattern(
                natural_language=p.natural_language,
                sql=p.sql,
                warnings=p.warnings,
            )
            for p in response.patterns
        ]

        # If no patterns were generated, create defaults
        if not patterns:
            patterns = generate_default_patterns(table_id, profiles)

        return patterns

    except ValueError:
        # Schema validation failed
        return generate_default_patterns(table_id, profiles)

    except Exception as e:
        # LLM call failed
        return [
            QueryPattern(
                natural_language="Select all records",
                sql=f"SELECT * FROM {table_id} LIMIT 100",
                warnings=f"Default query - pattern generation failed: {str(e)}",
            )
        ]


def generate_default_patterns(
    table_id: str, profiles: list[ColumnProfile]
) -> list[QueryPattern]:
    """Generate basic default patterns when LLM fails."""
    patterns = []

    # Basic select
    patterns.append(
        QueryPattern(
            natural_language="View sample data",
            sql=f"SELECT * FROM {table_id} LIMIT 100",
            warnings=None,
        )
    )

    # Count
    patterns.append(
        QueryPattern(
            natural_language="Count total records",
            sql=f"SELECT COUNT(*) as total_records FROM {table_id}",
            warnings=None,
        )
    )

    # Find a good column for GROUP BY
    for p in profiles:
        if p.unique_values and 2 <= p.unique_values <= 20:
            col_name = f'"{p.name}"'
            patterns.append(
                QueryPattern(
                    natural_language=f"Count by {p.name}",
                    sql=f"SELECT {col_name}, COUNT(*) as count FROM {table_id} GROUP BY {col_name}",
                    warnings=None,
                )
            )
            break

    # Find a numeric column for aggregation
    for p in profiles:
        if p.data_type in ["INTEGER", "FLOAT"] and not p.format_warnings:
            col_name = f'"{p.name}"'
            patterns.append(
                QueryPattern(
                    natural_language=f"Sum and average of {p.name}",
                    sql=f"SELECT SUM({col_name}) as total, AVG({col_name}) as average FROM {table_id}",
                    warnings=None,
                )
            )
            break

    return patterns
