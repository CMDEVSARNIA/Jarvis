"""Chat with Jarvis from your phone over Telegram.

Uses long polling, so it works from behind a home router with no public URL.
Only the owner's chat id is answered; everyone else is ignored.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from .brain import brain
from .config import settings

log = logging.getLogger("jarvis.telegram")
API = "https://api.telegram.org/bot{token}/{method}"


async def _call(client: httpx.AsyncClient, method: str, **params) -> dict:
    r = await client.post(API.format(token=settings.telegram_token, method=method),
                          json=params, timeout=40)
    r.raise_for_status()
    return r.json()


async def send_to_owner(text: str) -> str:
    if not (settings.telegram_enabled and settings.telegram_owner_chat_id):
        return "Telegram is not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_OWNER_CHAT_ID)."
    async with httpx.AsyncClient() as client:
        await _call(client, "sendMessage", chat_id=settings.telegram_owner_chat_id, text=text)
    return "Message sent."


async def run() -> None:
    if not settings.telegram_enabled:
        log.info("Telegram disabled (no TELEGRAM_BOT_TOKEN)")
        return
    log.info("Telegram bot polling")
    offset = 0
    async with httpx.AsyncClient() as client:
        while True:
            try:
                data = await _call(client, "getUpdates", offset=offset, timeout=30,
                                   allowed_updates=["message"])
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("Telegram poll failed: %s", exc)
                await asyncio.sleep(5)
                continue

            for update in data.get("result", []):
                offset = update["update_id"] + 1
                try:
                    await _handle(client, update)
                except Exception:
                    log.exception("Failed to handle Telegram update")


async def _handle(client: httpx.AsyncClient, update: dict) -> None:
    msg = update.get("message") or {}
    chat_id = str(msg.get("chat", {}).get("id", ""))
    text = (msg.get("text") or "").strip()
    if not chat_id or not text:
        return

    if not settings.telegram_owner_chat_id:
        # First-run helper: tell the owner which id to put in .env.
        await _call(client, "sendMessage", chat_id=chat_id, text=(
            f"Your chat id is {chat_id}. Put TELEGRAM_OWNER_CHAT_ID={chat_id} "
            "in Jarvis's .env file and restart him."))
        return
    if chat_id != settings.telegram_owner_chat_id:
        log.warning("Ignoring Telegram message from unknown chat %s", chat_id)
        return

    if text == "/reset":
        brain.reset()
        reply = "Memory of this conversation cleared."
    else:
        await _call(client, "sendChatAction", chat_id=chat_id, action="typing")
        reply = await brain.ask(text, channel="telegram")
    await _call(client, "sendMessage", chat_id=chat_id, text=reply)
