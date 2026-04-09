# hs-ev-machine — Project Roadmap

> Last updated: 2026-04-09
> Current milestone: **Alpha** (Phases 1–2 complete)

---

## Milestone Summary

| Milestone | Phases | What it enables |
|---|---|---|
| **MVP** ✅ | 1 | Represent and mutate game states |
| **Alpha** ✅ | 1–2 | Simulate full games, measure deck win rates |
| Beta | 1–3 | RTA recommendations for any board state |
| V1.0 | 1–5 | Full GTO engine + meta grounding |
| V1.5 | 1–6 | Real-time overlay + exportable reports |

---

## Phase 1 — Foundation ✅ Complete

### 1.1 Card Data Ingestion ✅
- `hs_solver/card.py` — `Card` dataclass, `CardDB`, `load_card_db()`
- `scripts/fetch_cards.py` — downloads HearthstoneJSON dump (34k entries, 12.8 MB)
- Normalized fields: cost, attack/health, mechanics (taunt, divine shield, charge, rush, windfury, poisonous, lifesteal, stealth, deathrattle, battlecry, overload)
- Filtered to modeled mechanics only; unknown mechanics silently ignored
- Tests: 31 (unit + integration against real card data)

### 1.2 Game State Model ✅
- `hs_solver/state.py`
- `MinionInstance` — live board entity: current HP/ATK, divine shield, exhausted, attacks_used, frozen, silenced, taunt, stealth, immune, poisonous, lifesteal, instance_id
- `HeroInstance` — health, armor, weapon (attack + durability), hero power tracking
- `PlayerState` — deck/hand/board/graveyard, mana, overload, fatigue draw
- `GameState` — active/inactive player, turn counter, phase, win detection
- `new_game()` — shuffled decks, opening hands (P1 draws 3+1, P2 draws 4), mana ramp
- Fast `clone()` — custom implementation sharing immutable `Card` references (~5-8x faster than `deepcopy`)

### 1.3 Simplified Rules Engine ✅
- `hs_solver/rules.py`
- `play_minion()` — mana cost, hand removal, board placement, overload, charge/rush exhausted
- `play_spell()` — `SpellEffect` dispatch: DAMAGE_TARGET, DAMAGE_ALL_ENEMIES, DAMAGE_ALL, BUFF, SILENCE, DESTROY, HEAL, DRAW, GIVE_ARMOR
- `end_turn()` — phase transition, player swap, mana ramp, draw, minion refresh
- `use_hero_power()` — stub 2-damage implementation; full per-class effects in Phase 5

### 1.4 Combat System ✅
- `hs_solver/combat.py`
- `resolve_minion_vs_minion()` — simultaneous damage, divine shield, poisonous, lifesteal
- `resolve_minion_vs_hero()` — armor absorption, immune, lifesteal
- `resolve_hero_vs_minion()` — weapon attack, weapon durability, minion counterattack
- `resolve_hero_vs_hero()` — weapon face damage
- `process_deaths()` — board sweep → graveyard, hero death → GAME_OVER

### 1.5 State Validation ✅
- Integrated into `rules.py`
- `check_play_minion()`, `check_play_spell()`, `check_attack()`, `check_use_hero_power()`
- Taunt targeting enforcement, immune/stealth untargetable, rush hero restriction
- Exhausted, frozen, 0-attack minion guards

**Phase 1 tests: 148 passing**

---

## Phase 2 — Simulation Engine ✅ Complete

### 2.1 Action Generator ✅
- `hs_solver/actions.py`
- `Action` — frozen dataclass (all int/bool fields for hashability — CFR-ready)
- `ActionType`: PLAY_MINION, PLAY_SPELL, PLAY_WEAPON, ATTACK, USE_HERO_POWER, END_TURN
- `get_legal_actions(state, full_positions=False)`:
  - Single-pass indexed defender enumeration (no O(n) `list.index` calls)
  - `full_positions=True` for MCTS (one action per board insertion slot)
  - Rush hero-attack restriction enforced
- `apply_action()` — bypasses `check_attack` validation in hot rollout path (actions pre-validated)

### 2.2 Random Rollout Engine ✅
- `hs_solver/simulator.py`
- `random_rollout(state, max_turns=200, clone=True)` — uniform random policy
- `simulate_n(state, n)` — win rates, draws, timing stats
- `get_outcome(state, perspective)` — +1/-1/0 for MCTS backpropagation

### 2.3 Win Condition Detection ✅
- Hero death (combat) → `process_deaths()` sets `phase = GAME_OVER`
- Fatigue death → `start_turn()` sets `phase = GAME_OVER`
- `is_game_over` — O(1) phase check + direct health comparison (no `winner` recomputation in loop)
- Max turns safety cap in simulator

