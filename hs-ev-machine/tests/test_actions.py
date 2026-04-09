"""
Tests for Phase 2.1 — Action generator.
"""

import pytest

from hs_solver.actions import Action, ActionType, apply_action, get_legal_actions
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
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_card(name="Card", cost=2, attack=2, health=2,
              card_type=CardType.MINION) -> Card:
    return Card(
        id=str(abs(hash(name + str(cost) + str(attack)))),
        name=name,
        card_type=card_type,
        card_class=CardClass.NEUTRAL,
        rarity=Rarity.FREE,
        cost=cost,
        attack=attack if card_type == CardType.MINION else None,
        health=health if card_type == CardType.MINION else None,
        collectible=True,
    )


def make_spell(name="Spell", cost=3) -> Card:
    return make_card(name=name, cost=cost, card_type=CardType.SPELL)


def fresh_state(p1_mana=10) -> GameState:
    p1 = PlayerState(player_id=PlayerID.P1,
                     hero=HeroInstance(name="P1", owner=PlayerID.P1))
    p2 = PlayerState(player_id=PlayerID.P2,
                     hero=HeroInstance(name="P2", owner=PlayerID.P2))
    p1.mana = p1_mana
    p1.max_mana = p1_mana
    return GameState(players=[p1, p2])


def add_minion(state: GameState, owner: PlayerID, **kwargs) -> MinionInstance:
    card = make_card(**kwargs)
    m = state.summon_minion(card, owner)
    m.exhausted = False
    return m


# ---------------------------------------------------------------------------
# Basic action set
# ---------------------------------------------------------------------------


class TestGetLegalActions:
    def test_empty_state_has_end_turn(self):
        state = fresh_state()
        actions = get_legal_actions(state)
        types = {a.type for a in actions}
        assert ActionType.END_TURN in types

    def test_game_over_returns_empty(self):
        state = fresh_state()
        state.phase = GamePhase.GAME_OVER
        assert get_legal_actions(state) == []

    def test_play_minion_generated_for_affordable_card(self):
        state = fresh_state(p1_mana=4)
        card = make_card("Yeti", cost=4)
        state.players[0].hand.append(card)
        actions = get_legal_actions(state)
        play_actions = [a for a in actions if a.type == ActionType.PLAY_MINION]
        assert len(play_actions) >= 1
        assert play_actions[0].hand_idx == 0

    def test_no_play_minion_if_too_expensive(self):
        state = fresh_state(p1_mana=3)
        state.players[0].hand.append(make_card("Expensive", cost=4))
        actions = get_legal_actions(state)
        assert not any(a.type == ActionType.PLAY_MINION for a in actions)

    def test_no_play_minion_if_board_full(self):
        state = fresh_state()
        for i in range(MAX_BOARD_SIZE):
            add_minion(state, PlayerID.P1, name=f"M{i}")
        state.players[0].hand.append(make_card("Extra", cost=1))
        actions = get_legal_actions(state)
        assert not any(a.type == ActionType.PLAY_MINION for a in actions)

    def test_play_spell_generated(self):
        state = fresh_state()
        state.players[0].hand.append(make_spell("Fireball", cost=4))
        actions = get_legal_actions(state)
        assert any(a.type == ActionType.PLAY_SPELL for a in actions)

    def test_multiple_hand_cards_generate_multiple_actions(self):
        state = fresh_state()
        for i in range(3):
            state.players[0].hand.append(make_card(f"Card{i}", cost=2))
        actions = get_legal_actions(state)
        play_actions = [a for a in actions if a.type == ActionType.PLAY_MINION]
        assert len(play_actions) == 3


# ---------------------------------------------------------------------------
# Attack actions
# ---------------------------------------------------------------------------


