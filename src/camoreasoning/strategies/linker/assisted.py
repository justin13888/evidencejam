"""Phrase-first class linking (`lexical_v2`) with one batched LLM fallback for uncertain sides.

A side is uncertain when lexical linking found no class, several tied classes, or a margin below
MIN_MARGIN. Only those sides go to the model, all questions in one `batch_json` request (chunks of 25,
within the stage's ceil(n/25) call budget). The model may only pick from the candidate ids sent for
that side; anything else is ignored and the lexical result stands. Any LLMError keeps the lexical
frames, so this never does worse than `lexical_v2` on what lexical already resolved.

Prompt size drives cost (ROADMAP item 2), so candidates are capped and carry few synonyms.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from camoreasoning.components import Context
from camoreasoning.contracts import Frame, ParsedQuestion, Ref, Side
from camoreasoning.llm import LLMError
from camoreasoning.registry import register
from camoreasoning.strategies.linker.baseline import _index, _rank
from camoreasoning.strategies.linker.lexical_v2 import PhraseLinker
from camoreasoning.strategies.text import tokens

MIN_MARGIN = 0.12  # below this the lexical pick is treated as uncertain
MAX_CANDIDATES = 5  # ranked candidates sent per side
SYNONYMS_PER_CANDIDATE = 3
TOKENS_PER_ITEM = 40  # reply is {"cause": id, "outcome": id}; ~20-30 tokens used
LLM_SCORE = 0.5  # Ref.score for a class the model picked

SYSTEM = (
    "Link question phrases to taxonomy classes. Each input line is "
    '{"id", "cause"?: {"text", "options"}, "outcome"?: {"text", "options"}}. '
    "For each side present, pick the one option id that names the same concept as the text, "
    "or null if none does. Do not pick a merely related class. "
    'Reply only JSON: {"<id>": {"cause": id_or_null, "outcome": id_or_null}, ...}'
)


def _options(text: str, kind: str, ctx: Context, ix: dict) -> list[dict]:
    """Top ranked classes with a few synonyms; if nothing ranks, every class of the kind, ids and labels only."""
    classes = ctx.taxonomy.of_kind(kind)
    ranked = _rank(set(tokens(text)), {c.id: ix["class_toks"][c.id] for c in classes}, ix)
    if not ranked:
        return [{"id": c.id, "label": c.label} for c in classes]
    keep = [cid for _, cid in ranked[:MAX_CANDIDATES]]
    by_id = {c.id: c for c in classes}
    return [
        {
            "id": cid,
            "label": by_id[cid].label,
            "aka": [s.replace("*", "") for s in by_id[cid].synonyms[:SYNONYMS_PER_CANDIDATE]],
        }
        for cid in keep
    ]


@register("linker", "assisted")
class AssistedLinker(PhraseLinker):
    def link(self, batch: Sequence[ParsedQuestion], ctx: Context) -> list[Frame]:
        ix = _index(ctx)
        frames: list[Frame] = []
        pending: dict[str, dict] = {}
        for i, p in enumerate(batch):
            cause, m1 = self._side(p.cause_text, "cause", ctx, ix)
            outcome, m2 = self._side(p.outcome_text, "outcome", ctx, ix)
            via = "lexical" if not (cause.empty or outcome.empty) else "none"
            frames.append(Frame(p, cause, outcome, via, round(min(m1, m2), 4)))
            if ctx.taxonomy.empty:
                continue
            row: dict = {}
            for name, text, side, margin in (
                ("cause", p.cause_text, cause, m1),
                ("outcome", p.outcome_text, outcome, m2),
            ):
                if text and tokens(text) and (len(side.classes) != 1 or margin < MIN_MARGIN):
                    row[name] = {"text": text, "options": _options(text, name, ctx, ix)}
            if row:
                pending[str(i)] = {"id": str(i), **row}

        if not pending or not ctx.llm.available:
            return frames
        try:
            replies = ctx.llm.batch_json(
                SYSTEM, list(pending.values()), tokens_per_item=TOKENS_PER_ITEM, purpose="linker"
            )
        except LLMError:
            return frames

        for key, reply in replies.items():
            if not isinstance(reply, dict):
                continue
            pos = int(key)
            frame = frames[pos]
            sides = {"cause": frame.cause, "outcome": frame.outcome}
            changed = False
            for name in ("cause", "outcome"):
                sent = pending[key].get(name)
                pick = reply.get(name)
                if sent and isinstance(pick, str) and pick in {o["id"] for o in sent["options"]}:
                    sides[name] = Side(sides[name].text, classes=(Ref(pick, 1, LLM_SCORE),), nodes=sides[name].nodes)
                    changed = True
            if changed:
                via = "llm" if not (sides["cause"].empty or sides["outcome"].empty) else frame.via
                frames[pos] = replace(frame, cause=sides["cause"], outcome=sides["outcome"], via=via)
        return frames
