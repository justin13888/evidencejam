"""Bulk labelling harness (offline). Deliberately small and file-based so any strong model can fill it:
a Claude Code session (see .claude/agents/labeler.md) or the endpoint (`annotate run`).

    experiments/annotate/<task>/
      PROMPT.md          instructions, owner-edited (written once by `export`, never overwritten)
      vocab.json         task-wide allowed values (e.g. class ids); part of the stable prompt prefix
      in/NNNN.jsonl      items to label, one JSON object per line, each with "id"
      in/NNNN.meta.jsonl hidden per-item data (real edge ids, seeds); never shown to the labeller
      out/NNNN.jsonl     labels, one JSON object per line: {"id": ..., <fields>, "note"?: str}
      merged.jsonl       valid labels + meta, consumed by the `annotated` strategies
      human.jsonl        human corrections from `review import`; they win in `merge`

Anti-hallucination is enforced by `check`, not trusted: exact id set per chunk, closed vocabularies,
references only to ids the item offered (gold uses short refs e1..eN, mapped back at merge),
cross-field rules, no extra keys. Commands: export | check | merge | run | review-export | review-import.
"""

from __future__ import annotations

import csv
import json
import math
import random
import re
from collections import Counter, defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from camoreasoning.config import ANNOTATE_DIR, DEVSETS_DIR
from camoreasoning.schema import ANSWER_CERTAINTY, DIRECTIONS, STATUSES
from camoreasoning.signs import is_null_finding, predicate_sign, variable_level_sign
from camoreasoning.text import tokens

TRAP_TAGS = ("trap:null", "trap:removed_subject", "trap:unchanged", "trap:associational", "trap:sign_flip",
             "trap:twin", "trap:moderator", "trap:reversed")  # fmt: skip
OPTIONAL_KEYS = ("note",)  # labeller may flag doubts; shown in review


# --- field specs: each returns an error string or None ----------------------------------------------


@dataclass(frozen=True)
class Spec:
    check: Callable[[Any, dict, dict], str | None]  # (value, item, vocab) -> error
    fmt: Callable[[Any], str] = lambda v: "" if v is None else str(v)  # for review CSVs
    parse: Callable[[str], Any] = lambda s: s  # inverse of fmt for human corrections


def enum(*values, nullable: bool = False) -> Spec:
    def check(v, item, vocab):
        return None if v in values or (nullable and v is None) else f"{v!r} not in {list(values)}"

    def parse(s):
        s = s.strip()
        if s in ("", "null", "None"):
            return None
        for v in values:
            if str(v) == s or (isinstance(v, int) and s.lstrip("+") == str(v)):
                return v
        return s

    return Spec(check, parse=parse)


def text(max_len: int = 200) -> Spec:
    def check(v, item, vocab):
        return None if isinstance(v, str) and 0 < len(v.strip()) <= max_len else f"need text <= {max_len} chars"

    return Spec(check)


def labelled_refs(key: str, ref_name: str, label_name: str, labels: tuple, where: str) -> Spec:
    """List of {ref_name: <id from item/vocab[key]>, label_name: <one of labels>}, refs unique."""

    def allowed(item, vocab):
        return set(item.get(key) or ()) if where == "item" else set(vocab.get(key) or ())

    def check(v, item, vocab):
        if not isinstance(v, list):
            return "need a list"
        ok, seen = allowed(item, vocab), set()
        for x in v:
            if not isinstance(x, dict) or set(x) != {ref_name, label_name}:
                return f"each entry must be exactly {{{ref_name!r}, {label_name!r}}}"
            if x[ref_name] not in ok:
                return f"unknown {ref_name} {x[ref_name]!r} (not offered)"
            if x[ref_name] in seen:
                return f"duplicate {ref_name} {x[ref_name]!r}"
            if x[label_name] not in labels:
                return f"{label_name} {x[label_name]!r} not in {list(labels)}"
            seen.add(x[ref_name])
        return None

    def fmt(v):
        return "; ".join(f"{x[ref_name]}:{'+' if x[label_name] == 1 else ''}{x[label_name]}" for x in v or [])

    def parse(s):
        out = []
        for part in filter(None, (p.strip() for p in s.split(";"))):
            ref, _, lab = part.rpartition(":")
            lab = lab.strip().lstrip("+")
            out.append({ref_name: ref.strip(), label_name: None if lab in ("", "None", "null") else int(lab)})
        return out

    return Spec(check, fmt, parse)


