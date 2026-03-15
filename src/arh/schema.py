from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Dict, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


DEFAULT_RESEARCH_MD = "research.md"


def sanitize_model_text(value: Any) -> str:
    text = str(value).strip() if value is not None else ""
    text = text.replace("\r", "")
    text = re.sub(r"<system-reminder>.*$", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(
        r"<system-reminder>.*?</system-reminder>",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    text = re.sub(r"<system-reminder>.*$", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(
        r"your operational mode has changed.*$",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    text = re.sub(
        r"you are no longer in read-only mode.*$",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    text = re.sub(
        r"you are permitted to make file changes.*$",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    blocked_line_fragments = (
        "<system-reminder>",
        "</system-reminder>",
        "your operational mode has changed",
        "you are no longer in read-only mode",
        "you are permitted to make file changes",
    )
    lines = [
        line.rstrip()
        for line in text.splitlines()
        if not any(fragment in line.lower() for fragment in blocked_line_fragments)
    ]
    return "\n".join(line for line in lines if line.strip()).strip()


def is_meta_text(value: str) -> bool:
    text = sanitize_model_text(value).lower()
    if not text:
        return False
    blocked_fragments = (
        "<system-reminder>",
        "</system-reminder>",
        "latest user response:",
        "current inspection json:",
        "confirmed inspection json:",
        "current contract markdown:",
        "reply `confirm`",
        "type `confirm`",
        "if something is ambiguous",
        "your job:",
        "rules:",
    )
    return any(fragment in text for fragment in blocked_fragments)


def sanitize_model_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        text = sanitize_model_text(item)
        if not text or is_meta_text(text):
            continue
        cleaned.append(text)
    return cleaned


class Evaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    main_metric: str = ""
    direction: str = ""
    tie_breaker: str = ""

    @field_validator("main_metric", "tie_breaker", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return sanitize_model_text(value)

    @field_validator("direction", mode="before")
    @classmethod
    def _normalize_direction(cls, value: Any) -> str:
        direction = str(value).strip().lower() if value is not None else ""
        aliases = {
            "maximize": "maximize",
            "max": "maximize",
            "higher": "maximize",
            "higher_is_better": "maximize",
            "up": "maximize",
            "increase": "maximize",
            "minimize": "minimize",
            "min": "minimize",
            "lower": "minimize",
            "lower_is_better": "minimize",
            "down": "minimize",
            "decrease": "minimize",
        }
        return aliases.get(direction, "")


class Execution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_time: str = ""
    train_entrypoint: str = ""

    @field_validator("experiment_time", "train_entrypoint", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return sanitize_model_text(value)


class ContractState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    research_goal: str = ""
    evaluation: Evaluation = Field(default_factory=Evaluation)
    execution: Execution = Field(default_factory=Execution)
    stop_condition: str = ""
    allowed_modifications: list[str] = Field(default_factory=list)
    forbidden_modifications: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    ready_for_review: bool = False
    next_question: str = "Please clarify the next missing detail."

    @field_validator(
        "research_goal",
        "stop_condition",
        "next_question",
        mode="before",
    )
    @classmethod
    def _normalize_scalar(cls, value: Any) -> str:
        return sanitize_model_text(value)

    @field_validator(
        "allowed_modifications",
        "forbidden_modifications",
        "missing_fields",
        mode="before",
    )
    @classmethod
    def _normalize_list(cls, value: Any) -> list[str]:
        return sanitize_model_list(value)

    def as_prompt_json(self) -> str:
        return self.model_dump_json(indent=2)

    @model_validator(mode="after")
    def _enforce_review_gate(self) -> "ContractState":
        missing = []
        if not self.research_goal:
            missing.append("research_goal")
        if not self.evaluation.main_metric:
            missing.append("main_metric")
        if not self.evaluation.direction:
            missing.append("direction")
        if not self.execution.experiment_time:
            missing.append("experiment_time")
        if not self.execution.train_entrypoint:
            missing.append("train_entrypoint")
        if not self.stop_condition:
            missing.append("stop_condition")
        if not self.allowed_modifications:
            missing.append("allowed_modifications")
        if not self.forbidden_modifications:
            missing.append("forbidden_modifications")

        self.missing_fields = missing
        if missing:
            self.ready_for_review = False
            self.next_question = sanitize_model_text(self.next_question)
            if not self.next_question or "confirm" in self.next_question.lower():
                self.next_question = (
                    "Please clarify the single most important missing contract detail."
                )
        return self


class SmokeInspection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entrypoint: str = ""
    file_tree: list[str] = Field(default_factory=list)
    key_files: list[str] = Field(default_factory=list)
    model_summary: str = ""
    modifiable_files: list[str] = Field(default_factory=list)
    modifiable_parameters: list[str] = Field(default_factory=list)
    smoke_command: str = ""
    entrypoint_patch_plan: str = ""
    missing_fields: list[str] = Field(default_factory=list)
    ready_for_confirmation: bool = False
    next_question: str = "Please confirm or provide edits."

    @field_validator(
        "entrypoint",
        "model_summary",
        "smoke_command",
        "entrypoint_patch_plan",
        "next_question",
        mode="before",
    )
    @classmethod
    def _normalize_scalar(cls, value: Any) -> str:
        return sanitize_model_text(value)

    @field_validator(
        "file_tree",
        "key_files",
        "modifiable_files",
        "modifiable_parameters",
        "missing_fields",
        mode="before",
    )
    @classmethod
    def _normalize_list(cls, value: Any) -> list[str]:
        return sanitize_model_list(value)

    @model_validator(mode="after")
    def _enforce_confirmation_gate(self) -> "SmokeInspection":
        missing = []
        if not self.entrypoint:
            missing.append("entrypoint")
        if not self.file_tree:
            missing.append("file_tree")
        if not self.key_files:
            missing.append("key_files")
        if not self.model_summary:
            missing.append("model_summary")
        if not self.modifiable_files:
            missing.append("modifiable_files")
        if not self.modifiable_parameters:
            missing.append("modifiable_parameters")
        if not self.smoke_command:
            missing.append("smoke_command")
        if not self.entrypoint_patch_plan:
            missing.append("entrypoint_patch_plan")

        self.missing_fields = missing
        if missing:
            self.ready_for_confirmation = False
            self.next_question = sanitize_model_text(self.next_question)
            if not self.next_question or "confirm" in self.next_question.lower():
                self.next_question = (
                    "Please clarify the single most important missing setup detail."
                )
        else:
            self.next_question = (
                sanitize_model_text(self.next_question)
                or "Reply `confirm` or provide edits."
            )
        if self.next_question and "<system-reminder>" in self.next_question.lower():
            self.next_question = "Reply `confirm` or provide edits."
        return self


class SetupPreparation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preparation_summary: str = ""
    changed_files: list[str] = Field(default_factory=list)
    smoke_command: str = ""
    patch_plan: str = ""
    missing_fields: list[str] = Field(default_factory=list)
    ready_for_confirmation: bool = False
    next_question: str = "Please confirm or provide edits."

    @field_validator(
        "preparation_summary",
        "smoke_command",
        "patch_plan",
        "next_question",
        mode="before",
    )
    @classmethod
    def _normalize_scalar(cls, value: Any) -> str:
        return sanitize_model_text(value)

    @field_validator("changed_files", "missing_fields", mode="before")
    @classmethod
    def _normalize_list(cls, value: Any) -> list[str]:
        return sanitize_model_list(value)

    @model_validator(mode="after")
    def _enforce_confirmation_gate(self) -> "SetupPreparation":
        if not self.preparation_summary and self.patch_plan:
            self.preparation_summary = self.patch_plan.split(";", 1)[0].strip()
        missing = []
        if not self.preparation_summary:
            missing.append("preparation_summary")
        if not self.changed_files:
            missing.append("changed_files")
        if not self.smoke_command:
            missing.append("smoke_command")
        if not self.patch_plan:
            missing.append("patch_plan")
        self.missing_fields = missing
        if missing:
            self.ready_for_confirmation = False
            self.next_question = sanitize_model_text(self.next_question)
            if not self.next_question or "confirm" in self.next_question.lower():
                self.next_question = (
                    "Please clarify the single most important smoke preparation detail."
                )
        else:
            self.next_question = (
                sanitize_model_text(self.next_question)
                or "Reply `confirm` or provide edits."
            )
        if self.next_question and "<system-reminder>" in self.next_question.lower():
            self.next_question = "Reply `confirm` or provide edits."
        return self


class SetupPatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "patched"
    summary: str = ""
    changed_files: list[str] = Field(default_factory=list)
    user_action: str = ""

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, value: Any) -> str:
        raw = sanitize_model_text(value).lower()
        aliases = {
            "patched": "patched",
            "fixed": "patched",
            "done": "patched",
            "needs_user_action": "needs_user_action",
            "user_action": "needs_user_action",
            "blocked": "needs_user_action",
        }
        return aliases.get(raw, "patched")

    @field_validator("summary", "user_action", mode="before")
    @classmethod
    def _normalize_summary(cls, value: Any) -> str:
        return sanitize_model_text(value)

    @field_validator("changed_files", mode="before")
    @classmethod
    def _normalize_changed_files(cls, value: Any) -> list[str]:
        return sanitize_model_list(value)


class ResearchPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypothesis: str = ""
    tmux_session_name: str = ""
    launch_command: str = ""
    files_to_modify: list[str] = Field(default_factory=list)
    polling_interval_seconds: int = 30

    @field_validator("hypothesis", "tmux_session_name", "launch_command", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return sanitize_model_text(value)

    @field_validator("files_to_modify", mode="before")
    @classmethod
    def _normalize_files(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [
            sanitize_model_text(item) for item in value if sanitize_model_text(item)
        ]

    @field_validator("polling_interval_seconds", mode="before")
    @classmethod
    def _normalize_polling_interval(cls, value: Any) -> int:
        try:
            polling = int(value)
        except (TypeError, ValueError):
            return 30
        return max(5, min(polling, 3600))


class ResearchPatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "patched"
    summary: str = ""
    changed_files: list[str] = Field(default_factory=list)
    launch_command: str = ""
    user_action: str = ""

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, value: Any) -> str:
        raw = sanitize_model_text(value).lower()
        aliases = {
            "patched": "patched",
            "fixed": "patched",
            "done": "patched",
            "needs_user_action": "needs_user_action",
            "user_action": "needs_user_action",
            "blocked": "needs_user_action",
        }
        return aliases.get(raw, "patched")

    @field_validator("summary", "launch_command", "user_action", mode="before")
    @classmethod
    def _normalize_text_fields(cls, value: Any) -> str:
        return sanitize_model_text(value)

    @field_validator("changed_files", mode="before")
    @classmethod
    def _normalize_changed_files(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [
            sanitize_model_text(item) for item in value if sanitize_model_text(item)
        ]


class FeedbackSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    next_phase: str = "research"
    suggested_sleep_sec: int = 0
    main_metric: str = ""
    sub_metric: str = "null"
    status: str = ""
    description: str = ""
    branch_action: str = "keep_current_commit"
    accepted_commit: str = ""
    record_error: bool = False
    error_summary: str = ""

    @field_validator(
        "main_metric",
        "sub_metric",
        "description",
        "accepted_commit",
        "error_summary",
        mode="before",
    )
    @classmethod
    def _normalize_feedback_text(cls, value: Any) -> str:
        return sanitize_model_text(value)

    @field_validator("sub_metric", mode="before")
    @classmethod
    def _normalize_sub_metric(cls, value: Any) -> str:
        text = sanitize_model_text(value)
        return text if text else "null"

    @field_validator("next_phase", mode="before")
    @classmethod
    def _normalize_next_phase(cls, value: Any) -> str:
        raw = sanitize_model_text(value).lower()
        return raw if raw in {"research", "feedback"} else "research"

    @field_validator("suggested_sleep_sec", mode="before")
    @classmethod
    def _normalize_sleep(cls, value: Any) -> int:
        try:
            sleep = int(value)
        except (TypeError, ValueError):
            return 0
        return max(0, min(sleep, 86400))

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_feedback_status(cls, value: Any) -> str:
        raw = sanitize_model_text(value).lower()
        aliases = {
            "keep": "keep",
            "accepted": "keep",
            "improved": "keep",
            "discard": "discard",
            "drop": "discard",
            "worse": "discard",
            "crash": "crash",
            "failed": "crash",
            "timeout": "crash",
        }
        return aliases.get(raw, "crash")

    @field_validator("branch_action", mode="before")
    @classmethod
    def _normalize_branch_action(cls, value: Any) -> str:
        raw = sanitize_model_text(value).lower()
        allowed = {
            "keep_current_commit",
            "reset_to_previous_accepted_commit",
            "record_failure",
            "wait",
        }
        return raw if raw in allowed else "record_failure"

    @model_validator(mode="after")
    def _align_feedback_fields(self) -> "FeedbackSummary":
        if self.status == "keep":
            self.branch_action = "keep_current_commit"
        elif self.status == "discard":
            self.branch_action = "reset_to_previous_accepted_commit"
        elif self.status == "crash":
            self.branch_action = "record_failure"
        if not self.sub_metric:
            self.sub_metric = "null"
        return self


class LoopFinalSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = ""

    @field_validator("summary", mode="before")
    @classmethod
    def _normalize_summary(cls, value: Any) -> str:
        return sanitize_model_text(value)


ModelT = TypeVar("ModelT", bound=BaseModel)


def empty_contract_state() -> ContractState:
    return ContractState()


def empty_setup_state() -> ContractState:
    return empty_contract_state()


SetupState = ContractState


def parse_contract_markdown(text: str) -> ContractState:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line.startswith("# "):
            current = line[2:].strip().lower()
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)

    def bullet_value(lines: list[str], key: str) -> str:
        prefix = f"- {key}:"
        for line in lines:
            stripped = line.strip()
            if stripped.lower().startswith(prefix.lower()):
                return stripped[len(prefix) :].strip()
        return ""

    def bullet_list(lines: list[str]) -> list[str]:
        items: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("- "):
                items.append(stripped[2:].strip())
        return items

    stop_lines = [
        line.strip() for line in sections.get("stop condition", []) if line.strip()
    ]
    return ContractState(
        research_goal=" ".join(
            line.strip() for line in sections.get("research goal", []) if line.strip()
        ),
        evaluation=Evaluation(
            main_metric=bullet_value(sections.get("evaluation", []), "main metric tag"),
            direction=bullet_value(sections.get("evaluation", []), "direction"),
            tie_breaker=bullet_value(
                sections.get("evaluation", []), "tie-breaker metric tag"
            ),
        ),
        execution=Execution(
            experiment_time=bullet_value(
                sections.get("execution", []), "experiment time"
            ),
            train_entrypoint=bullet_value(
                sections.get("execution", []), "train entrypoint"
            ),
        ),
        stop_condition=" ".join(stop_lines),
        allowed_modifications=bullet_list(sections.get("allowed modifications", [])),
        forbidden_modifications=bullet_list(
            sections.get("forbidden modifications", [])
        ),
        ready_for_review=True,
        next_question="confirm",
    )


def load_contract_markdown(path: Path) -> ContractState:
    return parse_contract_markdown(path.read_text(encoding="utf-8", errors="ignore"))


def structured_output_format(
    model_type: type[ModelT], retry_count: int = 2
) -> Dict[str, Any]:
    schema = model_type.model_json_schema()
    schema["additionalProperties"] = False
    return {
        "type": "json_schema",
        "schema": schema,
        "retryCount": retry_count,
    }


def parse_model_output(model_type: type[ModelT], payload: Dict[str, Any]) -> ModelT:
    return model_type.model_validate(payload)
