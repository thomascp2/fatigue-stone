"""
Tests for Phase 1.3 + 1.5 — Rules engine and state validation.
"""

import pytest

from hs_solver.card import Card, CardClass, CardType, Rarity
from hs_solver.rules import (
    EffectType,
    SpellEffect,
    attack,
    check_attack,
    check_play_minion,
    check_play_spell,
    check_use_hero_power,
    end_turn,
    play_minion,
    play_spell,
    use_hero_power,
)
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


def make_card(name="Card", cost=2, attack=2, health=2, card_type=CardType.MINION) -> Card:
    return Card(
        id=str(hash(name + str(cost))),
        name=name,
        card_type=card_type,
        card_class=CardClass.NEUTRAL,
        rarity=Rarity.FREE,
        cost=cost,
        attack=attack if card_type == CardType.MINION else None,
        health=health if card_type == CardType.MINION else None,
        collectible=True,
    )


def make_spell_card(name="Fireball", cost=4) -> Card:
    return make_card(name=name, cost=cost, card_type=CardType.SPELL)


def fresh_state() -> GameState:
    """State with P1 having 10 mana, no cards. Blank slate for rules tests."""
    p1 = PlayerState(
        player_id=PlayerID.P1,
        hero=HeroInstance(name="P1Hero", owner=PlayerID.P1),
    )
    p2 = PlayerState(
        player_id=PlayerID.P2,
        hero=HeroInstance(name="P2Hero", owner=PlayerID.P2),
    )
    p1.mana = 10
    p1.max_mana = 10
    state = GameState(players=[p1, p2], active_player_id=PlayerID.P1)
    return state


def place_on_board(state: GameState, owner: PlayerID, **kwargs) -> MinionInstance:
    card = make_card(**kwargs)
    m = state.summon_minion(card, owner)
    m.exhausted = False
    return m


# ---------------------------------------------------------------------------
# play_minion tests
# ---------------------------------------------------------------------------


class TestPlayMinion:
    def setup_method(self):
        self.state = fresh_state()
        self.card = make_card("Yeti", cost=4, attack=4, health=5)
        self.state.players[0].hand.append(self.card)

    def test_play_minion_basic(self):
        m = play_minion(self.state, self.card)
        assert m in self.state.players[0].board
        assert self.card not in self.state.players[0].hand
        assert self.state.players[0].mana == 6

    def test_play_minion_removes_from_hand(self):
        play_minion(self.state, self.card)
        assert self.card not in self.state.players[0].hand

    def test_play_minion_position(self):
        card2 = make_card("Right", cost=2, attack=1, health=1)
        self.state.players[0].hand.append(card2)
        m1 = play_minion(self.state, self.card, position=0)
        m2 = play_minion(self.state, card2, position=0)
        assert self.state.players[0].board[0] is m2
        assert self.state.players[0].board[1] is m1

    def test_play_minion_not_in_hand_raises(self):
        card = make_card("Ghost", cost=1)
        with pytest.raises(ValueError, match="not in hand"):
            play_minion(self.state, card)

    def test_play_minion_not_enough_mana(self):
        self.state.players[0].mana = 2
        with pytest.raises(ValueError, match="mana"):
            play_minion(self.state, self.card)

    def test_play_minion_board_full(self):
        for i in range(MAX_BOARD_SIZE):
            c = make_card(f"M{i}", cost=0)
            self.state.players[0].hand.append(c)
            play_minion(self.state, c)
        cheap = make_card("Overflow", cost=0)
        self.state.players[0].hand.append(cheap)
        with pytest.raises(ValueError, match="full"):
            play_minion(self.state, cheap)

    def test_play_non_minion_raises(self):
        spell = make_spell_card("Fireball", cost=4)
        self.state.players[0].hand.append(spell)
        with pytest.raises(ValueError, match="not a minion"):
            play_minion(self.state, spell)

    def test_overload_applied(self):
        card = make_card("Lightning Bolt", cost=1)
        card.overload = 1
        self.state.players[0].hand.append(card)
        play_minion(self.state, card)
        assert self.state.players[0].mana_overloaded == 1

    def test_minion_starts_exhausted(self):
        m = play_minion(self.state, self.card)
        assert m.exhausted is True

    def test_charge_minion_not_exhausted(self):
        card = make_card("Rush Piggy", cost=3, attack=3, health=2)
        card.mechanics.add("CHARGE")
        self.state.players[0].hand.append(card)
        m = play_minion(self.state, card)
        assert m.exhausted is False


