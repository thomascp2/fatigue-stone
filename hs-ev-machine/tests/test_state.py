"""
Tests for Phase 1.2 — GameState model.
"""

import pytest

from hs_solver.card import Card, CardClass, CardType, Rarity
from hs_solver.state import (
    GamePhase,
    GameState,
    HeroInstance,
    MinionInstance,
    PlayerID,
    PlayerState,
    new_game,
    MAX_BOARD_SIZE,
    MAX_HAND_SIZE,
)


# ---------------------------------------------------------------------------
# Card fixtures
# ---------------------------------------------------------------------------


def make_minion(name="Test Minion", cost=2, attack=2, health=2, **kwargs) -> Card:
    return Card(
        id=str(hash(name)),
        name=name,
        card_type=CardType.MINION,
        card_class=CardClass.NEUTRAL,
        rarity=Rarity.FREE,
        cost=cost,
        attack=attack,
        health=health,
        collectible=True,
        **kwargs,
    )


def make_spell(name="Test Spell", cost=3) -> Card:
    return Card(
        id=str(hash(name)),
        name=name,
        card_type=CardType.SPELL,
        card_class=CardClass.NEUTRAL,
        rarity=Rarity.FREE,
        cost=cost,
        collectible=True,
    )


def make_deck(size=20) -> list[Card]:
    return [make_minion(name=f"Card{i}", cost=i % 10) for i in range(size)]


# ---------------------------------------------------------------------------
# HeroInstance tests
# ---------------------------------------------------------------------------


class TestHeroInstance:
    def setup_method(self):
        self.hero = HeroInstance(name="Jaina", owner=PlayerID.P1)

    def test_initial_health(self):
        assert self.hero.health == 30
        assert self.hero.armor == 0

    def test_take_damage_no_armor(self):
        self.hero.take_damage(10)
        assert self.hero.health == 20

    def test_take_damage_armor_absorbs(self):
        self.hero.armor = 5
        self.hero.take_damage(3)
        assert self.hero.armor == 2
        assert self.hero.health == 30

    def test_take_damage_armor_partial(self):
        self.hero.armor = 3
        self.hero.take_damage(8)
        assert self.hero.armor == 0
        assert self.hero.health == 25

    def test_heal_capped_at_max(self):
        self.hero.take_damage(5)
        self.hero.heal(10)
        assert self.hero.health == 30  # capped at max

    def test_is_alive(self):
        assert self.hero.is_alive
        self.hero.health = 0
        assert not self.hero.is_alive

    def test_weapon_attack(self):
        self.hero.equip_weapon(3, 2)
        assert self.hero.attack == 3
        assert self.hero.can_attack

    def test_weapon_degrades(self):
        self.hero.equip_weapon(3, 2)
        self.hero.use_weapon_attack()
        assert self.hero.weapon_durability == 1
        self.hero.refresh_for_turn()
        self.hero.use_weapon_attack()
        assert self.hero.weapon_durability == 0
        assert self.hero.weapon_attack == 0

    def test_refresh_resets_attacks(self):
        self.hero.equip_weapon(3, 3)
        self.hero.attacks_used = 1
        self.hero.refresh_for_turn()
        assert self.hero.attacks_used == 0

    def test_immune_blocks_damage(self):
        self.hero.immune = True
        self.hero.take_damage(99)
        assert self.hero.health == 30


# ---------------------------------------------------------------------------
# MinionInstance tests
# ---------------------------------------------------------------------------


