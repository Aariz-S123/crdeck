"""Build docs/crdeck-documentation.docx. Every number and code snippet is read from the project's own files.

    pip install python-docx        # once (not a project dependency)
    python scripts/make_docs.py    # after an export, so the numbers are current
"""
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from docx import Document  # noqa: E402
from docx.enum.table import WD_TABLE_ALIGNMENT  # noqa: E402
from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402
from docx.oxml import OxmlElement  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from docx.shared import Pt, RGBColor, Cm  # noqa: E402

ROOT = Path(r"C:\Users\simty\crdeck")
INDEX = json.loads((ROOT / "web" / "modes.json").read_text(encoding="utf-8"))
RANKED = json.loads((ROOT / "web" / "models" / "ranked.json").read_text(encoding="utf-8"))
EV = RANKED["evaluation"]
BUILD = INDEX["log"]["build"]
MODES = INDEX["modes"]

INK = RGBColor(0x17, 0x20, 0x2F)
ACCENT = RGBColor(0xA8, 0x24, 0x7F)
MUTED = RGBColor(0x56, 0x61, 0x76)

n = lambda x: f"{int(x):,}"  # noqa: E731
pct = lambda x, d=1: f"{100 * x:.{d}f}%"  # noqa: E731


def git(*a):
    return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True).stdout.strip()


def lines(p):
    return sum(1 for _ in open(p, encoding="utf-8"))


doc = Document()
sec = doc.sections[0]
sec.left_margin = sec.right_margin = Cm(2.2)
sec.top_margin = sec.bottom_margin = Cm(2.0)

st = doc.styles
st["Normal"].font.name = "Calibri"
st["Normal"].font.size = Pt(10.5)
st["Normal"].font.color.rgb = INK
st["Normal"].paragraph_format.space_after = Pt(6)
st["Normal"].paragraph_format.line_spacing = 1.15
for name, size in (("Title", 26), ("Heading 1", 17), ("Heading 2", 13), ("Heading 3", 11.5)):
    s = st[name]
    s.font.name = "Calibri"
    s.font.size = Pt(size)
    s.font.bold = True
    s.font.color.rgb = INK if name != "Heading 1" else ACCENT
st["Heading 1"].paragraph_format.space_before = Pt(18)
st["Heading 2"].paragraph_format.space_before = Pt(12)


def shade(cell, hexcolor):
    tcPr = cell._tc.get_or_add_tcPr()
    sh = OxmlElement("w:shd")
    sh.set(qn("w:val"), "clear")
    sh.set(qn("w:color"), "auto")
    sh.set(qn("w:fill"), hexcolor)
    tcPr.append(sh)


def table(head, rows, widths=None, small=True):
    t = doc.add_table(rows=1, cols=len(head))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    for i, h in enumerate(head):
        c = t.rows[0].cells[i]
        c.text = ""
        r = c.paragraphs[0].add_run(h)
        r.bold = True
        r.font.size = Pt(9.5 if small else 10.5)
        shade(c, "E8ECF2")
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            r = cells[i].paragraphs[0].add_run(str(v))
            r.font.size = Pt(9.5 if small else 10.5)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)
    doc.add_paragraph()
    return t


def p(text, bold_lead=None, muted=False, size=None):
    para = doc.add_paragraph()
    if bold_lead:
        r = para.add_run(bold_lead + " ")
        r.bold = True
    r = para.add_run(text)
    if muted:
        r.font.color.rgb = MUTED
    if size:
        r.font.size = Pt(size)
    return para


def bullets(items, style="List Bullet"):
    for it in items:
        para = doc.add_paragraph(style=style)
        if isinstance(it, tuple):
            r = para.add_run(it[0] + " ")
            r.bold = True
            para.add_run(it[1])
        else:
            para.add_run(it)


def code(text):
    para = doc.add_paragraph()
    para.paragraph_format.left_indent = Cm(0.5)
    r = para.add_run(text)
    r.font.name = "Consolas"
    r._element.rPr.rFonts.set(qn("w:eastAsia"), "Consolas")
    r.font.size = Pt(9.5)
    return para


# ------------------------------------------------------------------ title
t = doc.add_paragraph(style="Title")
t.add_run("crdeck: a Clash Royale deck builder that learns from real battles")
p(f"Project documentation · {date.today().strftime('%d %B %Y')} · code version {git('rev-parse', '--short', 'HEAD')} "
  f"({git('log', '-1', '--format=%cd', '--date=short')})", muted=True)
p("A solo learning project. Not affiliated with, endorsed by or sponsored by Supercell. Battle data comes from the "
  "official Clash Royale API.", muted=True, size=9.5)

# ------------------------------------------------------------------ 1 goal
doc.add_heading("1. What the project is for", 1)
p("crdeck is a personal deck-building assistant. You give it 0 to 3 cards you want to play, and it returns three legal "
  "8-card decks built around them. For each deck it names the style (archetype), estimates how often the deck wins "
  "against the decks top players use, shows which cards and card pairs carry that estimate, warns about weaknesses, and "
  "suggests swaps. Every number comes with its evidence and its uncertainty.")
p("The project's own specification (docs/spec.md) sets the promise and the limits:")
bullets([
    ("Legality is a hard rule.", "An illegal deck is never shown. Everything else, such as a missing air defense or a "
     "high elixir cost, is a warning that never blocks a deck."),
    ("Win rates describe top players.", "An estimate describes battles in the collected window, at equal player rating. "
     "It is not a promise about anyone's own games."),
    ("Synergy is a pattern, not proof.", "Two cards that won together more than expected in the data are not proven to be a combo."),
    ("It is a learning project.", "Sites like RoyaleAPI already offer meta decks. The point here is a careful, checkable "
     "implementation: real data, time-based testing, simple baselines and stated assumptions."),
])
doc.add_heading("Ground rules the project follows", 2)
bullets([
    ("No made-up numbers.", "Every number, chart point and log line on the site is computed from official API data, "
     "the project's labels, or pipeline output derived from them."),
    ("Time-based splits only.", "Models train on older battles, pick settings on newer ones, and are tested on the "
     "newest ones. Nothing is split at random."),
    ("One place decides legality.", "Only src/crdeck/rules.py decides whether a deck is legal. The website's JavaScript "
     "copy is checked against it on every export."),
    ("Synthetic data never stands in for real data.", "Generated test data lives in its own folder and is labeled SYNTHETIC everywhere."),
    ("Secrets stay local.", "The API key lives only in .env, which git ignores. It is never printed or committed."),
    ("Assumptions are written down.", "Each modeling assumption is stated next to its result, on the site and in "
     "docs/model-notes.md, with what it would take to test it."),
])

# ------------------------------------------------------------------ 2 overview
doc.add_heading("2. How it works, end to end", 1)
p("The project is a pipeline. Each step writes files the next step reads, so any step can be re-run on its own.")
table(["Step", "Command", "What it does"], [
    ["1. Collect", "python -m crdeck collect --window auto", "Fetches battle logs of top Path of Legends players from the official API and caches every response under data/raw/."],
    ["1b. Collect arenas", "python -m crdeck collect --arenas --window auto", "Finds players in every Trophy Road arena through clan search, then fetches their battle logs (kept apart, in battlelog_arena/)."],
    ["2. Build", "python -m crdeck build", "Parses the raw logs into tables of battles, decks and cards, removes duplicates, and tags each battle's mode, league or arena, and sample."],
    ["3. Evaluate", "python -m crdeck evaluate", "Trains the models on a time split and scores them on held-out battles against simple baselines."],
    ["4. Export", "python scripts/export_web.py", "Writes one model file per mode, league and arena for the website, plus Python's own answers for checking."],
    ["5. Check", "node scripts/check_web_engine.mjs", "Confirms the website's JavaScript engine gives the same legality, decks, scores and swaps as Python."],
    ["6. Sweep", "node scripts/sweep_web_engine.mjs", "Seeds the engine with every card form and checks every result for legal, distinct decks and explanations that add up."],
], widths=[2.6, 5.4, 9.0])

