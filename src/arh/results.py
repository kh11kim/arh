from __future__ import annotations

from pathlib import Path


RESULTS_TEMPLATE = """# RESEARCH PHASE LOG
columns: exp_id | tmux_session_name | commit | hypothesis

# FEEDBACK PHASE LOG
columns: exp_id | main_metric_value | sub_metric_value | status | description
"""


def ensure_results_file(path: Path) -> None:
    if path.exists():
        return
    path.write_text(RESULTS_TEMPLATE, encoding="utf-8")


def _sanitize_cell(value: str) -> str:
    return str(value).replace("|", "/").replace("\n", " ").strip()


def _read_lines(path: Path) -> list[str]:
    ensure_results_file(path)
    return path.read_text(encoding="utf-8", errors="ignore").splitlines()


def _write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _append_row(path: Path, header: str, row: list[str]) -> None:
    lines = _read_lines(path)
    row_text = " | ".join(_sanitize_cell(item) for item in row)
    insert_index: int | None = None
    in_section = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == header:
            in_section = True
            continue
        if in_section and stripped.startswith("# "):
            insert_index = index
            break
    if insert_index is None:
        insert_index = len(lines)
    if insert_index > 0 and lines[insert_index - 1].strip() != "":
        lines.insert(insert_index, "")
        insert_index += 1
    lines.insert(insert_index, row_text)
    _write_lines(path, lines)


def append_research_row(
    path: Path,
    exp_id: int,
    tmux_session_name: str,
    commit_hash: str,
    hypothesis: str,
) -> None:
    _append_row(
        path,
        "# RESEARCH PHASE LOG",
        [str(exp_id), tmux_session_name, commit_hash, hypothesis],
    )


def append_feedback_row(
    path: Path,
    exp_id: int,
    main_metric: str,
    sub_metric: str,
    status: str,
    description: str,
) -> None:
    _append_row(
        path,
        "# FEEDBACK PHASE LOG",
        [str(exp_id), main_metric, sub_metric, status, description],
    )


def _parse_rows(lines: list[str], header: str) -> list[list[str]]:
    rows: list[list[str]] = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# "):
            in_section = stripped == header
            continue
        if not in_section or not stripped or stripped.startswith("columns:"):
            continue
        rows.append([part.strip() for part in line.split("|")])
    return rows


def read_research_rows(path: Path) -> list[dict[str, str]]:
    lines = _read_lines(path)
    rows = _parse_rows(lines, "# RESEARCH PHASE LOG")
    result: list[dict[str, str]] = []
    for row in rows:
        if len(row) < 4:
            continue
        result.append(
            {
                "exp_id": row[0],
                "tmux_session_name": row[1],
                "commit": row[2],
                "hypothesis": row[3],
            }
        )
    return result


def read_feedback_rows(path: Path) -> list[dict[str, str]]:
    lines = _read_lines(path)
    rows = _parse_rows(lines, "# FEEDBACK PHASE LOG")
    result: list[dict[str, str]] = []
    for row in rows:
        if len(row) < 5:
            continue
        result.append(
            {
                "exp_id": row[0],
                "main_metric": row[1],
                "sub_metric": row[2],
                "status": row[3],
                "description": row[4],
            }
        )
    return result


def next_research_exp_id(path: Path) -> int:
    rows = read_research_rows(path)
    if not rows:
        return 1
    return max(int(row["exp_id"]) for row in rows) + 1


def find_pending_feedback_exp_id(path: Path) -> int | None:
    research = read_research_rows(path)
    feedback_ids = {row["exp_id"] for row in read_feedback_rows(path)}
    for row in reversed(research):
        if row["exp_id"] not in feedback_ids:
            return int(row["exp_id"])
    return None
