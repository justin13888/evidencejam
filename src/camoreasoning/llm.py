"""The only network path: an OpenAI-compatible chat client for the LiteLLM endpoint (BRINE_*).

Energy rules baked in: temperature 0, thinking disabled, capped max_tokens, batched prompts, every
request metered and budgeted. Any failure surfaces as LLMError so callers can fall back to 0-call paths.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from typing import Any

from camoreasoning.config import CACHE_DIR, Settings
from camoreasoning.meter import BudgetExceeded, Meter

# Qwen3-family switch; sent as chat_template_kwargs and dropped automatically if the proxy rejects it.
EXTRA_BODY = {"chat_template_kwargs": {"enable_thinking": False}}
NO_THINK = " /no_think"
RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    pass


def extract_json(text: str) -> Any:
    """Parse the first JSON object/array in a reply; tolerates <think> blocks and ``` fences."""
    text = re.sub(r"<think>.*?(</think>|$)", "", text or "", flags=re.S)
    text = re.sub(r"```(?:json)?", "", text)
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError(f"no JSON in reply: {text[:120]!r}")


class LLM:
    def __init__(self, settings: Settings, meter: Meter | None = None):
        self.settings = settings
        self.meter = meter or Meter(max_calls=settings.max_calls)
        self._extras = dict(EXTRA_BODY)

    @property
    def available(self) -> bool:
        return self.settings.llm_configured

    def _url(self) -> str:
        url = (self.settings.llm_url or "").rstrip("/")
        return url if url.endswith("/chat/completions") else url + "/chat/completions"

    def chat(
        self, system: str, user: str, *, max_tokens: int = 256, purpose: str = "", extra: dict | None = None
    ) -> str:
        """One metered completion. Raises LLMError on any failure (never other exceptions).
        `extra` adds request fields (e.g. response_format) and is part of the cache key."""
        if not self.available:
            raise LLMError("LLM not configured (BRINE_URL/BRINE_MODEL)")
        body = {
            "model": self.settings.llm_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user + NO_THINK}],
            "temperature": 0,
            "max_tokens": max_tokens,
            **(extra or {}),
        }
        key = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        cache = CACHE_DIR / "llm" / f"{key}.json"
        if self.settings.llm_cache and cache.exists():
            self.meter.cache_hits += 1
            return json.loads(cache.read_text())["content"]
        for attempt in range(2):
            try:
                content = self._post({**body, **self._extras}, purpose)
                break
            except _Retry as e:
                if attempt or not e.retry:
                    self.meter.failures += 1
                    raise LLMError(str(e)) from None
                if e.drop_extras:
                    self._extras = {}
                else:
                    time.sleep(2)
        if self.settings.llm_cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"content": content}))
        return content

    def _post(self, body: dict, purpose: str) -> str:
        headers = {"Content-Type": "application/json"}
        if self.settings.llm_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_key}"
        try:  # a scheme-less BRINE_URL makes urllib raise ValueError; surface it as LLMError, before any call is spent
            req = urllib.request.Request(self._url(), json.dumps(body).encode(), headers, method="POST")
        except ValueError as e:
            raise _Retry(f"bad BRINE_URL: {e}", retry=False) from None
        try:
            self.meter.reserve()
        except BudgetExceeded as e:
            raise _Retry(str(e), retry=False) from None
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.settings.llm_timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            bad_extras = e.code == 400 and bool(self._extras)
            raise _Retry(f"HTTP {e.code}", retry=e.code in RETRY_STATUS or bad_extras,
                         drop_extras=bad_extras) from None  # fmt: skip
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            # A timeout already spent the whole budget; retrying would double the wait (ask.sh must answer < 10 s).
            timed_out = isinstance(e, TimeoutError) or isinstance(getattr(e, "reason", None), TimeoutError)
            raise _Retry(f"network: {e}", retry=not timed_out) from None
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise _Retry(f"bad response body: {e}", retry=False) from None
        try:
            content = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise _Retry(f"unexpected response shape: {str(data)[:120]}", retry=False) from None
        usage = data.get("usage") or {}
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
        self.meter.record(
            purpose,
            int(usage.get("prompt_tokens") or len(json.dumps(body)) // 4),
            int(usage.get("completion_tokens") or len(content) // 4),
            time.perf_counter() - t0,
            usage_reported=bool(usage.get("prompt_tokens")),
            **({"cached_tokens": cached} if cached is not None else {}),
        )
        return content

    def chat_json(self, system: str, user: str, *, max_tokens: int = 256, purpose: str = "") -> Any:
        return extract_json(self.chat(system, user, max_tokens=max_tokens, purpose=purpose))

    def batch_json(
        self,
        system: str,
        items: Sequence[dict],
        *,
        chunk: int = 25,
        tokens_per_item: int = 48,
        purpose: str = "batch",
    ) -> dict[str, Any]:
        """Send items (each with an "id") in chunks; the model must reply {"<id>": <value>, ...}.
        Returns merged results; ids the model omitted are simply absent (caller falls back)."""
        out: dict[str, Any] = {}
        error: LLMError | None = None
        for i in range(0, len(items), chunk):
            part = items[i : i + chunk]
            user = "\n".join(json.dumps(it, ensure_ascii=False) for it in part)
            try:
                reply = self.chat_json(system, user, max_tokens=32 + tokens_per_item * len(part), purpose=purpose)
            except LLMError as e:  # keep other chunks; caller falls back for missing ids
                error = e
                continue
            if isinstance(reply, dict):
                ids = {str(it["id"]) for it in part}
                out.update({str(k): v for k, v in reply.items() if str(k) in ids})
        if error and not out:
            raise error
        return out


class _Retry(Exception):
    def __init__(self, msg: str, retry: bool, drop_extras: bool = False):
        super().__init__(msg)
        self.retry = retry
        self.drop_extras = drop_extras


def probe(settings: Settings) -> dict:
    """Endpoint facts the energy plan depends on (ROADMAP #2). Never raises; writes nothing itself."""
    import dataclasses

    if not settings.llm_configured:
        return {"ok": False, "note": "BRINE_URL/BRINE_MODEL not set; nothing probed"}
    s = dataclasses.replace(settings, llm_cache=False, max_calls=10)
    out: dict[str, Any] = {"model": s.llm_model}
    llm = LLM(s)
    try:
        reply = llm.chat("Reply with exactly: OK", "ping", max_tokens=16, purpose="probe")
        last = llm.meter.log[-1]
        out.update(ok=True, reply=reply[:60], thinking_leaked="<think" in reply, latency_s=last["s"],
                   usage_reported=last.get("usage_reported"), completion_tokens=last["completion"],
                   thinking_switch_accepted=bool(llm._extras))  # fmt: skip
    except LLMError as e:
        return {**out, "ok": False, "error": str(e)}
    schema = {"type": "json_schema", "json_schema": {"name": "probe", "schema": {
        "type": "object", "properties": {"label": {"type": "string", "enum": ["alpha", "beta"]}},
        "required": ["label"], "additionalProperties": False}}}  # fmt: skip
    try:
        r = LLM(s).chat("Pick a label.", "Choose beta.", max_tokens=32, purpose="probe",
                        extra={"response_format": schema})  # fmt: skip
        out["json_schema"] = extract_json(r).get("label") in ("alpha", "beta")
    except (LLMError, AttributeError) as e:
        out["json_schema"] = f"unsupported ({e})"
    prefix = "You label items. " + " ".join(f"Rule {i}: be exact." for i in range(300))
    timings = []
    for i in range(2):
        try:
            llm.chat(prefix, f"item {i}", max_tokens=8, purpose="probe")
            timings.append(llm.meter.log[-1])
        except LLMError as e:
            timings.append({"error": str(e)})
    out["prefix_cache"] = {"first": timings[0], "second": timings[1]}
    out["meter"] = {k: v for k, v in llm.meter.summary().items() if k != "log"}
    return out
