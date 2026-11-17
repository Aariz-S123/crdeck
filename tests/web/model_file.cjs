// A model file as the engine sees it: web/models/<slug>.json with its decks part (<slug>.decks.json, the per-deck
// tables split off by crdeck.explore.model_parts) merged back in. Older unsplit files load as they are.
const fs = require("fs");
const path = require("path");

function loadModel(file) {
  const body = JSON.parse(fs.readFileSync(file, "utf8"));
  const decks = file.replace(/\.json$/, ".decks.json");
  if (fs.existsSync(decks)) Object.assign(body, JSON.parse(fs.readFileSync(decks, "utf8")));
  return body;
}
module.exports = { loadModel };
