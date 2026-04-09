"""
Tests for Phase 1.4 — Combat system.
"""

import pytest

from hs_solver.card import Card, CardClass, CardType, Rarity
from hs_solver.combat import (
    process_deaths,
    resolve_hero_vs_hero,
    resolve_hero_vs_minion,
    resolve_minion_vs_hero,
    resolve_minion_vs_minion,
)
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


def make_minion_card(name="Fighter", attack=3, health=3, **mechanics) -> Card:
    card = Card(
        id=str(hash(name + str(attack) + str(health))),
        name=name,
        card_type=CardType.MINION,
        card_class=CardClass.NEUTRAL,
        rarity=Rarity.FREE,
        cost=3,
        attack=attack,
        health=health,
        collectible=True,
    )
    for m in mechanics:
        if mechanics[m]:
            card.mechanics.add(m.upper())
    return card


def make_board_state() -> GameState:
    """Create a minimal game state with 2 players, no cards in hand/deck."""
    p1 = PlayerState(
        player_id=PlayerID.P1,
        hero=HeroInstance(name="Jaina", owner=PlayerID.P1),
    )
    p2 = PlayerState(
        player_id=PlayerID.P2,
        hero=HeroInstance(name="Rexxar", owner=PlayerID.P2),
    )
    return GameState(players=[p1, p2], active_player_id=PlayerID.P1)


def place_minion(state: GameState, owner: PlayerID, **kwargs) -> MinionInstance:
    card = make_minion_card(**kwargs)
    m = state.summon_minion(card, owner)
    m.exhausted = False
    return m


# ---------------------------------------------------------------------------
# Minion vs Minion
# ---------------------------------------------------------------------------


class TestMinionVsMinion:
    def setup_method(self):
        self.state = make_board_state()

    def test_basic_trade(self):
        atk = place_minion(self.state, PlayerID.P1, name="A", attack=3, health=3)
        def_ = place_minion(self.state, PlayerID.P2, name="D", attack=2, health=4)
        dead = resolve_minion_vs_minion(self.state, atk, def_)
        # Attacker survives (3 hp - 2 dmg = 1 hp), defender survives (4 hp - 3 dmg = 1 hp)
        assert atk.current_health == 1
        assert def_.current_health == 1
        assert dead == []

    def test_attacker_dies(self):
        atk = place_minion(self.state, PlayerID.P1, name="A", attack=2, health=2)
        def_ = place_minion(self.state, PlayerID.P2, name="D", attack=3, health=5)
        dead = resolve_minion_vs_minion(self.state, atk, def_)
        assert atk.current_health == -1  # 2 - 3 = -1
        assert def_.current_health == 3   # 5 - 2 = 3
        assert atk in dead
        assert def_ not in dead
        assert atk not in self.state.players[0].board
        assert atk in self.state.players[0].graveyard

    def test_both_die(self):
        atk = place_minion(self.state, PlayerID.P1, name="A", attack=4, health=2)
        def_ = place_minion(self.state, PlayerID.P2, name="D", attack=5, health=3)
        dead = resolve_minion_vs_minion(self.state, atk, def_)
        assert atk in dead
        assert def_ in dead
        assert len(self.state.players[0].board) == 0
        assert len(self.state.players[1].board) == 0

    def test_divine_shield_absorbs(self):
        card = make_minion_card(name="DS", attack=2, health=3, divine_shield=True)
        card.mechanics.add("DIVINE_SHIELD")
        ds_m = MinionInstance(card=card, owner=PlayerID.P1)
        ds_m.instance_id = 99
        ds_m.exhausted = False
        self.state.players[0].board.append(ds_m)

        def_ = place_minion(self.state, PlayerID.P2, name="D", attack=5, health=4)
        dead = resolve_minion_vs_minion(self.state, ds_m, def_)
        # DS absorbs 5 damage
        assert ds_m.current_health == 3
        assert not ds_m.divine_shield
        # DS minion deals 2 damage to defender
        assert def_.current_health == 2
        assert dead == []

    def test_poisonous_kills_regardless(self):
        atk = place_minion(self.state, PlayerID.P1, name="Snake", attack=1, health=1)
        atk.poisonous = True
        def_ = place_minion(self.state, PlayerID.P2, name="Dragon", attack=0, health=20)
        dead = resolve_minion_vs_minion(self.state, atk, def_)
        assert def_ in dead, "Poisonous should kill dragon"

    def test_lifesteal_heals_controller(self):
        self.state.players[0].hero.health = 20
        atk = place_minion(self.state, PlayerID.P1, name="LS", attack=4, health=5)
        atk.lifesteal = True
        def_ = place_minion(self.state, PlayerID.P2, name="D", attack=1, health=5)
        resolve_minion_vs_minion(self.state, atk, def_)
        # Attacker deals 4 damage, should heal P1 hero by 4
        assert self.state.players[0].hero.health == 24

    def test_attacks_used_tracked(self):
        atk = place_minion(self.state, PlayerID.P1, name="A", attack=2, health=5)
        def_ = place_minion(self.state, PlayerID.P2, name="D", attack=1, health=5)
        resolve_minion_vs_minion(self.state, atk, def_)
        assert atk.attacks_used == 1
        assert atk.exhausted is True

    def test_windfury_not_exhausted_after_first_attack(self):
        card = make_minion_card(name="WF", attack=2, health=5)
        card.mechanics.add("WINDFURY")
        wf = MinionInstance(card=card, owner=PlayerID.P1)
        wf.instance_id = 50
        wf.exhausted = False
        self.state.players[0].board.append(wf)
        def_ = place_minion(self.state, PlayerID.P2, name="D", attack=1, health=10)
        resolve_minion_vs_minion(self.state, wf, def_)
        assert wf.attacks_used == 1
        assert wf.exhausted is False  # windfury → can attack again

    def test_stealth_cleared_on_attack(self):
        atk = place_minion(self.state, PlayerID.P1, name="Stealth", attack=2, health=3)
        atk.stealth = True
        def_ = place_minion(self.state, PlayerID.P2, name="D", attack=1, health=5)
        resolve_minion_vs_minion(self.state, atk, def_)
        assert not atk.stealth

    def test_simultaneous_death(self):
        """Both minions deal lethal — both should die."""
        atk = place_minion(self.state, PlayerID.P1, name="A", attack=3, health=3)
        def_ = place_minion(self.state, PlayerID.P2, name="D", attack=3, health=3)
        dead = resolve_minion_vs_minion(self.state, atk, def_)
        assert len(dead) == 2


