"""Explanation objects for every recommended deck (spec section 8).

Structural checks are advisory: they never block a deck. Warnings that share a
root cause share a `group` and are reported together under one heading.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .cards import CardTable
from .rules import DeckCard, DeckRules, check_deck, deck_key

FORM_UNKNOWN = "FORM_UNKNOWN"
INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
UNKNOWN_CARD = "UNKNOWN_CARD"
LOW_CARD_DATA = "LOW_CARD_DATA"
UNSEEN_DECK = "UNSEEN_DECK"
STALE_AFTER_BALANCE = "STALE_AFTER_BALANCE"  # reserved (spec 8): balance-change handling is deferred

GROUP_TITLES = {
    "win_condition": "No way to pressure towers",
    "air": "Weak against air (Balloon, Lava Hound, air swarms)",
    "spells": "Spell coverage",
    "tank_defense": "Weak against big tanks",
    "elixir": "Elixir cost",
}


@dataclass
class Advisory:
    code: str
    group: str
    message: str
    rule: str
    observed: Any


def avg_elixir(entries: list[DeckCard], cards: CardTable) -> float | None:
    vals = [c.elixir for e in entries if (c := cards.get(e.card_id)) and c.elixir is not None and not c.elixir_variable]
    return float(np.mean(vals)) if vals else None


def structural_warnings(entries: list[DeckCard], cards: CardTable, cfg: dict) -> list[Advisory]:
    cs = [cards[e.card_id] for e in entries if e.card_id in cards]
    roles = [r for c in cs for r in c.roles]
    w: list[Advisory] = []
    n_wc = sum(c.is_win_condition for c in cs)
    if n_wc == 0:
        w.append(Advisory("NO_WIN_CONDITION", "win_condition", "no win condition", ">= 1 win condition", 0))
    n_air = roles.count("air_defense")
    if n_air == 0:
        w.append(Advisory("NO_AIR_DEFENSE", "air", "no air defense", ">= 1 air_defense card", 0))
    elif n_air == 1:
        w.append(Advisory("THIN_AIR_DEFENSE", "air", "only one air defense card", ">= 2 air_defense cards", 1))
    n_spell = sum(c.card_type == "spell" for c in cs)
    n_small = roles.count("small_spell")
    if n_spell == 0:
        w.append(Advisory("NO_SPELL", "spells", "no spell", ">= 1 spell", 0))
    if n_small == 0:
        w.append(Advisory("NO_SMALL_SPELL", "spells", "no small spell for swarms", ">= 1 small_spell", 0))
    if roles.count("building") == 0 and roles.count("tank_killer") == 0:
        w.append(Advisory("NO_TANK_ANSWER", "tank_defense", "no building or tank killer against tanks",
                         ">= 1 building or tank_killer", 0))
    ae = avg_elixir(entries, cards)
    if ae is not None and ae > cfg["elixir_max"]:
        w.append(Advisory("ELIXIR_HIGH", "elixir", f"avg elixir {ae:.1f}, rule <= {cfg['elixir_max']}", f"<= {cfg['elixir_max']}", round(ae, 2)))
    if ae is not None and ae < cfg["elixir_min"]:
        w.append(Advisory("ELIXIR_LOW", "elixir", f"avg elixir {ae:.1f}, rule >= {cfg['elixir_min']}", f">= {cfg['elixir_min']}", round(ae, 2)))
    for role in cfg["narrow_roles"]:
        n = roles.count(role)
        if n >= 2:
            w.append(Advisory(f"DUPLICATE_ROLE_{role.upper()}", f"role:{role}", f"{n} cards with role {role}", f"<= 1 {role}", n))
    return w


def group_warnings(ws: list[Advisory]) -> list[dict]:
    groups: dict[str, list[Advisory]] = {}
    for x in ws:
        groups.setdefault(x.group, []).append(x)
    out = []
    for g, items in groups.items():
        title = GROUP_TITLES.get(g, f"Redundant role: {g.split(':', 1)[-1]}" if g.startswith("role:") else g)
        out.append({"group": g, "root_cause": title, "warnings": [asdict(i) for i in items]})
    return out


def has_win_condition(entries: list[DeckCard], cards: CardTable) -> bool:
    return any(cards[e.card_id].is_win_condition for e in entries if e.card_id in cards)


def describe_entry(e: DeckCard, cards: CardTable) -> str:
    n = cards.name(e.card_id)
    return n if e.form == "base" else f"{n} ({'Evolution' if e.form == 'evo' else 'Hero'})"


@dataclass
class Explanation:
    deck: list[str]
    deck_key: str
    legality: dict
    archetype: dict
    score: dict
    synergy_top: list[dict]
    synergy_bottom: list[dict]
    synergy_insufficient_pairs: int
    warnings: list[dict]
    data_quality: list[dict]
    objective: dict
    source: str
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _pair_row(p: dict, cards: CardTable) -> dict:
    return {
        "pair": f"{cards.name(p['card_i'])} + {cards.name(p['card_j'])}",
        "synergy": round(float(p["synergy"]), 4),
        "interval": [round(float(p["lo"]), 4), round(float(p["hi"]), 4)],
        "lift": round(float(p["lift"]), 3),
        "games": int(p["games"]),
        "shrunk_wr": round(float(p["shrunk_wr"]), 4),
    }


def build_explanation(entries: list[DeckCard], ctx, objective: dict | None = None) -> Explanation:
    """ctx: crdeck.pipeline.Context (cards, rules, synergy, strength, scorer, archetype, ...)."""
    cards: CardTable = ctx.cards
    rules: DeckRules = ctx.rules
    entries = sorted(entries)
    legal = check_deck(entries, cards, rules)
    legality = {
        "legal": legal.legal,
        "reasons": legal.reasons,
        "details": legal.details,
        "special_slots": {describe_entry(DeckCard.parse(k), cards): s for k, s in legal.slots.items()},
    }
    pred = ctx.archetype.predict(entries)
    archetype = {"label": pred.label, "probability": pred.probability, "status": pred.status}

    ds = ctx.scorer.score(entries)
    key = deck_key(entries)
    # Battle data records hero cards as base when hero form is not observable,
    # so look the deck up under that observed key.
    obs_key = key if ctx.hero_observable else deck_key(
        [DeckCard(e.card_id, "base") if e.form == "hero" else e for e in entries])
    exact = ctx.test_deck_records.get(obs_key, (0, 0))
    score = {
        "meta_win_prob": round(ds.win_prob, 4),
        "interval": [round(ds.lo, 4), round(ds.hi, 4)],
        "interval_kind": (f"approx. {int(ds.interval * 100)}%: model uncertainty (sd {ds.sd_model:.3f}) + opponent sampling "
                          f"(sd {ds.sd_opponents:.3f}); excludes selection effects"),
        "opponent_decks": ds.n_opponents,
        "test_window": ctx.split.window("test"),
        "train_window": ctx.split.window("train"),
        "test_battles_total": len(ctx.split.test),
        "test_battles_exact_deck": exact[0],
        "test_wins_exact_deck": exact[1],
        "model": ctx.strength.name,
    }

    pairs = ctx.synergy.deck_pairs([e.card_id for e in entries])
    scored = pairs[pairs["status"] == "OK"].sort_values("synergy", ascending=False)
    top = [_pair_row(p, cards) for p in scored.head(3).to_dict("records")]
    bottom = [_pair_row(p, cards) for p in scored.iloc[3:].tail(3).iloc[::-1].to_dict("records")]  # never overlaps top
    n_insuff = int((pairs["status"] != "OK").sum())

    ws = structural_warnings(entries, cards, ctx.cfg["warnings"])
    dq: list[dict] = []
    if n_insuff:
        dq.append({"state": INSUFFICIENT_SAMPLE, "detail": f"{n_insuff} of {len(pairs)} pairs under {ctx.synergy.min_games} games: no synergy score"})
    unknown = [e.card_id for e in entries if e.card_id not in cards]
    if unknown:
        dq.append({"state": UNKNOWN_CARD, "detail": f"card ids {unknown} not in card table"})
    fu = [describe_entry(e, cards) for e in entries
          if not ctx.hero_observable and e.card_id in cards and (e.form == "hero" or (e.form == "base" and cards[e.card_id].has_hero))]
    if fu:
        dq.append({"state": FORM_UNKNOWN, "detail": "hero vs base form not distinguishable in battle data; strength for these uses combined data: " + ", ".join(fu)})
    seen_any = ctx.deck_appearances.get(obs_key, 0)
    if seen_any == 0:
        dq.append({"state": UNSEEN_DECK, "detail": "this exact deck never appears in the collected battles; the score is a model extrapolation from its cards"})
    low = [describe_entry(e, cards) for e in entries if not ctx.strength.known(e)]
    if low:
        dq.append({"state": LOW_CARD_DATA, "detail": f"under {ctx.strength.min_feature_games} train games, no learned weight: " + ", ".join(low)})

    return Explanation(
        deck=[describe_entry(e, cards) for e in entries],
        deck_key=key,
        legality=legality,
        archetype=archetype,
        score=score,
        synergy_top=top,
        synergy_bottom=bottom,
        synergy_insufficient_pairs=n_insuff,
        warnings=group_warnings(ws),
        data_quality=dq,
        objective=objective or {},
        source=ctx.paths.banner(),
        extra={"avg_elixir": avg_elixir(entries, cards)},
    )


def render_text(x: Explanation) -> str:
    s = x.score
    lines = [f"[{x.source}]", "Deck: " + ", ".join(x.deck)]
    lines.append(f"Legal: {x.legality['legal']}" + (f"  special slots: {x.legality['special_slots']}" if x.legality["special_slots"] else ""))
    if x.legality["reasons"]:
        lines.append("  reasons: " + "; ".join(x.legality["details"]))
    a = x.archetype
    lines.append(f"Archetype: {a['label']}" + (f" (p={a['probability']:.2f})" if a["probability"] is not None else " (no archetype labels yet)"))
    lines.append(
        f"Est. win rate vs test-window meta: {s['meta_win_prob']:.1%} "
        f"[{s['interval'][0]:.1%}, {s['interval'][1]:.1%}] ({s['interval_kind']})"
    )
    lines.append(
        f"  model {s['model']}, trained {s['train_window'][0]} to {s['train_window'][1]}; "
        f"test window {s['test_window'][0]} to {s['test_window'][1]} ({s['test_battles_total']} battles); "
        f"this exact deck in test: {s['test_battles_exact_deck']} battles, {s['test_wins_exact_deck']} wins"
    )
    if x.extra.get("avg_elixir") is not None:
        lines.append(f"Avg elixir: {x.extra['avg_elixir']:.2f}")
    lines.append("Top synergy pairs:" if x.synergy_top else "Top synergy pairs: none with enough games")
    for p in x.synergy_top:
        lines.append(f"  + {p['pair']}: {p['synergy']:+.3f} [{p['interval'][0]:+.3f}, {p['interval'][1]:+.3f}], lift {p['lift']}, {p['games']} games, shrunk wr {p['shrunk_wr']:.3f}")
    if x.synergy_bottom:
        lines.append("Bottom synergy pairs:")
        for p in x.synergy_bottom:
            lines.append(f"  - {p['pair']}: {p['synergy']:+.3f} [{p['interval'][0]:+.3f}, {p['interval'][1]:+.3f}], lift {p['lift']}, {p['games']} games, shrunk wr {p['shrunk_wr']:.3f}")
    if x.warnings:
        lines.append("Advisory warnings (do not block the deck):")
        for g in x.warnings:
            lines.append(f"  ! {g['root_cause']}: " + "; ".join(f"{w['message']} (rule {w['rule']}, observed {w['observed']})" for w in g["warnings"]))
    else:
        lines.append("Advisory warnings: none")
    for d in x.data_quality:
        lines.append(f"  [{d['state']}] {d['detail']}")
    if x.objective:
        lines.append(f"Objective: {x.objective}")
    return "\n".join(lines)


def explanations_frame(xs: list[Explanation]) -> pd.DataFrame:
    return pd.DataFrame([{
        "deck": ", ".join(x.deck), "archetype": x.archetype["label"],
        "win_prob": x.score["meta_win_prob"], "interval": x.score["interval"],
        "warnings": "; ".join(g["root_cause"] for g in x.warnings),
    } for x in xs])
