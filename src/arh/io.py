from __future__ import annotations

from importlib.resources import files
from typing import TypeVar

from pydantic import BaseModel

from .opencode import run_streaming_prompt
from .schema import parse_model_output, structured_output_format


ModelT = TypeVar("ModelT", bound=BaseModel)


def load_prompt(name: str) -> str:
    return files("arh.prompts").joinpath(name).read_text(encoding="utf-8")


def render_prompt(template: str, **values: str) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered


def request_structured(
    *,
    base_url: str,
    session_id: str,
    prompt: str,
    model_type: type[ModelT],
    model: str | None = None,
    verbose: bool = False,
    status_hint: str | None = None,
) -> ModelT:
    raw_message = run_streaming_prompt(
        base_url=base_url,
        session_id=session_id,
        prompt=prompt,
        model=model,
        response_format=structured_output_format(model_type),
        verbose=verbose,
        status_hint=status_hint,
    )
    structured = raw_message.get("info", {}).get("structured")
    if not isinstance(structured, dict):
        raise ValueError(
            f"structured output missing from model response: {raw_message}"
        )
    return parse_model_output(model_type, structured)
