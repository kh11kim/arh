from __future__ import annotations

from importlib.resources import files
from typing import TypeVar

from pydantic import BaseModel

from .opencode import extract_text_reply, run_streaming_prompt
from .schema import parse_model_output, sanitize_model_text, structured_output_format


ModelT = TypeVar("ModelT", bound=BaseModel)


class StructuredResponseError(ValueError):
    """Raised when the model fails to return structured output."""


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
    info = raw_message.get("info", {})
    structured = info.get("structured")
    if not isinstance(structured, dict):
        error_name = str(info.get("error", {}).get("name", "")).strip()
        finish_reason = str(info.get("finish", "")).strip().lower()
        if error_name == "StructuredOutputError" or finish_reason == "length":
            raise StructuredResponseError(
                "모델 응답이 너무 길거나 형식이 깨져 구조화 출력 생성에 실패했습니다. "
                "더 짧게 답하거나 `confirm`으로 진행해 주세요."
            )
        raise StructuredResponseError(
            "구조화 출력 생성에 실패했습니다. 다시 시도해 주세요."
        )
    return parse_model_output(model_type, structured)


def request_text(
    *,
    base_url: str,
    session_id: str,
    prompt: str,
    model: str | None = None,
    verbose: bool = False,
    status_hint: str | None = None,
) -> str:
    raw_message = run_streaming_prompt(
        base_url=base_url,
        session_id=session_id,
        prompt=prompt,
        model=model,
        verbose=verbose,
        status_hint=status_hint,
    )
    text = extract_text_reply(raw_message)
    if text:
        lowered = text.lower()
        if (
            "<system-reminder>" in lowered
            or "your operational mode has changed" in lowered
            or "you are no longer in read-only mode" in lowered
            or "you are permitted to make file changes" in lowered
        ):
            return "응답 형식이 깨졌습니다. 같은 내용을 짧게 다시 입력해 주세요."
        cleaned = sanitize_model_text(text)
        if cleaned:
            return cleaned
    raise StructuredResponseError(
        "텍스트 응답 생성에 실패했습니다. 다시 시도해 주세요."
    )


def request_discussion_then_structured(
    *,
    base_url: str,
    session_id: str,
    discussion_prompt: str,
    finalize_prompt: str,
    model_type: type[ModelT],
    model: str | None = None,
    verbose: bool = False,
    discussion_status_hint: str | None = None,
    finalize_status_hint: str | None = None,
) -> ModelT:
    request_text(
        base_url=base_url,
        session_id=session_id,
        prompt=discussion_prompt,
        model=model,
        verbose=verbose,
        status_hint=discussion_status_hint,
    )
    return request_structured(
        base_url=base_url,
        session_id=session_id,
        prompt=finalize_prompt,
        model_type=model_type,
        model=model,
        verbose=verbose,
        status_hint=finalize_status_hint,
    )