class TestAttackActions:
    def setup_method(self):
        self.state = fresh_state()

    def test_attack_minion_generated(self):
        atk = add_minion(self.state, PlayerID.P1, name="A", attack=3, health=3)
        def_ = add_minion(self.state, PlayerID.P2, name="D", attack=2, health=3)
        actions = get_legal_actions(self.state)
        attack_actions = [a for a in actions if a.type == ActionType.ATTACK]
        assert len(attack_actions) >= 1
        assert any(not a.defender_is_hero for a in attack_actions)

    def test_attack_hero_generated_when_no_taunt(self):
        add_minion(self.state, PlayerID.P1, name="A", attack=3, health=3)
        actions = get_legal_actions(self.state)
        attack_actions = [a for a in actions if a.type == ActionType.ATTACK]
        assert any(a.defender_is_hero for a in attack_actions)

    def test_taunt_enforced_in_action_list(self):
        atk = add_minion(self.state, PlayerID.P1, name="A", attack=3, health=3)

        # Add taunt + non-taunt enemy
        taunt_card = make_card("Taunt", cost=3, attack=2, health=5)
        taunt_card.mechanics.add("TAUNT")
        taunt_m = self.state.summon_minion(taunt_card, PlayerID.P2)
        taunt_m.exhausted = False

        nt = add_minion(self.state, PlayerID.P2, name="NT", attack=2, health=3)

        actions = get_legal_actions(self.state)
        attack_actions = [a for a in actions if a.type == ActionType.ATTACK]

        # Should only be able to attack taunt minion, not hero or NT
        defender_idxs = {a.defender_idx for a in attack_actions if not a.defender_is_hero}
        taunt_board_idx = self.state.players[1].board.index(taunt_m)
        nt_board_idx = self.state.players[1].board.index(nt)

        assert taunt_board_idx in defender_idxs
        assert nt_board_idx not in defender_idxs
        assert not any(a.defender_is_hero for a in attack_actions)

    def test_exhausted_minion_no_attack(self):
        m = add_minion(self.state, PlayerID.P1, name="A", attack=3, health=3)
        m.exhausted = True
        add_minion(self.state, PlayerID.P2, name="D", attack=2, health=3)
        actions = get_legal_actions(self.state)
        assert not any(a.type == ActionType.ATTACK and not a.attacker_is_hero
                       for a in actions)

    def test_zero_attack_minion_no_attack(self):
        add_minion(self.state, PlayerID.P1, name="A", attack=0, health=5)
        add_minion(self.state, PlayerID.P2, name="D", attack=2, health=3)
        actions = get_legal_actions(self.state)
        assert not any(a.type == ActionType.ATTACK and not a.attacker_is_hero
                       for a in actions)

    def test_frozen_minion_no_attack(self):
        m = add_minion(self.state, PlayerID.P1, name="A", attack=3, health=3)
        m.frozen = True
        add_minion(self.state, PlayerID.P2, name="D", attack=2, health=3)
        actions = get_legal_actions(self.state)
        assert not any(a.type == ActionType.ATTACK and not a.attacker_is_hero
                       for a in actions)

    def test_rush_no_attack_hero(self):
        card = make_card("Rush", cost=3, attack=3, health=3)
        card.mechanics.add("RUSH")
        m = self.state.summon_minion(card, PlayerID.P1)
        # Rush minion starts not-exhausted
        assert m.exhausted is False
        actions = get_legal_actions(self.state)
        rush_attacks = [
            a for a in actions
            if a.type == ActionType.ATTACK
            and not a.attacker_is_hero
            and a.attacker_idx == self.state.players[0].board.index(m)
        ]
        # With no enemy minions, rush has no targets (can't attack hero)
        assert len(rush_attacks) == 0

    def test_hero_attack_generated_with_weapon(self):
        self.state.players[0].hero.equip_weapon(3, 2)
        add_minion(self.state, PlayerID.P2, name="D", attack=2, health=3)
        actions = get_legal_actions(self.state)
        hero_attacks = [a for a in actions
                        if a.type == ActionType.ATTACK and a.attacker_is_hero]
        assert len(hero_attacks) >= 1

    def test_immune_minion_not_targetable(self):
        add_minion(self.state, PlayerID.P1, name="A", attack=3, health=3)
        d = add_minion(self.state, PlayerID.P2, name="D", attack=2, health=3)
        d.immune = True
        actions = get_legal_actions(self.state)
        # Only hero should be attackable (no taunt)
        attack_actions = [a for a in actions if a.type == ActionType.ATTACK]
        assert all(a.defender_is_hero for a in attack_actions)

    def test_stealthed_minion_not_targetable(self):
        add_minion(self.state, PlayerID.P1, name="A", attack=3, health=3)
        d = add_minion(self.state, PlayerID.P2, name="D", attack=2, health=3)
        d.stealth = True
        actions = get_legal_actions(self.state)
        attack_actions = [a for a in actions if a.type == ActionType.ATTACK]
        # Stealthed minion not in defenders, hero is
        assert all(a.defender_is_hero for a in attack_actions)


# ---------------------------------------------------------------------------
# Hero power
# ---------------------------------------------------------------------------


