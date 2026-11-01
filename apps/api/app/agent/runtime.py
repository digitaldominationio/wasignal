"""The orchestrator.

One turn = assemble -> LLM loop with tools -> admit a reply (or explain why
not). Everything here is deterministic given the LLM and the repository, which
is what makes `trigger: test` runs reproducible.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Optional

from .. import repo
from ..config import settings
from ..llm import LLMError, get_llm
from ..llm.base import LLMResponse, ToolCall
from . import capabilities as caps
from .prompts import build_messages
from .tools import ToolContext, execute, tool_result_content, tool_specs


@dataclass
class RunOutcome:
    run_id: Optional[int]
    status: str
    reply: str
    iterations: int
    tokens: int
    stage: str = "done"
    reason: Optional[str] = None
    handed_over: bool = False


class AgentRuntime:
    def __init__(self, agent: dict[str, Any], account: dict[str, Any], room: dict[str, Any], lane_key: str = "main") -> None:
        self.agent = agent
        self.account = account
        self.room = room
        self.lane_key = lane_key
        self.llm = get_llm(agent)
        self.tool_log: list[dict[str, Any]] = []

    async def run(self, *, text: str, history: list[dict[str, Any]], sender_name: str = "",
                  trigger: str = "event") -> RunOutcome:
        run_id = repo.create_run(self.agent["id"], self.account["id"], self.room["id"], trigger, self.lane_key)
        started = time.monotonic()
        self.tool_log = []
        try:
            outcome = await asyncio.wait_for(
                self._loop(run_id, text=text, history=history, sender_name=sender_name),
                timeout=max(5, int(self.agent.get("timeout_seconds") or 60)),
            )
        except asyncio.TimeoutError:
            outcome = RunOutcome(run_id, "error", "", 0, 0, stage="llm_loop", reason="timeout")
        except LLMError as exc:
            outcome = RunOutcome(run_id, "error", "", 0, 0, stage="llm_call", reason=str(exc)[:300])
        except Exception as exc:  # never lose the run row
            outcome = RunOutcome(run_id, "error", "", 0, 0, stage="runtime", reason=f"{type(exc).__name__}: {exc}"[:300])

        repo.finish_run(
            run_id,
            status=outcome.status,
            stage=outcome.stage,
            iterations=outcome.iterations,
            tokens=outcome.tokens,
            reply=outcome.reply,
            reason=outcome.reason,
            provider=getattr(self.llm, "provider", None),
            model=getattr(self.llm, "model", None),
            tool_calls=self.tool_log,
        )
        repo.touch_lane(self.agent["id"], self.room["id"], self.lane_key)
        _ = started
        return outcome

    async def _loop(self, run_id: int, *, text: str, history: list[dict[str, Any]], sender_name: str) -> RunOutcome:
        lane = repo.get_lane(self.agent["id"], self.room["id"], self.lane_key)
        if lane["handed_over"]:
            return RunOutcome(run_id, "handover", "", 0, 0, stage="gate", reason="lane is handed over")

        knowledge_sources = repo.agent_knowledge_sources(self.agent["id"])
        memory_block = repo.memory_block(self.agent["id"], int(self.agent.get("max_memory_chars") or 4000))
        messages = build_messages(
            self.agent,
            history=history,
            text=text,
            sender_name=sender_name,
            memory_block=memory_block,
            knowledge_titles=[source["name"] for source in knowledge_sources],
        )

        specs = tool_specs(self.agent)
        allowed = caps.can(self.agent, "send")
        ctx = ToolContext(account=self.account, room=self.room, agent=self.agent, lane_key=self.lane_key)

        iterations = 0
        tokens = 0
        handover = False
        max_iterations = int(self.agent.get("max_iterations") or 6)

        while iterations < max_iterations:
            iterations += 1
            response: LLMResponse = await self.llm.complete(messages, specs)
            tokens += response.tokens

            if not response.tool_calls:
                reply = (response.text or "").strip()
                if not allowed:
                    return RunOutcome(run_id, "read_only", "", iterations, tokens, stage="admitted", reason="no send capability")
                return RunOutcome(run_id, "ok", reply, iterations, tokens, stage="admitted")

            messages.append({
                "role": "assistant",
                "content": response.text or "",
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                    }
                    for call in response.tool_calls
                ],
            })

            for call in response.tool_calls:
                result = await execute(call.name, call.arguments, ctx)
                self.tool_log.append({
                    "name": call.name,
                    "ok": bool(result.get("ok")),
                    "arguments": _short_args(call.arguments),
                })
                if call.name == "request_handover" and result.get("ok"):
                    handover = True
                    ctx.agent = {**self.agent, "_handed_over": True}
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": call.name,
                    "content": tool_result_content(result),
                })

        # iteration budget exhausted: say something rather than vanish
        reply = "Let me get a colleague to pick this up."
        if not allowed:
            return RunOutcome(run_id, "limit", "", iterations, tokens, stage="iteration_limit", reason="max_iterations reached")
        return RunOutcome(run_id, "limit", reply, iterations, tokens, stage="iteration_limit",
                          reason="max_iterations reached", handed_over=handover)


async def run_agent(agent: dict[str, Any], account: dict[str, Any], room: dict[str, Any],
                    *, text: str, history: list[dict[str, Any]], sender_name: str = "",
                    trigger: str = "event", lane_key: str = "main") -> RunOutcome:
    runtime = AgentRuntime(agent, account, room, lane_key)
    return await runtime.run(text=text, history=history, sender_name=sender_name, trigger=trigger)


def _short_args(arguments: dict[str, Any], limit: int = 240) -> str:
    try:
        text = json.dumps(arguments, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(arguments)
    return text[:limit]


def default_history_limit() -> int:
    return settings.history_limit


__all__ = ["AgentRuntime", "RunOutcome", "run_agent", "ToolCall"]
