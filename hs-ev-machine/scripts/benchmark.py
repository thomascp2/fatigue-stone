"""
Phase 2.5 — Benchmarking Harness

Measures random rollout speed (games/sec) to track performance against the
Phase 2 target of 1,000+ games/sec.

Usage:
    python scripts/benchmark.py
    python scripts/benchmark.py --n 500 --seed 42
    python scripts/benchmark.py --profile   # cProfile output

Output:
    Per-game timing, games/sec, and a per-action breakdown.
"""

import argparse
import cProfile
import io
import pstats
import sys
import time
from pathlib import Path

# Ensure the project root is on the path when running as a script
sys.path.insert(0, str(Path(__file__).parent.parent))

from hs_solver.card import load_card_db, CardClass
from hs_solver.deck import random_deck
from hs_solver.simulator import random_rollout, simulate_n
from hs_solver.state import new_game, PlayerID


def run_benchmark(n: int = 200, seed: int = 0, verbose: bool = True) -> dict:
    """
    Run N rollouts with randomly-built decks and report performance.

    Returns the simulate_n() result dict augmented with per-game stats.
    """
    if verbose:
        print(f"Loading card database...")
    db = load_card_db()

    if verbose:
        print(f"Building random decks (seed={seed})...")
    deck1 = random_deck(db, card_class=CardClass.MAGE, size=30, seed=seed)
    deck2 = random_deck(db, card_class=CardClass.WARRIOR, size=30, seed=seed + 1)

    if verbose:
        print(f"Deck 1: {len(deck1)} cards ({CardClass.MAGE.value})")
        print(f"Deck 2: {len(deck2)} cards ({CardClass.WARRIOR.value})")
        print(f"\nRunning {n} rollouts...")

    # Create one starting state (will be cloned for each rollout inside simulate_n)
    state = new_game(deck1, deck2, hero1_name="Jaina", hero2_name="Garrosh")

    results = simulate_n(state, n=n)

    if verbose:
        _print_results(results)

    return results


def _print_results(r: dict) -> None:
    n = r["n"]
    elapsed = r["elapsed_s"]
    gps = r["games_per_sec"]
    p1wr = r["p1_winrate"] * 100
    p2wr = r["p2_winrate"] * 100

    print("\n" + "=" * 50)
    print(f"  Rollouts:        {n}")
    print(f"  P1 wins:         {r['p1_wins']} ({p1wr:.1f}%)")
    print(f"  P2 wins:         {r['p2_wins']} ({p2wr:.1f}%)")
    print(f"  Draws:           {r['draws']}")
    print(f"  Total time:      {elapsed:.2f}s")
    print(f"  Games/sec:       {gps:,.1f}")
    print("=" * 50)

    target = 1_000
    if gps >= target:
        print(f"  Phase 2 target ({target:,} g/s): MET")
    else:
        pct = gps / target * 100
        print(f"  Phase 2 target ({target:,} g/s): {pct:.0f}% — optimization needed")


def run_profile(n: int = 50) -> None:
    """Run a cProfile pass and print the top 20 hotspots."""
    db = load_card_db()
    deck1 = random_deck(db, card_class=CardClass.MAGE, size=30, seed=0)
    deck2 = random_deck(db, card_class=CardClass.WARRIOR, size=30, seed=1)
    state = new_game(deck1, deck2)

    pr = cProfile.Profile()
    pr.enable()
    for _ in range(n):
        random_rollout(state, clone=True)
    pr.disable()

    s = io.StringIO()
    ps = pstats.Stats(pr, stream=s).sort_stats("cumulative")
    ps.print_stats(20)
    print(s.getvalue())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HS Solver benchmarking harness.")
    parser.add_argument("--n", type=int, default=200, help="Number of rollouts.")
    parser.add_argument("--seed", type=int, default=0, help="RNG seed.")
    parser.add_argument("--profile", action="store_true", help="Run cProfile.")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    if args.profile:
        run_profile(n=args.n)
    else:
        run_benchmark(n=args.n, seed=args.seed, verbose=not args.quiet)
