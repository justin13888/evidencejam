"""Per-run footprint ledger. The scored energy is estimated from LLM endpoint tokens plus local
compute, so every call is counted here and `eval` reports calls and tokens per question."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field, fields
from pathlib import Path

# Rough guesses, for relative comparison only (the organizers' formula is unpublished).
WH_PER_PROMPT_TOKEN = 0.00005
WH_PER_COMPLETION_TOKEN = 0.0005
CPU_WATTS = 30.0


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Meter:
    max_calls: int = 8
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_hits: int = 0
    failures: int = 0
    questions: int = 0
    log: list[dict] = field(default_factory=list)
    _wall0: float = field(default_factory=time.perf_counter, repr=False)
    _cpu0: float = field(default_factory=time.process_time, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)  # annotate runs threads

    def reserve(self) -> None:
        """Call before every network request; raises once the per-run budget is spent."""
        with self._lock:
            if self.calls >= self.max_calls:
                raise BudgetExceeded(f"LLM call budget {self.max_calls} exhausted")
            self.calls += 1

    def record(self, purpose: str, prompt_tokens: int, completion_tokens: int, seconds: float, **info) -> None:
        with self._lock:
            self.prompt_tokens += prompt_tokens
            self.completion_tokens += completion_tokens
            self.log.append({"purpose": purpose, "prompt": prompt_tokens, "completion": completion_tokens,
                             "s": round(seconds, 3), **info})  # fmt: skip

    def summary(self) -> dict:
        cpu = time.process_time() - self._cpu0
        wh_llm = self.prompt_tokens * WH_PER_PROMPT_TOKEN + self.completion_tokens * WH_PER_COMPLETION_TOKEN
        wh_cpu = cpu * CPU_WATTS / 3600
        q = max(self.questions, 1)
        d = {f.name: getattr(self, f.name) for f in fields(self) if not f.name.startswith("_") and f.name != "log"}
        d.update(
            wall_s=round(time.perf_counter() - self._wall0, 3),
            cpu_s=round(cpu, 3),
            est_wh=round(wh_llm + wh_cpu, 5),
            est_wh_per_question=round((wh_llm + wh_cpu) / q, 6),
            calls_per_question=round(self.calls / q, 4),
            tokens_per_question=round((self.prompt_tokens + self.completion_tokens) / q, 2),
            log=list(self.log),
        )
        return d

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.summary(), indent=2))