# ---------------------------------------------------------------------------
# play_spell tests
# ---------------------------------------------------------------------------


class TestPlaySpell:
    def setup_method(self):
        self.state = fresh_state()
        self.target_minion = place_on_board(
            self.state, PlayerID.P2, name="Target", cost=3, attack=2, health=6
        )

    def _give_spell(self, name="Fireball", cost=4) -> Card:
        spell = make_spell_card(name, cost=cost)
        self.state.players[0].hand.append(spell)
        return spell

    def test_play_damage_spell(self):
        spell = self._give_spell("Fireball", cost=4)
        effect = SpellEffect(EffectType.DAMAGE_TARGET, value=6, can_target_minions=True, can_target_heroes=True)
        play_spell(self.state, spell, effect, self.target_minion)
        assert self.target_minion.current_health == 0
        # Dead minion removed
        assert self.target_minion not in self.state.players[1].board

    def test_play_spell_costs_mana(self):
        spell = self._give_spell(cost=4)
        play_spell(self.state, spell, None)
        assert self.state.players[0].mana == 6

    def test_play_spell_not_in_hand_raises(self):
        spell = make_spell_card()
        effect = SpellEffect(EffectType.DAMAGE_TARGET, value=4)
        with pytest.raises(ValueError, match="not in hand"):
            play_spell(self.state, spell, effect, self.target_minion)

    def test_play_spell_not_enough_mana(self):
        spell = self._give_spell(cost=11)
        with pytest.raises(ValueError, match="mana"):
            play_spell(self.state, spell, None)

    def test_play_non_spell_raises(self):
        minion = make_card("Yeti", cost=2, attack=2, health=2)
        self.state.players[0].hand.append(minion)
        with pytest.raises(ValueError, match="not a spell"):
            play_spell(self.state, minion, None)

    def test_spell_requires_target(self):
        spell = self._give_spell()
        effect = SpellEffect(EffectType.DAMAGE_TARGET, value=6, requires_target=True)
        with pytest.raises(ValueError, match="requires a target"):
            play_spell(self.state, spell, effect, target=None)

    def test_cannot_target_immune_minion(self):
        self.target_minion.immune = True
        spell = self._give_spell()
        effect = SpellEffect(EffectType.DAMAGE_TARGET, value=6)
        with pytest.raises(ValueError, match="immune"):
            play_spell(self.state, spell, effect, self.target_minion)

    def test_cannot_target_stealthed_minion(self):
        self.target_minion.stealth = True
        spell = self._give_spell()
        effect = SpellEffect(EffectType.DAMAGE_TARGET, value=6)
        with pytest.raises(ValueError, match="stealth"):
            play_spell(self.state, spell, effect, self.target_minion)

    def test_aoe_spell_hits_all_enemies(self):
        m2 = place_on_board(self.state, PlayerID.P2, name="M2", cost=3, attack=2, health=3)
        spell = self._give_spell("Flamestrike", cost=7)
        effect = SpellEffect(EffectType.DAMAGE_ALL_ENEMIES, value=4, requires_target=False)
        play_spell(self.state, spell, effect)
        # target has 6 hp, takes 4 → survives with 2
        assert self.target_minion in self.state.players[1].board
        assert self.target_minion.current_health == 2
        # m2 has 3 hp, takes 4 → dead
        assert m2 not in self.state.players[1].board

    def test_buff_spell(self):
        target = place_on_board(self.state, PlayerID.P1, name="Buff Target", attack=2, health=3)
        spell = self._give_spell("Power Word", cost=1)
        effect = SpellEffect(EffectType.BUFF_TARGET, value=2, value2=3, requires_target=True)
        play_spell(self.state, spell, effect, target)
        assert target.current_attack == 4
        assert target.current_health == 6

    def test_silence_spell(self):
        self.target_minion.taunt = True
        spell = self._give_spell("Silence", cost=0)
        effect = SpellEffect(EffectType.SILENCE_TARGET, requires_target=True)
        play_spell(self.state, spell, effect, self.target_minion)
        assert not self.target_minion.taunt
        assert self.target_minion.silenced

    def test_destroy_spell(self):
        spell = self._give_spell("Assassinate", cost=5)
        effect = SpellEffect(EffectType.DESTROY_TARGET, requires_target=True)
        play_spell(self.state, spell, effect, self.target_minion)
        assert self.target_minion not in self.state.players[1].board

    def test_heal_spell(self):
        self.state.players[0].hero.health = 20
        hero = self.state.players[0].hero
        spell = self._give_spell("Lesser Heal", cost=1)
        effect = SpellEffect(EffectType.HEAL_TARGET, value=2, requires_target=True)
        play_spell(self.state, spell, effect, hero)
        assert self.state.players[0].hero.health == 22

    def test_draw_spell(self):
        for i in range(5):
            self.state.players[0].deck.append(make_card(f"DeckCard{i}"))
        # Measure hand AFTER adding spell so the -1 accounts for its removal
        spell = self._give_spell("Arcane Intellect", cost=3)
        initial_hand = len(self.state.players[0].hand)  # includes the spell
        effect = SpellEffect(EffectType.DRAW, value=2, requires_target=False)
        play_spell(self.state, spell, effect)
        # spell removed (-1) + 2 drawn (+2) = net +1
        assert len(self.state.players[0].hand) == initial_hand + 1

    def test_armor_spell(self):
        spell = self._give_spell("Shield Block", cost=3)
        effect = SpellEffect(EffectType.GIVE_ARMOR, value=5, requires_target=False)
        play_spell(self.state, spell, effect)
        assert self.state.players[0].hero.armor == 5