# ------------------------------------------------------------------ 3 data
doc.add_heading("3. The data", 1)
p(f"All battles come from the official Clash Royale API. After removing battles seen in more than one player's log, "
  f"the project holds {n(BUILD['battles_after_dedupe'])} battles ({n(BUILD['duplicates_removed'])} duplicates removed) from "
  f"{n(BUILD['files'])} raw files, with {n(BUILD['distinct_decks'])} different decks. Battles run from "
  f"{BUILD['first_battle'][:10]} to {BUILD['last_battle'][:16]} UTC.")
doc.add_heading("Collection runs", 2)
table(["Window", "Battle logs", "Files", "First fetch (UTC)", "Last fetch (UTC)"],
      [[w["window_id"], n(w["battle_logs"]), n(w["files"]), w["first_fetch"][:16].replace("T", " "), w["last_fetch"][:16].replace("T", " ")]
       for w in sorted(BUILD["windows"], key=lambda w: w["first_fetch"])], widths=[2.8, 2.6, 2.2, 4.4, 4.4])
p("Battle logs counts only leaderboard players' logs; the 2026-10-20 window holds the arena sample's logs and clan lookups.", muted=True, size=9.5)
doc.add_heading("Modes, leagues and arenas", 2)
p("Each battle's mode comes from its type, game mode and deck selection. Only battles where players used their own deck count:")
bullets([
    ("Ranked (Path of Legends):", "type pathOfLegend. Split by league, read from each battle's leagueNumber (Master I to Ultimate Champion)."),
    ("Trophy Road:", "type trail or PvP with game mode Ladder. Split by arena, read from each battle's arena name (Goblin Stadium to the Seasonal Arenas)."),
    ("All modes:", "both together."),
    ("Not modeled:", "events, draft modes, friendlies, clan war, 2v2 and tournaments, because their decks are not the player's choice or the rules differ."),
])
p("League names, arena order and arenas' trophy floors were supplied by the project owner. They only order the site's "
  "picker and aim the arena collector; a battle's group always comes from the battle itself.")
p("Two samples of players feed the data. The leaderboard sample is top Path of Legends players from the global and 12 "
  "country leaderboards. The arena sample is up to 400 players per arena, found by searching clans by common name words "
  "and reading their member lists, where each member's record names their arena.")
groups = [m for m in MODES if m.get("group")]
table(["Mode", "League or arena", "Usable battles", "On the site"],
      [[("Ranked" if m["mode"] == "ranked" else "Trophy Road"), m["group"], n(m["ok_battles"]),
        "own model" if m["status"] == "exported" else "listed, too few to test"] for m in groups],
      widths=[2.6, 5.4, 3.2, 4.6])

# ------------------------------------------------------------------ 4 models
doc.add_heading("4. The models, in plain words", 1)
s = RANKED["config"]["search"]
doc.add_heading("Deck strength (which deck wins)", 2)
chosen = [r for r in EV["strength"] if r.get("selected")][0]["model"]
p("A logistic regression learns one weight for every card form (base, Evolution and Hero are separate). A deck's strength "
  "is the sum of its weights; the chance that deck A beats deck B is the sigmoid of the difference. The two players' rating "
  "difference is included as an extra input, so card weights describe decks at equal player skill. A second version also "
  "learns weights for the 100 most common card pairs. The validation battles decide which version each mode uses and how "
  f"strongly the weights are pulled toward zero. For Ranked they chose {'the cards-only version' if 'pairs' not in chosen else 'the version with pairs'} ({chosen}).")
doc.add_heading("Synergy (which cards work together)", 2)
p("For every pair of cards, synergy compares how often the pair won together with what each card wins on its own. "
  "Pairs with few games are pulled toward the average (shrinkage), and pairs under the minimum number of games get no score. "
  "Lift measures how much more often two cards appear together than chance would predict.")
doc.add_heading("Win-rate estimate for one deck", 2)
import yaml  # noqa: E402
DS = yaml.safe_load((ROOT / "config" / "model.yaml").read_text(encoding="utf-8"))["deck_score"]
p(f"A deck is played against {n(DS['n_opponent_decks'])} opponent decks sampled from the "
  "test window, at equal rating. The average is the estimated win rate; a bootstrap gives its 90% range.")
doc.add_heading("Building decks (search)", 2)
p(f"A beam search starts from your picks and adds cards one at a time, keeping the best {s['beam_width']} partial decks at each "
  "step and pruning any partial deck that can no longer be legal. Decks are ranked by:")
code(f"score = estimated win rate + {s['synergy_weight']} × mean pair synergy + {s['cooccurrence_weight']} × how often the cards are played together")
p(f"It returns {s['n_results']} decks that differ by at least {s['min_diff_cards']} cards. Swap suggestions try every legal "
  "replacement for each card and rank them by the change in score, split into its parts so each suggestion can be explained.")
doc.add_heading("Deck style (archetype)", 2)
arch = RANKED["archetype"]
p(f"A small classifier assigns one of {len(arch['classes'])} styles ({', '.join(arch['classes'])}) from a deck's card roles. "
  f"Below {int(arch['threshold'] * 100)}% confidence it says the deck is a mixed style. Its training labels were drafted by "
  "the project's assistant, so its accuracy means agreement with that labeler.")
doc.add_heading("Deck checks (warnings)", 2)
p("Advisory checks look for a win condition, air defense, spells and a workable average elixir cost. They never block a deck.")
doc.add_heading("Meta history and forecast", 2)
ms = INDEX["meta"]["status"]
p("The site tracks how card usage among top ranked players changes between collection runs, with 90% ranges. A Monte "
  "Carlo forecast of the next period is built in but stays hidden until it has been backtested and beats “no change”. "
  f"That needs at least {ms['min_periods']} collection periods; the project has {ms['periods']}. Only leaderboard players "
  "count here, so adding arena players can't look like a meta shift.")

# ------------------------------------------------------------------ 5 results
doc.add_heading("5. How well it works (Ranked, held-out battles)", 1)
sp = {x["part"]: x for x in EV["splits"]}
p(f"Trained on {n(sp['train']['battles'])} battles ({sp['train']['from']} to {sp['train']['to']}), settings chosen on "
  f"{n(sp['valid']['battles'])}, tested on the newest {n(sp['test']['battles'])} ({sp['test']['from']} to {sp['test']['to']}). "
  "Every result has a 90% bootstrap range and is compared with a simple baseline.")
