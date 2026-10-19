"""Generate notebooks/01..07 (clean, no outputs). Re-run after editing this file.

Every notebook reads CRDECK_DATA_SOURCE (default "real"). With no real data yet
they stop at the first data cell with a NoDataError that says what to run;
they never substitute synthetic data. To exercise them on synthetic data:
    CRDECK_DATA_SOURCE=synthetic python scripts/run_notebooks.py
"""

from __future__ import annotations

from pathlib import Path

import nbformat as nbf

ROOT = Path(__file__).resolve().parents[1]
NB = ROOT / "notebooks"

SETUP = '''import os
import json
import pandas as pd
pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 20)
pd.set_option("display.max_colwidth", 80)

DATA_SOURCE = os.environ.get("CRDECK_DATA_SOURCE", "real")  # "real" (default) or "synthetic"
from crdeck.config import Paths
paths = Paths.for_source(DATA_SOURCE)
print(paths.banner())'''

CTX = '''from crdeck.pipeline import load_context
ctx = load_context(DATA_SOURCE)  # raises NoDataError with instructions if data is missing; never substitutes
print(ctx.paths.banner())
ctx.split.describe()'''


def md(s):
    return nbf.v4.new_markdown_cell(s)


def code(s):
    return nbf.v4.new_code_cell(s)


