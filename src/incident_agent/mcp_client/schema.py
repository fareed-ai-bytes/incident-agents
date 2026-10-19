"""Convert discovered MCP tool schemas for model use, and validate arguments against them."""

from __future__ import annotations

from typing import Any

from incident_agent.llm.base import ToolSchema, tool_schema
from incident_agent.mcp_client.client import INJECTED_ARGS, ToolSpec

_JSON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}


def model_parameters(spec: ToolSpec, hide: frozenset[str] = INJECTED_ARGS) -> dict[str, Any]:
    """The tool's JSON schema without arguments the runtime injects."""
    schema = spec.input_schema
    props = {k: _clean(v) for k, v in schema.get("properties", {}).items() if k not in hide}
    required = [r for r in schema.get("required", []) if r not in hide]
    return {"type": "object", "properties": props, "required": required}


def _clean(prop: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in prop.items() if k != "title"}


def to_model_tool(spec: ToolSpec) -> ToolSchema:
    return tool_schema(spec.name, spec.description, model_parameters(spec))


def validate_args(spec: ToolSpec, args: dict[str, Any]) -> list[str]:
    """Problems with `args` for `spec` (missing required, unknown keys, wrong JSON types)."""
    if not isinstance(args, dict):
        return ["arguments must be a JSON object"]
    params = model_parameters(spec)
    props = params["properties"]
    errors = [f"missing required argument {r!r}" for r in params["required"] if r not in args]
    for key, value in args.items():
        if key in INJECTED_ARGS:
            continue
        if key not in props:
            errors.append(f"unknown argument {key!r}")
            continue
        expected = _types_of(props[key])
        if expected and not _matches(value, expected):
            errors.append(f"argument {key!r} should be {'/'.join(expected)}")
    return errors


def _types_of(prop: dict[str, Any]) -> list[str]:
    if "type" in prop:
        return [prop["type"]] if isinstance(prop["type"], str) else list(prop["type"])
    return [p["type"] for p in prop.get("anyOf", []) if "type" in p]


def _matches(value: Any, expected: list[str]) -> bool:
    for name in expected:
        if name == "null" and value is None:
            return True
        types = _JSON_TYPES.get(name, ())
        if isinstance(value, bool) and name in ("integer", "number"):
            continue
        if types and isinstance(value, types):
            return True
    return False
