"""Connect Huxley to your Google account (calendar, Gmail, Docs).

    connect-google.bat        (or: python -m jarvis.google_auth)

One-time: asks for the Client ID and secret of your own Google Cloud "Desktop app"
client (see docs/Huxley-Google-Setup.pdf), opens Google's sign-in page in your
browser, and saves the sign-in to data/google_token.json on this computer only.
Run it again any time to reconnect or to tick boxes you missed.

Huxley's Google tools are deliberately limited: read calendar + add/change events,
read Gmail + save DRAFTS (it has no tool that sends email), and read Docs/Drive.
"""

from __future__ import annotations

import base64
import html
import hashlib
import json
import os
import secrets
import sys
import time
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .config import DATA_DIR, ROOT

TOKEN_FILE = DATA_DIR / "google_token.json"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"

SCOPES = {
    "calendar": "https://www.googleapis.com/auth/calendar.events",
    "gmail_read": "https://www.googleapis.com/auth/gmail.readonly",
    "gmail_drafts": "https://www.googleapis.com/auth/gmail.compose",
    "docs": "https://www.googleapis.com/auth/drive.readonly",
}
RECONNECT = "Double-click connect-google.bat in the Huxley folder to reconnect Google."


REFRESH_ERRORS = {
    "invalid_grant": ("Google sign-in has expired or was cancelled (apps left in Testing expire "
                      "after 7 days). " + RECONNECT),
    "invalid_client": ("Google says the Client ID or Client secret is wrong, or that client was "
                       "deleted. Run connect-google.bat, type the Client ID again when asked, and "
                       "paste the secret carefully."),
    "deleted_client": "That Google client was deleted. Create a new Desktop app client and run connect-google.bat.",
    "unauthorized_client": ("Google won't let this client sign in this way. Make sure the client "
                            "type is 'Desktop app', then run connect-google.bat."),
}


def _error_code(r: httpx.Response) -> str:
    try:
        return str(r.json().get("error", ""))
    except ValueError:
        return ""


class NotConnected(Exception):
    """Google isn't connected, the sign-in expired, or a permission wasn't granted."""


# ------------------------------------------------------------------ runtime --

_token: dict = {"access": "", "expires": 0.0, "mtime": 0.0, "saved": {}}


def _saved() -> dict:
    """The saved sign-in, re-read when connect-google.bat updates it (no restart needed)."""
    try:
        mtime = TOKEN_FILE.stat().st_mtime
    except FileNotFoundError:
        _token.update(saved={}, mtime=0.0, access="")
        return {}
    if mtime != _token["mtime"]:
        try:
            saved = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        except ValueError:
            saved = {}
        _token.update(saved=saved, mtime=mtime, access="", expires=0.0)
    return _token["saved"]


def connected() -> bool:
    return bool(_saved().get("refresh_token"))


def has(scope: str) -> bool:
    return SCOPES[scope] in _saved().get("scope", "").split()


async def access_token(scope: str) -> str:
    saved = _saved()
    if not saved.get("refresh_token"):
        raise NotConnected("Google isn't connected yet: double-click connect-google.bat in the "
                           "Huxley folder (see the Google setup guide).")
    if not has(scope):
        raise NotConnected(f"Huxley wasn't given {scope.split('_')[0].title()} access. Run "
                           "connect-google.bat again and tick every box on Google's page.")
    if _token["access"] and time.time() < _token["expires"] - 60:
        return _token["access"]
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(TOKEN_URL, data={
            "client_id": saved["client_id"], "client_secret": saved["client_secret"],
            "refresh_token": saved["refresh_token"], "grant_type": "refresh_token"})
    if r.status_code in (400, 401):
        raise NotConnected(REFRESH_ERRORS.get(_error_code(r), "Google refused the saved sign-in. " + RECONNECT))
    r.raise_for_status()
    data = r.json()
    _token.update(access=data["access_token"], expires=time.time() + data.get("expires_in", 3600))
    return _token["access"]


async def request(scope: str, method: str, url: str, **kwargs) -> httpx.Response:
    """An authorised Google API call. Raises NotConnected, or httpx errors."""
    token = await access_token(scope)
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.request(method, url, headers={"Authorization": f"Bearer {token}"}, **kwargs)
    if r.status_code == 401:
        _token["access"] = ""
        raise NotConnected("Google sign-in was refused. " + RECONNECT)
    if r.status_code == 403 and "insufficient" in r.text.lower():
        raise NotConnected("Huxley doesn't have that Google permission. Run connect-google.bat "
                           "again and tick every box.")
    if r.status_code == 403 and ("has not been used" in r.text or "disabled" in r.text):
        raise NotConnected("That Google API isn't switched on in your Google Cloud project "
                           "(APIs & Services > Library). See the Google setup guide.")
    r.raise_for_status()
    return r


