"""The HUD's page viewer: show a web page inside Huxley instead of a new tab.

Many sites forbid being shown inside another page (X-Frame-Options / CSP
frame-ancestors), so each URL gets one of four modes:
- "frame":    the live page in an iframe (sites that allow it)
- "embed":    an official embed URL (YouTube, Google Maps, Spotify)
- "reader":   Huxley fetches the page and shows its text in its own style
- "external": login-type sites (mail, social) open in the normal browser

Reader mode fetches pages from this machine, so every request (and every
redirect) is checked to reach a public internet address only: never this PC,
the home network, or other private ranges.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse

import httpx

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Huxley/1.0"
MAX_BYTES = 3_000_000
MAX_BLOCKS = 400

# Sites people log into: never embed or fetch these, open them in the browser.
EXTERNAL_HOSTS = (
    "mail.google.com", "accounts.google.com", "outlook.live.com", "outlook.office.com",
    "facebook.com", "instagram.com", "x.com", "twitter.com", "linkedin.com", "web.whatsapp.com",
    "chatgpt.com", "claude.ai", "paypal.com",
)


class BlockedURL(Exception):
    pass


# ------------------------------------------------------------------ safety --

def _host_matches(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


async def _resolve(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


async def check_public(url: str) -> str:
    """Raise BlockedURL unless url is http(s) and resolves only to public addresses."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise BlockedURL("Only http(s) web addresses can be shown.")
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith((".local", ".lan", ".home", ".internal")):
        raise BlockedURL("That's an address on this computer or home network.")
    try:
        addresses = [host] if _is_ip(host) else await _resolve(host)
    except OSError:
        raise BlockedURL(f"Couldn't find {host}.") from None
    for addr in addresses:
        ip = ipaddress.ip_address(addr.split("%")[0])
        if not ip.is_global:
            raise BlockedURL("That address points to this computer or a private network, "
                             "which the viewer won't open.")
    return url


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


# --------------------------------------------------------------- embeds ----

