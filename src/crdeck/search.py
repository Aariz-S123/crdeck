"""Deck completion (beam search) and swap suggestions (spec section 7.4).

Legality comes only from crdeck.rules: partial decks are pruned with
check_partial, and every returned deck passes check_deck (asserted).

Objective (weights from config/model.yaml, reported with each result):
  objective = meta_win_prob + synergy_weight * mean_pair_synergy
                            + cooccurrence_weight * mean_log_lift
mean_pair_synergy averages only pairs with enough games (0 if none).
mean_log_lift (smoothed, all pairs) rewards card combinations players actually
use; its weight is tuned for completion recall on the validation window, never
on the test window (see evaluate.tune_cooccurrence).
"""

from __future__ import annotations

from dataclasses import dataclass

from .cards import CardTable
from .explain import has_win_condition
from .rules import DeckCard, check_deck, check_partial, deck_key


class SeedError(ValueError):
    """The seed cards cannot be part of any legal deck, or no completion exists."""


@dataclass
class ScoredDeck:
    entries: list[DeckCard]
    objective: float
    win_prob: float
    mean_synergy: float
    n_scored_pairs: int
    mean_log_lift: float = 0.0

    @property
    def key(self) -> str:
        return deck_key(self.entries)

    def objective_dict(self, weight: float, co_weight: float = 0.0) -> dict:
        return {
            "objective": round(self.objective, 5),
            "formula": f"meta_win_prob + {weight} * mean_pair_synergy + {co_weight} * mean_log_lift",
            "meta_win_prob": round(self.win_prob, 5),
            "mean_pair_synergy": round(self.mean_synergy, 5),
            "scored_pairs": self.n_scored_pairs,
            "mean_log_lift": round(self.mean_log_lift, 5),
        }


def parse_seed(text: str, cards: CardTable) -> DeckCard:
    """'Hog Rider', 'Knight@evo', 'Knight@hero' -> DeckCard."""
    name, _, form = text.partition("@")
    form = (form or "base").strip().lower()
    form = {"evolution": "evo", "evolved": "evo"}.get(form, form)
    return DeckCard(cards.by_name(name.strip()).card_id, form)