### 2.4 Deck Builder Interface ✅
- `hs_solver/deck.py`
- `decode_deck_string()` / `encode_deck_string()` — full HS varint + base64 codec
- Handles comment-prefixed deck strings (in-game copy format with `### Name` lines)
- `build_deck(card_db, deck_list)` — resolves IDs against CardDB, skips rotated cards with warning
- `random_deck(card_db, class, size, seed)` — reproducible random decks for simulation
- `validate_deck()` — size, copy limit, legendary cap checks

### 2.5 Benchmarking Harness ✅
- `scripts/benchmark.py` — `--n`, `--seed`, `--profile` flags
- Current baseline: **544 g/s** (Mage vs Warrior, 30-card random decks, Python 3.13)
- Phase 2 target was 1,000 g/s — 54% there
- Path to 1k: compact array-based board (Phase 3 optimization task)

**Phase 2 tests: 221 passing (+73)**

### Performance History
| Optimization | g/s |
|---|---|
| Initial naive implementation | 393 |
| Custom `clone()` sharing Card references | ~440 |
| Single-pass indexed attack generation (no `list.index`) | ~480 |
| `is_game_over` O(1) check (eager phase flag) | ~520 |
| `apply_action` bypasses `check_attack` | 544 |

---

## Phase 3 — RTA Decision Engine 🔜 Next

### 3.1 MCTS Core
- `hs_solver/mcts.py`
- UCB1 selection: `score = w/n + C * sqrt(ln(N)/n)`, default C = sqrt(2)
- Tree nodes: `MCTSNode(state_clone, action, parent, children, wins, visits)`
- Expand: get legal actions, create child nodes lazily
- Backpropagate: +1/0 win up the tree

### 3.2 Rollout Policy
- Start: uniform random (already implemented in simulator.py)
- Upgrade path: heuristic policy (see 3.3) — use heuristic to weight action selection in rollout

### 3.3 State Evaluator / Board Score Heuristic
- `hs_solver/evaluator.py`
- Inputs: my board, opponent board, hero HPs, hand sizes, mana differential
- Components:
  - **Tempo**: sum of (attack × health) for each friendly minion vs enemy
  - **Health differential**: my HP - opp HP
  - **Card advantage**: hand size difference (each card ~1.5 tempo equiv)
  - **Board control**: friendly minions with taunt, divine shield bonuses
- Output: single float, higher = better for active player
- Used by: MCTS rollout policy weighting, move ranker

### 3.4 Move Ranker
- Score all legal actions from a position
- Run MCTS from each resulting state for N iterations
- Rank by: visit count (most explored = most promising)
- Output: `[(action, score, confidence), ...]` sorted best→worst