sel = [r for r in EV["strength_intervals"] if r.get("selected")][0]
sig = {r["vs"]: r for r in EV["strength_significance"]}
comp, ar = EV["completion"], EV["archetype"]
syn = {r["score"]: r for r in EV["synergy"]}
used = [r for r in EV["synergy"] if "used" in r["score"]][0]
rng = lambda a, d=3: f"{a[0]:.{d}f} to {a[1]:.{d}f}"  # noqa: E731
verdict_strength = "Beats every baseline" if all(r["ci90_hi"] < 0 for r in EV["strength_significance"]) else "Not clearly better than every baseline"
table(["Check", "Result (90% range)", "Compared with", "Verdict"], [
    ["Picking the winner of a battle", f"AUC {sel['test_auc']:.3f} ({rng(sel['auc_ci90'])})",
     "Coin flip 0.500; player rating alone " + f"{[r for r in EV['strength'] if r['part'] == 'test' and r['model'] == 'rating_only'][0]['auc']:.3f}",
     verdict_strength],
    ["Finishing a deck (2 hidden cards in the top 10)", f"{pct(comp['recall_model'], 0)} ({pct(comp['recall_model_ci90'][0], 1)} to {pct(comp['recall_model_ci90'][1], 1)}) on {comp['decks_evaluated']} decks",
     f"Most popular cards: {pct(comp['recall_popular_fill'], 0)}", "Beats the baseline" if comp["difference_ci90"][0] > 0 else "Not clearly better"],
    ["Deck style", f"{pct(ar['accuracy'], 0)} ({pct(ar['accuracy_ci90'][0], 0)} to {pct(ar['accuracy_ci90'][1], 0)}) on {ar['heldout_decks']} decks",
     f"Always “{ar['majority_class']}”: {pct(ar['majority_accuracy'], 0)}", "Beats the baseline" if ar["accuracy_ci90"][0] > ar["majority_accuracy_ci90"][1] else "Not clearly better"],
    ["Pair synergy picking the winner", f"AUC {used['test_auc']:.3f} ({rng(used['auc_ci90'])})",
     f"Lift {syn['mean_lift']['test_auc']:.3f}; popularity {syn['popularity']['test_auc']:.3f}",
     "Beats both" if used["auc_ci90"][0] > max(syn["mean_lift"]["test_auc"], syn["popularity"]["test_auc"]) else "Not clearly better"],
], widths=[4.2, 4.8, 4.6, 3.4])
r = sig["rating_only"]
p("How to read this. Among top players, which deck wins a single battle is close to a coin flip: decks are similar in "
  f"strength and skill decides most games. The model beats a coin flip and card popularity, but its edge over player "
  f"rating alone is not clear (log-loss change {r['delta_log_loss']:.5f}, 90% range {r['ci90_lo']:.5f} to {r['ci90_hi']:.5f}). "
  "Where the model is strong is in knowing which cards belong together: it finds the hidden cards of real decks far "
  "better than filling with popular cards.")

# ------------------------------------------------------------------ 6 code
doc.add_heading("6. The code", 1)
p(f"Python package in src/crdeck/ ({sum(lines(f) for f in (ROOT / 'src' / 'crdeck').glob('*.py')):,} lines), a static website "
  f"in web/, scripts in scripts/, {len(list((ROOT / 'notebooks').glob('*.ipynb')))} notebooks and "
  f"{len(list((ROOT / 'tests').glob('test_*.py')))} test files. The project has {git('rev-list', '--count', 'HEAD')} commits since "
  f"{git('log', '--reverse', '--format=%ad', '--date=short').splitlines()[0]}.")
doc.add_heading("Folder layout", 2)
table(["Folder", "Holds"], [
    ["config/", "collection.yaml (API, leaderboards, modes, leagues, arenas, arena collector), deck_rules.yaml (slot rules with evidence), model.yaml (model, search and warning settings)"],
    ["src/crdeck/", "The Python package (table below)"],
    ["data/raw/", "Every API response, cached as JSON per collection window (not committed)"],
    ["data/interim/, data/processed/", "Parsed tables, trained-model caches, evaluation reports and the run log (not committed)"],
    ["data/labels/", "Hand-labeled card roles and archetype labels"],
    ["data/raw_manifest.csv", "One row per raw file with its fetch time (committed, since raw data is not)"],
    ["notebooks/", "01 cards, 02 rules, 03 data, 04 baselines, 05 models, 06 search, 07 demo; each re-runs from scratch with the same outputs"],
    ["scripts/", "Web export, the website checks, notebook generation and running, the one-time card label bootstrap"],
    ["web/", "The five-page website, its JavaScript engine and the exported models"],
    ["tests/", "pytest tests, run without any network"],
    ["docs/", "The spec, API notes (documented vs observed), model notes (every assumption), card label review"],
], widths=[4.2, 12.8])
doc.add_heading("Python modules", 2)
MOD = {
    "api.py": "The only network code. Reads the key from .env, caches every response, retries politely on rate limits, never re-requests a cached file.",
    "collect.py": "Decides what to fetch: the leaderboard collection, the arena collector (clan search, member lists, ladder opponents), and the API gate.",
    "parse.py": "Turns raw battle logs into battles, decks and slot records; assigns mode, league or arena, and sample; removes duplicates.",
    "cards.py": "Loads the hand-labeled card table and joins it to the API card list by id.",
    "rules.py": "Deck legality: the only code that decides it. Matches Evolution, Hero and Champion cards to the special slots.",
    "dataset.py": "Model-ready battles for one mode or group, and the time split.",
    "synergy.py": "Pair statistics: lift, shrunk win rates, synergy with intervals.",
    "strength.py": "Deck-strength models: coin flip, popularity and rating baselines, and the logistic regressions.",
    "search.py": "Beam search for decks and swap suggestions; every returned deck is checked by rules.py.",
    "archetype.py": "The style classifier, plus clustering to choose decks worth labeling.",
    "explain.py": "Explanations and advisory warnings for each deck.",
    "evaluate.py": "Held-out evaluation against baselines, with bootstrap intervals.",
    "forecast.py": "Meta history per collection period and the gated Monte Carlo forecast.",
    "pipeline.py": "build() and load_context(): trains or loads the models for one mode or group, with a fingerprint-checked cache.",
    "runlog.py": "The machine-readable run log the website's model log shows.",
    "labeling.py": "Interactive archetype labeling in the terminal.",
    "synthetic.py": "Synthetic battle data for testing the pipeline, never used in place of real data.",
    "config.py": "Loads config files and keeps real and synthetic data paths apart.",
    "cli.py": "The python -m crdeck command line.",
}
table(["File", "Lines", "Job"], [[f, n(lines(ROOT / "src" / "crdeck" / f)), MOD[f]] for f in MOD], widths=[2.8, 1.4, 12.8])

# ------------------------------------------------------------------ 7 code walkthrough
import ast  # noqa: E402
import textwrap  # noqa: E402


def _lines(rel):
    return (ROOT / rel).read_text(encoding="utf-8").splitlines()


def _fit(ls, max_lines=None):
    out = textwrap.dedent("\n".join(ls)).splitlines()
    if max_lines and len(out) > max_lines:
        out = out[:max_lines] + ["...  (shortened here; the full code is in the file)"]
    return "\n".join(out)


def py_func(rel, qual, max_lines=None):
    """Source of a function or method (dotted name), straight from the file."""
    src = (ROOT / rel).read_text(encoding="utf-8")
    node = ast.parse(src)
    for part in qual.split("."):
        node = next(x for x in ast.walk(node) if isinstance(x, (ast.FunctionDef, ast.ClassDef)) and x.name == part)
    return _fit(src.splitlines()[node.lineno - 1:node.end_lineno], max_lines), node.lineno


def between(rel, start, end):
    """Lines from the first line containing `start` through the first later line containing `end`."""
    ls = _lines(rel)
    i = next(k for k, line in enumerate(ls) if start in line)
    j = next(k for k in range(i + 1, len(ls)) if end in ls[k])
    return _fit(ls[i:j + 1]), i + 1