def embed_url(url: str) -> str | None:
    """Official embeddable versions of common links."""
    p = urlparse(url)
    host = (p.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    if host in ("youtube.com", "music.youtube.com"):
        if p.path == "/watch":
            vid = parse_qs(p.query).get("v", [""])[0]
        elif p.path.startswith(("/shorts/", "/live/", "/embed/")):
            vid = p.path.split("/")[2]
        else:
            vid = ""
        if re.fullmatch(r"[\w-]{6,20}", vid or ""):
            return f"https://www.youtube.com/embed/{vid}"
    if host == "youtu.be":
        vid = p.path.strip("/").split("/")[0]
        if re.fullmatch(r"[\w-]{6,20}", vid):
            return f"https://www.youtube.com/embed/{vid}"
    if host == "open.spotify.com":
        parts = [x for x in p.path.split("/") if x and not x.startswith("intl-")]
        if len(parts) >= 2 and parts[0] in ("track", "album", "playlist", "artist", "episode", "show"):
            return f"https://open.spotify.com/embed/{parts[0]}/{parts[1]}"
    if (host == "google.com" and p.path.startswith("/maps")) or host == "maps.google.com":
        query = parse_qs(p.query).get("q", [""])[0]
        if not query and "/maps/search/" in p.path:
            query = p.path.split("/maps/search/")[1].split("/")[0].replace("+", " ")
        if not query and "/maps/place/" in p.path:
            query = p.path.split("/maps/place/")[1].split("/")[0].replace("+", " ")
        if query:
            return f"https://maps.google.com/maps?q={quote_plus(query)}&output=embed"
    return None


def map_embed(place: str) -> str:
    return f"https://maps.google.com/maps?q={quote_plus(place)}&output=embed"


def frame_allowed(headers: httpx.Headers) -> bool:
    if headers.get("x-frame-options"):
        return False  # DENY, SAMEORIGIN, ALLOW-FROM: none include Huxley
    csp = headers.get("content-security-policy", "")
    match = re.search(r"frame-ancestors([^;]*)", csp, re.I)
    if match and "*" not in match.group(1).split():
        return False
    return True


# --------------------------------------------------------------- reader ----

class _Extractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "aside", "form",
            "button", "iframe", "select", "template", "figure"}
    BLOCKS = {"p", "h1", "h2", "h3", "h4", "li", "blockquote", "pre"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.blocks: list[dict[str, str]] = []
        self._skip = 0
        self._in_title = False
        self._current: str | None = None
        self._buf: list[str] = []
        self.has_article = False
        self._article_depth = 0
        self.article_blocks: list[dict[str, str]] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "title" and not self._skip and not self.title:
            self._in_title = True  # the page title only, not icon <title>s inside <svg>
        elif tag in ("article", "main"):
            self.has_article = True
            self._article_depth += 1
        elif tag in self.BLOCKS and not self._skip:
            self._flush()
            self._current = tag
        elif tag == "br" and self._current:
            self._buf.append(" ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in ("article", "main") and self._article_depth:
            self._flush()
            self._article_depth -= 1
        elif tag == self._current:
            self._flush()

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif self._current and not self._skip:
            self._buf.append(data)

    def _flush(self):
        if self._current:
            text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            if len(text) > 1 and (self._current != "li" or len(text) > 20):
                block = {"tag": self._current, "text": text[:2000]}
                self.blocks.append(block)
                if self._article_depth:
                    self.article_blocks.append(block)
        self._current, self._buf = None, []


def extract(html: str) -> tuple[str, list[dict[str, str]]]:
    parser = _Extractor()
    parser.feed(html)
    parser.close()
    parser._flush()
    blocks = parser.article_blocks if len(parser.article_blocks) >= 3 else parser.blocks
    title = re.sub(r"\s+", " ", parser.title).strip()
    seen: set[str] = {title.lower()}
    clean = []
    for b in blocks:
        words = b["text"].split()
        # Menus glued together ("NewsMenuTelevisionheadphone...") and repeats are noise.
        if any(len(w) > 30 and "://" not in w and "/" not in w for w in words):
            continue
        key = b["text"].lower()
        if key in seen:
            continue
        seen.add(key)
        clean.append(b)
    return title, clean[:MAX_BLOCKS]


# ---------------------------------------------------------------- fetch ----

async def _fetch(url: str) -> tuple[str, httpx.Response, bytes]:
    """GET with redirects followed by hand, so every hop passes check_public."""
    async with httpx.AsyncClient(timeout=15, headers={
            "User-Agent": USER_AGENT, "Accept-Language": "en-CA,en;q=0.9"}) as client:
        for _hop in range(6):
            await check_public(url)
            async with client.stream("GET", url, follow_redirects=False) as resp:
                if resp.is_redirect and "location" in resp.headers:
                    url = urljoin(url, resp.headers["location"])
                    continue
                body = b""
                async for chunk in resp.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        break
                return url, resp, body
    raise BlockedURL("Too many redirects.")


async def prepare(url: str, force_reader: bool = False) -> dict:
    """Decide how to show url. Returns the event payload for the HUD."""
    url = url.strip()
    if not urlparse(url).scheme:
        url = "https://" + url
    host = (urlparse(url).hostname or "").lower()
    if _host_matches(host, EXTERNAL_HOSTS):
        return {"mode": "external", "url": url, "title": host,
                "note": "This site needs you to log in, so it opens in your browser."}
    if not force_reader and (emb := embed_url(url)):
        return {"mode": "embed", "url": url, "embed_url": emb, "title": host}

    final_url, resp, body = await _fetch(url)
    ctype = resp.headers.get("content-type", "")
    if resp.status_code >= 400:
        return {"mode": "external", "url": final_url, "title": host,
                "note": f"The site answered with error {resp.status_code}; try it in the browser."}
    if not force_reader and frame_allowed(resp.headers):
        return {"mode": "frame", "url": final_url, "embed_url": final_url, "title": host}
    if "html" not in ctype:
        return {"mode": "external", "url": final_url, "title": host,
                "note": "This isn't a web page the reader can show; opening it in the browser."}
    charset = resp.encoding or "utf-8"
    title, blocks = extract(body.decode(charset, errors="replace"))
    if not blocks:
        return {"mode": "external", "url": final_url, "title": title or host,
                "note": "This page has no readable text (it may need JavaScript)."}
    return {"mode": "reader", "url": final_url, "title": title or host, "blocks": blocks}
