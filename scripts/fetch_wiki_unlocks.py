"""Where each card, Evolution and Hero unlocks, from the Clash Royale Wiki (fandom).

    python scripts/fetch_wiki_unlocks.py

Writes config/card_unlocks.yaml. Sources (read through the wiki's MediaWiki API, about one
request per second):
  - each card's own page: the `Arena=` field of its {{Card Infobox}} (where the card unlocks);
    when a card page has no such field, the card list of its arena on the Arenas page;
  - the Arenas page: each arena's number, e.g. "Builder's Workshop (Arena 5)";
  - the Card Evolution and Heroes pages: the arena that unlocks the Evolution, Hero and Wild slots.

The official API does not publish unlock arenas, so this is the only source; it is a community
wiki and is recorded as such. The script stops with an error instead of guessing when a card or
an arena cannot be matched.
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
API = "https://clashroyale.fandom.com/api.php"
UA = {"User-Agent": "crdeck-learning-project/1.0 (personal, low volume)"}
OUT = ROOT / "config" / "card_unlocks.yaml"


def wikitext(title: str) -> tuple[str, str]:
    r = requests.get(API, params={"action": "parse", "page": title, "prop": "wikitext", "format": "json", "redirects": 1},
                     headers=UA, timeout=30)
    r.raise_for_status()
    j = r.json()
    if "parse" not in j:
        raise SystemExit(f"wiki page {title!r} not found: {j.get('error', {}).get('info')}")
    time.sleep(1.0)
    return j["parse"]["title"], j["parse"]["wikitext"]["*"]


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def main() -> None:
    cards_file = sorted(ROOT.glob("data/raw/*/cards/cards.json"))[-1]
    api_cards = json.loads(cards_file.read_text(encoding="utf-8"))["body"]["items"]

    _, arenas = wikitext("Arenas")
    numbers = {norm(n): int(k) for n, k in re.findall(r"<br>([^<\n]+?) \(Arena (\d+)\)<br>", arenas)}
    numbers[norm("Training Camp")] = 0
    # the Arenas page also lists the cards each arena unlocks: a second source, used when a card
    # page has no Arena field and to check the card pages against
    listed = {}
    for name, rest in re.findall(r"<br>([^<\n]+?) \(Arena \d+\)<br>([^\n]*)", arenas):
        for card in re.findall(r"\{\{Card\|Name=([^|}]+)", rest):
            listed.setdefault(norm(card), name.strip())
    if len(numbers) < 10:
        raise SystemExit("could not read arena numbers from the Arenas page")

    def slot_arena(page: str, pattern: str) -> int:
        _, t = wikitext(page)
        m = re.search(pattern, t)
        if not m:
            raise SystemExit(f"could not find the slot unlock arena on {page}")
        return int(m.group(1))

    evo = slot_arena("Card Evolution", r"Evolution slot are both unlocked at \[\[Arenas[^\]]*\]\] (\d+)")
    hero = slot_arena("Heroes", r"Heroes and the first \{\{Rarity\|Champion\}\} slot are both unlocked at \[\[Arenas[^\]]*\]\] (\d+)")
    wild = slot_arena("Heroes", r"Wild slot is unlocked at Arena (\d+)")

    out_cards, problems, disagree = {}, [], []
    for c in sorted(api_cards, key=lambda c: c["name"]):
        title, t = wikitext(c["name"])
        m = re.search(r"\{\{Card Infobox[^}]*\|\s*Arena\s*=\s*([^|}\n]+)", t)
        on_list = listed.get(norm(c["name"]))
        if m:
            arena, how = m.group(1).strip(), "card page"
            if on_list and norm(on_list) != norm(arena):
                disagree.append(f"{c['name']}: card page {arena!r}, Arenas page {on_list!r}")
        elif on_list:
            arena, how = on_list, "Arenas page"
        else:
            problems.append(f"{c['name']}: no Arena field on wiki page {title!r} and not on the Arenas page")
            continue
        n = numbers.get(norm(arena))
        if n is None:
            problems.append(f"{c['name']}: unknown arena {arena!r}")
            continue
        out_cards[c["name"]] = {"card_id": int(c["id"]), "arena": arena, "arena_number": n, "from": how,
                                "page": f"https://clashroyale.fandom.com/wiki/{quote(title.replace(' ', '_'))}"}
        print(f"  {c['name']}: {arena} ({n})")
    for d in disagree:
        print("  sources disagree (card page used):", d)
    if problems:
        raise SystemExit("stopped, not guessing:\n  " + "\n  ".join(problems))

    doc = {
        "source": "Clash Royale Wiki (clashroyale.fandom.com), a community wiki; read through its MediaWiki API",
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rule": "A card is available in an arena if it unlocks there or earlier; players are never moved back to an earlier arena (Arenas page).",
        "slot_unlock_arena": {"evo": evo, "hero": hero, "wild": wild},
        "slot_sources": {"evo": "https://clashroyale.fandom.com/wiki/Card_Evolution", "hero": "https://clashroyale.fandom.com/wiki/Heroes",
                         "wild": "https://clashroyale.fandom.com/wiki/Heroes"},
        "sources_disagree": disagree,
        "cards": out_cards,
    }
    header = ("# Where each card unlocks and when the special slots unlock. Generated by\n"
              "# scripts/fetch_wiki_unlocks.py from the Clash Royale Wiki; do not edit by hand.\n")
    OUT.write_text(header + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"wrote {OUT}: {len(out_cards)} cards; slots evo {evo}, hero {hero}, wild {wild}")


if __name__ == "__main__":
    sys.exit(main())