def friendly(exc: Exception) -> str:
    """An error message safe to show and speak (no URLs or tokens)."""
    if isinstance(exc, NotConnected):
        return str(exc)
    if isinstance(exc, httpx.HTTPStatusError):
        return f"Google returned an error ({exc.response.status_code})."
    if isinstance(exc, httpx.HTTPError):
        return f"Couldn't reach Google ({type(exc).__name__})."
    return f"{type(exc).__name__}"


# ---------------------------------------------------------- sign-in (CLI) --

def _ask_client() -> tuple[str, str]:
    from dotenv import dotenv_values, set_key

    from .configure import read_secret

    env_path = ROOT / ".env"
    env = dotenv_values(env_path) if env_path.exists() else {}
    cid = (env.get("GOOGLE_CLIENT_ID") or "").strip()
    secret = (env.get("GOOGLE_CLIENT_SECRET") or "").strip()
    if cid and secret:
        print(f"Using the saved Client ID ({cid[:12]}...). To use a different one, type it now,")
        new = input("or just press Enter: ").strip()
        if not new:
            return cid, secret
        cid, secret = new, ""
    print("You need the Client ID and Client secret of your 'Desktop app' client from")
    print("Google Cloud (see docs/Huxley-Google-Setup.pdf, steps 1-5).\n")
    while not cid.endswith(".apps.googleusercontent.com"):
        cid = input("Client ID (ends in .apps.googleusercontent.com): ").strip()
    while len(secret) < 10:
        secret = read_secret("Client secret (hidden while pasting, Ctrl+V then Enter): ").strip()
    set_key(str(env_path), "GOOGLE_CLIENT_ID", cid, quote_mode="never")
    set_key(str(env_path), "GOOGLE_CLIENT_SECRET", secret, quote_mode="never")
    return cid, secret


def _exchange(cid: str, secret: str, code: str, verifier: str, redirect: str) -> tuple[bool, str, dict]:
    """Swap Google's one-time code for a lasting sign-in. Returns (ok, message, token data)."""
    try:
        r = httpx.post(TOKEN_URL, timeout=30, data={
            "client_id": cid, "client_secret": secret, "code": code, "code_verifier": verifier,
            "redirect_uri": redirect, "grant_type": "authorization_code"})
    except httpx.HTTPError as exc:
        return False, f"Couldn't reach Google to finish signing in ({type(exc).__name__}).", {}
    if r.status_code != 200:
        err = _error_code(r) or str(r.status_code)
        hint = REFRESH_ERRORS.get(err, "Check the Client ID and secret, then try again.")
        return False, f"Google refused to finish the sign-in ({err}). {hint}", {}
    data = r.json()
    if not data.get("refresh_token"):
        return False, "Google didn't return a lasting sign-in. Run connect-google.bat again.", {}
    return True, "", data


