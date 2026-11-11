"""Long-term facts about the owner (data/memory.json), viewable and editable from
the HUD's MEMORY panel or by asking Jarvis."""

from __future__ import annotations

import json

from . import events
from .config import DATA_DIR

MEMORY_FILE = DATA_DIR / "memory.json"
MAX_FACTS = 200


def load() -> list[str]:
    try:
        facts = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        return [str(f) for f in facts if str(f).strip()]
    except (FileNotFoundError, ValueError):
        return []


def _save(facts: list[str]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    MEMORY_FILE.write_text(json.dumps(facts, indent=2, ensure_ascii=False), encoding="utf-8")
    events.publish({"type": "memory", "facts": facts})


async def remember(fact: str) -> str:
    fact = fact.strip()
    if not fact:
        return "Nothing to remember."
    facts = load()
    if any(fact.lower() == f.lower() for f in facts):
        return "Already known."
    facts.append(fact)
    _save(facts[-MAX_FACTS:])
    return "Saved to memory."


async def recall_memory() -> str:
    facts = load()
    if not facts:
        return "Nothing saved about the owner yet."
    return "\n".join(f"{n}. {f}" for n, f in enumerate(facts, 1))


async def forget(item: str) -> str:
    """Forget by number (from recall_memory), by matching text, or 'all'."""
    facts = load()
    target = item.strip()
    if target.lower() == "all":
        _save([])
        return f"Forgot all {len(facts)} facts."
    if target.isdigit() and 1 <= int(target) <= len(facts):
        removed = facts.pop(int(target) - 1)
    else:
        match = next((f for f in facts if target.lower() in f.lower()), None)
        if match is None:
            return f"No saved fact matches '{target}'."
        facts.remove(match)
        removed = match
    _save(facts)
    return f"Forgot: {removed}"