def snippet(title, rel, got, explain):
    text, line = got
    doc.add_heading(title, 2)
    cap = doc.add_paragraph()
    r = cap.add_run(f"{rel}, from line {line}")
    r.italic = True
    r.font.size = Pt(9)
    r.font.color.rgb = MUTED
    para = doc.add_paragraph()
    para.paragraph_format.left_indent = Cm(0.3)
    para.paragraph_format.space_after = Pt(8)
    sh = OxmlElement("w:shd")
    sh.set(qn("w:val"), "clear")
    sh.set(qn("w:color"), "auto")
    sh.set(qn("w:fill"), "F2F4F8")
    para._p.get_or_add_pPr().append(sh)
    run = para.add_run(text)
    run.font.name = "Consolas"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Consolas")
    run.font.size = Pt(8.5)
    for item in explain:
        p(item[1], bold_lead=item[0])


doc.add_heading("7. Code walkthrough", 1)
p("The snippets below are copied from the source files each time this document is generated, so they match the code at "
  "the version on the title page. Each is followed by what it does and why it is written that way.")

snippet("Every API response is saved, and never fetched twice", "src/crdeck/api.py",
        between("src/crdeck/api.py", "def get(self, endpoint", "retries = int("),
        [("What it does.", "Before any network call, the client looks for a saved copy of that exact request in the "
          "current collection window's folder. If one exists, it returns the saved copy and sends nothing."),
         ("Why.", "Collection runs can be stopped and restarted at any point (which happened twice when the university "
          "network changed IP addresses) without wasting requests, and every number in the project can be traced back to "
          "a saved, timestamped API response.")])

snippet("Each battle's league or arena comes from the battle itself", "src/crdeck/parse.py",
        py_func("src/crdeck/parse.py", "ModeRules.group"),
        [("What it does.", "For a Trophy Road battle it returns the arena name recorded in the battle. For a Ranked "
          "battle it reads the league number and turns it into a name such as Ultimate Champion, using the names in the config."),
         ("Why.", "The owner's arena table and league names only label and order things. Which group a battle belongs to "
          "is never guessed from trophy counts, and an unknown league number still gets a name (League 9) instead of being dropped.")])

snippet("Duplicate battles: the leaderboard copy wins", "src/crdeck/parse.py",
        between("src/crdeck/parse.py", "in_leaderboard = set(", 'bdf["sample"] = bdf["battle_key"].isin'),
        [("What it does.", "The same battle appears in both players' logs, so battles are de-duplicated by a key made of "
          "the two player tags and the time. Before that, it notes which battles were seen in a leaderboard player's log; "
          "afterwards, any such battle is tagged as leaderboard even if the arena-sample copy was the one kept."),
         ("Why.", "The meta history uses leaderboard battles only. Without this step, a battle that happened to be "
          "collected through an arena player first would silently drop out of the leaderboard sample.")])

snippet("Splitting by time, never at random", "src/crdeck/dataset.py",
        py_func("src/crdeck/dataset.py", "time_split"),
        [("What it does.", "Sorts battles by time. The oldest 70% train the models, the next 15% pick settings, and the "
          "newest 15% are the test. Battles that share the boundary second all go to the earlier part."),
         ("Why.", "A random split would let the model learn from battles played after the ones it is tested on, which "
          "flatters it. Testing on the newest battles is closer to real use: learn from the past, predict what comes next.")])

snippet("Legality: matching special cards to slots", "src/crdeck/rules.py",
        between("src/crdeck/rules.py", "def slot_kind(", "_KIND_ORDER"),
        [("What it does.", "slot_kind says what a card needs: an Evolution needs a slot that takes Evolutions, a Hero or "
          "Champion needs one that takes Heroes or Champions, and anything else is a normal card. _assign then tries every "
          "way to place the special cards in distinct special slots and returns the first one that fits, or nothing."),
         ("Why.", "With only three special slots (Evolution, Hero, Wild), trying every placement is instant and can never "
          "miss a legal one. This file is the only place in the project that decides legality; search, explanations and "
          "the website all rely on it (the website through its checked JavaScript copy).")])

snippet("Synergy math: shrinking small samples", "src/crdeck/synergy.py",
        between("src/crdeck/synergy.py", "def shrunk_rate(", "return sigmoid(logit(swr_i)"),
        [("What it does.", "shrunk_rate adds k imaginary games at the global win rate g to a card's or pair's record, so "
          "a pair that won 3 of 3 games is not treated as a 100% pair. expected_pair_wr predicts what a pair should win if the "
          "two cards simply added their strengths, by adding their effects on the log-odds scale."),
         ("Why.", "Synergy is the pair's shrunk win rate minus this expectation. Positive means the pair did better "
          "together than its two cards predict. Shrinkage keeps rare pairs from topping the list by luck.")])

snippet("The strength model: cards in, chance of winning out", "src/crdeck/strength.py",
        py_func("src/crdeck/strength.py", "CardModel.fit", max_lines=22),
        [("What it does.", "Each battle becomes one row: the cards of deck A minus the cards of deck B (each card form is "
          "a column), plus the rating difference between the two players. A logistic regression without an intercept learns "
          "a weight per card form from who won."),
         ("Why the rating column is scaled up.", "Regularization pulls every weight toward zero. Multiplying the rating "
          "column by a large number makes its penalty negligible, so skill is fully accounted for and card weights describe "
          "decks at equal skill. Good players can't make their favourite cards look strong."),
         ("Why no intercept.", "Swapping A and B must flip the prediction exactly; with no intercept, the chance that A beats B "
          "is always one minus the chance that B beats A.")])

snippet("A deck's estimated win rate and its range", "src/crdeck/strength.py",
        py_func("src/crdeck/strength.py", "MetaScorer.score", max_lines=22),
        [("What it does.", "The deck is played, on paper, against every sampled opponent deck from the test window, and "
          "the average win chance is the estimate. The range combines two sources of doubt: uncertainty in the learned "
          "weights (from the model's covariance) and which opponents happened to be sampled."),
         ("Why it is written as a formula.", "The website recomputes this in JavaScript. An exact formula, rather than "
          "random resampling, lets the JavaScript match Python to many decimal places, which the export check verifies."),
         ("What it does not cover.", "The best of many noisy estimates tends to be lucky, so a search's top deck is likely a little optimistic.")])

snippet("Building decks: beam search with legality at every step", "src/crdeck/search.py",
        between("src/crdeck/search.py", "for _ in range(size - len(seeds)):", "children.append((pi, self.evaluate(new)))"),
        [("What it does.", "Starting from the picked cards, each step tries adding every candidate card to every deck "
          "in the beam, skips duplicates, and throws away any partial deck that can no longer become legal. The best "
          "children by score form the next beam, with a cap per parent so the beam doesn't fill up with near-copies."),
         ("Why.", "Checking legality on partial decks means illegal decks are never even scored. At the end, every returned "
          "deck is checked again in full and the code raises an error if one is illegal, so the promise never to output an "
          "illegal deck holds even if something upstream breaks.")])

snippet("The arena collector: placing a clan member in an arena", "src/crdeck/collect.py",
        between("src/crdeck/collect.py", "def arena_of(member", "source[arena][via] += 1"),
        [("What it does.", "arena_of uses the arena named in the member's own record. Only if that is missing does it "
          "fall back to the trophy floors from the config, and it counts how often each route was used. add accepts a player "
          "only if the arena still has room and the player hasn't been placed already."),
         ("What happened in practice.", "In the 2026-10-20 run, the member record named the arena 46,166 times and the "
          "trophy floors were needed 42 times. Players at 14,000+ trophies are recorded as Spirit Square, so the two Seasonal "
          "Arenas are skipped by the collector and filled from leaderboard players instead.")])

snippet("The meta history counts one fixed group of players", "src/crdeck/forecast.py",
        between("src/crdeck/forecast.py", 'keep = (battles["mode"] == mode)', 'keep &= battles["sample"] == "leaderboard"'),
        [("What it does.", "When it measures how often each card is used per collection period, it keeps only Ranked "
          "battles from leaderboard players."),
         ("Why.", "Arena-sample players were first collected on 2026-10-20. Counting them would change who is being "
          "measured between periods, and that change would look like a shift in the meta.")])

