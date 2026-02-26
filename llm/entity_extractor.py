"""
Extract entities and cross-references from tables using LLM with Pydantic validation.

Identifies what real-world things the table describes and how it might
connect to other tables.
"""

from typing import Optional

import pandas as pd

from models.table_card import ColumnProfile, EntityProfile, CrossReference
from config.settings import Settings, get_settings
from .bedrock_client import LLMClient, get_llm_client
from .schemas import EntityExtractionResponse


ENTITY_SYSTEM_PROMPT = """You are a data analyst identifying the real-world entities in a data table.

Your task is to identify:
1. The PRIMARY entity - the main thing each row represents (e.g., in a client table, each row is a Client)
2. SECONDARY entities - things mentioned as attributes but are entities in their own right (e.g., Industry, Region)
3. CROSS-REFERENCES - columns that likely refer to entities in OTHER tables (for future joins)

Rules:
- The primary entity has ONE ROW PER INSTANCE (e.g., one row per client, one row per deal)
- Secondary entities appear in multiple rows (e.g., "Finance" industry appears for many clients)
- Cross-references are columns that look like foreign keys or references to external data"""


def format_for_entity_extraction(
    df: pd.DataFrame,
    profiles: list[ColumnProfile],
    description: str,
    purpose: str,
    caveats: str,
) -> str:
    """Format all information for the entity extraction prompt."""
    # Column summary
    columns_info = []
    for p in profiles:
        info = f"- {p.name} ({p.data_type}): {p.unique_values} unique"
        if p.all_values:
            info += f" = {p.all_values}"
        columns_info.append(info)

    # Sample data
    sample = df.head(10).to_string(index=False)

    return f"""TABLE DESCRIPTION: {description}

PURPOSE: {purpose}

CAVEATS: {caveats}

COLUMNS:
{chr(10).join(columns_info)}

SAMPLE DATA:
{sample}

ROW COUNT: {len(df)}"""


def extract_entities(
    df: pd.DataFrame,
    profiles: list[ColumnProfile],
    description: str,
    purpose: str,
    caveats: str,
    client: Optional[LLMClient] = None,
    settings: Optional[Settings] = None,
) -> tuple[list[EntityProfile], list[CrossReference]]:
    """
    Extract entities and cross-references from a table.

    Args:
        df: The DataFrame
        profiles: Column profiles
        description: Generated description
        purpose: Generated purpose
        caveats: Generated caveats
        client: Optional LLM client
        settings: Optional settings

    Returns:
        Tuple of (list of EntityProfile, list of CrossReference)
    """
    if settings is None:
        settings = get_settings()

    if client is None:
        client = get_llm_client(settings)

    prompt = format_for_entity_extraction(df, profiles, description, purpose, caveats)

    try:
        # Use Pydantic-validated response
        response, _ = client.invoke_with_schema(
            prompt=prompt,
            response_schema=EntityExtractionResponse,
            system=ENTITY_SYSTEM_PROMPT,
            max_tokens=settings.llm_max_tokens,
            temperature=settings.llm_temperature,
        )

        # Convert Pydantic models to our dataclasses
        entities = [
            EntityProfile(
                name=e.name,
                is_primary=e.is_primary,
                identified_by=e.identified_by,
                cardinality=e.cardinality,
                attributes=e.attributes,
                description=e.description,
            )
            for e in response.entities
        ]

        cross_refs = [
            CrossReference(
                column=cr.column,
                likely_entity_type=cr.likely_entity_type,
                match_quality=cr.match_quality,
                notes=cr.notes,
            )
            for cr in response.cross_references
        ]

        # If no entities found, create a default one
        if not entities:
            entities = [_create_default_entity(profiles)]

        return entities, cross_refs

    except ValueError:
        # Schema validation failed
        return [_create_default_entity(profiles)], []

    except Exception as e:
        # LLM call failed
        return [
            EntityProfile(
                name="Record",
                is_primary=True,
                identified_by=profiles[0].name if profiles else "Unknown",
                cardinality="one per row",
                attributes=[],
                description=f"Entity extraction failed: {str(e)}",
            )
        ], []


def _create_default_entity(profiles: list[ColumnProfile]) -> EntityProfile:
    """Create a default entity when extraction fails."""
    # Try to find an identifier column
    primary_col = None
    for p in profiles:
        name_lower = p.name.lower()
        if any(x in name_lower for x in ["id", "name", "key", "code", "number"]):
            primary_col = p.name
            break

    if primary_col is None and profiles:
        primary_col = profiles[0].name

    return EntityProfile(
        name="Record",
        is_primary=True,
        identified_by=primary_col or "Unknown",
        cardinality="one per row",
        attributes=[p.name for p in profiles if p.name != primary_col],
        description="Each row represents one record.",
    )