### 3.5 Time Budget Manager
- `run_mcts(state, time_budget_sec=10.0)` — runs iterations until deadline
- Progress callback for live UI updates
- Minimum iterations guard (don't cut short under budget)

**Performance note for Phase 3:**
MCTS needs more rollouts than raw g/s benchmark shows because each branch requires a `clone()`. Target: 500–1000 MCTS iterations in a 10s RTA window = 50–100 rollouts/sec. Current 544 g/s baseline is sufficient for a functional MCTS; full 1k g/s becomes important at Phase 5 when running tournament simulations.

**Path to 1k+ g/s if needed:**
- Compact board representation: `board_attacks: list[int]`, `board_healths: list[int]` as raw arrays
- Eliminate dataclass attribute lookup overhead in hot path
- PyPy compatibility (already achievable, just swap interpreter)

---

## Phase 4 — GTO / EV Engine

### 4.1 Information Set Modeling
- Hidden info: opponent hand cards (known count, unknown identity)
- Opponent deck: probability distribution from meta snapshot (Phase 5)
- Abstract opponent hand as draw probabilities

### 4.2 CFR Implementation
- `hs_solver/cfr.py`
- Counterfactual Regret Minimization core
- Regret table: `dict[InfoSet, dict[Action, float]]` — Action is already hashable ✅
- Average strategy computation
- Tabular CFR for small games; deep CFR / neural extension for full Hearthstone

### 4.3 EV Calculator
- `expected_value(state, action, n_rollouts)` using MCTS win rates
- Multi-step lookahead EV tree

### 4.4 Strategy Distillation
- Convert Nash strategy tables into human-readable heuristics
- "Always attack face when ahead on board by 8+ tempo"

### 4.5 Exploitability Benchmarks
- Play Nash vs. random — measure win rate (should be >>50%)
- Play Nash vs. Nash — measure convergence to 50%

---

## Phase 5 — Meta Integration

### 5.1 HearthstoneJSON Pipeline
- `hs_solver/meta.py`
- Auto-pull latest card set on patch detection
- Compare dbfId sets between cached and live data

### 5.2 HSReplay Scraper
- Scrape top Legend decklists (public API or HTML)
- Store: deck code, class, archetype, win rate, games played, rank range, date

### 5.3 Meta Snapshot Model
- `P(opponent deck | observed cards)` — Bayesian update as cards are revealed
- Prior: HSReplay popularity weights
- Update: remove incompatible decklists as opponent plays cards

### 5.4 Deck Archetype Classifier
- Tag decklists: aggro / midrange / control / combo / tempo
- Features: avg mana cost, minion/spell ratio, win condition cards

### 5.5 Matchup Matrix Builder
- Simulate archetype × archetype at scale (Phase 2 simulator)
- Output: N×N win rate matrix for top-K archetypes

### 5.6 Spell Effect Wiring
- Map HearthstoneJSON card text → `SpellEffect` dataclass
- Regex + manual override registry for well-known cards
- Priority: high-play-rate cards first (top 100 by HSReplay appearance)

---

## Phase 6 — Interface Layer

### 6.1 CLI Interface
- `python -m hs_solver.cli --state game_state.json`
- Input: JSON game state (manual or from log parser)
- Output: ranked move list with scores

### 6.2 Log Parser
- Read `%AppData%/Hearthstone/Logs/Power.log`
- Parse `FULL_ENTITY`, `TAG_CHANGE`, `BLOCK_START` entries
- Maintain live `GameState` from log events

### 6.3 Overlay Prototype
- Minimal tkinter or web-based UI
- Show top-3 recommended actions with confidence %
- Update on each game log change

### 6.4 REST API
- `hs_solver/api.py` using FastAPI
- `POST /recommend` — takes game state JSON, returns ranked moves
- `POST /simulate` — win rate simulation for a given state

### 6.5 Export / Reporting
- Win rate reports by deck vs. meta snapshot
- Mulligan EV: expected value of keeping vs. replacing each opening card
- Matchup guides: "vs Aggro Demon Hunter: prioritize board clears"

---

## Known Issues / Technical Debt

| Issue | Severity | Phase to fix |
|---|---|---|
| Spell effects are no-ops in simulation | Medium | 5.6 |
| Hero powers all use generic 2-damage stub | Low | 5 |
| Deathrattles flagged but not resolved | Medium | 3–4 |
| Battlecry targets not prompted | Medium | 3 |
| Multi-class cards take first class only | Low | 5 |
| No coin (The Coin) for P2 opening hand | Low | 2.4 |
| Board position doesn't affect AoE targeting | Low | 3 |
| `random_deck` can build invalid decks (no class check on neutrals) | Low | 2.4 |

---

## File Structure

```
hs-ev-machine/
├── data/
│   ├── .gitkeep
│   └── cards.json              # fetched by scripts/fetch_cards.py (gitignored)
├── hs_solver/
│   ├── __init__.py
│   ├── card.py                 ✅ Phase 1.1
│   ├── state.py                ✅ Phase 1.2
│   ├── combat.py               ✅ Phase 1.4
│   ├── rules.py                ✅ Phase 1.3 + 1.5
│   ├── actions.py              ✅ Phase 2.1
│   ├── simulator.py            ✅ Phase 2.2 + 2.3
│   ├── deck.py                 ✅ Phase 2.4
│   ├── evaluator.py            🔜 Phase 3.3
│   ├── mcts.py                 🔜 Phase 3.1
│   ├── cfr.py                  🔜 Phase 4.2
│   └── meta.py                 🔜 Phase 5
├── tests/
│   ├── conftest.py
│   ├── test_card.py            ✅ 31 tests
│   ├── test_state.py           ✅ 42 tests
│   ├── test_combat.py          ✅ 26 tests
│   ├── test_rules.py           ✅ 49 tests
│   ├── test_actions.py         ✅ 37 tests
│   ├── test_simulator.py       ✅ 18 tests
│   └── test_deck.py            ✅ 18 tests
├── scripts/
│   ├── fetch_cards.py          ✅ Phase 1.1
│   └── benchmark.py            ✅ Phase 2.5
├── ROADMAP.md                  ← this file
├── README.md
└── requirements.txt
```

---

## Session Notes

### 2026-04-08/09 — Phase 1 + 2
- Built Phases 1.1 through 2.5 in a single session
- 221 tests, all passing
- Baseline performance: 544 g/s (Python 3.13, Windows 11)
- Key design choice: `Action` is frozen/hashable from day 1 — CFR strategy tables are a dict keyed on Action, so this needs to be true before Phase 4 locks in the format
- Overload bug found and fixed: single-pass `refresh_mana` applies overload on correct turn
- Performance profiling done: custom clone + indexed attack generation + eager game-over flag together brought 393 → 544 g/s