snippet("Keeping the website honest: the Python-vs-JavaScript check", "scripts/check_web_engine.mjs",
        between("scripts/check_web_engine.mjs", 'the "why this swap" breakdown must add up', "swap breakdown ${"),
        [("What it does.", "For every swap suggestion in the test searches, it asks the website's engine to explain the "
          "swap, adds up the parts of the explanation, and fails if they don't equal the score change used to rank the swap."),
         ("Why.", "The site shows each swap's score split into parts (card weight, pair weights, synergy, played-together). "
          "This check guarantees those bars always add up to the number shown. The same script also compares legality, "
          "decks, scores and explanations with Python's own answers for every exported mode, league and arena.")])



snippet("The card map: vectors from which cards share decks", "src/crdeck/embedding.py",
        py_func("src/crdeck/embedding.py", "factorize"),
        [("What it does.", "Takes the positive-PMI matrix (how much more often two card forms share a training deck than "
          "chance), keeps the strongest d patterns from an SVD, and turns each card form into a d-number vector of length 1. "
          "The sign of each pattern is fixed so the result is the same on every run."),
         ("Why.", "Cards used in the same kinds of decks end up pointing the same way, which lets the site measure how "
          "well a card fits a deck as one number: its distance to the deck's center.")])

snippet("Card-map swaps: close to the deck and stronger", "src/crdeck/embedding.py",
        between("src/crdeck/embedding.py", "    for old in entries:", "out.sort(key=lambda s:"),
        [("What it does.", "For every card that may be replaced, it takes the center of the other 7 cards, ranks every "
          "legal candidate by distance to that center (in all dimensions), scores the closest few with the strength model, "
          "and keeps those that raise the estimated win rate."),
         ("Why both checks.", "Closeness alone would suggest cards that are merely popular alongside the deck; the win-rate "
          "check alone would ignore whether the card fits. Requiring both keeps suggestions in character and better. "
          "Ties are broken at a fixed precision so the website reproduces the exact same list.")])


# ------------------------------------------------------------------ 8 machine learning in depth
import numpy as _np  # noqa: E402
import pandas as _pd  # noqa: E402

MCFG = yaml.safe_load((ROOT / "config" / "model.yaml").read_text(encoding="utf-8"))
ST = RANKED["strength"]
W_CARDS = _np.array(ST["coef"][: ST["n_card_features"]])
CANDS = EV["strength_candidates"]
SEL = [r for r in CANDS if r["selected"]][0]
LABELS = _pd.read_csv(ROOT / "data" / "labels" / "archetype_labels.csv")
N_TRAIN_BATTLES = sp["train"]["battles"]


def formula(text):
    para = doc.add_paragraph()
    para.paragraph_format.left_indent = Cm(1.0)
    para.paragraph_format.space_after = Pt(8)
    r = para.add_run(text)
    r.font.name = "Cambria Math"
    r._element.rPr.rFonts.set(qn("w:eastAsia"), "Cambria Math")
    r.font.size = Pt(11)
    return para


doc.add_heading("8. Machine learning in depth", 1)
p("This section goes through every learned or statistical part of the project: what goes in, what is optimized, how "
  "the optimizer uses gradients, how settings are chosen, and how uncertainty is computed. Notation: σ is the sigmoid "
  "function σ(z) = 1 / (1 + e^(−z)), logit is its inverse logit(p) = ln(p / (1 − p)), and xᵀ means a transposed vector. "
  "Numbers come from the current Ranked model.")

# 8.1
doc.add_heading("8.1 Deck strength: the data the model sees", 2)
p(f"Each training battle becomes one row. The Ranked model was trained on {n(N_TRAIN_BATTLES)} battles. A row has one "
  f"column per card form ({ST['n_card_features']} columns: every base, Evolution and Hero form seen in at least "
  f"{ST['min_feature_games']} training deck appearances) and one extra column for the players' rating difference.")
formula("x = (cards in deck A) − (cards in deck B), plus  s · (rating A − rating B)")
p("A card in deck A only gets +1, a card in deck B only gets −1, and a card in both cancels to 0. The label y is 1 if A "
  "won and 0 if B won. Draws and mirror matches (identical decks) are left out, because they say nothing about which deck is stronger.")
p("Why a difference of two decks: the model should only care about how the two decks differ. Writing the row this way "
  "makes the model symmetric: describing the same battle from B's side flips the signs of x and gives exactly 1 − p.")

# 8.2
doc.add_heading("8.2 The model: logistic regression without an intercept", 2)
formula("p = P(A wins) = σ(wᵀx) = σ( u(A) − u(B) + β · rating difference )")
p("w holds one weight per card form plus the rating weight. u(deck) is the sum of the deck's card weights: the deck's "
  "strength in log-odds. There is no intercept because an intercept would mean “deck A wins more just for being called A”, "
  "and it would break the symmetry above.")
p(f"The learned card weights are small: they range from {W_CARDS.min():+.4f} to {W_CARDS.max():+.4f} log-odds, with a "
  f"standard deviation of {W_CARDS.std():.4f}. Near 0, σ has slope ¼, so a weight of 0.04 moves a win chance by about one "
  "percentage point. Among top players, single cards change little; skill and matchups decide most of a battle.")

# 8.3
doc.add_heading("8.3 What is minimized: log loss plus an L2 penalty", 2)
p("scikit-learn's LogisticRegression minimizes, over all training rows i:")
formula("J(w) = C · Σᵢ [ −yᵢ · ln pᵢ − (1 − yᵢ) · ln(1 − pᵢ) ]  +  ½ ‖w‖²")
p("The first part is log loss: it is small when the model gave high probability to what actually happened, and large "
  "when it was confidently wrong. The second part is the L2 penalty (ridge regularization): it pulls every weight "
  "toward 0. C sets the balance. A small C trusts the penalty, so weights stay near 0 unless the data insists; a large "
  "C trusts the data and lets weights grow, which can fit noise.")
p("The rating column trick. The rating weight should not be pulled toward 0, or part of the skill effect would leak into "
  "the card weights (good players' favourite cards would look strong). The code multiplies the rating column by "
  "s = 100 / √C before fitting. If the fitted coefficient on the scaled column is g, the real effect is β = g · s, and "
  "its penalty is:")
formula("½ g² = ½ (β / s)² = ½ β² · C / 10,000")
p(f"A card weight of the same size β is penalized ½ β², so the rating effect's penalty is 10,000 / C times weaker: "
  f"{10000 / SEL['C']:,.0f} times at the chosen C = {SEL['C']}. Skill is accounted for almost freely while card weights stay "
  "regularized. When a deck's score is computed for the site, the rating term is left out, which means “at equal rating”.")

# 8.4
doc.add_heading("8.4 Gradients and the optimizer (L-BFGS)", 2)
p("The objective J is convex: it has one valley and no false bottoms, so any method that keeps going downhill reaches "
  "the same best answer. Its gradient, the direction of steepest increase, is:")
formula("∇J(w) = C · Xᵀ (p − y) + w")
p("Read it row by row: (p − y) is each battle's error, positive when the model was too sure A would win. Multiplying by "
  "Xᵀ adds those errors up per card: a card that kept appearing on the side that did worse than predicted gets a "
  "gradient pushing its weight down. The + w term is the pull toward 0 from the penalty.")
