from __future__ import annotations

import json
import os
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

from .opencode import (
    create_session,
    extract_text_reply,
    send_session_message,
    start_server,
    stop_process,
    wait_for_health,
)


RUN_DIR = Path(".autoresearch")
STATE_FILE = "state.json"
JOURNAL_FILE = "journal.jsonl"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def run_path(cwd: Path) -> Path:
    return cwd / RUN_DIR


def state_path(cwd: Path) -> Path:
    return run_path(cwd) / STATE_FILE


def journal_path(cwd: Path) -> Path:
    return run_path(cwd) / JOURNAL_FILE


def ensure_run_dir(cwd: Path) -> None:
    run_path(cwd).mkdir(parents=True, exist_ok=True)


def init_state(cwd: Path, spec_path: str = "experiment.md") -> Dict[str, Any]:
    ensure_run_dir(cwd)
    state_file = state_path(cwd)
    if state_file.exists():
        raise FileExistsError(
            "already initialized: .autoresearch/state.json already exists"
        )

    state = {
        "status": "initialized",
        "run_id": f"run-{int(time.time())}",
        "tick": 0,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "spec_path": spec_path,
        "last_summary": "Initialized.",
    }
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


def load_state(cwd: Path) -> Dict[str, Any]:
    state_file = state_path(cwd)
    if not state_file.exists():
        raise FileNotFoundError(
            "not initialized: .autoresearch/state.json is missing. run `arh init` first"
        )
    return json.loads(state_file.read_text(encoding="utf-8"))


def save_state(cwd: Path, state: Dict[str, Any]) -> None:
    state["updated_at"] = now_iso()
    state_path(cwd).write_text(json.dumps(state, indent=2), encoding="utf-8")


def append_journal(cwd: Path, event: Dict[str, Any]) -> None:
    ensure_run_dir(cwd)
    payload = dict(event)
    payload["_at"] = now_iso()
    with journal_path(cwd).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + os.linesep)


def read_spec(cwd: Path, state: Dict[str, Any]) -> str:
    path = cwd / state.get("spec_path", "experiment.md")
    if not path.exists():
        return "(spec file not found)"
    return path.read_text(encoding="utf-8", errors="ignore")


def read_recent_journal(cwd: Path, max_lines: int = 20) -> List[Dict[str, Any]]:
    path = journal_path(cwd)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        lines = deque(handle, maxlen=max_lines)
    result: List[Dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return result


def make_context(state: Dict[str, Any], cwd: Path) -> Dict[str, Any]:
    return {
        "run_id": state.get("run_id"),
        "tick": state.get("tick", 0),
        "status": state.get("status"),
        "spec_path": state.get("spec_path", "experiment.md"),
        "spec_excerpt": read_spec(cwd, state)[:600],
        "recent_decisions": [
            item
            for item in read_recent_journal(cwd, max_lines=10)
            if item.get("type") == "decision"
        ],
    }


def make_decision(context: Dict[str, Any]) -> Dict[str, Any]:
    tick = int(context.get("tick", 0))
    return {
        "type": "decision",
        "summary": f"tick {tick + 1} executed; ready for next research step",
        "next_action": {
            "type": "request_observation",
            "detail": "run an experiment based on this context and report results via `arh note`",
        },
        "state_update": {"status": "running" if tick < 1000 else "stopped"},
        "memory_update": "Persist the latest evidence and continue loop-based reasoning.",
    }


@dataclass
class TickResult:
    state: Dict[str, Any]
    context: Dict[str, Any]
    decision: Dict[str, Any]


def run_tick(cwd: Path = Path(".")) -> TickResult:
    state = load_state(cwd)
    if state.get("status") == "stopped":
        return TickResult(
            state=state,
            context={},
            decision={"type": "noop", "summary": "already stopped"},
        )

    context = make_context(state, cwd)
    decision = make_decision(context)
    state["tick"] = int(state.get("tick", 0)) + 1
    state["status"] = decision.get("state_update", {}).get(
        "status", state.get("status")
    )
    state["last_summary"] = decision.get("summary", "")
    save_state(cwd, state)
    append_journal(cwd, context)
    append_journal(cwd, decision)
    return TickResult(state=state, context=context, decision=decision)


def run_loop(
    cwd: Path, max_ticks: int = 1, sleep_secs: float = 0.0
) -> List[TickResult]:
    results: List[TickResult] = []
    for _ in range(max_ticks):
        result = run_tick(cwd)
        results.append(result)
        if result.state.get("status") == "stopped":
            break
        if sleep_secs > 0:
            time.sleep(sleep_secs)
    return results


def record_note(cwd: Path, text: str) -> None:
    append_journal(cwd, {"type": "note", "text": text})


def run_status(cwd: Path) -> str:
    state = load_state(cwd)
    history = read_recent_journal(cwd, max_lines=5)
    lines = [
        "Status summary",
        f"run_id: {state.get('run_id')}",
        f"status: {state.get('status')}",
        f"tick: {state.get('tick')}",
        f"spec: {state.get('spec_path')}",
        f"last_summary: {state.get('last_summary')}",
    ]
    if history:
        lines.append(f"recent_events: {len(history)}")
        for idx, item in enumerate(history[-3:], start=1):
            lines.append(
                f"  {idx}) {item.get('type')}: {item.get('summary', item.get('text', ''))}"
            )
    return "\n".join(lines)


def run_opencode_smoke(
    prompt: str = "Say hello in one short sentence.",
    host: str = "127.0.0.1",
    port: int = 4096,
    model: str | None = None,
) -> Dict[str, Any]:
    parsed = urlparse(f"http://{host}:{port}")
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    process = start_server(host=host, port=port)
    try:
        health = wait_for_health(base_url)
        session = create_session(base_url, title="arh smoke test")
        session_id = session.get("id") or session.get("session", {}).get("id")
        if not isinstance(session_id, str) or not session_id:
            raise RuntimeError(f"failed to extract session id from response: {session}")
        message = send_session_message(base_url, session_id, prompt, model=model)
        return {
            "base_url": base_url,
            "health": health,
            "session": session,
            "session_id": session_id,
            "message": message,
            "reply_text": extract_text_reply(message),
        }
    finally:
        stop_process(process)
