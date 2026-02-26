"""
Pydantic schemas for all LLM interactions.

Every LLM call should have a corresponding Pydantic model that defines
the expected response structure. This ensures:
1. Type safety and validation
2. Clear contracts for what the LLM should return
3. Automatic JSON schema generation for prompts
4. Easy serialization/deserialization
"""

from typing import Optional, Literal
from pydantic import BaseModel, Field, ConfigDict


# =============================================================================
# BASE CLASSES
# =============================================================================

class LLMResponseBase(BaseModel):
    """Base class for all LLM response schemas."""

    model_config = ConfigDict(extra="ignore")  # Ignore extra fields from LLM


# =============================================================================
# DESCRIPTION GENERATION
# =============================================================================

class TableDescriptionResponse(LLMResponseBase):
    """Response schema for table description generation."""

    description: str = Field(
        ...,
        description="Plain English explanation of what this table contains (2-4 sentences). "
                    "Mention who likely maintains it if you can infer that."
    )
    purpose: str = Field(
        ...,
        description="What kinds of questions this table can answer (comma-separated list of use cases)."
    )
    caveats: str = Field(
        ...,
        description="Warnings about data quality, inconsistencies, or limitations. "
                    "If no issues, say 'No significant data quality issues detected.'"
    )


# =============================================================================
# ENTITY EXTRACTION
# =============================================================================

class EntitySchema(BaseModel):
    """Schema for a single entity in the table."""

    name: str = Field(
        ...,
        description="The entity name, e.g. 'Client', 'Deal', 'Partner'"
    )
    is_primary: bool = Field(
        ...,
        description="True if this entity has one row per instance (primary entity)"
    )
    identified_by: str = Field(
        ...,
        description="Which column identifies this entity, e.g. 'Client Name'"
    )
    cardinality: Literal["one per row", "one to many"] = Field(
        ...,
        description="How the entity maps to rows"
    )
    attributes: list[str] = Field(
        default_factory=list,
        description="Which other columns describe this entity"
    )
    description: str = Field(
        ...,
        description="Brief note about this entity in context of this table"
    )


class CrossReferenceSchema(BaseModel):
    """Schema for a potential cross-table reference."""

    column: str = Field(
        ...,
        description="Which column in THIS table might connect to other tables"
    )
    likely_entity_type: str = Field(
        ...,
        description="What kind of entity this column refers to, e.g. 'Client'"
    )
    match_quality: Literal["exact", "fuzzy", "unknown"] = Field(
        ...,
        description="How reliable a join would be"
    )
    notes: str = Field(
        ...,
        description="Any caveats about matching"
    )


class EntityExtractionResponse(LLMResponseBase):
    """Response schema for entity extraction."""

    entities: list[EntitySchema] = Field(
        default_factory=list,
        description="List of entities identified in the table"
    )
    cross_references: list[CrossReferenceSchema] = Field(
        default_factory=list,
        description="Columns that might reference other tables"
    )


# =============================================================================
# QUERY PATTERN GENERATION
# =============================================================================

class QueryPatternSchema(BaseModel):
    """Schema for a single SQL query pattern."""

    natural_language: str = Field(
        ...,
        description="The kind of question this query answers, in plain English"
    )
    sql: str = Field(
        ...,
        description="The actual SQL query using exact column names (quoted with double quotes)"
    )
    warnings: Optional[str] = Field(
        None,
        description="Any caveats about this query, e.g. 'Column is text, cannot aggregate'"
    )


class QueryPatternResponse(LLMResponseBase):
    """Response schema for query pattern generation."""

    patterns: list[QueryPatternSchema] = Field(
        default_factory=list,
        description="List of 5-8 example SQL queries"
    )


# =============================================================================
# TABLE SELECTION (Query Time - Phase 2)
# =============================================================================

class TableSelectionSchema(BaseModel):
    """Schema for a single table's selection decision."""

    table_id: str = Field(
        ...,
        description="The table identifier"
    )
    selected: bool = Field(
        ...,
        description="Whether this table is relevant to the query"
    )
    reason: str = Field(
        ...,
        description="Why the table was selected or rejected"
    )
    relevance_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="How relevant is this table (0.0 to 1.0)"
    )


class TableSelectionResponse(LLMResponseBase):
    """Response schema for table selection."""

    selections: list[TableSelectionSchema] = Field(
        default_factory=list,
        description="Selection decision for each candidate table"
    )
    reasoning: str = Field(
        ...,
        description="Overall reasoning for the selection"
    )


# =============================================================================
# SQL GENERATION (Query Time - Phase 2)
# =============================================================================

class SQLGenerationResponse(LLMResponseBase):
    """Response schema for SQL query generation."""

    sql: str = Field(
        ...,
        description="The generated SQL query"
    )
    explanation: str = Field(
        ...,
        description="Explanation of what the query does"
    )
    tables_used: list[str] = Field(
        default_factory=list,
        description="List of table IDs used in the query"
    )
    warnings: Optional[str] = Field(
        None,
        description="Any caveats or potential issues with the query"
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence that this query answers the user's question"
    )


# =============================================================================
# VOCABULARY MAPPING (Learning)
# =============================================================================

class VocabularyMappingSchema(BaseModel):
    """Schema for a vocabulary mapping suggestion."""

    user_term: str = Field(
        ...,
        description="The term the user used"
    )
    maps_to_column: str = Field(
        ...,
        description="Which column this term maps to"
    )
    maps_to_values: list[str] = Field(
        default_factory=list,
        description="Which column values match this term"
    )
    confidence: Literal["high", "medium", "low"] = Field(
        ...,
        description="Confidence in this mapping"
    )


class VocabularyLearningResponse(LLMResponseBase):
    """Response schema for vocabulary learning."""

    mappings: list[VocabularyMappingSchema] = Field(
        default_factory=list,
        description="Suggested vocabulary mappings"
    )


# =============================================================================
# UTILITY: Get JSON Schema for Prompts
# =============================================================================

def get_response_schema(model_class: type[LLMResponseBase]) -> dict:
    """
    Get the JSON schema for a response model.

    This can be included in prompts to show the LLM exactly what structure
    to return.
    """
    return model_class.model_json_schema()


def get_response_schema_str(model_class: type[LLMResponseBase], indent: int = 2) -> str:
    """Get the JSON schema as a formatted string for prompts."""
    import json
    schema = get_response_schema(model_class)
    return json.dumps(schema, indent=indent)


def get_example_output(model_class: type[LLMResponseBase]) -> str:
    """
    Generate an example output structure for a response model.

    Useful for showing the LLM what the response should look like.
    """
    import json

    # Create a minimal example based on the schema
    schema = model_class.model_json_schema()

    def generate_example(schema_part: dict) -> any:
        if "properties" in schema_part:
            result = {}
            for prop_name, prop_schema in schema_part["properties"].items():
                result[prop_name] = generate_example(prop_schema)
            return result

        prop_type = schema_part.get("type", "string")

        if prop_type == "string":
            if "enum" in schema_part:
                return schema_part["enum"][0]
            return f"<{schema_part.get('description', 'string')[:30]}...>"
        elif prop_type == "integer":
            return 0
        elif prop_type == "number":
            return 0.0
        elif prop_type == "boolean":
            return True
        elif prop_type == "array":
            items = schema_part.get("items", {})
            return [generate_example(items)]
        elif prop_type == "null":
            return None
        else:
            return None

    example = generate_example(schema)
    return json.dumps(example, indent=2)
