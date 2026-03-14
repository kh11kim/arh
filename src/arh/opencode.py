from __future__ import annotations

import json
import queue
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Dict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def json_request(
    method: str,
    url: str,
    payload: Dict[str, Any] | None = None,
    timeout: float = 10.0,
) -> Dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(url, data=data, headers=headers, method=method)
    with urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    if not body:
        return {}
    return json.loads(body)


def start_server(host: str = "127.0.0.1", port: int = 4096) -> subprocess.Popen[str]:
    executable = shutil.which("opencode")
    if executable is None:
        raise FileNotFoundError("`opencode` command not found in PATH")

    command = [executable, "serve", "--hostname", host, "--port", str(port)]
    return subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def wait_for_health(
    base_url: str,
    timeout: float = 20.0,
    interval: float = 0.5,
) -> Dict[str, Any]:
    deadline = time.time() + timeout
    last_error: str | None = None
    while time.time() < deadline:
        try:
            payload = json_request(
                "GET",
                f"{base_url}/global/health",
                timeout=interval + 1,
            )
            if payload.get("healthy") is True:
                return payload
            last_error = f"unexpected health payload: {payload}"
        except (URLError, HTTPError, json.JSONDecodeError) as exc:
            last_error = str(exc)
        time.sleep(interval)
    raise TimeoutError(
        f"OpenCode server health check timed out: {last_error or 'unknown error'}"
    )


def create_session(base_url: str, title: str = "arh session") -> Dict[str, Any]:
    return json_request("POST", f"{base_url}/session", payload={"title": title})


def parse_model_string(model: str | None) -> Dict[str, str] | None:
    if model is None:
        return None
    value = model.strip()
    if not value:
        return None
    if "/" not in value:
        raise ValueError(
            "model must be in '<provider>/<model>' format, for example 'openai/gpt-5.3-codex-spark'"
        )
    provider_id, model_id = value.split("/", 1)
    if not provider_id or not model_id:
        raise ValueError(
            "model must be in '<provider>/<model>' format, for example 'openai/gpt-5.3-codex-spark'"
        )
    return {"providerID": provider_id, "modelID": model_id}


def build_prompt_payload(
    prompt: str,
    model: str | None = None,
    response_format: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "parts": [{"type": "text", "text": prompt}],
    }
    parsed_model = parse_model_string(model)
    if parsed_model is not None:
        payload["model"] = parsed_model
    if response_format is not None:
        payload["format"] = response_format
    return payload


