"""Chat with Jarvis from your phone over Telegram.

Uses long polling, so it works from behind a home router with no public URL.
Only the owner's chat id is answered; everyone else is ignored.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from .brain import brain
from .config import settings, valid_telegram_token

log = logging.getLogger("jarvis.telegram")
API = "https://api.telegram.org/bot{token}/{method}"

# Live state shown on the HUD: (ok, short explanation)
status: tuple[bool, str] = (False, "no bot token")


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


def _set_status(ok: bool, text: str) -> None:
    global status
    status = (ok, text)


async def run() -> None:
    if not settings.telegram_enabled:
        _set_status(False, "no bot token - run the settings tool")
        log.info("Telegram disabled (no TELEGRAM_BOT_TOKEN)")
        return
    if not valid_telegram_token(settings.telegram_token):
        log.error("The saved Telegram bot token doesn't look right. Re-enter it with "
                  "python -m jarvis.configure")
        _set_status(False, "bot token looks wrong - re-enter it")
        return
    log.info("Telegram bot polling")
    _set_status(False, "connecting...")
    offset = 0
    async with httpx.AsyncClient() as client:
        try:
            # A webhook left on the bot (e.g. by another tool) stops getUpdates working.
            await _call(client, "deleteWebhook")
            # Telegram accepted the token: show the real status now rather than
            # after the first 30-second poll returns.
            _set_status(bool(settings.telegram_owner_chat_id),
                        "connected" if settings.telegram_owner_chat_id
                        else "message your bot to get your chat id")
        except httpx.HTTPError:
            pass  # the poll loop below reports the real problem
        while True:
            try:
                data = await _call(client, "getUpdates", offset=offset, timeout=30,
                                   allowed_updates=["message"])
            except (httpx.HTTPError, ValueError) as exc:
                # Don't log str(exc): it contains the request URL, which holds the bot token.
                status = getattr(getattr(exc, "response", None), "status_code", None)
                log.warning("Telegram poll failed: %s%s", type(exc).__name__,
                            f" (HTTP {status})" if status else "")
                if status in (401, 404):
                    _set_status(False, "bot token rejected - copy it from @BotFather again")
                elif status == 409:
                    _set_status(False, "another copy of Jarvis is using this bot")
                else:
                    _set_status(False, "can't reach Telegram - retrying")
                await asyncio.sleep(5)
                continue

            if settings.telegram_owner_chat_id:
                _set_status(True, "connected")
            else:
                _set_status(False, "message your bot to get your chat id")

            for update in data.get("result", []):
                offset = update["update_id"] + 1
                try:
                    await _handle(client, update)
                except httpx.HTTPError as exc:  # message would include the token-bearing URL
                    # Telegram's own "description" is safe to log; the URL is not.
                    resp = getattr(exc, "response", None)
                    desc = ""
                    if resp is not None:
                        try:
                            desc = resp.json().get("description", "")
                        except ValueError:
                            pass
                    log.error("Telegram request failed: %s %s %s", type(exc).__name__,
                              getattr(resp, "status_code", ""), desc)
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
            f"Your chat id is {chat_id}. On the PC, run the settings tool "
            "(python -m jarvis.configure), enter this number at 'Your chat id', "
            "then restart Jarvis."))
        return
    if chat_id != settings.telegram_owner_chat_id:
        log.warning("Ignoring Telegram message from chat %s: the saved owner chat id is %s. "
                    "If that's you, fix it with python -m jarvis.configure",
                    chat_id, settings.telegram_owner_chat_id)
        return
    log.info("Telegram message received from the owner")

    if text == "/reset":
        brain.reset()
        reply = "Memory of this conversation cleared."
    else:
        await _call(client, "sendChatAction", chat_id=chat_id, action="typing")
        reply = await brain.ask(text, channel="telegram")
    await _call(client, "sendMessage", chat_id=chat_id, text=reply)
