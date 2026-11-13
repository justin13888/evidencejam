"""Question input and answers.json output, plus a strict validator mirroring the README format."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path

import yaml

from camoreasoning.contracts import Answer, Question
from camoreasoning.schema import ANSWER_CERTAINTY, DIRECTIONS, STATUSES


def load_questions(path: Path) -> list[Question]:
    """Accepts {questions: [...]}, a bare list, or JSON. Entries need `question` (or `text`); missing
    ids become Q-001...; ids are always strings; nothing is dropped or deduplicated."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8-sig"))
    if isinstance(raw, dict):
        raw = raw.get("questions", raw.get("items", []))
    out = []
    for i, q in enumerate(raw or []):
        if isinstance(q, dict):
            qid, text = q.get("id"), q.get("question", q.get("text"))
        else:
            qid, text = None, q
        qid = f"Q-{i + 1:03d}" if qid is None or str(qid).strip() == "" else str(qid)
        out.append(Question(id=qid, text=" ".join(str(text or "").split())))
    return out


def write_answers(path: Path, team: str, answers: Iterable[Answer]) -> None:
    """Atomic write so a crash never leaves a half-written answers.json."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"team": team, "answers": [a.to_json() for a in answers]}
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".answers.", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def validate_entry(a: dict, edge_ids: set[str]) -> list[str]:
    """Errors for one answers.json entry (empty list = parses and is well-formed)."""
    e = []
    if not isinstance(a, dict):
        return ["entry is not an object"]
    if not isinstance(a.get("id"), str) or not a.get("id"):
        e.append("id missing")
    status = a.get("status")
    if status not in STATUSES:
        e.append(f"status {status!r}")
    if not isinstance(a.get("answer"), str) or not a["answer"].strip():
        e.append("answer empty")
    c = a.get("confidence")
    if isinstance(c, bool) or not isinstance(c, (int, float)) or not 0 <= c <= 1:
        e.append(f"confidence {c!r}")
    ids = a.get("edge_ids")
    if not isinstance(ids, list):
        e.append("edge_ids not a list")
        ids = []
    if missing := [x for x in ids if x not in edge_ids]:
        e.append(f"unknown edge_ids {missing[:3]}")
    if status == "answered":
        if a.get("direction") not in DIRECTIONS:
            e.append(f"direction {a.get('direction')!r}")
        if a.get("certainty") not in ANSWER_CERTAINTY:
            e.append(f"certainty {a.get('certainty')!r}")
        if not ids:
            e.append("answered without edge_ids")
    elif status == "no_evidence":
        if a.get("direction") is not None:
            e.append("no_evidence with direction")
        if not isinstance(a.get("searched_for"), str) or not a["searched_for"].strip():
            e.append("no_evidence without searched_for")
    if not isinstance(a.get("extras", []), list):
        e.append("extras not a list")
    return e


def validate_answers(doc: dict, edge_ids: set[str], question_ids: Sequence[str] | None = None) -> dict:
    """Returns {"errors": [...], "parse_rate": float, "n": int}. Covers every README scoring rule we
    can check locally: shape, enums, edge ids exist, one entry per question."""
    errors: list[str] = []
    if not isinstance(doc, dict) or not isinstance(doc.get("answers"), list):
        return {"errors": ["top level must be {team, answers: [...]}"], "parse_rate": 0.0, "n": 0}
    if not isinstance(doc.get("team"), str):
        errors.append("team missing")
    bad = 0
    for a in doc["answers"]:
        if errs := validate_entry(a, edge_ids):
            bad += 1
            errors += [f"{a.get('id') if isinstance(a, dict) else '?'}: {x}" for x in errs]
    if question_ids is not None:
        got = [a.get("id") for a in doc["answers"] if isinstance(a, dict)]
        if missing := [q for q in question_ids if q not in set(got)]:
            errors.append(f"missing ids (scored wrong at full confidence): {missing[:5]}")
        if len(got) - len(set(got)) > len(question_ids) - len(set(question_ids)):
            errors.append("duplicate ids")
    n = len(doc["answers"])
    return {"errors": errors, "parse_rate": 1 - bad / n if n else 1.0, "n": n}
