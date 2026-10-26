import json
from typing import Any

from app.core.errors import LLMError


def extract_json(text: str) -> dict[str, Any]:
    start = text.find("{")
    if start < 0:
        raise LLMError("No JSON object in response")
    depth, quoted, escaped = 0, False, False
    for index in range(start, len(text)):
        char = text[index]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    value = json.loads(text[start : index + 1])
                except ValueError as exc:
                    raise LLMError("Invalid JSON object in response") from exc
                return value
    raise LLMError("Unterminated JSON object in response")