# ---------------------------------------------------------------------------
# attack() tests
# ---------------------------------------------------------------------------


class TestAttack:
    def setup_method(self):
        self.state = fresh_state()

    def test_minion_attacks_minion(self):
        atk = place_on_board(self.state, PlayerID.P1, name="A", attack=3, health=5)
        def_ = place_on_board(self.state, PlayerID.P2, name="D", attack=2, health=3)
        attack(self.state, atk, def_)
        assert def_.current_health == 0  # 3 - 3 = 0 → dead
        assert atk.current_health == 3   # 5 - 2 = 3

    def test_minion_attacks_hero(self):
        atk = place_on_board(self.state, PlayerID.P1, name="A", attack=4, health=3)
        attack(self.state, atk, self.state.players[1].hero)
        assert self.state.players[1].hero.health == 26

    def test_hero_attacks_minion(self):
        self.state.players[0].hero.equip_weapon(3, 2)
        def_ = place_on_board(self.state, PlayerID.P2, name="D", attack=2, health=5)
        attack(self.state, self.state.players[0].hero, def_)
        assert def_.current_health == 2

    def test_taunt_must_be_attacked(self):
        taunt_card = make_card("Taunt", cost=3, attack=2, health=5)
        taunt_card.mechanics.add("TAUNT")
        taunt_m = self.state.summon_minion(taunt_card, PlayerID.P2)
        taunt_m.exhausted = False

        non_taunt = place_on_board(self.state, PlayerID.P2, name="NT", attack=2, health=3)
        atk = place_on_board(self.state, PlayerID.P1, name="A", attack=3, health=3)

        with pytest.raises(ValueError, match="[Tt]aunt"):
            attack(self.state, atk, non_taunt)

        # Should be able to attack the taunt minion
        attack(self.state, atk, taunt_m)  # no exception

    def test_cannot_attack_heroes_with_taunt_on_board(self):
        taunt_card = make_card("Taunt", cost=3, attack=2, health=5)
        taunt_card.mechanics.add("TAUNT")
        self.state.summon_minion(taunt_card, PlayerID.P2)

        atk = place_on_board(self.state, PlayerID.P1, name="A", attack=3, health=3)
        with pytest.raises(ValueError, match="[Tt]aunt"):
            attack(self.state, atk, self.state.players[1].hero)

    def test_exhausted_minion_cannot_attack(self):
        atk = place_on_board(self.state, PlayerID.P1, name="A", attack=3, health=3)
        atk.exhausted = True
        def_ = place_on_board(self.state, PlayerID.P2, name="D", attack=2, health=3)
        with pytest.raises(ValueError, match="exhausted"):
            attack(self.state, atk, def_)

    def test_frozen_minion_cannot_attack(self):
        atk = place_on_board(self.state, PlayerID.P1, name="A", attack=3, health=3)
        atk.frozen = True
        def_ = place_on_board(self.state, PlayerID.P2, name="D", attack=2, health=3)
        with pytest.raises(ValueError, match="frozen"):
            attack(self.state, atk, def_)

    def test_cannot_attack_immune_minion(self):
        atk = place_on_board(self.state, PlayerID.P1, name="A", attack=3, health=3)
        def_ = place_on_board(self.state, PlayerID.P2, name="D", attack=2, health=3)
        def_.immune = True
        with pytest.raises(ValueError, match="immune"):
            attack(self.state, atk, def_)

    def test_cannot_attack_stealthed_minion(self):
        atk = place_on_board(self.state, PlayerID.P1, name="A", attack=3, health=3)
        def_ = place_on_board(self.state, PlayerID.P2, name="D", attack=2, health=3)
        def_.stealth = True
        with pytest.raises(ValueError, match="[Ss]tealth"):
            attack(self.state, atk, def_)

    def test_rush_cannot_attack_hero(self):
        card = make_card("Rush", cost=3, attack=3, health=3)
        card.mechanics.add("RUSH")
        m = self.state.summon_minion(card, PlayerID.P1)
        # Rush minion is not exhausted
        assert m.exhausted is False
        with pytest.raises(ValueError, match="[Rr]ush"):
            attack(self.state, m, self.state.players[1].hero)

    def test_zero_attack_minion_cannot_attack(self):
        atk = place_on_board(self.state, PlayerID.P1, name="A", attack=0, health=5)
        def_ = place_on_board(self.state, PlayerID.P2, name="D", attack=2, health=3)
        with pytest.raises(ValueError, match="0 attack"):
            attack(self.state, atk, def_)

    def test_attacker_must_be_own_minion(self):
        enemy = place_on_board(self.state, PlayerID.P2, name="E", attack=3, health=3)
        def_ = place_on_board(self.state, PlayerID.P2, name="D", attack=2, health=3)
        with pytest.raises(ValueError, match="your board"):
            attack(self.state, enemy, def_)

    def test_defender_must_be_enemy_minion(self):
        atk = place_on_board(self.state, PlayerID.P1, name="A", attack=3, health=3)
        own_m = place_on_board(self.state, PlayerID.P1, name="Own", attack=2, health=3)
        with pytest.raises(ValueError, match="opponent"):
            attack(self.state, atk, own_m)


