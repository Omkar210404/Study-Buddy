"""Turn raw model text into a JSON object."""

import json
import re

from app.errors import MalformedOutputError

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def extract_json_object(text: str) -> dict:
    """Parse the first JSON object in `text`, tolerating Markdown fences and surrounding prose."""
    cleaned = _FENCE_RE.sub("", text.strip())
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise MalformedOutputError("no JSON object found in model output")
        try:
            value = json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError as exc:
            raise MalformedOutputError(f"invalid JSON in model output: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise MalformedOutputError("model output JSON is not an object")
    return value