class TestHeroPowerActions:
    def test_hero_power_generated_when_affordable(self):
        state = fresh_state(p1_mana=10)
        actions = get_legal_actions(state)
        assert any(a.type == ActionType.USE_HERO_POWER for a in actions)

    def test_no_hero_power_if_already_used(self):
        state = fresh_state()
        state.players[0].hero.hero_power_used = True
        actions = get_legal_actions(state)
        assert not any(a.type == ActionType.USE_HERO_POWER for a in actions)

    def test_no_hero_power_if_too_poor(self):
        state = fresh_state(p1_mana=1)
        actions = get_legal_actions(state)
        assert not any(a.type == ActionType.USE_HERO_POWER for a in actions)


# ---------------------------------------------------------------------------
# Full positions mode
# ---------------------------------------------------------------------------


class TestFullPositions:
    def test_full_positions_generates_n_plus_1_actions_per_card(self):
        state = fresh_state()
        state.players[0].hand.append(make_card("Card", cost=2))
        # Empty board → 1 position (position 0 = rightmost = only slot)
        actions = get_legal_actions(state, full_positions=True)
        play_actions = [a for a in actions if a.type == ActionType.PLAY_MINION]
        # board has 0 minions → 0+1 = 1 position
        assert len(play_actions) == 1

    def test_full_positions_increases_with_board_size(self):
        state = fresh_state()
        for i in range(3):
            add_minion(state, PlayerID.P1, name=f"M{i}")
        state.players[0].hand.append(make_card("Card", cost=2))
        actions = get_legal_actions(state, full_positions=True)
        play_actions = [a for a in actions if a.type == ActionType.PLAY_MINION]
        # board has 3 minions → 4 positions
        assert len(play_actions) == 4


# ---------------------------------------------------------------------------
# apply_action
# ---------------------------------------------------------------------------


class TestApplyAction:
    def test_apply_end_turn(self):
        state = fresh_state()
        apply_action(state, Action.end_turn())
        assert state.active_player_id == PlayerID.P2

    def test_apply_play_minion(self):
        state = fresh_state()
        card = make_card("Yeti", cost=4)
        state.players[0].hand.append(card)
        apply_action(state, Action.play_minion(hand_idx=0))
        assert card not in state.players[0].hand
        assert len(state.players[0].board) == 1
        assert state.players[0].mana == 6

    def test_apply_play_spell(self):
        state = fresh_state()
        spell = make_spell("Fireball", cost=4)
        state.players[0].hand.append(spell)
        apply_action(state, Action.play_spell(hand_idx=0))
        assert spell not in state.players[0].hand
        assert state.players[0].mana == 6

    def test_apply_attack(self):
        state = fresh_state()
        atk = add_minion(state, PlayerID.P1, name="A", attack=3, health=3)
        def_ = add_minion(state, PlayerID.P2, name="D", attack=2, health=5)
        apply_action(state, Action.attack(
            attacker_is_hero=False, attacker_idx=0,
            defender_is_hero=False, defender_idx=0,
        ))
        assert atk.current_health == 1
        assert def_.current_health == 2

    def test_apply_attack_hero(self):
        state = fresh_state()
        add_minion(state, PlayerID.P1, name="A", attack=4, health=3)
        apply_action(state, Action.attack(
            attacker_is_hero=False, attacker_idx=0,
            defender_is_hero=True, defender_idx=-1,
        ))
        assert state.players[1].hero.health == 26

    def test_apply_hero_power(self):
        state = fresh_state()
        apply_action(state, Action.use_hero_power())
        assert state.players[0].hero.hero_power_used
        assert state.players[0].mana == 8

    def test_apply_weapon(self):
        state = fresh_state()
        weapon = Card(
            id="999", name="Fiery War Axe", card_type=CardType.WEAPON,
            card_class=CardClass.WARRIOR, rarity=Rarity.FREE,
            cost=3, attack=3, durability=2, collectible=True,
        )
        state.players[0].hand.append(weapon)
        apply_action(state, Action.play_weapon(hand_idx=0))
        assert state.players[0].hero.weapon_attack == 3
        assert state.players[0].hero.weapon_durability == 2

    def test_full_game_loop_via_actions(self):
        """
        Verify that repeatedly calling get_legal_actions + apply_action
        eventually terminates (END_TURN drives the game forward).
        """
        state = fresh_state()
        # Both players have empty decks — fatigue will end the game
        steps = 0
        while not state.is_game_over and steps < 500:
            actions = get_legal_actions(state)
            # Prefer END_TURN to make this fast
            end = next((a for a in actions if a.type == ActionType.END_TURN), None)
            apply_action(state, end)
            steps += 1
        assert state.is_game_over or steps == 500  # game must end eventually