# ---------------------------------------------------------------------------
# end_turn tests
# ---------------------------------------------------------------------------


class TestEndTurn:
    def test_end_turn_swaps_player(self):
        state = fresh_state()
        end_turn(state)
        assert state.active_player_id == PlayerID.P2

    def test_end_turn_game_over_raises(self):
        state = fresh_state()
        state.phase = GamePhase.GAME_OVER
        with pytest.raises(ValueError, match="over"):
            end_turn(state)

    def test_end_turn_mana_increases(self):
        state = fresh_state()
        # P1 has 10 mana. After end_turn, P2 gets their mana crystal
        state.players[1].max_mana = 1
        end_turn(state)
        assert state.active_player.mana == 2  # P2 now has 2

    def test_minions_refresh_after_end_turn(self):
        state = fresh_state()
        m = place_on_board(state, PlayerID.P1, name="A", attack=3, health=3)
        m.exhausted = True
        end_turn(state)  # P2 acts
        end_turn(state)  # back to P1
        assert not m.exhausted


# ---------------------------------------------------------------------------
# use_hero_power tests
# ---------------------------------------------------------------------------


class TestHeroPower:
    def test_hero_power_deals_damage(self):
        state = fresh_state()
        target = place_on_board(state, PlayerID.P2, name="T", attack=1, health=3)
        use_hero_power(state, target)
        assert target.current_health == 1
        assert state.players[0].mana == 8

    def test_hero_power_marked_used(self):
        state = fresh_state()
        use_hero_power(state)
        assert state.players[0].hero.hero_power_used

    def test_hero_power_used_twice_raises(self):
        state = fresh_state()
        use_hero_power(state)
        with pytest.raises(ValueError, match="already used"):
            use_hero_power(state)

    def test_hero_power_not_enough_mana(self):
        state = fresh_state()
        state.players[0].mana = 1
        with pytest.raises(ValueError, match="mana"):
            use_hero_power(state)

    def test_hero_power_kills_minion(self):
        state = fresh_state()
        target = place_on_board(state, PlayerID.P2, name="T", attack=1, health=2)
        use_hero_power(state, target)
        assert target not in state.players[1].board
