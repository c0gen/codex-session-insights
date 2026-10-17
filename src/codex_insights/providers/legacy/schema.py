"""Validate complete authenticated trajectories against a pinned reader schema."""
import json
from functools import lru_cache
from pathlib import Path

from .wire import WireError, fields, varint


@lru_cache(maxsize=1)
def catalog():
    return json.loads(Path(__file__).with_name("reader_schema.json").read_text(encoding="utf-8"))


def validate(data, name="gemini_coder.Trajectory"):
    definitions = catalog()["messages"]
    unknown = set()
    budget = [2000000]
    def walk(raw, typename, depth):
        if depth > 64:
            raise WireError("schema_depth_limit")
        definition = definitions.get(typename)
        if definition is None:
            raise WireError("missing_schema")
        for number, kind, value in fields(raw):
            budget[0] -= 1
            if budget[0] < 0:
                raise WireError("schema_field_limit")
            field = definition.get(str(number))
            if field is None:
                unknown.add((typename, number))
                continue
            field_type = field["type"]
            expected = 1 if field_type in (1, 6, 16) else 5 if field_type in (2, 7, 15) else 2 if field_type in (9, 11, 12) else 0
            if field["repeated"] and expected != 2 and kind == 2:
                if expected in (1, 5):
                    if len(value) % (8 if expected == 1 else 4):
                        raise WireError("invalid_packed_field")
                else:
                    position = 0
                    while position < len(value):
                        _, position = varint(value, position)
                continue
            if kind != expected:
                raise WireError("schema_wire_type_mismatch")
            if field_type == 11:
                walk(value, field["reference"], depth + 1)
            elif field_type == 9:
                try:
                    value.decode("utf-8")
                except UnicodeError:
                    raise WireError("invalid_utf8") from None
            elif field_type == 8 and value not in (0, 1):
                raise WireError("invalid_bool")
    walk(data, name, 0)
    return sorted(unknown)