class TestMinionInstance:
    def setup_method(self):
        self.card = make_minion("Yeti", cost=4, attack=4, health=5)
        self.minion = MinionInstance(card=self.card, owner=PlayerID.P1)

    def test_initial_stats(self):
        assert self.minion.current_attack == 4
        assert self.minion.current_health == 5
        assert self.minion.exhausted is True

    def test_charge_not_exhausted(self):
        from hs_solver.card import Card
        card = make_minion("Charge Minion", cost=3, attack=3, health=2)
        card.mechanics.add("CHARGE")
        m = MinionInstance(card=card, owner=PlayerID.P1)
        assert m.exhausted is False
        assert m.can_attack

    def test_rush_not_exhausted(self):
        card = make_minion("Rush Minion", cost=3, attack=3, health=2)
        card.mechanics.add("RUSH")
        m = MinionInstance(card=card, owner=PlayerID.P1)
        assert m.exhausted is False
        assert m.has_rush

    def test_take_damage(self):
        dmg = self.minion.take_damage(3)
        assert dmg == 3
        assert self.minion.current_health == 2

    def test_divine_shield_absorbs(self):
        card = make_minion("DS Minion", attack=2, health=3)
        card.mechanics.add("DIVINE_SHIELD")
        m = MinionInstance(card=card, owner=PlayerID.P1)
        assert m.divine_shield
        dmg = m.take_damage(5)
        assert dmg == 0
        assert m.current_health == 3
        assert not m.divine_shield

    def test_divine_shield_second_hit(self):
        card = make_minion("DS Minion", attack=2, health=3)
        card.mechanics.add("DIVINE_SHIELD")
        m = MinionInstance(card=card, owner=PlayerID.P1)
        m.take_damage(5)  # pops shield
        m.take_damage(2)  # now takes damage
        assert m.current_health == 1

    def test_silence_removes_keywords(self):
        card = make_minion("Taunt Minion", attack=2, health=4)
        card.mechanics.update({"TAUNT", "DIVINE_SHIELD", "STEALTH"})
        m = MinionInstance(card=card, owner=PlayerID.P1)
        m.silence()
        assert not m.taunt
        assert not m.divine_shield
        assert not m.stealth
        assert m.silenced

    def test_silence_preserves_stats(self):
        card = make_minion("Big Guy", attack=5, health=10)
        card.mechanics.add("TAUNT")
        m = MinionInstance(card=card, owner=PlayerID.P1)
        m.silence()
        assert m.current_attack == 5
        assert m.current_health == 10

    def test_heal_capped_at_max(self):
        self.minion.take_damage(3)
        self.minion.heal(100)
        assert self.minion.current_health == self.minion.max_health

    def test_refresh_for_turn(self):
        self.minion.exhausted = True
        self.minion.attacks_used = 2
        self.minion.frozen = True
        self.minion.refresh_for_turn()
        assert not self.minion.exhausted
        assert self.minion.attacks_used == 0
        assert not self.minion.frozen

    def test_windfury_attacks_per_turn(self):
        card = make_minion("Windfury", attack=3, health=3)
        card.mechanics.add("WINDFURY")
        m = MinionInstance(card=card, owner=PlayerID.P1)
        assert m.card.attacks_per_turn == 2

    def test_is_alive(self):
        assert self.minion.is_alive
        self.minion.current_health = 0
        assert not self.minion.is_alive

    def test_immune_blocks_damage(self):
        self.minion.immune = True
        dmg = self.minion.take_damage(99)
        assert dmg == 0
        assert self.minion.current_health == 5


# ---------------------------------------------------------------------------
# PlayerState tests
# ---------------------------------------------------------------------------


class TestPlayerState:
    def setup_method(self):
        self.hero = HeroInstance(name="Rexxar", owner=PlayerID.P1)
        self.player = PlayerState(player_id=PlayerID.P1, hero=self.hero)

    def test_gain_mana_crystal(self):
        self.player.gain_mana_crystal()
        assert self.player.max_mana == 1

    def test_mana_capped_at_10(self):
        for _ in range(15):
            self.player.gain_mana_crystal()
        assert self.player.max_mana == 10

    def test_draw_card_adds_to_hand(self):
        cards = make_deck(5)
        self.player.deck = list(cards)
        drawn = self.player.draw_card()
        assert drawn is not None
        assert drawn in self.player.hand
        assert len(self.player.deck) == 4

    def test_draw_empty_deck_fatigue(self):
        self.player.deck = []
        drawn = self.player.draw_card()
        assert drawn is None
        assert self.player.fatigue == 1
        assert self.hero.health == 29  # took 1 fatigue damage

    def test_fatigue_escalates(self):
        self.player.deck = []
        self.player.draw_card()  # 1
        self.player.draw_card()  # 2
        self.player.draw_card()  # 3
        assert self.player.fatigue == 3
        assert self.hero.health == 30 - (1 + 2 + 3)

    def test_overdraw_burns_card(self):
        self.player.hand = make_deck(MAX_HAND_SIZE)
        self.player.deck = [make_minion("Burnt Card")]
        drawn = self.player.draw_card()
        assert drawn is None  # burned
        assert len(self.player.hand) == MAX_HAND_SIZE

    def test_board_full(self):
        for i in range(MAX_BOARD_SIZE):
            m = MinionInstance(card=make_minion(f"M{i}"), owner=PlayerID.P1)
            self.player.board.append(m)
        assert self.player.board_full

    def test_overload_refresh(self):
        # mana_overloaded is set during a turn when overload cards are played.
        # On the NEXT call to refresh_mana (start of their next turn),
        # those crystals are locked (mana reduced).
        self.player.max_mana = 5
        self.player.mana_overloaded = 2
        self.player.refresh_mana()
        assert self.player.mana == 3           # 5 - 2 locked
        assert self.player.mana_overloaded == 0  # cleared for this turn
        # Next turn with no overload
        self.player.refresh_mana()
        assert self.player.mana == 5
        assert self.player.mana_locked == 0


