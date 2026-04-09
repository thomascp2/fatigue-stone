# hs-ev-machine

A modular Hearthstone solver engine in Python — RTA recommendations, GTO simulation via CFR, and EV calculation over decision trees. Built from scratch against live HearthstoneJSON card data.

## Setup

```bash
pip install -r requirements.txt
python scripts/fetch_cards.py     # download card data (~12.8 MB, one time)
python -m pytest tests/           # run all tests
python scripts/benchmark.py       # measure simulation speed
```

Python 3.10+ required. No C# dependencies.

## Architecture

```
Layer 1 — Game State Model       card.py, state.py
Layer 2 — Rules Engine           rules.py, combat.py
Layer 3 — Action Generator       actions.py
Layer 4 — Simulator              simulator.py, deck.py
Layer 5 — Solver                 mcts.py (Phase 3), cfr.py (Phase 4)
Layer 6 — Meta Ingestion         meta.py (Phase 5)
```

## Current Status

**Phase 2 complete** — 221 tests passing, 544 games/sec random rollout.

See [ROADMAP.md](ROADMAP.md) for full phase breakdown and next steps.

## Modules

| File | Phase | Description |
|---|---|---|
| `hs_solver/card.py` | 1.1 | Card dataclass + CardDB from HearthstoneJSON |
| `hs_solver/state.py` | 1.2 | MinionInstance, HeroInstance, PlayerState, GameState |
| `hs_solver/combat.py` | 1.4 | Attack resolution, divine shield, poisonous, lifesteal |
| `hs_solver/rules.py` | 1.3/1.5 | play_minion, play_spell, attack, end_turn + validation |
| `hs_solver/actions.py` | 2.1 | Action dataclass + get_legal_actions() + apply_action() |
| `hs_solver/simulator.py` | 2.2/2.3 | random_rollout, simulate_n, win conditions |
| `hs_solver/deck.py` | 2.4 | HS deck string codec, random_deck, validate_deck |
| `scripts/fetch_cards.py` | 1.1 | Download HearthstoneJSON card dump |
| `scripts/benchmark.py` | 2.5 | Simulation speed harness |

## Key Design Decisions

**Mutable state, explicit clone.** State is mutated in place during simulation. `GameState.clone()` is the gate for tree search — fast custom clone (5-8x faster than `deepcopy`) that shares immutable `Card` references.

**Actions are frozen/hashable.** `Action` uses `@dataclass(frozen=True)` so it can be used as a CFR strategy table key in Phase 4.

**Spell effects are stubs in Phase 2.** Cards are played for their mana cost; effects are wired via `SpellEffect` dataclass in Phase 5 from HearthstoneJSON data. The simulation is "mana correct" but not yet "effect correct" for spells.

**No hardcoded card IDs.** All card data comes from HearthstoneJSON. Effect mapping will use text classification, not card name checks.

## Running a rollout

```python
from hs_solver.card import load_card_db
from hs_solver.deck import random_deck
from hs_solver.simulator import random_rollout, simulate_n
from hs_solver.state import new_game
from hs_solver.card import CardClass

db = load_card_db()
deck1 = random_deck(db, card_class=CardClass.MAGE, size=30, seed=0)
deck2 = random_deck(db, card_class=CardClass.WARRIOR, size=30, seed=1)
state = new_game(deck1, deck2)

# Single rollout
winner = random_rollout(state)

# Win rate over N games
results = simulate_n(state, n=200)
print(f"P1 win rate: {results['p1_winrate']:.1%}")
print(f"Speed: {results['games_per_sec']:.0f} g/s")
```

## Loading a deck from a deck code

```python
from hs_solver.deck import decode_deck_string, build_deck
from hs_solver.card import load_card_db

db = load_card_db()
deck_list = decode_deck_string("AAECAa0G...")  # paste HS deck code here
cards = build_deck(db, deck_list)
```