def _receive(state: str, finish) -> tuple[int, object, dict]:
    """A one-off web server on 127.0.0.1 for Google's redirect. It finishes the sign-in
    before answering, so the browser page shows the real result."""
    import http.server
    import threading

    outcome: dict = {}
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = parse_qs(urlparse(self.path).query)
            if q.get("state", [""])[0] != state or done.is_set():
                self.send_response(400)
                self.end_headers()
                return
            code, error = q.get("code", [""])[0], q.get("error", [""])[0]
            ok, message = finish(code) if code else (False, f"Google sign-in was cancelled ({error or 'no code'}).")
            outcome.update(ok=ok, message=message)
            title = "Huxley is connected to Google." if ok else "Huxley is NOT connected yet."
            detail = ("You can close this tab." if ok else
                      html.escape(message) + "<br><br>Run connect-google.bat again.")
            body = (f"<html><body style='background:#040805;color:#4dff88;font-family:monospace;"
                    f"padding:40px;font-size:18px'><h1>{title}</h1><p>{detail}</p></body></html>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
            done.set()

        def log_message(self, *args):  # keep the console clean (and codes out of it)
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server.server_address[1], (server, done), outcome


def _save(cid: str, secret: str, data: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    TOKEN_FILE.write_text(json.dumps({
        "client_id": cid, "client_secret": secret, "refresh_token": data["refresh_token"],
        "scope": data.get("scope", ""), "connected": time.strftime("%Y-%m-%d %H:%M")}), encoding="utf-8")
    if os.name != "nt":
        os.chmod(TOKEN_FILE, 0o600)


def self_test() -> list[tuple[str, str]]:
    """Use the saved sign-in for real: (check, result) lines, safe to share."""
    import asyncio
    from datetime import datetime, timedelta

    out = [("Huxley folder", str(ROOT)), ("saved sign-in", "found" if TOKEN_FILE.exists() else "MISSING")]
    saved = _saved()
    if not saved.get("refresh_token"):
        out.append(("result", "Not connected: run connect-google.bat in THIS folder."))
        return out
    out.append(("connected on", saved.get("connected", "?")))
    for key in SCOPES:
        out.append((f"permission: {key}", "yes" if has(key) else "NO (box not ticked)"))

    async def probe() -> str:
        if not has("calendar"):
            await access_token("gmail_read" if has("gmail_read") else "docs")
            return "sign-in works"
        start = datetime.now()
        r = await request("calendar", "GET", "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                          params={"timeMin": start.astimezone().isoformat(),
                                  "timeMax": (start + timedelta(days=7)).astimezone().isoformat(),
                                  "singleEvents": "true", "maxResults": 50})
        return f"OK - read your calendar ({len(r.json().get('items', []))} events in the next 7 days)"
    try:
        out.append(("live test", asyncio.run(probe())))
    except Exception as exc:
        out.append(("live test", "FAILED - " + friendly(exc)))
    return out


def sign_in() -> int:
    import webbrowser

    print("\n  Connect Huxley to Google\n  ------------------------\n")
    print(f"Huxley folder: {ROOT}\n")
    cid, secret = _ask_client()
    state = secrets.token_urlsafe(16)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    box: dict = {}

    def finish(code: str) -> tuple[bool, str]:
        ok, message, data = _exchange(cid, secret, code, verifier, box["redirect"])
        if ok:
            _save(cid, secret, data)
            box["scope"] = data.get("scope", "")
        return ok, message

    port, (server, done), outcome = _receive(state, finish)
    box["redirect"] = f"http://127.0.0.1:{port}/"
    url = AUTH_URL + "?" + urlencode({
        "client_id": cid, "redirect_uri": box["redirect"], "response_type": "code",
        "scope": " ".join(SCOPES.values()), "access_type": "offline", "prompt": "consent",
        "include_granted_scopes": "true", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})
    print("\nOpening Google's sign-in page in your browser...")
    print("  - Pick your Google account.")
    print("  - 'Google hasn't verified this app': click Advanced, then 'Go to Huxley'.")
    print("  - TICK EVERY BOX (calendar, Gmail, Drive), then Continue.")
    print("  Keep this window open until the browser page says connected.\n")
    print("If the browser doesn't open, copy this address into it:\n" + url + "\n")
    webbrowser.open(url)
    if not done.wait(300):
        server.shutdown()
        print("Timed out waiting for Google (5 minutes). Run connect-google.bat again.")
        return 1
    server.shutdown()
    if not outcome.get("ok"):
        print("NOT CONNECTED: " + outcome.get("message", "unknown problem"))
        return 1
    granted = box.get("scope", "").split()
    labels = {"calendar": "read and add calendar events", "gmail_read": "read your Gmail",
              "gmail_drafts": "save Gmail drafts (never send)", "docs": "search and read Google Docs"}
    print("Signed in. Permissions:")
    for key, scope in SCOPES.items():
        mark = "[x]" if scope in granted else "[ ]"
        note = "" if scope in granted else "  <- not ticked; run this again and tick it if you want it"
        print(f"  {mark} {labels[key]}{note}")
    print("\nTesting it for real...")
    results = self_test()
    for label, value in results[-1:]:
        print(f"  {label}: {value}")
    if "FAILED" in results[-1][1]:
        return 1
    print("\nDone. No restart needed: Huxley picks this up within a few seconds.")
    print("(If Huxley still says Google isn't connected, it's running from a different folder")
    print(" than the one above, or it's an old copy: right-click the H > Restart Huxley.)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(sign_in())
    except KeyboardInterrupt:
        sys.exit(1)