# ---------------------------------------------------------------------------
# Minion vs Hero
# ---------------------------------------------------------------------------


class TestMinionVsHero:
    def setup_method(self):
        self.state = make_board_state()

    def test_minion_damages_hero(self):
        atk = place_minion(self.state, PlayerID.P1, name="A", attack=5, health=3)
        hero = self.state.players[1].hero
        resolve_minion_vs_hero(self.state, atk, hero)
        assert hero.health == 25

    def test_hero_does_not_counterattack(self):
        atk = place_minion(self.state, PlayerID.P1, name="Weak", attack=1, health=1)
        hero = self.state.players[1].hero
        resolve_minion_vs_hero(self.state, atk, hero)
        assert atk.current_health == 1  # no counterattack

    def test_lifesteal_heals_on_face_hit(self):
        self.state.players[0].hero.health = 15
        atk = place_minion(self.state, PlayerID.P1, name="LS", attack=6, health=5)
        atk.lifesteal = True
        resolve_minion_vs_hero(self.state, atk, self.state.players[1].hero)
        assert self.state.players[0].hero.health == 21

    def test_hero_armor_absorbs_first(self):
        hero = self.state.players[1].hero
        hero.armor = 3
        atk = place_minion(self.state, PlayerID.P1, name="A", attack=5, health=3)
        resolve_minion_vs_hero(self.state, atk, hero)
        assert hero.armor == 0
        assert hero.health == 28  # 30 - (5-3) = 28

    def test_immune_hero_takes_no_damage(self):
        hero = self.state.players[1].hero
        hero.immune = True
        atk = place_minion(self.state, PlayerID.P1, name="A", attack=99, health=3)
        resolve_minion_vs_hero(self.state, atk, hero)
        assert hero.health == 30

    def test_hero_death_triggers_game_over(self):
        hero = self.state.players[1].hero
        hero.health = 1
        atk = place_minion(self.state, PlayerID.P1, name="A", attack=5, health=3)
        resolve_minion_vs_hero(self.state, atk, hero)
        assert self.state.phase == GamePhase.GAME_OVER


# ---------------------------------------------------------------------------
# Hero vs Minion
# ---------------------------------------------------------------------------


class TestHeroVsMinion:
    def setup_method(self):
        self.state = make_board_state()
        self.state.players[0].hero.equip_weapon(3, 2)

    def test_hero_damages_minion(self):
        def_ = place_minion(self.state, PlayerID.P2, name="D", attack=2, health=5)
        resolve_hero_vs_minion(self.state, self.state.players[0].hero, def_)
        assert def_.current_health == 2

    def test_minion_hits_hero_back(self):
        def_ = place_minion(self.state, PlayerID.P2, name="D", attack=2, health=5)
        resolve_hero_vs_minion(self.state, self.state.players[0].hero, def_)
        assert self.state.players[0].hero.health == 28

    def test_weapon_durability_decrements(self):
        def_ = place_minion(self.state, PlayerID.P2, name="D", attack=1, health=5)
        hero = self.state.players[0].hero
        resolve_hero_vs_minion(self.state, hero, def_)
        assert hero.weapon_durability == 1

    def test_weapon_breaks_at_zero(self):
        self.state.players[0].hero.equip_weapon(3, 1)
        def_ = place_minion(self.state, PlayerID.P2, name="D", attack=1, health=5)
        hero = self.state.players[0].hero
        resolve_hero_vs_minion(self.state, hero, def_)
        assert hero.weapon_durability == 0
        assert hero.weapon_attack == 0


# ---------------------------------------------------------------------------
# Hero vs Hero
# ---------------------------------------------------------------------------


class TestHeroVsHero:
    def test_hero_face_damage(self):
        state = make_board_state()
        state.players[0].hero.equip_weapon(5, 2)
        resolve_hero_vs_hero(state, state.players[0].hero, state.players[1].hero)
        assert state.players[1].hero.health == 25


# ---------------------------------------------------------------------------
# process_deaths
# ---------------------------------------------------------------------------


class TestProcessDeaths:
    def test_removes_dead_minions(self):
        state = make_board_state()
        m = place_minion(state, PlayerID.P1, name="Dying", attack=1, health=1)
        m.current_health = 0
        dead = process_deaths(state)
        assert m in dead
        assert m not in state.players[0].board

    def test_leaves_alive_minions(self):
        state = make_board_state()
        alive = place_minion(state, PlayerID.P1, name="Alive", attack=3, health=3)
        dead_m = place_minion(state, PlayerID.P1, name="Dead", attack=1, health=1)
        dead_m.current_health = -1
        process_deaths(state)
        assert alive in state.players[0].board
        assert dead_m not in state.players[0].board

    def test_game_over_when_hero_dead(self):
        state = make_board_state()
        state.players[1].hero.health = -5
        process_deaths(state)
        assert state.phase == GamePhase.GAME_OVER
