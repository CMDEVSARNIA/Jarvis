"""Web server: serves the HUD, its WebSocket, and the Twilio webhooks."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
from contextlib import asynccontextmanager

import psutil
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import briefing, events, phone, reminders, telegram_bot
from .brain import brain
from .config import WEB_DIR, settings

log = logging.getLogger("jarvis.server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    tasks = [asyncio.create_task(telegram_bot.run()),
             asyncio.create_task(reminders.run_scheduler()),
             asyncio.create_task(briefing.run())]
    yield
    for task in tasks:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(phone.router)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


def _authorised(token: str | None, headers) -> bool:
    """The HUD can control the PC, so it only works locally with the install token.
    Requests arriving through a tunnel carry forwarding headers and are refused."""
    if any(h in headers for h in ("x-forwarded-for", "cf-connecting-ip", "x-real-ip")):
        return False
    return bool(token) and secrets.compare_digest(token, settings.hud_token)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.post("/api/call-me")
async def call_me(request: Request) -> dict:
    if not _authorised(request.headers.get("x-jarvis-token"), request.headers):
        raise HTTPException(status_code=403)
    return {"result": await phone.call_owner("You asked me to call. What can I do for you?")}


def _status() -> dict:
    return {
        "type": "status",
        "cpu": psutil.cpu_percent(interval=None),
        "mem": psutil.virtual_memory().percent,
        "telegram": telegram_bot.status[0],
        "telegram_status": telegram_bot.status[1],
        "phone": settings.phone_enabled,
        "model": settings.model,
        "dashboard": briefing.dashboard,
    }


async def _briefing_now() -> None:
    """The HUD's BRIEFING button: always give one, even if already given today."""
    briefing._mark_briefed("")
    await briefing.give_briefing(send_telegram=False)


@app.websocket("/ws")
async def ws(socket: WebSocket) -> None:
    if not _authorised(socket.query_params.get("token"), socket.headers):
        await socket.close(code=4403)
        return
    await socket.accept()
    queue = events.subscribe()

    async def pump_events() -> None:
        while True:
            await socket.send_json(await queue.get())

    async def pump_status() -> None:
        while True:
            await socket.send_json(_status())
            await asyncio.sleep(2)

    tasks = [asyncio.create_task(pump_events()), asyncio.create_task(pump_status())]
    asyncio.create_task(briefing.greet())  # only acts the first time per run
    try:
        while True:
            msg = await socket.receive_json()
            kind = msg.get("type")
            text = str(msg.get("text", "")).strip()
            if kind == "chat" and text:
                # Run in the background so the socket keeps streaming events.
                asyncio.create_task(brain.ask(text, channel="hud"))
            elif kind == "briefing":
                asyncio.create_task(_briefing_now())
            elif kind == "reset":
                brain.reset()
                events.publish({"type": "reply", "channel": "hud",
                                "text": "Conversation cleared."})
            elif kind == "state":  # HUD reports listening/speaking so other tabs mirror it
                events.publish({"type": "state", "state": msg.get("state", "idle")})
    except WebSocketDisconnect:
        pass
    finally:
        for t in tasks:
            t.cancel()
        events.unsubscribe(queue)
