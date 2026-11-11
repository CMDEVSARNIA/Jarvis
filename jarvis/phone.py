"""Phone calls through Twilio.

Flow: Twilio dials (or receives) a call -> hits /twilio/voice -> we answer with
<Gather input="speech"> -> Twilio transcribes what you say and posts it to
/twilio/gather -> Claude replies -> <Say> it -> listen again.

Twilio gives each webhook ~15 seconds. If Claude needs longer (web search,
tools), we say "one moment" and <Redirect> to /twilio/wait until it's ready.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Request, Response
from twilio.request_validator import RequestValidator
from twilio.rest import Client
from twilio.twiml.voice_response import Gather, VoiceResponse

from . import events
from .brain import brain
from .config import settings

log = logging.getLogger("jarvis.phone")
router = APIRouter(prefix="/twilio")

_pending: dict[str, asyncio.Task] = {}   # CallSid -> Claude reply in progress
_openers: dict[str, str] = {}            # CallSid -> what to say when the owner picks up
WAIT_SECONDS = 9


async def call_owner(reason: str) -> str:
    if not settings.phone_enabled:
        return "Phone calls are not configured (see TWILIO_* settings in .env)."

    def dial() -> str:
        client = Client(settings.twilio_sid, settings.twilio_token)
        call = client.calls.create(
            to=settings.owner_phone,
            from_=settings.twilio_from,
            url=f"{settings.public_base_url}/twilio/voice",
        )
        return call.sid

    sid = await asyncio.to_thread(dial)
    _openers[sid] = reason
    events.publish({"type": "call", "status": "dialing"})
    return f"Calling the owner now (call {sid})."


# ------------------------------------------------------------------ helpers --

async def _verified_form(request: Request) -> dict[str, str] | None:
    """Reject anything that isn't genuinely from Twilio."""
    form = {k: str(v) for k, v in (await request.form()).items()}
    url = settings.public_base_url + request.url.path
    if request.url.query:
        url += "?" + request.url.query
    signature = request.headers.get("X-Twilio-Signature", "")
    if not RequestValidator(settings.twilio_token).validate(url, form, signature):
        log.warning("Rejected unsigned/invalid Twilio request to %s", request.url.path)
        return None
    return form


def _is_owner(form: dict[str, str]) -> bool:
    if form.get("Direction") == "inbound":
        # Caller ID is spoofable; only trust inbound calls if explicitly enabled.
        return settings.allow_inbound_calls and form.get("From") == settings.owner_phone
    return form.get("To") == settings.owner_phone  # a call Huxley placed


def _twiml(vr: VoiceResponse) -> Response:
    return Response(content=str(vr), media_type="application/xml")


def _say_and_listen(text: str, silence_count: int = 0) -> Response:
    vr = VoiceResponse()
    gather = Gather(input="speech", action="/twilio/gather", method="POST",
                    speech_timeout="auto", language="en-GB")
    gather.say(text, voice=settings.twilio_voice)
    vr.append(gather)
    # Nothing heard: prompt once more, then hang up politely.
    vr.redirect("/twilio/voice?" + urlencode({"silence": silence_count + 1}), method="POST")
    return _twiml(vr)


async def _reply_or_wait(call_sid: str) -> Response:
    task = _pending.get(call_sid)
    if task is None:
        return _say_and_listen("Sorry, I lost my train of thought. Go on.")
    try:
        reply = await asyncio.wait_for(asyncio.shield(task), timeout=WAIT_SECONDS)
    except asyncio.TimeoutError:
        vr = VoiceResponse()
        vr.say("One moment.", voice=settings.twilio_voice)
        vr.pause(length=1)
        vr.redirect("/twilio/wait", method="POST")
        return _twiml(vr)
    _pending.pop(call_sid, None)
    return _say_and_listen(reply)


# ----------------------------------------------------------------- webhooks --

@router.post("/voice")
async def voice(request: Request) -> Response:
    form = await _verified_form(request)
    if form is None:
        return Response(status_code=403)
    vr = VoiceResponse()
    if not _is_owner(form):
        vr.say("This line is private. Goodbye.", voice=settings.twilio_voice)
        vr.hangup()
        return _twiml(vr)

    call_sid = form.get("CallSid", "")
    silence = int(request.query_params.get("silence", "0") or 0)
    if silence >= 2:
        vr.say("I'll let you go. Goodbye.", voice=settings.twilio_voice)
        vr.hangup()
        events.publish({"type": "call", "status": "ended"})
        return _twiml(vr)
    if silence == 1:
        return _say_and_listen("Are you still there?", silence_count=1)

    events.publish({"type": "call", "status": "connected"})
    opener = _openers.pop(call_sid, None)
    greeting = opener or f"Hello {settings.owner_name}. How can I help?"
    return _say_and_listen(greeting)


@router.post("/gather")
async def gather(request: Request) -> Response:
    form = await _verified_form(request)
    if form is None:
        return Response(status_code=403)
    if not _is_owner(form):
        return Response(status_code=403)

    call_sid = form.get("CallSid", "")
    heard = form.get("SpeechResult", "").strip()
    if not heard:
        return _say_and_listen("Sorry, I didn't catch that.")
    if heard.lower().rstrip(".!") in {"goodbye", "bye", "hang up", "that's all", "thanks bye"}:
        vr = VoiceResponse()
        vr.say(f"Very good, {settings.owner_name}. Goodbye.", voice=settings.twilio_voice)
        vr.hangup()
        events.publish({"type": "call", "status": "ended"})
        return _twiml(vr)

    _pending[call_sid] = asyncio.create_task(brain.ask(heard, channel="call"))
    return await _reply_or_wait(call_sid)


@router.post("/wait")
async def wait(request: Request) -> Response:
    form = await _verified_form(request)
    if form is None or not _is_owner(form):
        return Response(status_code=403)
    return await _reply_or_wait(form.get("CallSid", ""))
