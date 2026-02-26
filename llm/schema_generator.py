"""
Schema Generator Utility

This module provides tools to:
1. Generate Pydantic class definitions from example JSON/dict
2. Create a system prompt that instructs the LLM to produce output matching a schema
3. Validate LLM responses against schemas

The "init system" - give it the desired output structure, get back a Pydantic class.
"""

import json
from typing import Any, Optional, Type, get_origin, get_args
from pydantic import BaseModel, Field, create_model
from datetime import datetime


def infer_python_type(value: Any) -> tuple[type, Any]:
    """
    Infer Python type from a value.

    Returns (type, default) tuple.
    """
    if value is None:
        return Optional[str], None
    elif isinstance(value, bool):
        return bool, ...
    elif isinstance(value, int):
        return int, ...
    elif isinstance(value, float):
        return float, ...
    elif isinstance(value, str):
        return str, ...
    elif isinstance(value, list):
        if len(value) == 0:
            return list[Any], []
        # Infer type from first element
        elem_type, _ = infer_python_type(value[0])
        return list[elem_type], []
    elif isinstance(value, dict):
        return dict, ...
    else:
        return Any, ...


def generate_pydantic_class_code(
    example: dict,
    class_name: str = "GeneratedResponse",
    base_class: str = "BaseModel",
    descriptions: Optional[dict[str, str]] = None,
) -> str:
    """
    Generate Pydantic class code from an example dict.

    Args:
        example: Example dict showing the expected structure
        class_name: Name for the generated class
        base_class: Base class to inherit from
        descriptions: Optional dict mapping field names to descriptions

    Returns:
        Python code string defining the Pydantic class

    Example:
        >>> example = {"name": "Acme", "revenue": 1000000, "active": True}
        >>> print(generate_pydantic_class_code(example, "CompanySchema"))
        class CompanySchema(BaseModel):
            name: str
            revenue: int
            active: bool
    """
    descriptions = descriptions or {}
    lines = [f"class {class_name}({base_class}):"]

    if not example:
        lines.append("    pass")
        return "\n".join(lines)

    for key, value in example.items():
        type_hint = _get_type_hint_str(value)
        desc = descriptions.get(key)

        if desc:
            lines.append(f'    {key}: {type_hint} = Field(..., description="{desc}")')
        else:
            lines.append(f"    {key}: {type_hint}")

    return "\n".join(lines)


def _get_type_hint_str(value: Any) -> str:
    """Get type hint as a string."""
    if value is None:
        return "Optional[str]"
    elif isinstance(value, bool):
        return "bool"
    elif isinstance(value, int):
        return "int"
    elif isinstance(value, float):
        return "float"
    elif isinstance(value, str):
        return "str"
    elif isinstance(value, list):
        if len(value) == 0:
            return "list"
        elem_type = _get_type_hint_str(value[0])
        return f"list[{elem_type}]"
    elif isinstance(value, dict):
        return "dict"
    else:
        return "Any"


def create_dynamic_model(
    example: dict,
    model_name: str = "DynamicModel",
    descriptions: Optional[dict[str, str]] = None,
) -> Type[BaseModel]:
    """
    Dynamically create a Pydantic model from an example dict.

    Args:
        example: Example dict showing expected structure
        model_name: Name for the model
        descriptions: Optional field descriptions

    Returns:
        A Pydantic model class

    Example:
        >>> example = {"name": "Acme", "count": 42}
        >>> Model = create_dynamic_model(example, "MyModel")
        >>> instance = Model(name="Test", count=10)
    """
    descriptions = descriptions or {}
    field_definitions = {}

    for key, value in example.items():
        field_type, default = infer_python_type(value)
        desc = descriptions.get(key)

        if desc:
            field_definitions[key] = (field_type, Field(default, description=desc))
        else:
            field_definitions[key] = (field_type, default)

    return create_model(model_name, **field_definitions)


def generate_system_prompt_for_schema(
    schema_class: Type[BaseModel],
    task_description: str = "",
) -> str:
    """
    Generate a system prompt that instructs the LLM to output JSON matching a schema.

    Args:
        schema_class: The Pydantic model class defining the expected output
        task_description: Optional description of what the LLM should do

    Returns:
        System prompt string
    """
    schema_json = json.dumps(schema_class.model_json_schema(), indent=2)

    prompt = f"""{task_description}

You must respond with valid JSON that matches this exact schema:

```json
{schema_json}
```

Rules:
1. Return ONLY the JSON object, no markdown code blocks, no explanation
2. All required fields must be present
3. Use the exact field names shown
4. Follow the type constraints (string, number, boolean, array, etc.)
5. If a field has an enum constraint, use only the allowed values"""

    return prompt


def validate_llm_response(
    response_text: str,
    schema_class: Type[BaseModel],
) -> tuple[Optional[BaseModel], Optional[str]]:
    """
    Validate and parse an LLM response against a schema.

    Args:
        response_text: Raw text response from LLM
        schema_class: Pydantic model to validate against

    Returns:
        Tuple of (parsed_model, error_message)
        If successful, error_message is None
        If failed, parsed_model is None
    """
    # Clean up the response
    text = response_text.strip()

    # Remove markdown code blocks if present
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        data = json.loads(text)
        model = schema_class.model_validate(data)
        return model, None
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON: {e}"
    except Exception as e:
        return None, f"Validation error: {e}"


