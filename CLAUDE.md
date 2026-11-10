# Jarvis

A personal assistant run by Claude: a Python server (`jarvis/`) with a browser HUD
(`web/`), a Telegram bot, and Twilio phone calls. It normally runs on a Google Cloud
e2-micro VM (`deploy/`). Setup guides are in `docs/`.

## Setting it up

To set up or check the cloud server, use the `jarvis-cloud-setup` skill
(`/jarvis-cloud-setup`). It walks through Session 1 step by step.

## Rules for working in this repo

- Secrets live only in `.env` (git-ignored) and are entered with
  `python -m jarvis.configure`. Never ask for secrets in chat, and never read,
  print or commit `.env` or `data/`.
- Keep Jarvis's tools narrow. Don't add arbitrary shell or file access: anything that
  can reach the owner's phone can call those tools.
- Keep the Claude conversation append-only and the system prompt fixed
  (`jarvis/brain.py`), so prompt caching and replayed thinking stay valid.
- Don't log request URLs or exception text from Telegram calls; they contain the
  bot token.

## Running locally

```
python -m venv .venv
.venv/bin/pip install -r requirements.txt     # Windows: .venv\Scripts\pip
.venv/bin/python -m jarvis.configure
.venv/bin/python -m jarvis
```