def send_session_message(
    base_url: str,
    session_id: str,
    prompt: str,
    model: str | None = None,
    response_format: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    payload = build_prompt_payload(prompt, model=model, response_format=response_format)
    return json_request(
        "POST",
        f"{base_url}/session/{session_id}/message",
        payload=payload,
        timeout=60.0,
    )


def prompt_session_async(
    base_url: str,
    session_id: str,
    prompt: str,
    model: str | None = None,
    response_format: Dict[str, Any] | None = None,
) -> None:
    payload = build_prompt_payload(prompt, model=model, response_format=response_format)
    json_request(
        "POST",
        f"{base_url}/session/{session_id}/prompt_async",
        payload=payload,
        timeout=30.0,
    )


def get_session_message(
    base_url: str, session_id: str, message_id: str
) -> Dict[str, Any]:
    return json_request("GET", f"{base_url}/session/{session_id}/message/{message_id}")


def _event_subscriber(
    base_url: str,
    event_queue: "queue.Queue[Dict[str, Any]]",
    stop_event: threading.Event,
) -> None:
    request = Request(base_url + "/event", headers={"Accept": "text/event-stream"})
    try:
        with urlopen(request, timeout=300) as response:
            for raw_line in response:
                if stop_event.is_set():
                    return
                line = raw_line.decode("utf-8", errors="ignore").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data:
                    continue
                try:
                    event_queue.put(json.loads(data))
                except json.JSONDecodeError:
                    continue
    except Exception as exc:
        event_queue.put({"type": "stream.error", "properties": {"message": str(exc)}})


def run_streaming_prompt(
    base_url: str,
    session_id: str,
    prompt: str,
    model: str | None = None,
    response_format: Dict[str, Any] | None = None,
    verbose: bool = False,
    status_hint: str | None = None,
) -> Dict[str, Any]:
    def friendly_tool_status(tool_title: str) -> str:
        title = tool_title.strip().lower()
        if not title:
            return status_hint or "Working..."
        if "structuredoutput" in title:
            return "Structuring response..."
        if "read" in title:
            return "Reading files..."
        if "grep" in title or "search" in title or "glob" in title:
            return "Searching code..."
        if "patch" in title or "edit" in title or "write" in title:
            return "Editing files..."
        if "bash" in title or "command" in title or "shell" in title:
            return "Running command..."
        if "task" in title or "agent" in title:
            return "Delegating task..."
        return tool_title.strip() + "..."

    def show_status(text: str) -> None:
        if verbose:
            print(text)
            return
        if not sys.stdout.isatty():
            return
        padded = text.ljust(80)
        sys.stdout.write("\r" + padded)
        sys.stdout.flush()

    def clear_status() -> None:
        if verbose:
            return
        if not sys.stdout.isatty():
            return
        sys.stdout.write("\r" + (" " * 80) + "\r")
        sys.stdout.flush()

    event_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
    stop_event = threading.Event()
    subscriber = threading.Thread(
        target=_event_subscriber,
        args=(base_url, event_queue, stop_event),
        daemon=True,
    )
    subscriber.start()
    time.sleep(0.2)

    show_status(status_hint or "Thinking...")
    prompt_session_async(
        base_url=base_url,
        session_id=session_id,
        prompt=prompt,
        model=model,
        response_format=response_format,
    )

    assistant_message_id = ""
    last_status = ""
    seen_assistant_messages: set[str] = set()
    seen_parts: set[str] = set()
    while True:
        try:
            event = event_queue.get(timeout=0.2)
        except queue.Empty:
            continue

        event_type = event.get("type")
        properties = event.get("properties", {})

        if event_type == "session.status" and properties.get("sessionID") == session_id:
            status = properties.get("status", {}).get("type", "")
            if status and status != last_status:
                if verbose:
                    print(f"[status] {status}")
                elif status == "busy":
                    show_status(status_hint or "Thinking...")
                last_status = status

        if event_type == "message.updated":
            info = properties.get("info", {})
            if info.get("sessionID") == session_id and info.get("role") == "assistant":
                assistant_message_id = info.get("id", assistant_message_id)
                if (
                    assistant_message_id
                    and assistant_message_id not in seen_assistant_messages
                ):
                    seen_assistant_messages.add(assistant_message_id)
                    model_id = info.get("modelID", "unknown-model")
                    if verbose:
                        print(f"[assistant] {model_id} generating...")
                    else:
                        label = status_hint or f"{model_id} generating..."
                        show_status(label)

        if event_type == "message.part.updated":
            part = properties.get("part", {})
            if part.get("sessionID") == session_id:
                part_id = part.get("id", "")
                part_type = part.get("type")
                if part_type in {"step-start", "tool"} and part_id not in seen_parts:
                    seen_parts.add(part_id)
                    if part_type == "step-start":
                        if verbose:
                            print("[step] started")
                        else:
                            show_status(status_hint or "Working...")
                    elif part_type == "tool":
                        title = (
                            part.get("state", {}).get("title")
                            or part.get("tool")
                            or "tool"
                        )
                        if verbose:
                            print(f"[tool] {title}")
                        else:
                            show_status(friendly_tool_status(title))

        if (
            event_type == "message.part.delta"
            and properties.get("sessionID") == session_id
        ):
            delta = properties.get("delta", "")
            if verbose and delta:
                print(f"[stream] {delta}")

        if event_type == "session.idle" and properties.get("sessionID") == session_id:
            break

        if event_type == "stream.error":
            raise RuntimeError(properties.get("message", "event stream error"))

    stop_event.set()
    subscriber.join(timeout=1)
    clear_status()

    if not assistant_message_id:
        raise RuntimeError("assistant message id was not observed during streaming")
    return get_session_message(base_url, session_id, assistant_message_id)


def extract_text_reply(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, list):
        for item in payload:
            text = extract_text_reply(item)
            if text:
                return text
        return ""
    if not isinstance(payload, dict):
        return ""

    payload_type = payload.get("type")
    if payload_type == "text":
        text = payload.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()

    for key in ("text", "content", "message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    for key in ("parts", "messages", "items", "data"):
        value = payload.get(key)
        text = extract_text_reply(value)
        if text:
            return text
    return ""
