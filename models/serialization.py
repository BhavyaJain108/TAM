"""
JSON serialization and deserialization for TableCard and related models.
"""

import json
from dataclasses import asdict, fields, is_dataclass
from typing import Any, Type, TypeVar, get_type_hints, get_origin, get_args, Union
from datetime import date, datetime

from .table_card import (
    ColumnProfile,
    EntityProfile,
    CrossReference,
    QueryPattern,
    UsageEntry,
    VocabularyMapping,
    ConfirmedRelationship,
    TableCard,
)


T = TypeVar("T")


class TableCardEncoder(json.JSONEncoder):
    """Custom JSON encoder for TableCard and related dataclasses."""

    def default(self, obj: Any) -> Any:
        # Handle dates
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()

        # Handle numpy types
        try:
            import numpy as np
            if isinstance(obj, (np.integer, np.int64, np.int32)):
                return int(obj)
            if isinstance(obj, (np.floating, np.float64, np.float32)):
                return float(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            if isinstance(obj, np.bool_):
                return bool(obj)
        except ImportError:
            pass

        # Handle dataclasses
        if is_dataclass(obj) and not isinstance(obj, type):
            return asdict(obj)

        return super().default(obj)


def _get_dataclass_for_field(field_type: Type) -> Type | None:
    """Get the dataclass type for a field, handling Optional and list types."""
    origin = get_origin(field_type)

    # Handle Optional[X] which is Union[X, None]
    if origin is Union:
        args = get_args(field_type)
        non_none_args = [a for a in args if a is not type(None)]
        if len(non_none_args) == 1:
            return _get_dataclass_for_field(non_none_args[0])
        return None

    # Handle list[X]
    if origin is list:
        args = get_args(field_type)
        if args and is_dataclass(args[0]):
            return args[0]
        return None

    # Direct dataclass
    if is_dataclass(field_type):
        return field_type

    return None


def _from_dict(cls: Type[T], data: dict) -> T:
    """Convert a dictionary to a dataclass instance, handling nested types."""
    if not is_dataclass(cls):
        raise ValueError(f"{cls} is not a dataclass")

    type_hints = get_type_hints(cls)
    field_values = {}

    for f in fields(cls):
        field_name = f.name
        if field_name not in data:
            # Use default if available
            if f.default is not f.default_factory:
                if f.default is not None:
                    field_values[field_name] = f.default
            elif f.default_factory is not None:
                field_values[field_name] = f.default_factory()
            continue

        value = data[field_name]
        field_type = type_hints.get(field_name, f.type)

        if value is None:
            field_values[field_name] = None
            continue

        # Check if this field is a list of dataclasses
        origin = get_origin(field_type)
        if origin is list:
            args = get_args(field_type)
            if args and is_dataclass(args[0]):
                # Convert each item in the list
                field_values[field_name] = [_from_dict(args[0], item) for item in value]
            else:
                field_values[field_name] = value
        elif is_dataclass(field_type):
            # Single nested dataclass
            field_values[field_name] = _from_dict(field_type, value)
        else:
            # Check for Optional[dataclass]
            if origin is Union:
                non_none_args = [a for a in get_args(field_type) if a is not type(None)]
                if len(non_none_args) == 1 and is_dataclass(non_none_args[0]):
                    field_values[field_name] = _from_dict(non_none_args[0], value)
                else:
                    field_values[field_name] = value
            else:
                field_values[field_name] = value

    return cls(**field_values)


def table_card_to_json(card: TableCard, indent: int = 2) -> str:
    """Serialize a TableCard to JSON string."""
    return json.dumps(card, cls=TableCardEncoder, indent=indent)


def table_card_from_json(json_str: str) -> TableCard:
    """Deserialize a JSON string to a TableCard."""
    data = json.loads(json_str)
    return table_card_from_dict(data)


def table_card_from_dict(data: dict) -> TableCard:
    """Convert a dictionary to a TableCard instance."""
    return _from_dict(TableCard, data)


def table_card_to_dict(card: TableCard) -> dict:
    """Convert a TableCard to a dictionary."""
    return json.loads(table_card_to_json(card))


# Convenience functions for saving/loading from files
def save_card_to_file(card: TableCard, filepath: str) -> None:
    """Save a TableCard to a JSON file."""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(table_card_to_json(card))


def load_card_from_file(filepath: str) -> TableCard:
    """Load a TableCard from a JSON file."""
    with open(filepath, "r", encoding="utf-8") as f:
        return table_card_from_json(f.read())
