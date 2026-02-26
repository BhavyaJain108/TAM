"""
LLM client abstraction with Pydantic validation.

Supports:
- AWS Bedrock (Claude)
- Anthropic API (direct)
- Mock mode (for testing)

All responses are validated against Pydantic schemas.
"""

import json
import time
from abc import ABC, abstractmethod
from typing import Optional, Type, TypeVar
from dataclasses import dataclass

from pydantic import BaseModel

from config.settings import Settings, get_settings
from .schemas import LLMResponseBase
from .schema_generator import validate_llm_response, generate_system_prompt_for_schema


T = TypeVar("T", bound=BaseModel)


@dataclass
class LLMResponse:
    """Raw response from an LLM call."""

    content: str
    """The text response from the model."""

    input_tokens: int
    """Number of input tokens used."""

    output_tokens: int
    """Number of output tokens generated."""

    model: str
    """Model identifier used."""

    latency_ms: int
    """Time taken for the request in milliseconds."""


class LLMClient(ABC):
    """Abstract base class for LLM clients."""

    @abstractmethod
    def invoke(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """
        Send a prompt to the LLM and get a raw response.

        Args:
            prompt: The user prompt
            system: Optional system prompt
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature

        Returns:
            LLMResponse with the model's response
        """
        pass

    def invoke_with_schema(
        self,
        prompt: str,
        response_schema: Type[T],
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        max_retries: int = 2,
    ) -> tuple[T, LLMResponse]:
        """
        Send a prompt and validate response against a Pydantic schema.

        This is the preferred method for all LLM calls. It:
        1. Generates a system prompt that includes the JSON schema
        2. Sends the request to the LLM
        3. Validates the response against the schema
        4. Retries if validation fails

        Args:
            prompt: The user prompt
            response_schema: Pydantic model class defining expected response
            system: Additional system prompt (appended to schema instructions)
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature
            max_retries: Number of retries if validation fails

        Returns:
            Tuple of (validated_response, raw_response)

        Raises:
            ValueError: If response doesn't match schema after retries
        """
        # Build system prompt with schema
        schema_prompt = generate_system_prompt_for_schema(
            response_schema,
            system or ""
        )

        last_error = None
        for attempt in range(max_retries + 1):
            raw_response = self.invoke(
                prompt=prompt,
                system=schema_prompt,
                max_tokens=max_tokens,
                temperature=temperature,
            )

            validated, error = validate_llm_response(
                raw_response.content,
                response_schema
            )

            if validated is not None:
                return validated, raw_response

            last_error = error

            # If we have retries left, add error feedback to prompt
            if attempt < max_retries:
                prompt = f"{prompt}\n\n[Previous response had error: {error}. Please fix and try again.]"

        raise ValueError(f"Failed to get valid response after {max_retries + 1} attempts: {last_error}")

    def invoke_json(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> tuple[dict, LLMResponse]:
        """
        Send a prompt expecting a JSON response (unvalidated).

        DEPRECATED: Use invoke_with_schema() for type-safe responses.

        Returns:
            Tuple of (parsed JSON dict, LLMResponse)
        """
        json_system = system or ""
        json_system += "\n\nRespond with valid JSON only. No markdown code blocks, no explanation, just the JSON object."

        response = self.invoke(prompt, json_system, max_tokens, temperature)

        # Try to parse the response as JSON
        content = response.content.strip()

        # Remove markdown code blocks if present
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        parsed = json.loads(content)
        return parsed, response


class BedrockClient(LLMClient):
    """AWS Bedrock Claude client."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self.settings.aws_region,
            )
        return self._client

    def invoke(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        start_time = time.time()

        messages = [{"role": "user", "content": prompt}]

        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }

        if system:
            body["system"] = system

        response = self.client.invoke_model(
            modelId=self.settings.bedrock_model_id,
            body=json.dumps(body),
        )

        result = json.loads(response["body"].read())

        latency_ms = int((time.time() - start_time) * 1000)

        return LLMResponse(
            content=result["content"][0]["text"],
            input_tokens=result["usage"]["input_tokens"],
            output_tokens=result["usage"]["output_tokens"],
            model=self.settings.bedrock_model_id,
            latency_ms=latency_ms,
        )


class AnthropicClient(LLMClient):
    """Direct Anthropic API client."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(
                api_key=self.settings.anthropic_api_key,
            )
        return self._client

    def invoke(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        start_time = time.time()

        kwargs = {
            "model": self.settings.anthropic_model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }

        if system:
            kwargs["system"] = system

        response = self.client.messages.create(**kwargs)

        latency_ms = int((time.time() - start_time) * 1000)

        return LLMResponse(
            content=response.content[0].text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=self.settings.anthropic_model,
            latency_ms=latency_ms,
        )


class MockLLMClient(LLMClient):
    """Mock LLM client for testing."""

    def __init__(
        self,
        responses: Optional[dict] = None,
        default_response: Optional[dict] = None,
    ):
        """
        Initialize mock client.

        Args:
            responses: Dict mapping prompt substrings to response dicts.
            default_response: Default dict to return if no match found.
        """
        self.responses = responses or {}
        self.default_response = default_response or {
            "description": "Mock table description",
            "purpose": "Mock table purpose",
            "caveats": "No caveats detected (mock response)",
        }
        self.call_history: list[dict] = []

    def set_response_for_schema(
        self,
        schema_class: Type[BaseModel],
        response_data: dict,
    ) -> None:
        """
        Set a mock response for a specific schema type.

        Args:
            schema_class: The Pydantic schema class
            response_data: Dict that will be returned as JSON
        """
        # Use schema class name as key
        self.responses[schema_class.__name__] = response_data

    def invoke(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        self.call_history.append({
            "prompt": prompt,
            "system": system,
            "max_tokens": max_tokens,
            "temperature": temperature,
        })

        # Check for schema-based responses (look for schema name in system prompt)
        content = None
        if system:
            for key, response in self.responses.items():
                if key in system or key in prompt:
                    content = json.dumps(response)
                    break

        # Check for substring matches in prompt
        if content is None:
            for key, response in self.responses.items():
                if key in prompt:
                    content = json.dumps(response) if isinstance(response, dict) else response
                    break

        # Use default response
        if content is None:
            content = json.dumps(self.default_response)

        return LLMResponse(
            content=content,
            input_tokens=len(prompt.split()),
            output_tokens=len(content.split()),
            model="mock-model",
            latency_ms=10,
        )


def get_llm_client(settings: Optional[Settings] = None) -> LLMClient:
    """
    Get the appropriate LLM client based on settings.

    Args:
        settings: Settings object (uses global if not provided)

    Returns:
        LLMClient instance
    """
    if settings is None:
        settings = get_settings()

    provider = settings.llm_provider.lower()

    if provider == "bedrock":
        return BedrockClient(settings)
    elif provider == "anthropic":
        return AnthropicClient(settings)
    elif provider == "mock":
        return MockLLMClient()
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")
