"""Run traces and token accounting.

Every agent step, tool call and model usage figure for a planning run lands
here. Two consumers: the live UI (so a human can watch what the agents did
and why) and the report's tokenomics section (which needs measured input,
cached-input and output counts, not estimates).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

PROJECT = Path(__file__).resolve().parent.parent
TRACE_DIR = PROJECT / "output" / "traces"

# Price per million tokens, used for every dollar figure the app and the
# report quote. These are PLACEHOLDERS standing in for gpt-6-luna's published
# rates — confirm them against the gateway's own pricing page before the
# tokenomics section is final, and change them here only: nothing else in the
# codebase hard-codes a price.
PRICE_PER_MTOK = {"input": 1.25, "cached_input": 0.125, "output": 10.00}
PRICE_SOURCE = "placeholder - confirm against gateway pricing"


@dataclass
class Usage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    requests: int = 0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.cached_input_tokens += other.cached_input_tokens
        self.output_tokens += other.output_tokens
        self.requests += other.requests

    @property
    def fresh_input_tokens(self) -> int:
        """Input tokens that were not served from the prompt cache."""
        return max(0, self.input_tokens - self.cached_input_tokens)

    @property
    def cost_usd(self) -> float:
        return round(
            self.fresh_input_tokens / 1e6 * PRICE_PER_MTOK["input"]
            + self.cached_input_tokens / 1e6 * PRICE_PER_MTOK["cached_input"]
            + self.output_tokens / 1e6 * PRICE_PER_MTOK["output"],
            6,
        )

    def as_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "fresh_input_tokens": self.fresh_input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
            "requests": self.requests,
            "cost_usd": self.cost_usd,
        }


@dataclass
class Trace:
    run_id: str
    started: float = field(default_factory=time.time)
    events: list[dict] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    by_agent: dict[str, Usage] = field(default_factory=dict)
    tool_calls: int = 0
    cache_hits: int = 0

    def as_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "started": self.started,
            "elapsed_s": round(time.time() - self.started, 2),
            "events": self.events,
            "usage": self.usage.as_dict(),
            "by_agent": {k: v.as_dict() for k, v in self.by_agent.items()},
            "tool_calls": self.tool_calls,
            "cache_hits": self.cache_hits,
        }


_lock = Lock()
_traces: dict[str, Trace] = {}


def start(run_id: str) -> Trace:
    with _lock:
        _traces[run_id] = Trace(run_id=run_id)
        return _traces[run_id]


def get(run_id: str) -> Trace | None:
    return _traces.get(run_id)


def record(run_id: str, kind: str, actor: str, target: str = "",
           detail: Any = None, result: Any = None, cached: bool = False) -> None:
    """Append one step to a run's trace."""
    trace = _traces.get(run_id)
    if trace is None:
        return
    with _lock:
        if kind == "tool_call":
            trace.tool_calls += 1
            if cached:
                trace.cache_hits += 1
        trace.events.append({
            "at": round(time.time() - trace.started, 2),
            "kind": kind,
            "actor": actor,
            "target": target,
            "detail": _safe(detail),
            "result": _safe(result),
            "cached": cached,
        })


def record_usage(run_id: str, actor: str, result_usage) -> None:
    """Fold one agent run's measured token usage into the trace.

    PydanticAI reports cached input under `details`, with the key varying by
    provider, so several spellings are checked rather than one.
    """
    trace = _traces.get(run_id)
    if trace is None or result_usage is None:
        return

    # PydanticAI exposes cached input as `cache_read_tokens`; older releases and
    # some providers only report it inside `details` under a provider-specific
    # key, so both are checked.
    cached = int(getattr(result_usage, "cache_read_tokens", 0) or 0)
    if not cached:
        details = getattr(result_usage, "details", None) or {}
        for key in ("cached_tokens", "cache_read_input_tokens",
                    "cache_read_tokens", "prompt_cached_tokens"):
            if details.get(key):
                cached = int(details[key])
                break

    usage = Usage(
        input_tokens=int(getattr(result_usage, "input_tokens", 0) or 0),
        cached_input_tokens=cached,
        output_tokens=int(getattr(result_usage, "output_tokens", 0) or 0),
        requests=int(getattr(result_usage, "requests", 0) or 1),
    )
    with _lock:
        trace.usage.add(usage)
        trace.by_agent.setdefault(actor, Usage()).add(usage)
        trace.events.append({
            "at": round(time.time() - trace.started, 2),
            "kind": "usage",
            "actor": actor,
            "target": "",
            "detail": usage.as_dict(),
            "result": None,
            "cached": False,
        })


def save(run_id: str) -> Path | None:
    """Write a finished trace to output/traces/ for the report."""
    trace = _traces.get(run_id)
    if trace is None:
        return None
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    path = TRACE_DIR / f"{run_id}.json"
    path.write_text(json.dumps(trace.as_dict(), indent=2, default=str), encoding="utf-8")
    return path


# A trace is evidence: the injection harness searches it to decide whether a
# payload reached a model, so anything cut here is invisible to that check.
# These caps exist only to stop one pathological value bloating a file, and
# are set well above the size of a real prompt or tool result.
MAX_TRACE_STRING = 40_000
MAX_TRACE_JSON = 40_000


def _safe(value: Any) -> Any:
    """Make a value JSON-friendly without letting one huge payload bloat a trace."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return (value if len(value) <= MAX_TRACE_STRING
                else value[:MAX_TRACE_STRING] + f"... [{len(value)} chars]")
    try:
        text = json.dumps(value, default=str)
    except Exception:
        text = str(value)
    if len(text) > MAX_TRACE_JSON:
        return text[:MAX_TRACE_JSON] + f"... [{len(text)} chars]"
    return json.loads(text)
