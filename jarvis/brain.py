"""Jarvis's brain: one shared conversation with Claude across every channel
(HUD, Telegram, phone), so what you say on the phone is remembered at the desk.

The conversation is kept append-only and the system prompt never changes,
which keeps prompt caching effective and replayed thinking blocks valid.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

import anthropic

from . import events
from .config import DATA_DIR, claude_headers, local_now, settings
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
- "briefing": the owner asked for their daily briefing; it is SPOKEN aloud. Greet them by
  time of day, then cover weather (and what to wear or bring), today's reminders and to-dos
  in four to six natural sentences. No lists, no markdown. Skip anything empty.

When a protocol runs, speak any "say:" lines from its result as part of your reply.

You can act on the PC and reach the owner by phone through your tools. Use get_weather for
weather rather than web search. To read a web page yourself, use web_fetch on its URL; to SHOW one to the owner, use
show_on_screen (it appears inside the Jarvis screen). If a web tool
returns an error, tell the owner which error it was. Confirm before anything
irreversible. You cannot place calls to anyone except the owner. If a tool fails, say so plainly.
"""

# Rough size guard (characters of history) before we fold old turns into a summary.
MAX_HISTORY_CHARS = 300_000

REFUSAL_REPLY = "I'm afraid I can't help with that one."

# A plain-text log of exchanges, so Jarvis remembers recent conversations after a
# restart (only the words, never tool data or keys).
TRANSCRIPT_FILE = DATA_DIR / "transcript.jsonl"
SESSION_START = datetime.now().isoformat(timespec="seconds")
RECALL_EXCHANGES = 12


class Brain:
    def __init__(self) -> None:
        self.client = anthropic.AsyncAnthropic(default_headers=claude_headers())
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

            stamp = local_now().strftime("%a %d %b %Y %H:%M")
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
                detail = _api_error_detail(exc)
                log.error("Claude API error %s: %s", exc.status_code, detail)
                if "credit balance" in detail.lower():
                    reply = ("My API account is out of credit. Add credit at platform.claude.com, "
                             "under Billing, for the organization this key belongs to.")
                elif "anthropic-workspace-id" in detail:
                    reply = ("Your API key isn't tied to one workspace, so I need a workspace ID. "
                             "Run checkup.bat or the settings tool for the fix.")
                elif "usage limit" in detail.lower():
                    reply = "I've hit the monthly spend limit you set. Raise it at platform.claude.com."
                else:
                    reply = f"Something went wrong on my end (error {exc.status_code}): {detail}"
                self._rollback_turn()
            self._log_exchange(channel, text, reply)
            events.publish({"type": "reply", "channel": channel, "text": reply})
            events.publish({"type": "state", "state": "idle"})
            return reply

    def reset(self) -> None:
        self.messages = []
        self._carryover = ""
        self._append_transcript({"reset": True, "t": datetime.now().isoformat(timespec="seconds")})

    # ------------------------------------------------------ memory on disk --
    def _append_transcript(self, entry: dict) -> None:
        try:
            DATA_DIR.mkdir(exist_ok=True)
            with TRANSCRIPT_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
            if TRANSCRIPT_FILE.stat().st_size > 2_000_000:  # keep the file small
                lines = TRANSCRIPT_FILE.read_text(encoding="utf-8").splitlines()[-500:]
                TRANSCRIPT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            log.warning("Couldn't write the transcript")

    def _log_exchange(self, channel: str, text: str, reply: str) -> None:
        user = "(asked for the daily briefing)" if channel == "briefing" else text
        self._append_transcript({"t": datetime.now().isoformat(timespec="seconds"),
                                 "channel": channel, "user": user, "jarvis": reply})

    def _recent_history(self) -> str:
        """Exchanges from earlier sessions (after the last reset), newest last."""
        try:
            lines = TRANSCRIPT_FILE.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return ""
        entries = []
        for line in lines:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("reset"):
                entries = []
            elif e.get("t", "") < SESSION_START:
                entries.append(e)
        out = []
        for e in entries[-RECALL_EXCHANGES:]:
            when = e["t"][:16].replace("T", " ")
            out.append(f"[{when} via {e['channel']}] Owner: {e['user'][:300]}\n"
                       f"  You: {e['jarvis'][:300]}")
        return "\n".join(out)

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
        recent = self._recent_history()
        if recent:
            parts.append("Your most recent exchanges from earlier sessions (for context; "
                         "don't repeat them unless asked):\n" + recent)
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


def _api_error_detail(exc: anthropic.APIStatusError) -> str:
    """The API's own explanation (it never contains the API key)."""
    body = exc.body if isinstance(exc.body, dict) else {}
    error = body.get("error")
    message = error.get("message") if isinstance(error, dict) else None
    if not message and not (exc.response.text or "").strip():
        # Anthropic always explains its errors; an empty reply came from something
        # in between (proxy, antivirus, a redirected base URL) or a mangled request.
        return "the server sent no explanation. Run: python -m jarvis.doctor"
    return (message or str(exc))[:300]


def _text_of(content: list[Any]) -> str:
    return " ".join(b.text for b in content if getattr(b, "type", None) == "text").strip()


brain = Brain()
