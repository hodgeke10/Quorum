"""Model wiring and tool attachment for Quorum.

Project code reaches OpenAI through Portkey. The model id is defined once here
and shared by every agent.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.openai import OpenAIProvider

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent

# Key lookup order required by the assignment: this repo's own folder first,
# then the folder one level above it. load_dotenv does not overwrite a value
# that is already set, so the repo's own .env wins when both exist.
load_dotenv(PROJECT / ".env")
load_dotenv(PROJECT.parent / ".env")

# The only model the course key is permitted to reach.
MODEL_NAME = "gpt-6-luna"

PROMPTS_DIR = HERE / "prompts"

MCP_DIR = PROJECT / "mcp_server"
if str(MCP_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_DIR))

# gpt-6-luna rejects function tools on /chat/completions unless reasoning
# effort is 'none'. Every agent here calls tools, so this is required.
MODEL_SETTINGS = OpenAIChatModelSettings(openai_reasoning_effort="none")


def credential() -> tuple[str, str]:
    """Return (provider, key). Portkey is preferred; a personal OpenAI key works."""
    portkey = os.getenv("PORTKEY_API_KEY")
    if portkey:
        return "portkey", portkey
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        return "openai", openai_key
    raise RuntimeError(
        "No API key found. Put PORTKEY_API_KEY in a .env file either in this "
        f"repo ({PROJECT / '.env'}) or one level above it "
        f"({PROJECT.parent / '.env'}). See .env.example."
    )


def build_model() -> OpenAIChatModel:
    """Create the shared gpt-6-luna model."""
    provider, key = credential()
    if provider == "portkey":
        client = AsyncOpenAI(
            api_key=key,
            base_url=os.getenv("PORTKEY_BASE_URL", "https://api.portkey.ai/v1"),
            default_headers={"x-portkey-api-key": key},
        )
    else:
        client = AsyncOpenAI(api_key=key)
    return OpenAIChatModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))


# Read-only facts that cannot change inside one planning run. Five advocates
# asking the same price question is five identical answers at five times the
# cost, so the first one is reused. See the tokenomics section of the report.
_CACHEABLE = {
    "list_travelers", "find_windows", "list_destinations", "get_seasonality",
    "price_flight", "price_lodging", "price_trip", "cheapest_months", "survey",
}

# Tools a human reads, never an agent. `security_report` returns the text the
# calendar screen quarantined — showing it to an agent would walk the payload
# into a model's context by the front door, which is precisely what the screen
# exists to prevent. The interface calls it directly in Python instead.
HUMAN_ONLY_TOOLS = {"security_report"}

_toolset: MCPToolset | None = None


async def _traced_call(ctx, call_tool, name: str, tool_args: dict):
    """Record every tool call on the run trace, serving from cache when possible."""
    from trace_log import record  # local import keeps config standalone

    deps = getattr(ctx, "deps", None)
    run_id = getattr(deps, "run_id", "unattributed")
    actor = getattr(deps, "actor", "unknown")
    cache = getattr(deps, "tool_cache", None)

    key = (name, repr(sorted(tool_args.items())))
    if cache is not None and name in _CACHEABLE and key in cache:
        record(run_id, "tool_call", actor, name, tool_args, "(reused earlier answer)",
               cached=True)
        return cache[key]

    try:
        result = await call_tool(name, tool_args)
    except Exception as exc:
        record(run_id, "tool_call", actor, name, tool_args, {"error": str(exc)})
        raise

    record(run_id, "tool_call", actor, name, tool_args, getattr(result, "data", result))
    if cache is not None and name in _CACHEABLE:
        cache[key] = result
    return result


def toolset() -> MCPToolset:
    """Attach the trip-ops MCP server in-process, shared by every agent."""
    global _toolset
    if _toolset is None:
        from server import mcp as trip_mcp  # noqa: PLC0415  (path set above)

        _toolset = MCPToolset(
            trip_mcp, process_tool_call=_traced_call
        ).filtered(
            lambda ctx, tool: tool.name not in HUMAN_ONLY_TOOLS
        )
    return _toolset


# The injection warning in _shared.md is itself a defense. The report's
# undefended baseline has to run without it, or the comparison is measuring two
# things at once, so it is fenced in the file and stripped when screening is off.
GUARD_OPEN = "<!-- injection-guard -->"
GUARD_CLOSE = "<!-- /injection-guard -->"


def load_prompt(name: str, *, guarded: bool = True) -> str:
    """Read an agent's system prompt from backend/prompts/."""
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Missing system prompt: {path}")
    text = path.read_text(encoding="utf-8")
    if not guarded and GUARD_OPEN in text and GUARD_CLOSE in text:
        head, rest = text.split(GUARD_OPEN, 1)
        text = head + rest.split(GUARD_CLOSE, 1)[1]
    return text
