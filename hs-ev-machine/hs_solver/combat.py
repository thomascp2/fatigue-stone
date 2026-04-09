"""
Phase 1.4 — Combat System

Handles attack resolution between:
  - Minion → Minion
  - Minion → Hero
  - Hero   → Minion
  - Hero   → Hero

Key mechanics modeled:
  - Divine shield (absorbs first hit)
  - Poisonous (kills anything it damages, regardless of amount)
  - Lifesteal (attacker's controller gains HP equal to damage dealt)
  - Frozen (can't attack; applied by some spells/effects)
  - Stealth (cleared when minion attacks)
  - Death: minion health <= 0 → removed from board, added to graveyard

Death order: both entities take damage simultaneously, then deaths are
processed together (standard HS behavior — simultaneous combat).
"""

from __future__ import annotations

from typing import Union

from hs_solver.state import GameState, HeroInstance, MinionInstance, PlayerID

# Type alias for attack participants
Attacker = Union[MinionInstance, HeroInstance]
Defender = Union[MinionInstance, HeroInstance]


# ---------------------------------------------------------------------------
# Core damage application
# ---------------------------------------------------------------------------


def deal_damage_to_minion(minion: MinionInstance, amount: int) -> int:
    """
    Deal damage to a minion. Returns actual damage dealt (0 if divine shield).
    Does NOT remove the minion from board — caller handles death check.
    """
    return minion.take_damage(amount)


def deal_damage_to_hero(hero: HeroInstance, amount: int) -> int:
    """
    Deal damage to a hero (armor first, then health).
    Returns actual health damage taken.
    """
    return hero.take_damage(amount)


# ---------------------------------------------------------------------------
# Lifesteal application
# ---------------------------------------------------------------------------


def apply_lifesteal(state: GameState, owner: PlayerID, damage_dealt: int) -> None:
    """Restore damage_dealt HP to the owner's hero (up to max HP)."""
    if damage_dealt > 0:
        state.players[owner].hero.heal(damage_dealt)


# ---------------------------------------------------------------------------
# Death processing
# ---------------------------------------------------------------------------


def process_deaths(state: GameState) -> list[MinionInstance]:
    """
    Find all dead minions on both boards, remove them, trigger no deathrattles yet
    (deathrattle resolution is a Phase 2+ concern).

    Returns list of minions that died (for caller awareness).
    """
    dead: list[MinionInstance] = []
    for player in state.players:
        still_alive = []
        for m in player.board:
            if m.current_health <= 0:
                dead.append(m)
                player.graveyard.append(m)
            else:
                still_alive.append(m)
        player.board = still_alive

    # Check if either hero is dead → mark game over
    for player in state.players:
        if not player.hero.is_alive:
            from hs_solver.state import GamePhase
            state.phase = GamePhase.GAME_OVER

    return dead


# ---------------------------------------------------------------------------
# Attack resolution
# ---------------------------------------------------------------------------


def resolve_minion_vs_minion(
    state: GameState,
    attacker: MinionInstance,
    defender: MinionInstance,
) -> list[MinionInstance]:
    """
    Resolve combat between two minions.

    Both deal damage simultaneously. Poisonous kills regardless of damage amount.
    Returns list of minions that died.
    """
    atk_dmg = attacker.current_attack
    def_dmg = defender.current_attack

    # Apply damage simultaneously
    actual_to_defender = deal_damage_to_minion(defender, atk_dmg)
    actual_to_attacker = deal_damage_to_minion(attacker, def_dmg)

    # Poisonous: if any damage was dealt, the target dies
    if attacker.poisonous and actual_to_defender > 0:
        defender.current_health = min(defender.current_health, 0)
    if defender.poisonous and actual_to_attacker > 0:
        attacker.current_health = min(attacker.current_health, 0)

    # Lifesteal: heal attacker's controller for damage dealt to defender
    if attacker.lifesteal and actual_to_defender > 0:
        apply_lifesteal(state, attacker.owner, actual_to_defender)
    # Defender lifesteal (less common but valid)
    if defender.lifesteal and actual_to_attacker > 0:
        apply_lifesteal(state, defender.owner, actual_to_attacker)

    # Stealth: cleared when minion attacks
    attacker.stealth = False

    # Track attack usage
    attacker.attacks_used += 1
    if attacker.card.attacks_per_turn <= attacker.attacks_used:
        attacker.exhausted = True

    return process_deaths(state)


def resolve_minion_vs_hero(
    state: GameState,
    attacker: MinionInstance,
    defender_hero: HeroInstance,
) -> list[MinionInstance]:
    """
    Minion attacks a hero.
    Hero does NOT deal damage back (heroes can't counterattack minions).
    """
    atk_dmg = attacker.current_attack
    actual = deal_damage_to_hero(defender_hero, atk_dmg)

    if attacker.lifesteal and actual > 0:
        apply_lifesteal(state, attacker.owner, actual)

    attacker.stealth = False
    attacker.attacks_used += 1
    if attacker.card.attacks_per_turn <= attacker.attacks_used:
        attacker.exhausted = True

    return process_deaths(state)


def resolve_hero_vs_minion(
    state: GameState,
    attacker_hero: HeroInstance,
    defender: MinionInstance,
) -> list[MinionInstance]:
    """
    Hero (with weapon) attacks a minion.
    The minion deals its attack back to the hero.
    """
    hero_atk = attacker_hero.weapon_attack
    minion_atk = defender.current_attack

    actual_to_defender = deal_damage_to_minion(defender, hero_atk)
    deal_damage_to_hero(attacker_hero, minion_atk)

    if defender.poisonous and minion_atk > 0:
        # Poisonous minions destroy weapons on hit (simplified: just take dmg)
        pass  # weapon durability handled separately

    attacker_hero.use_weapon_attack()

    # Defender lifesteal vs hero
    if defender.lifesteal and minion_atk > 0:
        apply_lifesteal(state, defender.owner, minion_atk)

    defender.stealth = False

    return process_deaths(state)


def resolve_hero_vs_hero(
    state: GameState,
    attacker_hero: HeroInstance,
    defender_hero: HeroInstance,
) -> list[MinionInstance]:
    """
    Hero attacks opposing hero (uncommon but legal with weapon).
    """
    deal_damage_to_hero(defender_hero, attacker_hero.weapon_attack)
    attacker_hero.use_weapon_attack()
    return process_deaths(state)