NOTEBOOKS = {
    "01_cards.ipynb": [
        md("# 01 · Card table\n\nHand labels (`data/labels/cards.csv`) joined to the API `/cards` response by ID (spec §5).\n"
           "Roles are judgment calls that drive advisory warnings and features; they are not ground truth.\n"
           "The current labels are **drafts (`v0-draft`)**: review every row, then bump `label_version`."),
        code(SETUP),
        code('''from crdeck.cards import load_labels, ROLES
from crdeck.config import CARD_LABELS
labels = load_labels(CARD_LABELS)
print(len(labels), "labeled base cards; label versions:", labels["label_version"].unique().tolist())
labels[["name", "elixir", "card_type", "has_evolution", "has_hero", "is_champion", "is_win_condition", "roles", "targets"]].head(10)'''),
        md("## Rows that need your attention\nNotes mark draft labels the drafter was unsure about or cards it did not know."),
        code('''labels.loc[labels["notes"] != "", ["name", "card_type", "roles", "targets", "is_win_condition", "notes"]]'''),
        md("## Coverage of roles and forms"),
        code('''role_counts = pd.Series([r for rs in labels["roles_list"] for r in rs]).value_counts().reindex(sorted(ROLES), fill_value=0)
print(role_counts.to_string())
print()
print("with Evolution:", int(labels.has_evolution.sum()), "| with Hero:", int(labels.has_hero.sum()),
      "| champions:", int(labels.is_champion.sum()), "| win conditions:", int(labels.is_win_condition.sum()))'''),
        md("## Issues found in the source CSV (bootstrap report)"),
        code('''print((paths.root.parent / "labels" / "cards_label_report.md" if paths.is_synthetic else paths.root / "labels" / "cards_label_report.md").read_text(encoding="utf-8"))'''),
        md("## Join to API `/cards`\nNeeds `python -m crdeck build` (after the API gate). Lists labeled cards with no API match, API cards with no labels (these become `UNKNOWN_CARD` in battles), and values the API overrode."),
        code('''counts_file = paths.interim / "counts.json"
if not counts_file.exists():
    from crdeck.pipeline import NoDataError
    raise NoDataError(f"{counts_file} missing: run the gate (`python -m crdeck gate`) and `python -m crdeck build` first.")
counts = json.loads(counts_file.read_text())
print("\\n".join(counts["card_attach_report"]))'''),
    ],
    "02_rules.ipynb": [
        md("# 02 · Deck legality\n\n`crdeck.rules` is the only code that decides legality. Slot rules come from `config/deck_rules.yaml`.\n"
           "Unresolved rules (two champions? what the Wild slot accepts?) are config values, defaulting to the safe reading."),
        code(SETUP),
        code('''from crdeck.rules import DeckRules, DeckCard, check_deck, check_partial
from crdeck.cards import load_card_table
rules = DeckRules.load()
print(rules)
try:
    cards = load_card_table(paths.processed / "cards.parquet")
    print("card table: API ids from", paths.processed / "cards.parquet")
except FileNotFoundError:
    # Legality depends only on card flags, not on ids, so placeholder ids are fine for this demo.
    from crdeck.synthetic import synthetic_card_table
    cards = synthetic_card_table()
    print("card table: hand labels with PLACEHOLDER ids (no /cards response yet); fine for legality demos only")
C = lambda name, form="base": DeckCard(cards.by_name(name).card_id, form)'''),
        code('''base = ["Hog Rider", "Fireball", "The Log", "Ice Spirit", "Skeletons", "Cannon"]
examples = {
    "two evolutions + one hero": [C(n) for n in base[:5]] + [C("Archers", "evo"), C("Bats", "evo"), C("Musketeer", "hero")],
    "three evolutions": [C(n) for n in base[:5]] + [C("Archers", "evo"), C("Bats", "evo"), C("Zap", "evo")],
    "champion + evo + hero": [C(n) for n in base[:5]] + [C("Archer Queen"), C("Archers", "evo"), C("Knight", "hero")],
    "two champions": [C(n) for n in base] + [C("Archer Queen"), C("Golden Knight")],
    "same card base + evo": [C(n) for n in base] + [C("Knight"), C("Knight", "evo")],
    "nine cards": [C(n) for n in base] + [C("Knight"), C("Valkyrie"), C("Goblins")],
    "Hog Rider evolution (no such form)": [C(n) for n in base[1:]] + [C("Hog Rider", "evo"), C("Knight"), C("Valkyrie")],
}
rows = []
for name, d in examples.items():
    r = check_deck(d, cards, rules)
    rows.append({"case": name, "legal": r.legal, "reasons": ", ".join(r.reasons), "slots": {cards.name(DeckCard.parse(k).card_id) + ":" + DeckCard.parse(k).form: s for k, s in r.slots.items()}})
pd.DataFrame(rows)'''),
        md("`max_champions` is a config value; both settings are tested:"),
        code('''d = examples["two champions"]
print("max_champions=1:", check_deck(d, cards, rules).legal, "| max_champions=2:", check_deck(d, cards, rules.with_max_champions(2)).legal)
print(check_partial([C("Archer Queen"), C("Golden Knight"), C("Mighty Miner")], cards, rules).details)'''),
        md("## Do the rules match real play?\nThe slot rules are checked against every deck played in usable battles. "
           "Slots come from deck positions (observed: 0 = Evolution, 1 = Hero, 2 = Wild). "
           "Any deck the validator rejects means `config/deck_rules.yaml` disagrees with the game."),
        code('''from crdeck.evaluate import observed_deck_audit
try:
    audit = observed_deck_audit(paths, cards, rules)
except FileNotFoundError as e:
    audit = None
    print("No collected battles yet:", e)
if audit:
    print("distinct decks:", audit["distinct_decks"], "| rejected by validator:", audit["rejected_by_validator"] or "none")
    print("champion slots:", audit["champion_slots"], "| evo slots:", audit["evo_slots"], "| hero slots:", audit["hero_slots"])
    print("base cards in special slots:", audit["base_cards_in_special_slots"])
    display(audit["combinations"])'''),
        md("## Legality tests"),
        code('''import subprocess, sys
from crdeck.config import PROJECT_ROOT
out = subprocess.run([sys.executable, "-m", "pytest", "-q", str(PROJECT_ROOT / "tests" / "test_rules.py")], capture_output=True, text=True)
print(out.stdout[-600:])
assert out.returncode == 0, "legality tests failing: do not move on (spec 11)"'''),
    ],
    "03_data.ipynb": [
        md("# 03 · Data: collection, parsing, dedupe, sanity counts\n\n"
           "Collection (needs `CR_API_KEY` in `.env`, key registered for your current IP):\n"
           "```\npython -m crdeck gate      # /cards, leaderboard, one battle log -> fill docs/api-notes.md\npython -m crdeck collect   # top players' logs for config window (cached; resumable)\npython -m crdeck build     # raw + labels -> data/interim\n```\n"
           "This notebook only reads what `build` produced. If the API failed or nothing was collected, it says so and stops."),
        code(SETUP),
        code('''from crdeck.pipeline import load_interim
battles, dib, decks, counts = load_interim(paths)
print(json.dumps({k: v for k, v in counts.items() if k != "card_attach_report"}, indent=1, default=str))'''),
        md("## Status counts\n`OK` battles feed the models. Mirrors and draws are stored but excluded; `UNKNOWN_CARD` battles wait for labels."),
        code('''pd.Series(counts["status"]).rename("battles").to_frame()'''),
        code('''if counts["unknown_card_ids"]:
    print("Card ids missing from the label table (add them to data/labels/cards.csv):", counts["unknown_card_ids"])
else:
    print("No unknown cards.")'''),
        md("## Battles per day (UTC) and battle types"),
        code('''ok = battles[battles.status == "OK"].copy()
ok["day"] = pd.to_datetime(ok["battle_time"]).dt.strftime("%Y-%m-%d")
print(ok.groupby("day").size().to_string())
print(battles["battle_type"].value_counts().to_string())'''),
        md("## Sanity checks"),
        code('''assert battles["battle_key"].is_unique, "duplicate battles after dedupe"
assert (dib.groupby("battle_key").size() == 2).all()
print("battles after dedupe:", len(battles), "| duplicates removed:", counts["duplicates_removed"])
print("distinct decks:", len(decks), "| decks seen once:", int((decks.appearances == 1).sum()))
print("decks with hero-capable cards in unknown form:", int(decks.form_unknown.sum()))
lg = dib["level_deficit"].dropna()
print("per-side mean level deficit (maxLevel - level): ", lg.describe().round(2).to_dict())'''),
    ],
    "04_baselines.ipynb": [
        md("# 04 · Time split and baselines\n\nSplit by time, never randomly (spec §9.4): train on the earliest 70%, select models on the next 15%, test on the last 15%.\n"
           "Baselines: always 50%, and \"the more popular deck wins\"."),
        code(SETUP),
        code(CTX),
        code('''comp = ctx.model_comparison
comp[comp.model.isin(["constant_0.5", "popularity"])]'''),
        md("Any model below has to beat both of these on held-out log loss and AUC."),
    ],
    "05_models.ipynb": [
        md("# 05 · Models: synergy, strength, archetype\n\nAll fit on train (+ valid for the final refit); every number below is checked on the later test window."),
        code(SETUP),
        code(CTX),
        md("## Pair synergy (spec §7.1)\nEvery score comes with lift, games and an interval. Pairs under `min_games` are `INSUFFICIENT_SAMPLE` and have no score.\n"
           "High synergy means \"won together more than expected\" in this data, **not** a proven combo: cards in the same popular deck share credit."),
        code('''syn = ctx.synergy
name = ctx.cards.name
p = syn.pairs.copy()
p["pair"] = [f"{name(a)} + {name(b)}" for a, b in zip(p.card_i, p.card_j)]
print("expected_from:", syn.expected_from, "| k:", syn.k, "| min_games:", syn.min_games, "| global wr:", round(syn.global_wr, 4))
print(p.status.value_counts().to_string())
cols = ["pair", "synergy", "lo", "hi", "lift", "games", "shrunk_wr", "expected_wr"]
scored = p[p.status == "OK"].sort_values("synergy", ascending=False)
pd.concat([scored.head(10), scored.tail(5)])[cols].round(4)'''),
        md("### Which \"expected win rate\"?\nThe spec's literal reading (`marginal`) uses each card's overall win rate. When two cards nearly always appear together, "
           "that rate already contains the pair's effect, so the bonus is counted twice and real synergies look negative. "
           "`without_partner` compares against games where each card appears *without* the other. "
           "With `expected_from: auto` the variant is chosen on the validation window:"),
        code('''ctx.synergy_choice'''),
        md("Held-out comparison on the test window (the variant was fixed before this was computed):"),
        code('''from crdeck.evaluate import synergy_eval
synergy_eval(ctx)'''),
        code('''if ctx.paths.is_synthetic:
    truth = json.loads((ctx.paths.root / "truth.json").read_text())
    rows = []
    for t in truth["planted_synergy"]:
        r = syn.pair(t["a_id"], t["b_id"])
        rows.append({"pair": f"{t['a']} + {t['b']}", "planted log-odds bonus": t["bonus"], "estimated synergy": r["synergy"], "lo": r["lo"], "hi": r["hi"], "games": r["games"]})
    print("SYNTHETIC check: planted pairs vs estimates")
    display(pd.DataFrame(rows).round(3))
else:
    print("Real data: no planted truth to compare against.")'''),
        md("## Deck strength (spec §7.2)\nLogistic regression on card:form one-hot differences; L2 strength picked on validation log loss. "
           "The pair-feature model is kept only if it beats the card model on validation. With `skill_control`, the players' "
           "rating difference is a separate covariate, so card weights are estimated at equal rating. `rating_only` shows how much "
           "is skill rather than deck."),
        code('''ctx.model_comparison.round(4)'''),
        md("Is each difference from a baseline more than resampling noise? Paired bootstrap over test battles "
           "(negative delta = model better):"),
        code('''from crdeck.evaluate import strength_significance
strength_significance(ctx).round(5)'''),
        code('''w = pd.Series(ctx.strength.card_weights)
games = pd.Series({k: ctx.strength.feature_games[k] for k in w.index})
def label(k):
    cid, form = k.split(":")
    return name(int(cid)) + ("" if form == "base" else f" ({form})")
tab = pd.DataFrame({"card": [label(k) for k in w.index], "weight (log-odds)": w.values, "train games": games.values})
print("Strongest and weakest card forms (conditional on everything else in the deck; confounded by player skill)")
pd.concat([tab.sort_values("weight (log-odds)", ascending=False).head(8), tab.sort_values("weight (log-odds)").head(5)]).round(3)'''),
        md("### Level gaps (documented confounder)"),
        code('''from crdeck.evaluate import level_gap_check
level_gap_check(ctx)'''),
        md("## Archetypes (spec §7.3)\nLabels live in the archetype label file. Label the 20 held-out decks **before** fitting anything. "
           "Below 0.5 top probability, the output is `HYBRID / UNCERTAIN`."),
        code('''from crdeck.evaluate import archetype_eval
labs = ctx.archetype_labels
print("label file:", ctx.paths.archetype_labels, "| rows:", 0 if labs is None else len(labs))
if labs is not None and len(labs):
    print(labs.groupby(["split", "archetype"]).size().unstack(fill_value=0))
archetype_eval(ctx)'''),
        md("Clustering is used only to pick decks worth labeling:"),
        code('''from crdeck.archetype import suggest_decks_to_label
ac = ctx.cfg["archetype"]
done = set(labs["deck_key"]) if labs is not None else set()
work = suggest_decks_to_label(ctx.decks, ctx.cards, ac["n_clusters"], 2, ctx.cfg["seed"], done)
work[["cluster", "appearances", "cards"]].head(12)'''),
    ],
    "06_search.ipynb": [
        md("# 06 · Completion and swaps (spec §7.4)\n\nBeam search over legal partial decks (legality only from `crdeck.rules`). Objective, with weights from config:\n\n"
           "`meta_win_prob + synergy_weight · mean_pair_synergy + cooccurrence_weight · mean_log_lift`\n\n"
           "The co-occurrence term (do players actually pair these cards?) is tuned for completion recall on the **validation** window only."),
        code(SETUP),
        code(CTX),
        code('''from crdeck.evaluate import tune_cooccurrence, choose_cooccurrence
tuning = tune_cooccurrence(ctx)
chosen = choose_cooccurrence(tuning)
print("config cooccurrence_weight:", ctx.cfg["search"]["cooccurrence_weight"], "| chosen on validation:", chosen)
tuning'''),
        md("If the chosen value differs from `config/model.yaml`, update the config (it is a starting value tuned on synthetic data)."),
        md("## Completion recall@10 on held-out decks (test window)\nMask 2 cards from frequent test-window decks; does the model's ranked fill contain them? Baseline: most popular cards."),
        code('''from crdeck.evaluate import completion_recall
w = chosen if chosen is not None else ctx.cfg["search"]["cooccurrence_weight"]
completion_recall(ctx, n_decks=100, cooccurrence_weight=w)'''),
        md("## Swaps\nFor each non-seed card, the top legal replacements with the objective change and the pair evidence."),
        code('''from crdeck.search import Searcher, parse_seed
s = Searcher(ctx, w)
seed = [parse_seed("Golem", ctx.cards)]
deck = s.complete(seed)[0]
print([s._name(e) for e in deck.entries])
pd.DataFrame(s.swaps(deck.entries, locked=seed)).drop(columns=["new_deck_key"]).head(12)'''),
    ],
    "07_demo.ipynb": [
        md("# 07 · Signature demonstration\n\nPick Hog Rider → three legal decks, each with archetype, estimated win rate (with sample size and uncertainty), "
           "top synergy pairs with evidence, and advisory warnings. Then swap a card and watch the score and warnings recompute.\n\n"
           "Estimated win rates describe top-player battles in the sampled window. They are not a promise about your games, and the top result of a search tends to be optimistic."),
        code(SETUP),
        code(CTX),
        code('''from crdeck.search import Searcher, parse_seed
from crdeck.explain import build_explanation, render_text, explanations_frame
searcher = Searcher(ctx)
seeds = [parse_seed("Hog Rider", ctx.cards)]
results = searcher.complete(seeds)
explanations = [build_explanation(d.entries, ctx, searcher.objective_dict(d)) for d in results]
explanations_frame(explanations)'''),
        code('''for i, x in enumerate(explanations, 1):
    print(f"=== Deck {i} ===")
    print(render_text(x))
    print()'''),
        md("## Swap a card\nTake the best suggested swap for deck 1 and recompute everything."),
        code('''from crdeck.rules import parse_deck_key
deck = results[0]
swaps = searcher.swaps(deck.entries, locked=seeds)
best = max(swaps, key=lambda s_: s_["delta_objective"])
print(f"Swap {best['replace']} -> {best['with']}: objective {best['delta_objective']:+.4f}, win prob {best['delta_win_prob']:+.4f}; {best['reason']}")
new_entries = parse_deck_key(best["new_deck_key"])
before, after = explanations[0], build_explanation(new_entries, ctx, searcher.objective_dict(searcher.evaluate(new_entries)))
print()
print(render_text(after))'''),
        code('''pd.DataFrame({
    "before": [before.score["meta_win_prob"], before.score["interval"], "; ".join(g["root_cause"] for g in before.warnings) or "none"],
    "after": [after.score["meta_win_prob"], after.score["interval"], "; ".join(g["root_cause"] for g in after.warnings) or "none"],
}, index=["meta win prob", "interval", "warnings"])'''),
        md("## Full explanation object\nEverything above comes from this structure (spec §8)."),
        code('''json.loads(json.dumps(explanations[0].to_dict(), default=str))'''),
    ],
}


def main() -> None:
    NB.mkdir(exist_ok=True)
    for name, cells in NOTEBOOKS.items():
        nb = nbf.v4.new_notebook()
        nb["cells"] = cells
        nb["metadata"]["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
        nbf.write(nb, NB / name)
        print("wrote", NB / name)


if __name__ == "__main__":
    main()