p("The second derivative (Hessian) says how curved the valley is:")
formula("H = C · Xᵀ D X + I,   where D is diagonal with pᵢ (1 − pᵢ)")
p("Battles the model is unsure about (p near 0.5) carry the most curvature, because pᵢ(1 − pᵢ) is largest there: a small "
  "change in the weights moves their predicted probability the most. Plain gradient descent would need a hand-tuned step size. Newton's method uses H directly but needs to "
  "invert a large matrix every step. L-BFGS (limited-memory BFGS), the solver used here, sits in between. It keeps the "
  "last few gradient changes, builds a cheap approximation of H⁻¹ from them, steps along −H⁻¹∇J, and picks the step "
  f"length with a line search. It stops when the gradient is close to zero (or after {MCFG['strength']['max_iter']:,} iterations).")
p("L-BFGS stops at a tolerance: the largest gradient component must be under 0.0001. In this very flat valley that left "
  "card weights up to 0.006 log-odds from the exact bottom, so the fit then takes exact Newton steps, w ← w − H⁻¹∇J, using "
  "the full Hessian (cheap with under 200 weights). Two steps bring the gradient to about 10⁻¹². Held-out results barely "
  "moved (Ranked test log loss 0.69242 → 0.69240).")

# 8.5
doc.add_heading("8.5 Choosing C and the model version on validation battles", 2)
p(f"Two versions are trained at each C in the grid {', '.join(str(c) for c in MCFG['strength']['C_grid'])}: cards only, "
  f"and cards plus the {MCFG['strength']['top_n_pairs']} most common card pairs (each pair gets its own column, encoded +1 / −1 / 0 like the cards). "
  f"Each is scored on the {n(sp['valid']['battles'])} validation battles, which come after the training battles in time, "
  "by log loss. The lowest log loss wins.")
grid = {}
for r in CANDS:
    grid.setdefault(r["C"], {})["pairs" if "pairs" in r["model"] else "cards"] = r["valid_log_loss"]
table(["C", "Cards only: validation log loss", "Cards + pairs: validation log loss"],
      [[str(c), f"{v.get('cards', float('nan')):.6f}" + ("  ← chosen" if c == SEL["C"] and "pairs" not in SEL["model"] else ""),
        f"{v.get('pairs', float('nan')):.6f}" + ("  ← chosen" if c == SEL["C"] and "pairs" in SEL["model"] else "")]
       for c, v in sorted(grid.items())], widths=[2.5, 7.0, 7.0])
p(f"Ranked chose cards only at C = {SEL['C']}. The table shows the usual pattern: too small a C under-fits (all weights "
  "squashed to 0, log loss near the coin-flip value 0.6931), too large a C over-fits (the pair version gets worse fastest, "
  "because 100 extra columns give it more room to fit noise). The best C sits in between.")

# 8.6
doc.add_heading("8.6 How sure is each card weight? (Laplace approximation)", 2)
p("Near its best value, the log loss is close to a bowl shape described by the Hessian. Treating the fitted weights as "
  "approximately normally distributed around their best value gives:")
formula("Cov(w) ≈ H⁻¹ = ( Xᵀ D X + I / C )⁻¹")
p("(written here with the objective divided by C, which gives the same minimum). The code builds this matrix after "
  "fitting, inverts it with numpy.linalg.pinv (a pseudo-inverse that copes with near-singular cases), and keeps the "
  "card-weight block. The square root of each diagonal entry is that card's standard error. A card played in many "
  "battles with a consistent effect gets a narrow range; a rare card gets a wide one. These are the horizontal lines in "
  "the “Which cards carry this deck” chart (weight ± 1.645 standard errors for 90%).")

# 8.7
doc.add_heading("8.7 From weights to a deck's win rate, and its range (delta method)", 2)
p(f"The site's win rate for a deck is its average win chance against {n(DS['n_opponent_decks'])} opponent decks o "
  "sampled from the test window, at equal rating:")
formula("W(deck) = (1/N) Σₒ σ( u(deck) − u(o) )")
p("Two things are uncertain: the weights (section 8.6) and which opponents were sampled. For the weights, the delta "
  "method asks how much W would move if the weights moved. Using σ′(z) = σ(z)(1 − σ(z)) and writing pₒ for each term:")
formula("∂W/∂w = x_deck · mean(pₒ(1 − pₒ))  −  mean( pₒ(1 − pₒ) · x_o )")
formula("Var_model(W) ≈ (∂W/∂w)ᵀ · Cov(w) · (∂W/∂w)")
p("For the opponents, the standard error of a mean: sd(pₒ) / √N. The two are combined and turned into a 90% range:")
formula("range = W ± 1.645 · √( Var_model + Var_opponents )")
p("This is computed with formulas rather than by resampling, so the website's JavaScript reproduces it exactly; the "
  "export check compares the two. What it does not include: the top deck of a search is the best of many noisy "
  "estimates, so it is likely a little optimistic.")

# 8.8
doc.add_heading("8.8 Synergy as Bayesian shrinkage", 2)
k_, g_ = MCFG["synergy"]["k"], 0.5
p(f"Each pair's win rate is estimated with a Beta prior worth k = {k_} games centred on the overall win rate g (0.5 once "
  "draws and mirrors are removed). In Bayesian terms the prior is Beta(k·g, k·(1 − g)); after seeing the pair's wins and losses:")
formula("posterior = Beta( wins + k·g,  losses + k·(1 − g) ),   mean = (wins + k·g) / (games + k)")
p("That mean is the “shrunk” win rate: few games are pulled strongly toward 50%, many games barely at all. The pair's "
  "expected win rate, if the two cards simply added their strengths, adds their effects on the log-odds scale, using each "
  "card's shrunk win rate in games without the other:")
formula("expected = σ( logit(A without B) + logit(B without A) − logit(g) )")
formula("synergy = posterior mean − expected,   90% range = Beta 5% and 95% quantiles − expected")
vc = {r["expected_from"]: r["valid_auc"] for r in EV["synergy_variant_choice (validation)"]}
p(f"Pairs with fewer than {MCFG['synergy']['min_games']} games together get no score. Whether “without the other” or "
  f"the card's overall win rate is used is chosen on validation battles; for Ranked, without the other scored AUC "
  f"{vc.get('without_partner', float('nan')):.4f} against {vc.get('marginal', float('nan')):.4f}. The expected value is "
  "treated as fixed, so the range is slightly too narrow; this is noted in the code.")

# 8.9
doc.add_heading("8.9 Deck style: a multinomial logistic regression", 2)
ntr = LABELS[LABELS["split"] == "train"]
dist = ntr["archetype"].value_counts()
nf = len(RANKED["archetype"]["coef"][0])
p(f"Each deck becomes {nf} numbers: one 0/1 column per card ({nf - len(RANKED['archetype']['roles']) - 3}), a count per "
  f"role ({len(RANKED['archetype']['roles'])} roles: {', '.join(r.replace('_', ' ') for r in RANKED['archetype']['roles'])}), "
  "the average elixir cost, the number of win conditions and the number of spells. A multinomial logistic regression "
  f"(C = {MCFG['archetype']['C']}) gives one weight vector w_s and one intercept b_s per style and turns the scores into probabilities with softmax:")
formula("P(style s | deck) = exp(w_sᵀ x + b_s) / Σ_t exp(w_tᵀ x + b_t)")
p(f"It was trained on {len(ntr)} labeled decks ({', '.join(f'{k} {v}' for k, v in dist.items())}) and tested on "
  f"{int((LABELS['split'] == 'heldout').sum())} held-out decks labeled before anything was fitted. If the top probability "
  f"is under {int(MCFG['archetype']['uncertain_threshold'] * 100)}%, the deck is called a mixed style. To choose which "
  f"decks to label, k-means groups the 3,000 most-played decks into {MCFG['archetype']['n_clusters']} clusters by their card "
  f"columns and offers up to {MCFG['archetype']['per_cluster']} of the most-played from each, taking clusters in turn, so labels "
  "cover the variety of decks rather than only the most common. "
  "k-means never predicts anything itself.")

