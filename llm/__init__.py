"""LLM integration for metadata generation."""

from .bedrock_client import (
    LLMClient,
    LLMResponse,
    BedrockClient,
    AnthropicClient,
    MockLLMClient,
    get_llm_client,
)
from .schemas import (
    LLMResponseBase,
    TableDescriptionResponse,
    EntityExtractionResponse,
    EntitySchema,
    CrossReferenceSchema,
    QueryPatternResponse,
    QueryPatternSchema,
    TableSelectionResponse,
    SQLGenerationResponse,
    get_response_schema,
    get_response_schema_str,
)
from .schema_generator import (
    SchemaInitSystem,
    schema_init,
    generate_pydantic_class_code,
    create_dynamic_model,
    validate_llm_response,
    generate_system_prompt_for_schema,
)
from .description_generator import generate_description
from .entity_extractor import extract_entities
from .pattern_generator import generate_query_patterns

__all__ = [
    # Clients
    "LLMClient",
    "LLMResponse",
    "BedrockClient",
    "AnthropicClient",
    "MockLLMClient",
    "get_llm_client",
    # Schemas
    "LLMResponseBase",
    "TableDescriptionResponse",
    "EntityExtractionResponse",
    "EntitySchema",
    "CrossReferenceSchema",
    "QueryPatternResponse",
    "QueryPatternSchema",
    "TableSelectionResponse",
    "SQLGenerationResponse",
    "get_response_schema",
    "get_response_schema_str",
    # Schema generator
    "SchemaInitSystem",
    "schema_init",
    "generate_pydantic_class_code",
    "create_dynamic_model",
    "validate_llm_response",
    "generate_system_prompt_for_schema",
    # Generators
    "generate_description",
    "extract_entities",
    "generate_query_patterns",
]