# =============================================================================
# INIT SYSTEM: Generate schema from desired output
# =============================================================================

class SchemaInitSystem:
    """
    The "init system" for generating Pydantic schemas from examples.

    Usage:
        init = SchemaInitSystem()

        # Define what you want the output to look like
        desired_output = {
            "summary": "This is a summary",
            "confidence": 0.95,
            "tags": ["tag1", "tag2"],
            "metadata": {
                "source": "example",
                "verified": True
            }
        }

        # Generate the Pydantic class code
        code = init.generate_class(
            example=desired_output,
            class_name="MySummaryResponse",
            descriptions={
                "summary": "A brief summary of the content",
                "confidence": "Confidence score from 0 to 1",
            }
        )
        print(code)

        # Or create the class dynamically
        MyClass = init.create_model(desired_output, "MySummaryResponse")
    """

    def generate_class(
        self,
        example: dict,
        class_name: str = "GeneratedResponse",
        descriptions: Optional[dict[str, str]] = None,
        include_imports: bool = True,
    ) -> str:
        """
        Generate Pydantic class code from an example.

        Args:
            example: Example dict showing desired output structure
            class_name: Name for the generated class
            descriptions: Field descriptions
            include_imports: Whether to include import statements

        Returns:
            Python code string
        """
        code_lines = []

        if include_imports:
            code_lines.extend([
                "from typing import Optional, Any",
                "from pydantic import BaseModel, Field",
                "",
                "",
            ])

        # Handle nested dicts by creating nested classes
        nested_classes = self._extract_nested_classes(example, class_name)
        code_lines.extend(nested_classes)

        # Generate main class
        main_class = self._generate_single_class(
            example, class_name, descriptions, nested_classes
        )
        code_lines.append(main_class)

        return "\n".join(code_lines)

    def _extract_nested_classes(
        self, example: dict, parent_name: str, depth: int = 0
    ) -> list[str]:
        """Extract nested dict structures into separate classes."""
        classes = []

        for key, value in example.items():
            if isinstance(value, dict) and value:
                nested_name = f"{parent_name}{key.title().replace('_', '')}"
                # Recursively handle deeper nesting
                deeper = self._extract_nested_classes(value, nested_name, depth + 1)
                classes.extend(deeper)
                # Generate this nested class
                nested_code = self._generate_single_class(value, nested_name, {}, [])
                classes.append(nested_code)
                classes.append("")

            elif isinstance(value, list) and value and isinstance(value[0], dict):
                # List of dicts - create a class for the item type
                item_name = f"{parent_name}{key.title().replace('_', '')}Item"
                deeper = self._extract_nested_classes(value[0], item_name, depth + 1)
                classes.extend(deeper)
                item_code = self._generate_single_class(value[0], item_name, {}, [])
                classes.append(item_code)
                classes.append("")

        return classes

    def _generate_single_class(
        self,
        example: dict,
        class_name: str,
        descriptions: Optional[dict[str, str]],
        nested_classes: list[str],
    ) -> str:
        """Generate a single class definition."""
        descriptions = descriptions or {}
        lines = [f"class {class_name}(BaseModel):"]

        if not example:
            lines.append("    pass")
            return "\n".join(lines)

        for key, value in example.items():
            type_hint = self._get_type_hint(value, class_name, key)
            desc = descriptions.get(key)

            if desc:
                lines.append(f'    {key}: {type_hint} = Field(..., description="{desc}")')
            else:
                lines.append(f"    {key}: {type_hint}")

        return "\n".join(lines)

    def _get_type_hint(self, value: Any, parent_name: str, field_name: str) -> str:
        """Get type hint string, handling nested structures."""
        if value is None:
            return "Optional[str]"
        elif isinstance(value, bool):
            return "bool"
        elif isinstance(value, int):
            return "int"
        elif isinstance(value, float):
            return "float"
        elif isinstance(value, str):
            return "str"
        elif isinstance(value, list):
            if len(value) == 0:
                return "list"
            if isinstance(value[0], dict):
                item_name = f"{parent_name}{field_name.title().replace('_', '')}Item"
                return f"list[{item_name}]"
            elem_type = self._get_type_hint(value[0], parent_name, field_name)
            return f"list[{elem_type}]"
        elif isinstance(value, dict):
            nested_name = f"{parent_name}{field_name.title().replace('_', '')}"
            return nested_name
        else:
            return "Any"

    def create_model(
        self,
        example: dict,
        model_name: str = "DynamicModel",
        descriptions: Optional[dict[str, str]] = None,
    ) -> Type[BaseModel]:
        """
        Dynamically create a Pydantic model from an example.

        Note: For nested structures, use generate_class() and exec() instead.
        """
        return create_dynamic_model(example, model_name, descriptions)

    def get_system_prompt(
        self,
        schema_class: Type[BaseModel],
        task_description: str = "",
    ) -> str:
        """Generate a system prompt for the schema."""
        return generate_system_prompt_for_schema(schema_class, task_description)


# Global instance for convenience
schema_init = SchemaInitSystem()