# 8.10
doc.add_heading("8.10 The forecast: weighted least squares plus Monte Carlo", 2)
p("For each card form, the change in usage share between two collection periods is modelled on the log-odds scale, as "
  "depending on how well the card did in the earlier period:")
formula("logit(share next) − logit(share now) = α + β · (win rate now − 0.5)")
p(f"α and β are fitted with weighted least squares (numpy.linalg.lstsq), each card weighted by √games so well-measured "
  f"cards count more; cards under {MCFG['forecast']['min_games']} appearances are left out. The Monte Carlo then repeats "
  f"{MCFG['forecast']['runs']:,} times: draw a bootstrap version of the past periods, refit α and β, step every card "
  "forward, and add binomial noise for the size of the next period. The spread of the runs is the forecast range.")
bt = INDEX["meta"]["backtest"]
if bt:
    b0 = bt[-1]
    p(f"Backtest so far: predicting period {b0['target_period'] + 1} from the earlier ones, the forecast missed by "
      f"{b0['mae_points_monte_carlo']:.3f} share points on average, against {b0['mae_points_no_change']:.3f} for assuming "
      f"no change, and its 90% ranges contained the true value {pct(b0['coverage_90'], 0)} of the time (90% would be "
      "right). So it stays hidden: it has not yet beaten the simplest alternative, and its ranges are too narrow.")

# 8.11
doc.add_heading("8.11 How results are tested", 2)
p("Log loss on the test battles (lower is better; 0.6931 is a coin flip):")
formula("log loss = −(1/n) Σᵢ [ yᵢ ln pᵢ + (1 − yᵢ) ln(1 − pᵢ) ]")
p("AUC is the chance that, for a random win and a random loss, the model rated the win higher; 0.5 is a coin flip. "
  "Ranges come from the bootstrap: resample the test battles with replacement hundreds of times, recompute the metric "
  "each time, and take the 5th and 95th percentiles. To compare two models, the same resampled battles are scored by both "
  "and the difference is taken each time (a paired bootstrap), so the shared luck of the test set cancels out. A model "
  "only counts as better when the whole 90% range of the difference favours it.")



# ------------------------------------------------------------------ 8.12-8.13 card map and swap math
EMB = RANKED.get("embedding")
doc.add_heading("8.12 The card map: card embeddings", 2)
if EMB:
    ev_e, ch_e = EMB["evaluation"], EMB["choice"]
    p("Every card form also gets a vector: a list of numbers whose direction says what kinds of decks the card is "
      "played in. Cards played in the same kinds of decks point in similar directions. The vectors are learned from the "
      "training decks only.")
    p("Step 1, how much more often two card forms share a deck than chance (positive PMI). For each pair, with N "
      "training deck appearances, count(i) decks holding card form i, and co(i, j) decks holding both:")
    formula("PMI(i, j) = ln( co(i, j) · N / (count(i) · count(j)) ),      M(i, j) = max(PMI(i, j), 0),  M(i, i) = 0")
    p("PMI is the logarithm of the lift used for synergy: 0 means “together as often as chance”, positive means more "
      "often. Only the positive part is kept, because “rarely together” is a much noisier signal than “often together”.")
    p("Step 2, compress the matrix with a singular value decomposition, keeping the d strongest patterns:")
    formula("M ≈ U_d S_d U_dᵀ,      vector(i) = row i of U_d · √S_d,  then scaled to length 1")
    p("This is the matrix form of word2vec, the method that learns word meanings from which words appear together: here a "
      "“sentence” is a deck. It needs no random start, so it gives the same vectors every run. A card form whose vector "
      "comes out all zero (the kept patterns don't describe it) is left off the map.")
    p(f"Step 3, choose d on the validation battles. For each of the 100 most-played validation decks, 2 cards are hidden; "
      f"the 10 cards whose vectors point most like the average of the other 6 are the guesses. Recall is the share of hidden "
      f"cards found. For Ranked: {', '.join(f'd = {c['dim']}: {pct(c['valid_recall'], 1)}' for c in ch_e)}, so d = {EMB['dim']}.")
    p(f"Step 4, test once on the held-out battles: {pct(ev_e['recall'], 1)} of hidden cards found (90% range "
      f"{pct(ev_e['recall_ci90'][0], 1)} to {pct(ev_e['recall_ci90'][1], 1)}), against {pct(ev_e['recall_popular'], 1)} for "
      "the 10 most popular cards.")
    import glob as _glob
    mods = [json.loads(Path(f).read_text(encoding="utf-8")).get("embedding") for f in sorted(_glob.glob(str(ROOT / "web" / "models" / "*.json")))]
    mods = [m for m in mods if m]
    earned = sum(1 for m in mods if m["evaluation"].get("difference_ci90") and m["evaluation"]["difference_ci90"][0] > 0)
    p(f"Where it works: across the {len(mods)} exported modes, the card map clearly beat the popular-cards guess in {earned} "
      "(the whole 90% range of the difference above zero). Those are the modes with the most battles. In small leagues and "
      "most arenas it was not clearly better, and in a few low arenas worse, because with few card forms “most popular” is "
      "already a strong guess. The website shows this verdict for the current mode and warns when it is not earned.")
    doc.add_heading("Distance and the deck's center", 3)
    formula("center c = average of the vectors of the other 7 cards")
    formula("distance(card) = 1 − (v · c) / ‖c‖")
    p("v has length 1, so v · c / ‖c‖ is the cosine of the angle between the card and the center: distance 0 means the "
      "same direction, 1 means unrelated, 2 means opposite. Distances are always measured in all "
      f"{EMB['dim']} dimensions.")
    doc.add_heading("Card-map swaps", 3)
    p(f"For each card that may be replaced (cards you picked are never replaced), every candidate that keeps the deck legal "
      f"and is unlocked is ranked by its distance to the center of the other 7. The {EMB['near']} closest are scored with the "
      f"strength model; those that raise the estimated win rate are suggested, largest gain first, up to {EMB['top']}, each "
      "with its distance and its win-rate change. Closeness means “played in the same kinds of decks”, not “wins together”; "
      "the win-rate check is what guards the second.")
    doc.add_heading("The 3D picture", 3)
    p(f"The {EMB['dim']}-dimensional vectors are squashed into 3 dimensions with PCA (principal component analysis: the 3 "
      f"directions along which the cards spread out most) only to draw them. For Ranked those 3 directions keep "
      f"{pct(sum(EMB['pca_explained']), 0)} of the spread, so two cards can look close in the picture without being close. "
      "No decision uses the picture. Cards are coloured by the style most often predicted for the most-played training decks "
      "that hold them; only the three most common styles get a colour, because more colours cannot be told apart in a "
      "scatter plot by colour-blind readers.")
    p("Python and the website must agree: the vectors are rounded to 7 decimals before use, so both sides compute the "
      "same distances, and ties in win-rate change or distance are broken at a fixed precision the same way on both sides. "
      "The export check compares every card-map swap.")