class Searcher:
    def __init__(self, ctx, cooccurrence_weight: float | None = None):
        self.ctx = ctx
        self.cards: CardTable = ctx.cards
        self.rules = ctx.rules
        self.cfg = ctx.cfg["search"]
        self.weight = float(self.cfg["synergy_weight"])
        self.co_weight = float(self.cfg["cooccurrence_weight"] if cooccurrence_weight is None else cooccurrence_weight)
        self.candidates = self._candidates()

    def _candidates(self) -> list[DeckCard]:
        """Card forms with enough training data to have a learned weight."""
        out = []
        min_games = int(self.cfg["min_card_games"])
        for cid in self.cards.ids:
            for form in self.cards[cid].allowed_forms():
                e = DeckCard(cid, form)
                if form == "hero" and not self.ctx.hero_observable:
                    # Strength cannot tell hero from base; offer hero only via the base entry.
                    continue
                if self.ctx.strength.known(e) and self.ctx.strength.games(e) >= min_games:
                    out.append(e)
        return out

    def evaluate(self, entries: list[DeckCard]) -> ScoredDeck:
        u = self.ctx.strength.utility(entries)
        wp = self.ctx.scorer.win_prob_from_u(u)
        ids = [e.card_id for e in entries]
        syn, n = self.ctx.synergy.mean_synergy(ids)
        ll = self.ctx.synergy.mean_log_lift(ids) if self.co_weight else 0.0
        return ScoredDeck(sorted(entries), wp + self.weight * syn + self.co_weight * ll, wp, syn, n, ll)

    def objective_dict(self, d: ScoredDeck) -> dict:
        return d.objective_dict(self.weight, self.co_weight)

    def complete(self, seeds: list[DeckCard], n_results: int | None = None, beam_width: int | None = None) -> list[ScoredDeck]:
        n_results = n_results or int(self.cfg["n_results"])
        width = beam_width or int(self.cfg["beam_width"])
        size = self.rules.deck_size
        seeds = list(dict.fromkeys(seeds))
        if len(seeds) > size:
            raise SeedError(f"{len(seeds)} seed cards; a deck has {size}")
        res = check_partial(seeds, self.cards, self.rules)
        if not res.legal:
            raise SeedError("seed cards cannot form a legal deck: " + "; ".join(res.details))

        # Each parent may contribute at most `per_parent` children per step, so the
        # beam keeps several lineages instead of 50 near-copies of one deck.
        per_parent = max(2, width // int(self.cfg.get("beam_parents_min", 10)))
        beam = [self.evaluate(seeds)] if seeds else [ScoredDeck([], 0.0, 0.0, 0.0, 0)]
        nxt: list[ScoredDeck] = []
        for _ in range(size - len(seeds)):
            seen: set[str] = set()
            children: list[tuple[int, ScoredDeck]] = []
            for pi, d in enumerate(beam):
                ids = {e.card_id for e in d.entries}
                for c in self.candidates:
                    if c.card_id in ids:
                        continue
                    new = d.entries + [c]
                    k = deck_key(new)
                    if k in seen:
                        continue
                    seen.add(k)
                    if not check_partial(new, self.cards, self.rules).legal:
                        continue
                    children.append((pi, self.evaluate(new)))
            if not children:
                raise SeedError("no legal completion exists for these seeds with the current candidate cards")
            children.sort(key=lambda t: (-t[1].objective, t[1].key))
            nxt = [d for _, d in children]
            taken: dict[int, int] = {}
            beam = []
            for pi, d in children:
                if taken.get(pi, 0) < per_parent:
                    beam.append(d)
                    taken[pi] = taken.get(pi, 0) + 1
                if len(beam) == width:
                    break

        # Final selection draws on the whole last expansion, not just the beam.
        final = [d for d in nxt if check_deck(d.entries, self.cards, self.rules).legal]
        if self.cfg.get("require_win_condition"):
            final = [d for d in final if has_win_condition(d.entries, self.cards)]
        if not final:
            raise SeedError("search produced no legal deck satisfying the hard filters")
        chosen: list[ScoredDeck] = []
        min_diff = int(self.cfg["min_diff_cards"])
        for d in final:
            ids = {e.card_id for e in d.entries}
            if all(len(ids - {e.card_id for e in c.entries}) >= min_diff for c in chosen):
                chosen.append(d)
            if len(chosen) == n_results:
                break
        for d in chosen:  # invariant: never output an illegal deck
            assert check_deck(d.entries, self.cards, self.rules).legal, d.entries
        return chosen

    def swaps(self, entries: list[DeckCard], top: int | None = None, locked: list[DeckCard] | None = None) -> list[dict]:
        """For each card, the best legal replacements and the objective change, with the pair reason."""
        top = top or int(self.cfg["top_swaps"])
        locked_ids = {e.card_id for e in (locked or [])}
        entries = sorted(entries)
        base = self.evaluate(entries)
        out = []
        for i, old in enumerate(entries):
            if old.card_id in locked_ids:
                continue
            rest = entries[:i] + entries[i + 1:]
            rest_ids = {e.card_id for e in rest}
            options = []
            for c in self.candidates:
                if c.card_id in rest_ids or c == old:
                    continue
                new = rest + [c]
                if not check_deck(new, self.cards, self.rules).legal:
                    continue
                s = self.evaluate(new)
                options.append((s.objective - base.objective, c, s, new))
            options.sort(key=lambda t: (-t[0], t[1]))
            for delta, c, s, new in options[:top]:
                out.append({
                    "replace": self._name(old), "with": self._name(c), "new_deck_key": deck_key(new),
                    "delta_objective": round(delta, 5),
                    "delta_win_prob": round(s.win_prob - base.win_prob, 5),
                    "new_objective": round(s.objective, 5), "reason": self._pair_reason(old, c, rest),
                })
        return out

    def _name(self, e: DeckCard) -> str:
        n = self.cards.name(e.card_id)
        return n if e.form == "base" else f"{n} ({'Evolution' if e.form == 'evo' else 'Hero'})"

    def _pair_reason(self, old: DeckCard, new: DeckCard, rest: list[DeckCard]) -> str:
        syn = self.ctx.synergy
        gained, lost = [], []
        for e in rest:
            for card, bucket in ((new, gained), (old, lost)):
                p = syn.pair(card.card_id, e.card_id)
                if p and p["status"] == "OK":
                    bucket.append((p["synergy"], f"{self.cards.name(card.card_id)}+{self.cards.name(e.card_id)}", int(p["games"])))
        parts = []
        if gained:
            g = max(gained)
            parts.append(f"gains {g[1]} ({g[0]:+.3f}, {g[2]} games)")
        if lost:
            worst = max(lost)
            parts.append(f"loses {worst[1]} ({worst[0]:+.3f}, {worst[2]} games)")
        return "; ".join(parts) if parts else "no pair with enough games; change comes from card strength"
