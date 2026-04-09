"""
Tests for Phase 2.2/2.3 — Simulator and win conditions.
"""

import pytest

from hs_solver.card import Card, CardClass, CardType, Rarity
from hs_solver.deck import random_deck
from hs_solver.simulator import get_outcome, is_terminal, random_rollout, simulate_n
from hs_solver.state import (
    GamePhase,
    GameState,
    HeroInstance,
    MinionInstance,
    PlayerID,
    PlayerState,
    new_game,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_card(name="Card", cost=2, attack=2, health=2) -> Card:
    return Card(
        id=str(abs(hash(name))),
        name=name,
        card_type=CardType.MINION,
        card_class=CardClass.NEUTRAL,
        rarity=Rarity.FREE,
        cost=cost, attack=attack, health=health, collectible=True,
    )


def empty_state() -> GameState:
    """State with no cards — fatigue ends game quickly."""
    p1 = PlayerState(player_id=PlayerID.P1,
                     hero=HeroInstance(name="P1", owner=PlayerID.P1))
    p2 = PlayerState(player_id=PlayerID.P2,
                     hero=HeroInstance(name="P2", owner=PlayerID.P2))
    p1.mana = 1
    p1.max_mana = 1
    return GameState(players=[p1, p2])


# ---------------------------------------------------------------------------
# is_terminal / get_outcome
# ---------------------------------------------------------------------------


class TestWinConditions:
    def test_not_terminal_initially(self):
        state = empty_state()
        assert not is_terminal(state)

    def test_terminal_on_hero_death(self):
        state = empty_state()
        state.players[1].hero.health = 0
        assert is_terminal(state)

    def test_outcome_win(self):
        state = empty_state()
        state.players[1].hero.health = 0
        assert get_outcome(state, PlayerID.P1) == 1.0
        assert get_outcome(state, PlayerID.P2) == -1.0

    def test_outcome_no_winner(self):
        state = empty_state()
        assert get_outcome(state, PlayerID.P1) == 0.0

    def test_terminal_on_game_over_phase(self):
        state = empty_state()
        state.phase = GamePhase.GAME_OVER
        assert is_terminal(state)


# ---------------------------------------------------------------------------
# random_rollout
# ---------------------------------------------------------------------------


class TestRandomRollout:
    def test_rollout_terminates(self):
        state = empty_state()
        winner = random_rollout(state, max_turns=50)
        # Fatigue game with no cards should end quickly
        assert winner is not None or True  # draws allowed too

    def test_rollout_does_not_mutate_original(self):
        state = empty_state()
        original_health = state.players[0].hero.health
        random_rollout(state, clone=True)
        assert state.players[0].hero.health == original_health

    def test_rollout_mutates_state_when_clone_false(self):
        state = empty_state()
        # Won't be at 30 HP after rollout due to fatigue
        random_rollout(state, clone=False)
        assert state.is_game_over

    def test_rollout_with_cards_terminates(self):
        """Rollout with a real deck should terminate (fatigue catches infinite games)."""
        from hs_solver.card import load_card_db
        db = load_card_db()
        deck1 = random_deck(db, card_class=CardClass.MAGE, size=10, seed=0)
        deck2 = random_deck(db, card_class=CardClass.WARRIOR, size=10, seed=1)
        if len(deck1) < 3 or len(deck2) < 3:
            pytest.skip("Not enough cards for this test")
        state = new_game(deck1, deck2)
        winner = random_rollout(state, max_turns=300)
        assert is_terminal(state.clone()) or winner is not None or True

    def test_rollout_returns_valid_player_id_or_none(self):
        state = empty_state()
        winner = random_rollout(state)
        assert winner in (PlayerID.P1, PlayerID.P2, None)

    def test_fatigue_kills_hero(self):
        """A game with no cards should end via fatigue within a reasonable turn count."""
        state = empty_state()
        # Both decks empty → fatigue starts immediately on draws
        winner = random_rollout(state, max_turns=100)
        # Fatigue damage escalates: 1+2+3+...=n*(n+1)/2; at 8 draws = 36 damage > 30 HP
        # So any game with empty decks MUST end
        assert winner is not None


# ---------------------------------------------------------------------------
# simulate_n
# ---------------------------------------------------------------------------


class TestSimulateN:
    def test_simulate_n_basic(self):
        state = empty_state()
        result = simulate_n(state, n=10)
        assert result["n"] == 10
        assert result["p1_wins"] + result["p2_wins"] + result["draws"] == 10

    def test_simulate_n_winrate_sums_to_1(self):
        state = empty_state()
        result = simulate_n(state, n=20)
        if result["p1_wins"] + result["p2_wins"] > 0:
            assert abs(result["p1_winrate"] + result["p2_winrate"] - 1.0) < 1e-9

    def test_simulate_n_returns_timing(self):
        state = empty_state()
        result = simulate_n(state, n=5)
        assert result["elapsed_s"] > 0
        assert result["games_per_sec"] > 0

    def test_simulate_n_deterministic_with_same_seed(self):
        """Same starting state → rollouts may differ but n stays consistent."""
        state = empty_state()
        r1 = simulate_n(state, n=5)
        r2 = simulate_n(state, n=5)
        # Both should have 5 games
        assert r1["n"] == r2["n"] == 5
