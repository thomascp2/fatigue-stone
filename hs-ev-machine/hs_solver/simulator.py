"""
Phase 2.2 + 2.3 — Random Rollout Engine and Win Condition Detection

random_rollout():
  Clone the state, then loop: pick a random legal action, apply it,
  until the game is over or max_turns is hit. Returns the winner.

simulate_n():
  Run N rollouts from the same starting state and return win/draw rates.
  Useful for building win-rate estimates before MCTS is implemented.

Win conditions (all handled through state.winner + state.is_game_over):
  - Hero health <= 0 (hero death)
  - Both heroes die simultaneously → active player's opponent wins
  - Fatigue damage takes a hero to 0
  - max_turns hit → treated as a draw (neither player can force a win)

Performance notes:
  The deepcopy in clone() is the bottleneck. For Phase 2 targets (1k+ g/s)
  we need the per-turn loop to be fast. Each rollout is ~60-150 actions on
  random decks. Profiling will guide Phase 3 optimizations (e.g., a compact
  array-based state representation).
"""

from __future__ import annotations

import random
import time
from typing import Optional

from hs_solver.actions import get_legal_actions, apply_action
from hs_solver.state import GameState, PlayerID


# ---------------------------------------------------------------------------
# Core rollout
# ---------------------------------------------------------------------------


def random_rollout(
    state: GameState,
    max_turns: int = 200,
    clone: bool = True,
) -> Optional[PlayerID]:
    """
    Simulate one game to completion using uniformly random action selection.

    Args:
        state:     Starting game state.
        max_turns: Safety cap to prevent infinite games (fatigue should end
                   most games well before this).
        clone:     If True (default), deepcopy state before rolling out so
                   the original is unchanged. Set False when the caller already
                   manages cloning (e.g., the simulator creates fresh states).

    Returns:
        PlayerID of the winner, or None if the game ended in a draw
        (simultaneous hero death or max_turns hit without a winner).
    """
    s = state.clone() if clone else state

    while not s.is_game_over and s.turn <= max_turns:
        actions = get_legal_actions(s)
        if not actions:
            # Should not happen: get_legal_actions always includes END_TURN
            break
        action = random.choice(actions)
        apply_action(s, action)

    return s.winner


# ---------------------------------------------------------------------------
# Multi-rollout aggregation
# ---------------------------------------------------------------------------


def simulate_n(
    state: GameState,
    n: int,
    max_turns: int = 200,
) -> dict:
    """
    Run N random rollouts from the given state and aggregate outcomes.

    Returns:
        {
          "n":        int      — number of rollouts
          "p1_wins":  int      — games won by P1
          "p2_wins":  int      — games won by P2
          "draws":    int      — draws (simultaneous death / max_turns)
          "p1_winrate": float  — fraction of decisive games won by P1
          "p2_winrate": float  — fraction of decisive games won by P2
          "elapsed_s": float   — total wall time in seconds
          "games_per_sec": float
        }
    """
    p1_wins = 0
    p2_wins = 0
    draws = 0

    t0 = time.perf_counter()
    for _ in range(n):
        winner = random_rollout(state, max_turns=max_turns, clone=True)
        if winner == PlayerID.P1:
            p1_wins += 1
        elif winner == PlayerID.P2:
            p2_wins += 1
        else:
            draws += 1
    elapsed = time.perf_counter() - t0

    decisive = p1_wins + p2_wins
    return {
        "n": n,
        "p1_wins": p1_wins,
        "p2_wins": p2_wins,
        "draws": draws,
        "p1_winrate": p1_wins / decisive if decisive else 0.0,
        "p2_winrate": p2_wins / decisive if decisive else 0.0,
        "elapsed_s": elapsed,
        "games_per_sec": n / elapsed if elapsed > 0 else float("inf"),
    }


# ---------------------------------------------------------------------------
# Win condition helpers (exposed for external use)
# ---------------------------------------------------------------------------


def is_terminal(state: GameState) -> bool:
    """Return True if the game has ended."""
    return state.is_game_over


def get_outcome(state: GameState, perspective: PlayerID) -> float:
    """
    Return the outcome from `perspective`'s point of view.

    Used by MCTS backpropagation (Phase 3):
      +1.0  — perspective player won
      -1.0  — perspective player lost
       0.0  — draw or game not over
    """
    w = state.winner
    if w is None:
        return 0.0
    return 1.0 if w == perspective else -1.0