# --- tasks --------------------------------------------------------------------------------------------


@dataclass
class Task:
    name: str
    fields: dict[str, Spec]
    build: Callable[..., tuple[list[dict], dict]]  # (ctx, n, seed) -> (items, vocab)
    prompt: str
    tokens_per_item: int = 64
    row_check: Callable[[dict], str | None] = lambda row: None
    finalize: Callable[[dict, dict], dict] = lambda row, meta: {**row, "_meta": meta}  # label + meta -> merged
    defaults: dict = field(default_factory=dict)


def _node_text(n: dict, limit: int = 220) -> str:
    return (n.get("embedding_text") or n.get("name") or "")[:limit]


def _build_node_labels(ctx, n: int | None, seed: int) -> tuple[list[dict], dict]:
    tax = ctx.taxonomy
    if tax.empty:
        raise SystemExit("node_labels needs taxonomy classes first (taxonomy/classes.yaml)")
    vocab = {"classes": sorted(tax.classes),
             "class_info": {c.id: {"kind": c.kind, "label": c.label, "synonyms": list(c.synonyms),
                                   "description": c.description} for c in tax.classes.values()}}  # fmt: skip
    used = {e["subject"] for e in ctx.graph.edges.values()} | {e["object"] for e in ctx.graph.edges.values()}
    ids = sorted(used)
    if n:
        ids = random.Random(seed).sample(ids, min(n, len(ids)))
    return [{"id": i, "node": _node_text(ctx.graph.nodes[i])} for i in ids], vocab


def _edge_view(g, eid: str, ref: str | None = None, sentence: int = 300) -> dict:
    e = g.edges[eid]
    s, o = g.nodes[e["subject"]], g.nodes[e["object"]]
    d = {"subject": _node_text(s, 160), "predicate": e.get("predicate"), "object": _node_text(o, 160),
         "negated": bool(e.get("negated")), "language": e.get("causal_language"),
         "grade": e.get("certainty_grade"), "study": e.get("source_document"),
         "sentence": (e.get("original_sentence") or "")[:sentence]}  # fmt: skip
    return {"ref": ref, **d} if ref else d


def edge_trap_tags(g, eid: str, twins: set[str]) -> list[str]:
    """Mechanical trap hints for a seed edge (what a misreading of this edge would get wrong)."""
    e = g.edges[eid]
    s, o = g.nodes[e["subject"]], g.nodes[e["object"]]
    tags = []
    if is_null_finding(e):
        tags.append("trap:null")
    if s.get("state_or_change_qualifier") in ("removed", "decreased", "absent", "terminated", "interrupted"):
        tags.append("trap:removed_subject")
    if "unchanged" in (s.get("state_or_change_qualifier"), o.get("state_or_change_qualifier")):
        tags.append("trap:unchanged")
    if e.get("predicate") in ("associated_with", "correlated_with"):
        tags.append("trap:associational")
    p, v = predicate_sign(e.get("predicate")), variable_level_sign(e, s, o)
    if p is not None and v is not None and p != v and not is_null_finding(e):
        tags.append("trap:sign_flip")
    if eid in twins:
        tags.append("trap:twin")
    if e.get("predicate") in ("moderates", "mediates"):
        tags.append("trap:moderator")
    return tags


