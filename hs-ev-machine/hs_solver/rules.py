"""
Phase 1.3 + 1.5 — Rules Engine and State Validation

Provides:
  - play_minion()     — play a minion card from hand to board
  - play_spell()      — execute a direct-damage / buff / silence / destroy spell
  - attack()          — execute a legal attack action
  - end_turn()        — end the active player's turn
  - use_hero_power()  — use the hero power (stub: restores 2 HP for Priest etc.)

Phase 1 spell scope (intentionally limited):
  - Direct damage spells (fireball-style): card has "deal X damage" in effect_tag
  - AoE damage spells: effect_tag "deal X damage to all enemies"
  - Buff: +X/+Y to a minion
  - Silence: strip a minion's text
  - Destroy: destroy a minion (doesn't trigger deathrattle in Phase 1)

Spells are driven by a small EffectTag system so we can model real cards
without hardcoding every name. The tag is set when we build spells from
HearthstoneJSON data (Phase 5); in Phase 1 we use it for testing.

Validation (Phase 1.5):
  - check_play_minion()
  - check_play_spell()
  - check_attack()
  - check_use_hero_power()
All raise ValueError with human-readable messages on illegal actions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Union

from hs_solver.card import Card, CardType
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
    MAX_BOARD_SIZE,
)


# ---------------------------------------------------------------------------
# Spell effect system
# ---------------------------------------------------------------------------


class EffectType(Enum):
    DAMAGE_TARGET = auto()        # deal N damage to one target
    DAMAGE_ALL_ENEMIES = auto()   # deal N damage to all enemy minions
    DAMAGE_ALL = auto()           # deal N damage to all minions (both boards)
    BUFF_TARGET = auto()          # give target +N/+M
    SILENCE_TARGET = auto()       # silence a minion
    DESTROY_TARGET = auto()       # destroy a minion unconditionally
    HEAL_TARGET = auto()          # restore N HP to a target
    DRAW = auto()                 # draw N cards
    GIVE_ARMOR = auto()           # give hero N armor


@dataclass
class SpellEffect:
    """
    Describes what a spell does. Attached to a Card when we know its effect.
    In Phase 1 we attach this manually for tests; Phase 5 maps real cards.
    """
    effect_type: EffectType
    value: int = 0               # damage / heal amount / buff attack
    value2: int = 0              # secondary (buff health)

    # Targeting: which characters can be targeted
    can_target_minions: bool = True
    can_target_heroes: bool = False
    requires_target: bool = True


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _get_taunts(board: list[MinionInstance]) -> list[MinionInstance]:
    return [m for m in board if m.taunt and not m.stealth and not m.immune]


def check_play_minion(state: GameState, card: Card) -> None:
    """Raise ValueError if playing this minion is illegal."""
    ap = state.active_player
    if state.phase != GamePhase.MAIN:
        raise ValueError("Can only play cards in MAIN phase.")
    if card not in ap.hand:
        raise ValueError(f"{card.name} is not in hand.")
    if ap.mana < card.cost:
        raise ValueError(
            f"Not enough mana: have {ap.mana}, {card.name} costs {card.cost}."
        )
    if ap.board_full:
        raise ValueError(f"Board is full ({MAX_BOARD_SIZE} minions).")
    if not card.is_minion:
        raise ValueError(f"{card.name} is not a minion.")


def check_play_spell(
    state: GameState,
    card: Card,
    target: Optional[Union[MinionInstance, HeroInstance]] = None,
    effect: Optional[SpellEffect] = None,
) -> None:
    """Raise ValueError if casting this spell is illegal."""
    ap = state.active_player
    if state.phase != GamePhase.MAIN:
        raise ValueError("Can only play cards in MAIN phase.")
    if card not in ap.hand:
        raise ValueError(f"{card.name} is not in hand.")
    if ap.mana < card.cost:
        raise ValueError(
            f"Not enough mana: have {ap.mana}, {card.name} costs {card.cost}."
        )
    if not card.is_spell:
        raise ValueError(f"{card.name} is not a spell.")
    if effect and effect.requires_target and target is None:
        raise ValueError(f"{card.name} requires a target.")
    if target is not None:
        # Validate target legality
        if isinstance(target, MinionInstance):
            if target.immune:
                raise ValueError("Target is immune.")
            if target.stealth:
                raise ValueError("Cannot target a stealthed minion with a spell.")
        if isinstance(target, HeroInstance):
            if target.immune:
                raise ValueError("Target hero is immune.")


def check_attack(
    state: GameState,
    attacker: Union[MinionInstance, HeroInstance],
    defender: Union[MinionInstance, HeroInstance],
) -> None:
    """Raise ValueError if this attack is illegal."""
    ap = state.active_player
    ip = state.inactive_player

    if state.phase != GamePhase.MAIN:
        raise ValueError("Can only attack in MAIN phase.")

    # Validate attacker ownership
    if isinstance(attacker, MinionInstance):
        if attacker not in ap.board:
            raise ValueError("Attacker is not on your board.")
        if not attacker.can_attack:
            if attacker.exhausted:
                raise ValueError(f"{attacker.card.name} is exhausted.")
            if attacker.frozen:
                raise ValueError(f"{attacker.card.name} is frozen.")
            if attacker.current_attack <= 0:
                raise ValueError(f"{attacker.card.name} has 0 attack.")
        # Rush: can only attack minions on the turn it was played
        if attacker.has_rush:
            if isinstance(defender, HeroInstance):
                raise ValueError(f"{attacker.card.name} has Rush and cannot attack heroes this turn.")
    elif isinstance(attacker, HeroInstance):
        if attacker is not ap.hero:
            raise ValueError("That is not your hero.")
        if not attacker.can_attack:
            raise ValueError("Hero cannot attack (no weapon or already attacked).")

    # Validate defender ownership
    if isinstance(defender, MinionInstance):
        if defender not in ip.board:
            raise ValueError("Defender is not on opponent's board.")
        if defender.immune:
            raise ValueError("That minion is immune.")
        if defender.stealth:
            raise ValueError("Cannot attack a stealthed minion.")
        # Taunt check: must attack a taunt minion if any exist
        taunts = _get_taunts(ip.board)
        if taunts and defender not in taunts:
            raise ValueError("Must attack a Taunt minion.")
    elif isinstance(defender, HeroInstance):
        if defender is not ip.hero:
            raise ValueError("That is not the opponent's hero.")
        if defender.immune:
            raise ValueError("Opponent's hero is immune.")
        # Taunt check: if any taunt minions exist, hero cannot be attacked
        taunts = _get_taunts(ip.board)
        if taunts:
            raise ValueError("Must attack a Taunt minion before the hero.")


def check_use_hero_power(state: GameState) -> None:
    """Raise ValueError if using hero power is illegal."""
    ap = state.active_player
    if state.phase != GamePhase.MAIN:
        raise ValueError("Can only use hero power in MAIN phase.")
    if ap.hero.hero_power_used:
        raise ValueError("Hero power already used this turn.")
    if ap.mana < ap.hero.hero_power_cost:
        raise ValueError(
            f"Not enough mana for hero power: "
            f"have {ap.mana}, costs {ap.hero.hero_power_cost}."
        )


# ---------------------------------------------------------------------------
# Action execution
# ---------------------------------------------------------------------------


def play_minion(
    state: GameState,
    card: Card,
    position: int = -1,
) -> MinionInstance:
    """
    Play a minion from the active player's hand to their board.

    Validates legality, spends mana, removes from hand, creates MinionInstance.
    Battlecry effects are NOT resolved in Phase 1 (no targeting UI yet).

    Returns the new MinionInstance.
    """
    check_play_minion(state, card)
    ap = state.active_player

    ap.spend_mana(card.cost)
    ap.hand.remove(card)

    # Apply overload for next turn
    if card.overload:
        ap.mana_overloaded += card.overload

    minion = state.summon_minion(card, state.active_player_id, position)
    return minion


def play_spell(
    state: GameState,
    card: Card,
    effect: Optional[SpellEffect] = None,
    target: Optional[Union[MinionInstance, HeroInstance]] = None,
) -> None:
    """
    Cast a spell from the active player's hand.

    Resolves the effect immediately. Supported effect types: see EffectType.
    Unknown or None effects are a no-op (for future expansion).
    """
    check_play_spell(state, card, target, effect)
    ap = state.active_player
    ip = state.inactive_player

    ap.spend_mana(card.cost)
    ap.hand.remove(card)

    if card.overload:
        ap.mana_overloaded += card.overload

    if effect is None:
        return  # No effect modeled yet (placeholder for battlecry-like spells)

    _resolve_spell_effect(state, effect, target)

    # After any spell, check deaths (e.g., AoE damage)
    process_deaths(state)

    if state.is_game_over:
        state.phase = GamePhase.GAME_OVER


def _resolve_spell_effect(
    state: GameState,
    effect: SpellEffect,
    target: Optional[Union[MinionInstance, HeroInstance]],
) -> None:
    ap = state.active_player
    ip = state.inactive_player

    if effect.effect_type == EffectType.DAMAGE_TARGET:
        assert target is not None
        if isinstance(target, MinionInstance):
            target.take_damage(effect.value)
        elif isinstance(target, HeroInstance):
            target.take_damage(effect.value)

    elif effect.effect_type == EffectType.DAMAGE_ALL_ENEMIES:
        for m in list(ip.board):
            m.take_damage(effect.value)
        ip.hero.take_damage(effect.value)

    elif effect.effect_type == EffectType.DAMAGE_ALL:
        for player in state.players:
            for m in list(player.board):
                m.take_damage(effect.value)
            player.hero.take_damage(effect.value)

    elif effect.effect_type == EffectType.BUFF_TARGET:
        assert isinstance(target, MinionInstance), "Buff targets must be minions"
        target.current_attack += effect.value
        target.current_health += effect.value2
        target.max_health += effect.value2

    elif effect.effect_type == EffectType.SILENCE_TARGET:
        assert isinstance(target, MinionInstance), "Silence targets must be minions"
        target.silence()

    elif effect.effect_type == EffectType.DESTROY_TARGET:
        assert isinstance(target, MinionInstance), "Destroy targets must be minions"
        target.current_health = 0  # process_deaths() will clean it up

    elif effect.effect_type == EffectType.HEAL_TARGET:
        assert target is not None
        if isinstance(target, MinionInstance):
            target.heal(effect.value)
        elif isinstance(target, HeroInstance):
            target.heal(effect.value)

    elif effect.effect_type == EffectType.DRAW:
        for _ in range(effect.value):
            ap.draw_card()

    elif effect.effect_type == EffectType.GIVE_ARMOR:
        ap.hero.armor += effect.value


def attack(
    state: GameState,
    attacker: Union[MinionInstance, HeroInstance],
    defender: Union[MinionInstance, HeroInstance],
) -> list[MinionInstance]:
    """
    Execute an attack action after validating legality.
    Returns list of minions that died.
    """
    check_attack(state, attacker, defender)

    if isinstance(attacker, MinionInstance) and isinstance(defender, MinionInstance):
        return resolve_minion_vs_minion(state, attacker, defender)
    elif isinstance(attacker, MinionInstance) and isinstance(defender, HeroInstance):
        return resolve_minion_vs_hero(state, attacker, defender)
    elif isinstance(attacker, HeroInstance) and isinstance(defender, MinionInstance):
        return resolve_hero_vs_minion(state, attacker, defender)
    elif isinstance(attacker, HeroInstance) and isinstance(defender, HeroInstance):
        return resolve_hero_vs_hero(state, attacker, defender)
    else:
        raise ValueError(f"Invalid attacker/defender types: {type(attacker)}, {type(defender)}")


def end_turn(state: GameState) -> None:
    """End the active player's turn."""
    if state.phase == GamePhase.GAME_OVER:
        raise ValueError("Game is already over.")
    state.end_turn()


def use_hero_power(
    state: GameState,
    target: Optional[Union[MinionInstance, HeroInstance]] = None,
) -> None:
    """
    Use the active player's hero power.

    Phase 1 stub: implements a generic 2-damage hero power (like Mage's Fireblast).
    Real per-class hero powers will be wired in Phase 5.
    """
    check_use_hero_power(state)
    ap = state.active_player

    ap.spend_mana(ap.hero.hero_power_cost)
    ap.hero.hero_power_used = True

    # Generic stub: deal 2 damage to target if provided, otherwise no-op
    if target is not None:
        if isinstance(target, MinionInstance):
            target.take_damage(2)
        elif isinstance(target, HeroInstance):
            target.take_damage(2)
        process_deaths(state)
