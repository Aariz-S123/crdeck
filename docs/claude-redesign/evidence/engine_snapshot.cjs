// Records the web engine's answers for fixed inputs, so a run can prove it left recommendations unchanged.
//   node docs/claude-redesign/evidence/engine_snapshot.cjs <out.json>
// Inputs: web/models/ranked.json and web/models/trophy_road.json (read only).
const fs = require("fs");
const path = require("path");
const WEB = path.join(__dirname, "..", "..", "..", "web");
const { Engine, keyOf } = require(path.join(WEB, "engine.js"));

const out = {};
for (const slug of ["ranked", "trophy_road"]) {
  const E = new Engine(JSON.parse(fs.readFileSync(path.join(WEB, "models", slug + ".json"), "utf8")));
  // seed sets: none, the most played card form, the three most played card forms of different cards
  const byGames = E.candidates.slice().sort((a, b) => E.games(b) - E.games(a) || keyOf(a).localeCompare(keyOf(b)));
  const three = [];
  for (const c of byGames) { if (!three.some((t) => t.id === c.id) && E.checkPartial(three.concat([c])).legal) three.push(c); if (three.length === 3) break; }
  const cases = { none: [], one: [byGames[0]], three };
  const res = {};
  for (const [name, seeds] of Object.entries(cases)) {
    const decks = E.complete(seeds).map((d) => {
      const x = E.explain(d.entries, E.objectiveDict(E.evaluate(d.entries)));
      return {
        key: d.key, cards: x.deck, objective: d.objective, win_prob: x.score.meta_win_prob, interval: x.score.interval,
        archetype: x.archetype.label, style_probability: x.archetype.probability,
        warnings: x.warnings.flatMap((g) => g.warnings.map((w) => w.code)),
        exact_test_battles: x.score.test_battles_exact_deck, exact_test_wins: x.score.test_wins_exact_deck,
        appearances: E.m.deck_appearances[d.key] || 0, data_quality: x.data_quality.map((q) => q.state),
        swaps: E.swaps(d.entries, { locked: seeds }).map((s) => [s.new_deck_key, s.delta_objective]),
        embedding_swaps: E.embeddingSwaps(d.entries, seeds).map((s) => [s.new_deck_key, s.delta_win_prob]),
      };
    });
    res[name] = { seeds: seeds.map(keyOf), decks };
  }
  const styles = Object.keys((E.m.matchup && E.m.matchup.styles) || {}).sort();
  res.counters = styles.length ? { style: styles[0], decks: E.counterDecks(E.opponentsFor({ style: styles[0] })).map((d) => [d.key, d.win_vs, d.score, d.swap && d.swap.key]) } : null;
  out[slug] = res;
}
fs.writeFileSync(process.argv[2], JSON.stringify(out, null, 1));
console.log("wrote", process.argv[2]);
