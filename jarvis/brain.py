"""Jarvis's brain: one shared conversation with Claude across every channel
(HUD, Telegram, phone), so what you say on the phone is remembered at the desk.

The conversation is kept append-only and the system prompt never changes,
which keeps prompt caching effective and replayed thinking blocks valid.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

import anthropic

from . import events
from .config import settings
from .tools import TOOLS, load_memory, run_tool

log = logging.getLogger("jarvis.brain")

SYSTEM_PROMPT = f"""You are J.A.R.V.I.S., a personal AI assistant running on your owner's home PC.
Address the owner as "{settings.owner_name}". Your manner is calm, dry-witted, loyal and
efficient, like a seasoned British butler who happens to run the house's computers.

Each user message starts with a tag like [via hud | Mon 09 Nov 2026 14:02]. The channel tells
you how your reply will be delivered:
- "hud" or "call": your reply is SPOKEN aloud. Keep it to one to three short sentences,
  conversational, no markdown, no lists, no URLs read out character by character.
- "telegram": your reply is a text message. Brief, plain text, light formatting at most.

You can act on the PC and reach the owner by phone through your tools. Confirm before anything
irreversible. You cannot place calls to anyone except the owner. If a tool fails, say so plainly.
"""

# Rough size guard (characters of history) before we fold old turns into a summary.
MAX_HISTORY_CHARS = 300_000

REFUSAL_REPLY = "I'm afraid I can't help with that one."


class Brain:
    def __init__(self) -> None:
        self.client = anthropic.AsyncAnthropic()
        self.messages: list[dict[str, Any]] = []
        self.lock = asyncio.Lock()
        self._carryover = ""  # summary of a previous, folded conversation

    # ----------------------------------------------------------------- api --
    async def ask(self, text: str, channel: str) -> str:
        """Send one user utterance through Claude (running tools as needed)
        and return the final reply text."""
        async with self.lock:
            if self._history_chars() > MAX_HISTORY_CHARS:
                await self._fold_history()

            stamp = datetime.now().strftime("%a %d %b %Y %H:%M")
            content = f"[via {channel} | {stamp}] {text}"
            if not self.messages:
                content = self._preamble() + content
            self.messages.append({"role": "user", "content": content})

            events.publish({"type": "user", "channel": channel, "text": text})
            events.publish({"type": "state", "state": "thinking"})
            try:
                reply = await self._run_loop()
            except anthropic.APIConnectionError:
                reply = "I can't reach my servers at the moment. Check the internet connection."
                self._rollback_turn()
            except anthropic.RateLimitError:
                reply = "I'm being rate limited. Give me a moment and try again."
                self._rollback_turn()
            except anthropic.AuthenticationError:
                reply = "My API key was rejected. Check ANTHROPIC_API_KEY in the .env file."
                self._rollback_turn()
            except anthropic.APIStatusError as exc:
                log.exception("Claude API error")
                reply = f"Something went wrong on my end (error {exc.status_code})."
                self._rollback_turn()
            events.publish({"type": "reply", "channel": channel, "text": reply})
            events.publish({"type": "state", "state": "idle"})
            return reply

    def reset(self) -> None:
        self.messages = []
        self._carryover = ""

    # ------------------------------------------------------------ internals --
    async def _create(self, messages: list[dict[str, Any]], **extra: Any):
        return await self.client.beta.messages.create(
            model=settings.model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
            output_config={"effort": settings.effort},
            cache_control={"type": "ephemeral"},
            # If a safety classifier declines, retry server-side on Anthropic's
            # recommended fallback model instead of failing outright.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            **extra,
        )

    async def _run_loop(self) -> str:
        for _ in range(12):  # hard cap on tool round-trips per utterance
            response = await self._create(self.messages)
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "refusal":
                return REFUSAL_REPLY
            if response.stop_reason == "pause_turn":  # server tool (web search) mid-flight
                continue
            if response.stop_reason != "tool_use":
                return _text_of(response.content) or "Done."

            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                events.publish({"type": "tool", "name": block.name, "input": block.input})
                output, is_error = await run_tool(block.name, block.input)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output,
                        "is_error": is_error,
                    }
                )
            # All results go back together in a single user message.
            self.messages.append({"role": "user", "content": results})
        return "I've run out of steps on that one. Shall I try a different approach?"

    def _rollback_turn(self) -> None:
        """After a failed request, drop the dangling turn so history stays valid
        (it must end with an assistant message, and tool_use needs its result)."""
        while self.messages and self.messages[-1]["role"] == "user":
            self.messages.pop()
            if self.messages and self.messages[-1]["role"] == "assistant":
                last = self.messages[-1]["content"]
                if any(getattr(b, "type", None) == "tool_use" for b in last):
                    self.messages.pop()
                    continue
            break

    def _preamble(self) -> str:
        parts = []
        facts = load_memory()
        if facts:
            parts.append("Things you know about the owner:\n- " + "\n- ".join(facts))
        if self._carryover:
            parts.append("Summary of your earlier conversation:\n" + self._carryover)
        return ("\n\n".join(parts) + "\n\n") if parts else ""

    def _history_chars(self) -> int:
        return sum(len(str(m["content"])) for m in self.messages)

    async def _fold_history(self) -> None:
        """Replace the whole history with a summary (no earlier thinking blocks
        are replayed, so nothing is invalidated)."""
        ask = {"role": "user", "content": "Summarise our conversation so far in under 300 words, "
               "keeping any open tasks, decisions and facts about the owner."}
        try:
            response = await self._create(self.messages + [ask])
            self._carryover = _text_of(response.content)
        except anthropic.APIError:
            log.exception("Could not summarise history; starting fresh")
            self._carryover = ""
        self.messages = []


def _text_of(content: list[Any]) -> str:
    return " ".join(b.text for b in content if getattr(b, "type", None) == "text").strip()


brain = Brain()