LAND = INDEX.get("landscape")
if LAND:
    doc.add_heading("8.13 Seeing the gradient: the loss surface on the website", 2)
    s0 = LAND["slices"][0]
    import numpy as _np2
    Ls = _np2.array(s0["loss"])
    p("The How it works page draws the Ranked model's real training loss as a 3D surface. A full picture would need all "
      "weights at once, so it shows a slice: two card weights a and b change around their fitted values while every other "
      f"weight stays as trained. Each point of the surface is J computed on the {n(s0['n_train'])} battles the model was "
      "fitted on, and the arrows are the exact gradient there:")
    formula("J(a, b) = mean log loss + ‖w‖² / (2 C N)")
    formula("∂J/∂a = mean( (p − y) · x_a ) + a / (C N),      ∂J/∂b = mean( (p − y) · x_b ) + b / (C N)")
    p(f"Three slices can be picked: {', '.join(s['label'].lower() for s in LAND['slices'])}. For the first "
      f"({', '.join(s0['keys'])} in the model's card ids), the surface spans only {Ls.max() - Ls.min():.5f} in loss over "
      "± about 4 standard errors of each weight, so its height is stretched for display and the caption says so. The fitted "
      "point f(a, b) is exactly the lowest point of the grid and the gradient there is zero to machine precision, which the "
      "tests check. White arrows show −∇J: the downhill direction, shrinking toward the bottom.")
    p(f"The pink path is plain gradient descent on the slice: start in a corner, then repeatedly a ← a − η ∂J/∂a and "
      f"b ← b − η ∂J/∂b with η = 0.3 / (largest curvature), here {s0['learning_rate']:.2f}. It is an illustration of "
      "following the gradient; the real fit is L-BFGS and Newton steps over all weights together.")

doc.add_heading("8.14 The math shown for each swap", 2)
sw_w = RANKED["config"]["search"]
p("Regular swaps are ranked by the change in the deck's score. The Why this deck page writes it out for every suggestion:")
formula(f"Δscore = Δwin + {sw_w['synergy_weight']} × Δsynergy + {sw_w['cooccurrence_weight']} × Δplayed-together")
p("Δwin is the change in estimated win rate (in percentage points), Δsynergy the change in the deck's average pair synergy, "
  "and Δplayed-together the change in the average log-lift of its card pairs. The page fills in each term with the deck's "
  "values before and after the swap, so the three parts visibly add up to the number the swaps are sorted by.")


# ------------------------------------------------------------------ 7 website
doc.add_heading("9. The website", 1)
p("The website runs the trained model entirely in the browser; it needs no server beyond serving files. Each page has one job:")
table(["Page", "What it shows"], [
    ["Build decks (index.html)", "Pick up to 3 cards and a mode, league or arena; get three decks with style, estimated win rate and range, and deck checks."],
    ["Why this deck (reason.html)", "Opened from a deck: a plain-language summary, each card's weight, the model compared with real results, card pairs, warnings, swaps with their math written out, a rotatable 3D card map with card-map swaps and nearest-card tables, and the raw score."],
    ["All cards (cards.html)", "Every card form and every row of your card CSV: battle stats, learned weight, and your CSV's own numbers."],
    ["Meta (meta.html)", "How ranked card usage changed between collections, deck styles per period, and the forecast's status and assumptions."],
    ["Next season (seasons.html)", "Today's most-played ranked decks with their trend, new cards between saved card lists, and a next-season prediction that stays locked until enough seasons are collected."],
    ["How it works (model.html)", "The method in five steps, held-out results against baselines, limits, a glossary, and the full model log."],
], widths=[4.4, 12.6])
p("web/engine.js is a JavaScript copy of the Python legality, scoring, search, swap and explanation code. Because two "
  "copies can drift, every export writes Python's own answers for random decks and searches, and "
  "check_web_engine.mjs fails if the JavaScript disagrees anywhere. The sweep additionally runs every card form through "
  "the engine and checks every result. Links carry the mode, deck and picks after the # in the address, so a “Why this "
  "deck” page can be shared. Every number on the site is tagged as measured, model estimate, your CSV, or deck checks.")
doc.add_heading("Running it locally", 2)
code("cd C:\\Users\\simty\\crdeck\\web\n..\\.venv\\Scripts\\python -m http.server 8000\n# then open http://localhost:8000/")

# ------------------------------------------------------------------ 8 how to run
doc.add_heading("10. Day-to-day use", 1)
bullets([
    ("API key:", "create one at developer.clashroyale.com for your current public IP and put it in .env as CR_API_KEY. "
     "Keys only work from the IP they list; campus Wi-Fi changes it often. Setting CR_API_BASE=https://proxy.royaleapi.dev/v1 "
     "routes through a relay with a fixed IP instead."),
    ("Daily refresh:", "collect → build → evaluate → export → check → sweep. Models retrain automatically when data, labels, config or code change."),
    ("Suggest from the terminal:", "python -m crdeck suggest \"Hog Rider\" (forms: \"Knight@evo\", \"Knight@hero\"; add --mode and --group)."),
    ("Tests:", ".venv\\Scripts\\python -m pytest (no network needed)."),
], style="List Bullet")

# ------------------------------------------------------------------ 9 testing
doc.add_heading("11. How it is checked", 1)
bullets([
    ("pytest:", "unit and pipeline tests for parsing, legality, synergy, strength, search, explanations, the forecast, modes, "
     "leagues and arenas, and the collectors against fake API responses."),
    ("Website vs Python:", "the golden check after each export."),
    ("Rule sweep:", "every card form alone, forms that do not exist (must be refused), hard combinations such as three champions, and every swap."),
    ("Notebooks:", "each notebook runs twice in fresh kernels with caches off and must give identical outputs."),
    ("Headless page test:", "loads all five pages with the real data and checks picks, refusals, mode switches, swaps and undo, broken links and empty states."),
])

# ------------------------------------------------------------------ 10 limits
doc.add_heading("12. Limits and assumptions", 1)
bullets([
    "Win rates describe top players in the collected window, at equal rating, not anyone's own games.",
    "The best of many noisy estimates looks better than it is; the ranges cover model and sampling noise, not this selection effect.",
    "Unseen decks are estimated from their cards and pairs only.",
    "The arena sample is clan members found through name search and is not a random sample of each arena: players without a clan are missing.",
    "Models that mix groups (All modes, every league, every arena) are tuned and tested on different mixes of players, because the two samples were collected at different times. A single league or arena is the cleaner choice.",
    "Archetype labels were drafted by the project's assistant; style accuracy is agreement with that labeler.",
    "The co-occurrence weight's selection rule was revised after test results had been seen; this is disclosed on the site.",
    "Period lengths and time zones differ between collections, so part of a usage change can be who was playing, not a meta shift.",
])
p("docs/model-notes.md holds every assumption in full with what it would take to test it.", muted=True)

# ------------------------------------------------------------------ 11 status
doc.add_heading("13. Status and next steps", 1)
not_ok = [m for m in MODES if m["status"] != "exported"]
bullets([
    ("Done:", f"data pipeline, models, held-out evaluation, website with {sum(m['status'] == 'exported' for m in MODES)} trained "
     f"models (overall modes, {sum(1 for m in groups if m['mode'] == 'ranked' and m['status'] == 'exported')} leagues, "
     f"{sum(1 for m in groups if m['mode'] == 'trophy_road' and m['status'] == 'exported')} arenas)."),
    ("Forecast:", f"waiting for data. It needs {ms['min_periods']} collection periods to backtest and the project has {ms['periods']}; one more daily leaderboard collection unlocks the first backtest."),
    ("Not yet trained:", "; ".join(f"{m['label']} ({n(m['ok_battles'])} battles: {m.get('reason', '').split(': ', 2)[-1]})" for m in not_ok) or "none"),
    ("API access:", "the key is tied to one IP address; a new key is needed whenever the network changes it, or use the proxy."),
    ("Sharing:", "the online version on claude.ai still shows an older build until it is republished."),
])

out = ROOT / "docs" / "crdeck-documentation.docx"
doc.save(out)
print("wrote", out)
