"""Shared fixtures.

Card table: the real label file joined to fake (synthetic) card ids, so tests
also validate data/labels/cards.csv. Battle fixtures are small hand-built JSON
in the battle-log shape assumed in docs/api-notes.md.
"""

from __future__ import annotations

import pytest

from crdeck.config import Paths
from crdeck.rules import DeckCard, DeckRules
from crdeck.synthetic import synthetic_card_table


@pytest.fixture(scope="session")
def cards():
    return synthetic_card_table()


@pytest.fixture(scope="session")
def rules():
    return DeckRules.load()


@pytest.fixture(scope="session")
def C(cards):
    """C("Knight") -> base DeckCard; C("Knight", "evo") -> evo DeckCard."""
    def make(name: str, form: str = "base") -> DeckCard:
        return DeckCard(cards.by_name(name).card_id, form)
    return make


@pytest.fixture(scope="session")
def small_ctx(tmp_path_factory):
    """A small SYNTHETIC dataset built and modeled in a temp dir (session-scoped: built once)."""
    from crdeck.pipeline import build, load_context
    from crdeck.synthetic import SynthConfig, generate

    root = tmp_path_factory.mktemp("synthetic")
    paths = Paths(source="synthetic", root=root)
    generate(SynthConfig(n_players=120, n_battles=6000, seed=11), paths=paths)
    build(paths=paths, verbose=False)
    return load_context(paths=paths)
