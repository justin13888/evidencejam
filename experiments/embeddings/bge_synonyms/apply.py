"""Offline, 0 calls: add audited graph wording as label-only synonyms and relabel only the nodes they change.

    PYTHONPATH=src .venv/bin/python experiments/embeddings/bge_synonyms/apply.py [--dry-run]

1. Reads audit/out_*.jsonl (AUDIT.md). Drops a phrase accepted for two classes, one already a label or
   synonym (class or label-only), one shorter than 4 characters, and the ones in REJECT: a second review
   of every accepted phrase that changes an existing node label, against the old and new labels.
2. Writes them to taxonomy/label_synonyms.yaml, read only by `node_labeler/curated`. Not to
   curated_classes.yaml: as class synonyms the linker also matched them on question sides, and node dev
   fell (README.md: node-specific wording linked to a whole class pulls in other studies' edges).
3. Node labels as a delta: the curated labeller runs with the old and the new label-only phrases (no LLM,
   so committed LLM labels of still-unmatched nodes are kept). Only nodes whose labels differ between
   those two runs change in node_labels.jsonl, and only if their committed labels equal the old run's.
   Nodes someone corrected by hand (committed != old run) keep their labels and are listed. A plain
   rebuild would also undo those hand fixes, which is why this does not call `taxonomy`.
Writes applied.json: the phrases added, the nodes relabelled, and the nodes skipped.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

import yaml

from camoreasoning.config import TAXONOMY_DIR, Settings
from camoreasoning.pipeline import make_context
from camoreasoning.strategies.node_labeler.curated import LABEL_SYNONYMS, CuratedLabeler, load_label_synonyms
from camoreasoning.taxonomy import Taxonomy, load_taxonomy

HERE = Path(__file__).resolve().parent
# Second review (applied.json "changes", grouped by the phrase that caused them). Each one is right for
# the audited term but wrong for other text it matches.
REJECT = {
    "deer herd reduction*": "labels a herd reduction +1 grazing: the name has no negative cue the labeller reads",
    "reclaimed mine land": "turns 'breeding on reclaimed mine land' from breeding into the generic restoration class",
    "catch per unit effort": "turns fish catch per unit effort from fish_abundance into the generic trend class",
    "species assemblage*": "turns bird and insect assemblages into plant community composition",
    "water flow": "too broad: relabels 'preventing water flow to reactive tailings' as water level",
    "hemicryptophyte*": "pushes out the non-native label of 'exotic hemicryptophytes' (D-Q0052 then had no vote)",
}
HEAD = (
    "# Label-only synonyms: graph wording that places a node in a class. Read by node_labeler/curated only,\n"
    "# never by the linker (too specific to link a question side to a whole class). Proposed by\n"
    "# bge-base-en-v1.5 and audited: experiments/embeddings/bge_synonyms/. Same phrase syntax as\n"
    "# curated_classes.yaml (lower case, word boundaries, trailing * = any word ending).\n"
)


def accepted(tax: Taxonomy, have: dict[str, list[str]]) -> tuple[dict[str, list[str]], list[dict]]:
    outs = sorted((HERE / "audit").glob("out_*.jsonl"))
    rows = [json.loads(x) for p in outs for x in p.read_text().splitlines() if x]
    existing = {p for c in tax.classes.values() for p in (c.label.lower(), *c.synonyms)}
    existing |= {p for ps in have.values() for p in ps}
    by_phrase: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        if r.get("class") and r.get("phrase"):
            by_phrase[" ".join(r["phrase"].lower().split())].add(r["class"])
    add: dict[str, list[str]] = defaultdict(list)
    dropped = []
    for phrase, cids in sorted(by_phrase.items()):
        why = ("two classes" if len(cids) > 1 else "unknown class" if not cids <= set(tax.classes)
               else "already a phrase" if phrase in existing else "too short" if len(phrase.rstrip("*")) < 4
               else f"review: {REJECT[phrase]}" if phrase in REJECT else "")  # fmt: skip
        if why:
            dropped.append({"phrase": phrase, "classes": sorted(cids), "why": why})
        else:
            add[next(iter(cids))].append(phrase)
    return dict(add), dropped


def dump(phrases: dict[str, list[str]]) -> str:
    body = {"classes": {c: sorted(set(ps)) for c, ps in sorted(phrases.items()) if ps}}
    return HEAD + yaml.safe_dump(body, sort_keys=False, allow_unicode=True, width=120)


def labels_by_node(labels) -> dict[str, tuple]:
    out = defaultdict(list)
    for lb in labels:
        out[lb.node_id].append(lb)
    return {n: tuple(sorted((lb.class_id, lb.polarity, lb.score, lb.source) for lb in v)) for n, v in out.items()}


def run_labeller(phrases: dict[str, list[str]], work: Path):
    """Curated labeller, no endpoint, on a copy of the committed taxonomy with these label-only phrases."""
    work.mkdir(parents=True, exist_ok=True)
    for f in ("classes.yaml", "node_labels.jsonl"):
        shutil.copy(TAXONOMY_DIR / f, work / f)
    (work / LABEL_SYNONYMS).write_text(dump(phrases), encoding="utf-8")
    ctx = make_context(Settings(taxonomy_dir=work))
    assert not ctx.llm.available  # keeps committed LLM labels of nodes still unmatched
    return ctx, CuratedLabeler().label(ctx.taxonomy, ctx)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    committed = load_taxonomy()
    have = load_label_synonyms()
    add, dropped = accepted(committed, have)
    merged = {c: [*have.get(c, ()), *add.get(c, ())] for c in set(have) | set(add)}
    with tempfile.TemporaryDirectory() as tmp:
        _, old_labels = run_labeller(have, Path(tmp) / "old")
        ctx, new_labels = run_labeller(merged, Path(tmp) / "new")
    old, new, cur = labels_by_node(old_labels), labels_by_node(new_labels), labels_by_node(committed.labels)
    changed = sorted(n for n in set(old) | set(new) if old.get(n) != new.get(n))
    apply = {n for n in changed if cur.get(n) == old.get(n)}
    skipped = [n for n in changed if cur.get(n) != old.get(n)]
    labels = [lb for lb in committed.labels if lb.node_id not in apply]
    labels += [lb for lb in new_labels if lb.node_id in apply]
    report = {
        "phrases_added": add,
        "n_phrases": sum(map(len, add.values())),
        "dropped": dropped,
        "nodes_relabelled": len(apply),
        "nodes_skipped_hand_fixed": skipped,
        "label_sources_before": dict(Counter(lb.source for lb in committed.labels)),
        "label_sources_after": dict(Counter(lb.source for lb in labels)),
        "changes": [
            {
                "node": n,
                "name": ctx.graph.nodes[n].get("name"),
                "before": [c for c, *_ in old.get(n, ())],
                "after": [c for c, *_ in new.get(n, ())],
            }
            for n in sorted(apply)
        ],  # fmt: skip
    }
    (HERE / "applied.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("phrases_added", "changes", "dropped")}
                     | {"dropped": len(dropped)}, indent=1))  # fmt: skip
    if args.dry_run:
        return
    (TAXONOMY_DIR / LABEL_SYNONYMS).write_text(dump(merged), encoding="utf-8")
    order = {n: i for i, n in enumerate(dict.fromkeys(lb.node_id for lb in committed.labels))}
    labels.sort(key=lambda lb: order.get(lb.node_id, len(order)))
    lines = (json.dumps(asdict(lb), ensure_ascii=False) for lb in labels)  # same format as save_taxonomy
    (TAXONOMY_DIR / "node_labels.jsonl").write_text("".join(f"{x}\n" for x in lines), encoding="utf-8")


if __name__ == "__main__":
    main()