def _build_questions(ctx, n: int | None, seed: int) -> tuple[list[dict], dict]:
    """~2/3 seed edges (stratified by trap hint, ~1/8 asked in reverse) + ~1/3 random node pairs."""
    g, rng = ctx.graph, random.Random(seed)
    n = n or 180
    by_sentence = defaultdict(list)
    for eid, e in g.edges.items():
        by_sentence[(e.get("source_document"), e.get("original_sentence"))].append(eid)
    twins = {x for ids in by_sentence.values() if len(ids) > 1 for x in ids}
    tagged = {eid: edge_trap_tags(g, eid, twins) for eid in g.edges}
    n_seed, picked = n * 2 // 3, []
    for tag in TRAP_TAGS[:-1]:
        pool = sorted(e for e, t in tagged.items() if tag in t)
        picked += rng.sample(pool, min(len(pool), max(1, n_seed // 12)))
    rest = sorted(set(g.edges) - set(picked))
    picked = list(dict.fromkeys(picked + rng.sample(rest, max(0, n_seed - len(picked)))))[:n_seed]
    items = []
    for i, eid in enumerate(picked):
        reverse = i % 8 == 7
        hint = tagged[eid] + (["trap:reversed"] if reverse else [])
        view = _edge_view(g, eid)
        items.append({"id": f"Q{len(items) + 1:04d}", "kind": "edge", "ask": "reverse" if reverse else "forward",
                      **{k: view[k] for k in ("subject", "predicate", "object", "sentence")},
                      "_meta": {"seed_edge": eid, "hint_tags": hint}})  # fmt: skip
    subjects, objects = sorted(g.out_edges), sorted(g.in_edges)
    while len(items) < n:
        s, o = rng.choice(subjects), rng.choice(objects)
        if s == o or g.edges_between({s}, {o}):
            continue
        items.append({"id": f"Q{len(items) + 1:04d}", "kind": "pair", "ask": "forward",
                      "subject": _node_text(g.nodes[s], 160), "object": _node_text(g.nodes[o], 160),
                      "_meta": {"pair": [s, o], "hint_tags": ["pair"]}})  # fmt: skip
    return items, {}


_SPLIT = re.compile(r"^what (?:is the )?effects? (?:does|do|did) (?P<c>.+?) (?:have|has) on (?P<o>.+?)[?.!]*$", re.I)


_GOLD_IDX: dict[int, tuple] = {}


def gold_candidates(g, question: str, k: int = 60, seed_edge: str | None = None) -> list[str]:
    """Taxonomy-free prefilter: IDF overlap of each question side with node text, both edge directions.
    Lexical, so broad wording can miss specific nodes; the labeller may say so in `note`."""
    m = _SPLIT.match(" ".join(question.split()))
    c_side, o_side = (m["c"], m["o"]) if m else (question, question)
    if id(g) not in _GOLD_IDX:
        toks = {nid: set(tokens(_node_text(n, 400))) for nid, n in g.nodes.items()}
        df = Counter(t for ts in toks.values() for t in ts)
        _GOLD_IDX[id(g)] = (toks, {t: math.log(len(toks) / c) + 1 for t, c in df.items()})
    toks, idf = _GOLD_IDX[id(g)]

    def cov(q: set[str], node: str) -> float:
        tot = sum(idf.get(t, 1.0) for t in q)
        return sum(idf.get(t, 1.0) for t in q & toks[node]) / tot if tot else 0.0

    qc, qo = set(tokens(c_side)), set(tokens(o_side))
    scored = []
    for eid, e in g.edges.items():
        fwd = cov(qc, e["subject"]) * cov(qo, e["object"])
        rev = cov(qo, e["subject"]) * cov(qc, e["object"])
        if max(fwd, rev) > 0:
            scored.append((max(fwd, rev), eid))
    out = [eid for _, eid in sorted(scored, reverse=True)[:k]]
    if seed_edge and seed_edge in g.edges and seed_edge not in out:
        out = [seed_edge] + out[: k - 1]
    return out


def _build_gold(ctx, n: int | None, seed: int) -> tuple[list[dict], dict]:
    path = DEVSETS_DIR / "generated.yaml"
    if not path.exists():
        raise SystemExit("gold needs experiments/devsets/generated.yaml (run `camoreasoning devset --build-only`)")
    rows = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("items") or []
    if n:
        rows = rows[:n]
    items = []
    for r in rows:
        cands = gold_candidates(ctx.graph, r["question"], seed_edge=(r.get("meta") or {}).get("seed_edge"))
        refs = {f"e{i + 1}": eid for i, eid in enumerate(cands)}
        items.append({"id": str(r["id"]), "question": r["question"],
                      "candidates": [_edge_view(ctx.graph, eid, ref) for ref, eid in refs.items()],
                      "refs": list(refs), "_meta": {"refs": refs, "tags": r.get("tags") or [],
                                                     "split": r.get("split", "dev")}})  # fmt: skip
    return items, {}


def _gold_row_check(row: dict) -> str | None:
    if row.get("status") == "no_evidence":
        if row.get("direction") is not None or row.get("certainty") is not None or row.get("edges"):
            return "no_evidence needs direction=null, certainty=null, edges=[]"
    elif row.get("status") == "answered" and (
        row.get("direction") is None or row.get("certainty") is None or not row.get("edges")
    ):
        return "answered needs direction, certainty and at least one edge"
    return None


def _gold_finalize(row: dict, meta: dict) -> dict:
    refs = meta.get("refs") or {}
    return {**row, "edges": [{"id": refs[x["ref"]], "effect": x["effect"]} for x in row.get("edges") or []],
            "_meta": meta}  # fmt: skip


PROMPTS = {
    "node_labels": """# Task: label graph nodes with taxonomy classes

Each input line is one node of an ecological causal graph (`node` = name | entity | attribute | qualifier).
Output one JSON line per input line: {"id": <same id>, "labels": [{"class": <class id>, "polarity": -1|0|1}]}

- `class` must be one of `classes` in vocab.json (read `class_info` for meaning). Use [] if none fits.
- A node may get several classes (e.g. "Removal of buckthorn" -> invasive_removal +1 AND invasive_abundance -1).
- polarity = the node's state relative to the class concept, qualifier folded in:
  increased/present/introduced/occurred -> +1; decreased/absent/removed/terminated -> -1; unchanged -> 0.
- Keep near-misses apart: native vs non-native, survival vs growth, cover vs richness.
- Optional "note" for doubts. No other keys. Never invent ids or classes.
""",
    "questions": """# Task: write dev questions like the hidden set

Hidden questions ask what one broad kind of intervention or condition does to one broad kind of outcome,
e.g. "What effect does mulch & surface cover have on invasive / non-native species abundance?".
Each input line gives a seed: an edge (`kind: edge`) or a random node pair (`kind: pair`).
Output one JSON line per input: {"id": <same id>, "cause": <broad cause phrase>, "outcome": <broad outcome phrase>}

- Generalise the specific node to the broad class a practitioner would name (2-8 words, lower case).
  Drop the qualifier: "Removal of buckthorn" -> "invasive shrub removal"; "Increased graminoid cover" ->
  "graminoid cover". Keep the measured attribute (cover vs richness vs biomass vs survival...).
- `ask: forward`: cause = subject, outcome = object. `ask: reverse`: cause = object, outcome = subject.
- The question becomes "What effect does <cause> have on <outcome>?" mechanically. Do not answer it.
- Optional "note". No other keys.
""",
    "gold": """# Task: gold-label a question from the graph's own sentences

Input: a question and up to 60 candidate edges (`ref` e1..eN) found by a crude lexical search.
Output one JSON line per input:
{"id": <same id>, "status": "answered"|"no_evidence", "direction": ..., "certainty": ...,
 "edges": [{"ref": "e3", "effect": 1}]}

Rubric (locked decisions, ROADMAP "Decisions"):
- An edge is relevant only if its subject is an instance of the question's cause AND its object an
  instance of the question's outcome. Edges running outcome -> cause are NOT relevant (reversed).
- effect = what the edge says happens to the OUTCOME when the CAUSE is applied/higher, read from the
  sentence: 1 increase, -1 decrease, 0 tested and no effect / no change, null = no usable sign
  (moderator, mediator, pure association with no direction). Watch qualifiers: "removal of X" decreasing Y
  means X increases Y. associated_with/correlated_with count, signed via the qualifiers.
- One vote per study (`study`). direction: a value held by >= 2/3 of studies wins
  (increase / decrease / no_effect); otherwise "mixed"; "unclear" if no study gives a usable sign.
- certainty: median `grade` of the relevant edges, one level lower if mixed or if every edge is
  associational; never "high".
- No relevant edge -> status "no_evidence", direction null, certainty null, edges [].
- If the candidates look incomplete for this question, still label what you see and add a "note".
- Only refs offered in that line. No other keys.
""",
}

TASKS: dict[str, Task] = {
    "node_labels": Task("node_labels", {"labels": labelled_refs("classes", "class", "polarity", (-1, 0, 1), "vocab")},
                        _build_node_labels, PROMPTS["node_labels"], tokens_per_item=40),
    "questions": Task("questions", {"cause": text(80), "outcome": text(80)}, _build_questions,
                      PROMPTS["questions"], tokens_per_item=40),
    "gold": Task("gold", {"status": enum(*STATUSES), "direction": enum(*DIRECTIONS, nullable=True),
                          "certainty": enum(*ANSWER_CERTAINTY, nullable=True),
                          "edges": labelled_refs("refs", "ref", "effect", (-1, 0, 1, None), "item")},
                 _build_gold, PROMPTS["gold"], tokens_per_item=220, row_check=_gold_row_check,
                 finalize=_gold_finalize),
}  # fmt: skip


# --- files ----------------------------------------------------------------------------------------


def task_dir(task: str) -> Path:
    return ANNOTATE_DIR / task


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def vocab(task: str) -> dict:
    p = task_dir(task) / "vocab.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def chunks(task: str) -> list[str]:
    return sorted(p.stem for p in (task_dir(task) / "in").glob("[0-9]*.jsonl") if ".meta" not in p.name)


def export(task: str, ctx, chunk: int = 40, n: int | None = None, seed: int = 0) -> dict:
    """Write items into in/ chunks (clears old in/ but never out/ or PROMPT.md)."""
    t, d = TASKS[task], task_dir(task)
    items, voc = t.build(ctx, n, seed)
    for p in (d / "in").glob("*.jsonl"):
        p.unlink()
    (d / "in").mkdir(parents=True, exist_ok=True)
    if not (d / "PROMPT.md").exists():
        (d / "PROMPT.md").write_text(t.prompt, encoding="utf-8")
    (d / "vocab.json").write_text(json.dumps(voc, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    for i in range(0, len(items), chunk):
        part, name = items[i : i + chunk], f"{i // chunk + 1:04d}"
        _write_jsonl(d / "in" / f"{name}.jsonl", ({k: v for k, v in it.items() if k != "_meta"} for it in part))
        _write_jsonl(d / "in" / f"{name}.meta.jsonl", ({"id": it["id"], **it.get("_meta", {})} for it in part))
    return {"task": task, "items": len(items), "chunks": len(chunks(task)), "dir": str(d)}


def check_rows(task: str, items: list[dict], rows: list[dict], voc: dict) -> tuple[list[str], dict[str, dict]]:
    """Errors and the valid rows (by id) for one chunk."""
    t, errs, ok = TASKS[task], [], {}
    by_id = {it["id"]: it for it in items}
    seen = Counter(r.get("id") if isinstance(r, dict) else None for r in rows)
    for r in rows:
        if not isinstance(r, dict) or r.get("id") not in by_id:
            errs.append(f"unknown id {r.get('id') if isinstance(r, dict) else r!r}")
            continue
        rid = r["id"]
        if seen[rid] > 1:
            errs.append(f"{rid}: duplicate id")
            continue
        extra = set(r) - set(t.fields) - {"id", *OPTIONAL_KEYS}
        missing = set(t.fields) - set(r)
        bad = [f"extra keys {sorted(extra)}"] if extra else []
        bad += [f"missing keys {sorted(missing)}"] if missing else []
        bad += [f"{k}: {e}" for k, s in t.fields.items() if k in r and (e := s.check(r[k], by_id[rid], voc))]
        if not bad and (e := t.row_check(r)):
            bad.append(e)
        if bad:
            errs += [f"{rid}: {b}" for b in bad]
        else:
            ok[rid] = r
    errs += [f"{i}: no label" for i in by_id if i not in seen]
    return errs, ok


def check(task: str, only: str | None = None) -> dict:
    d, voc, report = task_dir(task), vocab(task), {}
    for name in chunks(task):
        if only and name != only.zfill(4):
            continue
        items = _read_jsonl(d / "in" / f"{name}.jsonl")
        try:
            rows = _read_jsonl(d / "out" / f"{name}.jsonl")
        except json.JSONDecodeError as e:
            report[name] = {"errors": [f"out/{name}.jsonl is not JSON lines: {e}"], "valid": 0, "items": len(items)}
            continue
        if not rows:
            report[name] = {"errors": ["not labelled yet"], "valid": 0, "items": len(items)}
            continue
        errs, ok = check_rows(task, items, rows, voc)
        report[name] = {"errors": errs, "valid": len(ok), "items": len(items)}
    todo = [k for k, v in report.items() if v["errors"]]
    return {"task": task, "chunks": len(report), "valid": sum(v["valid"] for v in report.values()),
            "items": sum(v["items"] for v in report.values()), "redo": todo,
            "errors": {k: v["errors"][:10] for k, v in report.items() if v["errors"]}}  # fmt: skip


def merge(task: str) -> dict:
    """merged.jsonl = valid labels (human.jsonl rows replace them) + hidden meta, finalized per task."""
    t, d, voc = TASKS[task], task_dir(task), vocab(task)
    human = {r["id"]: r for r in _read_jsonl(d / "human.jsonl")}
    out, n_human = [], 0
    for name in chunks(task):
        items = _read_jsonl(d / "in" / f"{name}.jsonl")
        meta = {m["id"]: m for m in _read_jsonl(d / "in" / f"{name}.meta.jsonl")}
        _, ok = check_rows(task, items, _read_jsonl(d / "out" / f"{name}.jsonl"), voc)
        for it in items:
            row = ok.get(it["id"])
            if it["id"] in human:
                h = {k: v for k, v in human[it["id"]].items() if k != "by"}
                errs, good = check_rows(task, [it], [h], voc)
                if good:
                    row, n_human = {**good[it["id"]], "by": human[it["id"]].get("by", "human")}, n_human + 1
            if row:
                m = {k: v for k, v in meta.get(it["id"], {}).items() if k != "id"}
                out.append(t.finalize(row, m))
    _write_jsonl(d / "merged.jsonl", out)
    return {"task": task, "merged": len(out), "human": n_human, "path": str(d / "merged.jsonl")}


def merged(task: str) -> list[dict]:
    return _read_jsonl(task_dir(task) / "merged.jsonl")


# --- endpoint runner --------------------------------------------------------------------------------


def run(task: str, llm, workers: int = 4, redo: bool = False) -> dict:
    """Fill out/ for unlabelled (or failing, with redo) chunks via the endpoint. System prompt =
    PROMPT.md + vocab.json, byte-identical across calls so the server's prefix cache can hit."""
    t, d = TASKS[task], task_dir(task)
    system = (d / "PROMPT.md").read_text(encoding="utf-8")
    voc = vocab(task)
    if voc:
        system += "\n## vocab.json\n" + json.dumps(voc, ensure_ascii=False, sort_keys=True)
    system += '\n\nReply with ONE JSON object mapping each input id to its label object (without "id").'
    status = check(task)
    todo = [c for c in chunks(task) if not (d / "out" / f"{c}.jsonl").exists() or (redo and c in status["redo"])]

    def one(name: str) -> str:
        items = _read_jsonl(d / "in" / f"{name}.jsonl")
        try:
            got = llm.batch_json(system, items, chunk=len(items), tokens_per_item=t.tokens_per_item,
                                 purpose=f"annotate:{task}")  # fmt: skip
        except Exception as e:  # noqa: BLE001 - keep other chunks going
            return f"{name}: {e}"
        _write_jsonl(
            d / "out" / f"{name}.jsonl",
            ({"id": k, **v} if isinstance(v, dict) else {"id": k, "value": v} for k, v in got.items()),
        )
        return f"{name}: {len(got)}/{len(items)}"

    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        log = list(ex.map(one, todo))
    return {"ran": log, **{k: v for k, v in check(task).items() if k != "errors"}}


# --- human review -----------------------------------------------------------------------------------


def _describe(item: dict) -> str:
    keep = {k: v for k, v in item.items() if k not in ("id", "refs")}
    if "candidates" in keep:
        keep["candidates"] = "\n".join(
            f"{c['ref']}: {c['subject']} --{c['predicate']}{' (negated)' if c['negated'] else ''}--> {c['object']}"
            f" [{c['study']}] \"{c['sentence']}\"" for c in keep["candidates"])  # fmt: skip
    return "\n".join(f"{k}: {v}" for k, v in keep.items())


def review_export(task: str, out: Path, n: int = 60, stratify: str | None = None, seed: int = 0) -> dict:
    """CSV for non-technical reviewers: context, the model's label, then `ok` (y/n) and human_* columns
    to fill only when ok=n. Lists use "ref:effect; ref:effect"."""
    t, d = TASKS[task], task_dir(task)
    items = {it["id"]: it for c in chunks(task) for it in _read_jsonl(d / "in" / f"{c}.jsonl")}
    rows = [r for r in merged(task) if r["id"] in items]
    rng = random.Random(seed)
    if stratify:
        groups = defaultdict(list)
        for r in rows:
            groups[str(r.get(stratify))].append(r)
        per = max(1, n // max(1, len(groups)))
        pick = [x for g in groups.values() for x in rng.sample(g, min(per, len(g)))][:n]
    else:
        pick = rng.sample(rows, min(n, len(rows)))
    names = list(t.fields)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "context", *[f"model_{k}" for k in names], "model_note", "ok", *[f"human_{k}" for k in names],
                    "reviewer", "comment"])  # fmt: skip
        for r in pick:
            shown = dict(r)
            if task == "gold":  # show refs, not raw edge ids
                inv = {v: k for k, v in (r.get("_meta") or {}).get("refs", {}).items()}
                shown["edges"] = [
                    {"ref": inv.get(x["id"], x["id"]), "effect": x["effect"]} for x in r.get("edges") or []
                ]
            labels = [t.fields[k].fmt(shown.get(k)) for k in names]
            w.writerow([r["id"], _describe(items[r["id"]]), *labels, r.get("note", ""), "", *[""] * len(names), "", ""])
    return {"task": task, "rows": len(pick), "path": str(out)}


def review_import(task: str, path: Path) -> dict:
    """Agreement on reviewed rows (ok = y/n) and human.jsonl corrections for ok = n rows."""
    t, d = TASKS[task], task_dir(task)
    model = {r["id"]: r for r in merged(task)}
    human = {r["id"]: r for r in _read_jsonl(d / "human.jsonl")}
    agree = reviewed = 0
    disagreements: Counter = Counter()
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            ok = (row.get("ok") or "").strip().lower()[:1]
            if ok not in ("y", "n") or row["id"] not in model:
                continue
            reviewed += 1
            if ok == "y":
                agree += 1
                continue
            m = model[row["id"]]
            fixed = {"id": row["id"], "by": row.get("reviewer") or "human"}
            for k, spec in t.fields.items():
                raw = (row.get(f"human_{k}") or "").strip()
                if task == "gold" and k == "edges":
                    inv = {v: kk for kk, v in (m.get("_meta") or {}).get("refs", {}).items()}
                    default = [{"ref": inv.get(x["id"]), "effect": x["effect"]} for x in m.get("edges") or []]
                else:
                    default = m.get(k)
                fixed[k] = spec.parse(raw) if raw else default
                if raw:
                    disagreements[k] += 1
            human[row["id"]] = fixed
    _write_jsonl(d / "human.jsonl", human.values())
    return {"task": task, "reviewed": reviewed, "agreement": round(agree / reviewed, 4) if reviewed else None,
            "fields_corrected": dict(disagreements), "human_rows": len(human)}  # fmt: skip