# ---------------------------------------------------------------------------
# GameState tests
# ---------------------------------------------------------------------------


class TestGameState:
    def setup_method(self):
        self.deck1 = make_deck(20)
        self.deck2 = make_deck(20)

    def test_new_game_creates_state(self):
        state = new_game(self.deck1, self.deck2)
        assert state.turn == 1
        assert state.active_player_id == PlayerID.P1
        assert state.phase == GamePhase.MAIN

    def test_opening_hands(self):
        state = new_game(self.deck1, self.deck2)
        # P1: drew 3 (mulligan) + 1 (turn start) = 4 cards
        # P2: drew 4 (mulligan) but hasn't started their turn yet = 4 cards
        assert len(state.players[0].hand) == 4
        assert len(state.players[1].hand) == 4

    def test_p1_starts_with_1_mana(self):
        state = new_game(self.deck1, self.deck2)
        assert state.active_player.mana == 1

    def test_active_inactive_player(self):
        state = new_game(self.deck1, self.deck2)
        assert state.active_player is state.players[0]
        assert state.inactive_player is state.players[1]

    def test_end_turn_swaps_player(self):
        state = new_game(self.deck1, self.deck2)
        state.end_turn()
        assert state.active_player_id == PlayerID.P2

    def test_p2_gets_1_mana_on_their_first_turn(self):
        # Both players get 1 mana crystal on "turn 1" — P2 is no different.
        # P2 gains their first crystal when their turn starts, same as P1.
        state = new_game(self.deck1, self.deck2)
        state.end_turn()
        assert state.active_player.mana == 1

    def test_turn_counter_increments_after_p2(self):
        state = new_game(self.deck1, self.deck2)
        assert state.turn == 1
        state.end_turn()  # P2's turn
        assert state.turn == 1
        state.end_turn()  # Back to P1, turn 2
        assert state.turn == 2

    def test_summon_minion(self):
        state = new_game(self.deck1, self.deck2)
        card = make_minion("Test", attack=3, health=3)
        m = state.summon_minion(card, PlayerID.P1)
        assert m in state.players[0].board
        assert m.instance_id > 0

    def test_summon_minion_board_full_raises(self):
        state = new_game(self.deck1, self.deck2)
        for i in range(MAX_BOARD_SIZE):
            state.summon_minion(make_minion(f"M{i}"), PlayerID.P1)
        with pytest.raises(AssertionError):
            state.summon_minion(make_minion("overflow"), PlayerID.P1)

    def test_remove_minion_goes_to_graveyard(self):
        state = new_game(self.deck1, self.deck2)
        card = make_minion("Doomed")
        m = state.summon_minion(card, PlayerID.P1)
        state.remove_minion(m)
        assert m not in state.players[0].board
        assert m in state.players[0].graveyard

    def test_winner_detection_p1_dead(self):
        state = new_game(self.deck1, self.deck2)
        state.players[0].hero.health = 0
        assert state.winner == PlayerID.P2

    def test_winner_detection_p2_dead(self):
        state = new_game(self.deck1, self.deck2)
        state.players[1].hero.health = 0
        assert state.winner == PlayerID.P1

    def test_no_winner_initially(self):
        state = new_game(self.deck1, self.deck2)
        assert state.winner is None
        assert not state.is_game_over

    def test_clone_is_independent(self):
        state = new_game(self.deck1, self.deck2)
        clone = state.clone()
        clone.players[0].hero.health = 5
        assert state.players[0].hero.health == 30  # original unchanged

    def test_player_id_opponent(self):
        assert PlayerID.P1.opponent == PlayerID.P2
        assert PlayerID.P2.opponent == PlayerID.P1
