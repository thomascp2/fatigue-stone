"""
Phase 2.1 — Action Generator

Defines the Action type and enumerates all legal actions from a GameState.
Also provides apply_action() to execute an action in place.

Action representation:
  All fields are primitive (int, bool) so Action is hashable and can be used
  as a dict key for CFR strategy tables in Phase 4.

Board position references:
  attacker_idx / defender_idx  — index into active / inactive player's board
  target_owner (0/1)           — active (0) or inactive (1) player for spells
  target_idx                   — index into that player's board

Targeting conventions:
  - Attackers are always on the ACTIVE player's board
  - Defenders are always on the INACTIVE player's board
  - Spell / hero power targets can be on either board or either hero
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from hs_solver.state import GameState, GamePhase, PlayerID


# ---------------------------------------------------------------------------
# Action types
# ---------------------------------------------------------------------------


class ActionType(Enum):
    PLAY_MINION = auto()
    PLAY_SPELL = auto()
    PLAY_WEAPON = auto()
    ATTACK = auto()
    USE_HERO_POWER = auto()
    END_TURN = auto()


# ---------------------------------------------------------------------------
# Action dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Action:
    """
    An atomic game action. Frozen and hashable for use as a CFR dict key.

    Fields used per action type:
      PLAY_MINION:    hand_idx, board_pos
      PLAY_SPELL:     hand_idx, target_owner, target_is_hero, target_idx
      PLAY_WEAPON:    hand_idx
      ATTACK:         attacker_is_hero, attacker_idx,
                      defender_is_hero, defender_idx
      USE_HERO_POWER: target_owner, target_is_hero, target_idx
      END_TURN:       (no extra fields)
    """

    type: ActionType

    # Card play
    hand_idx: int = -1
    board_pos: int = -1          # minion placement position (-1 = rightmost)

    # Attack
    attacker_is_hero: bool = False
    attacker_idx: int = -1       # active player board index
    defender_is_hero: bool = False
    defender_idx: int = -1       # inactive player board index

    # Spell / hero power target
    target_owner: int = -1       # 0 = active player, 1 = inactive player
    target_is_hero: bool = False
    target_idx: int = -1         # board index (-1 if hero)

    # -----------------------------------------------------------------------
    # Convenience constructors
    # -----------------------------------------------------------------------

    @staticmethod
    def end_turn() -> "Action":
        return Action(type=ActionType.END_TURN)

    @staticmethod
    def play_minion(hand_idx: int, board_pos: int = -1) -> "Action":
        return Action(type=ActionType.PLAY_MINION, hand_idx=hand_idx, board_pos=board_pos)

    @staticmethod
    def play_spell(hand_idx: int, target_owner: int = -1,
                   target_is_hero: bool = False, target_idx: int = -1) -> "Action":
        return Action(
            type=ActionType.PLAY_SPELL,
            hand_idx=hand_idx,
            target_owner=target_owner,
            target_is_hero=target_is_hero,
            target_idx=target_idx,
        )

    @staticmethod
    def play_weapon(hand_idx: int) -> "Action":
        return Action(type=ActionType.PLAY_WEAPON, hand_idx=hand_idx)

    @staticmethod
    def attack(attacker_is_hero: bool, attacker_idx: int,
               defender_is_hero: bool, defender_idx: int) -> "Action":
        return Action(
            type=ActionType.ATTACK,
            attacker_is_hero=attacker_is_hero,
            attacker_idx=attacker_idx,
            defender_is_hero=defender_is_hero,
            defender_idx=defender_idx,
        )

    @staticmethod
    def use_hero_power(target_owner: int = -1,
                       target_is_hero: bool = False,
                       target_idx: int = -1) -> "Action":
        return Action(
            type=ActionType.USE_HERO_POWER,
            target_owner=target_owner,
            target_is_hero=target_is_hero,
            target_idx=target_idx,
        )

    def __repr__(self) -> str:  # noqa: too-many-return-statements
        t = self.type
        if t == ActionType.END_TURN:
            return "Action<END_TURN>"
        if t == ActionType.PLAY_MINION:
            return f"Action<PLAY_MINION hand[{self.hand_idx}] pos={self.board_pos}>"
        if t == ActionType.PLAY_SPELL:
            tgt = "hero" if self.target_is_hero else f"board[{self.target_idx}]"
            owner = "active" if self.target_owner == 0 else "inactive"
            return f"Action<PLAY_SPELL hand[{self.hand_idx}] → {owner}.{tgt}>"
        if t == ActionType.PLAY_WEAPON:
            return f"Action<PLAY_WEAPON hand[{self.hand_idx}]>"
        if t == ActionType.ATTACK:
            a = "hero" if self.attacker_is_hero else f"board[{self.attacker_idx}]"
            d = "hero" if self.defender_is_hero else f"board[{self.defender_idx}]"
            return f"Action<ATTACK {a} → {d}>"
        if t == ActionType.USE_HERO_POWER:
            tgt = "hero" if self.target_is_hero else f"board[{self.target_idx}]"
            owner = "active" if self.target_owner == 0 else "inactive"
            return f"Action<HERO_POWER → {owner}.{tgt}>"
        return f"Action<{t.name}>"


# ---------------------------------------------------------------------------
# Legal action enumeration
# ---------------------------------------------------------------------------


def get_legal_actions(state: GameState, full_positions: bool = False) -> list[Action]:
    """
    Return all legal actions from the current game state.

    Args:
        state:          Current game state.
        full_positions: If True, generate one action per board position for
                        each playable minion (needed for MCTS). If False,
                        generate one action per card (position=-1, rightmost),
                        which is faster for random rollouts.

    Returns:
        List of legal Action objects. Always contains at least END_TURN
        unless the game is already over.
    """
    if state.is_game_over:
        return []

    actions: list[Action] = []
    ap = state.active_player
    ip = state.inactive_player

    # ------------------------------------------------------------------
    # 1. Play cards from hand
    # ------------------------------------------------------------------
    for hand_idx, card in enumerate(ap.hand):
        if card.cost > ap.mana:
            continue

        if card.is_minion and not ap.board_full:
            if full_positions:
                # One action per board position (0..len(board))
                n_positions = len(ap.board) + 1
                for pos in range(n_positions):
                    actions.append(Action.play_minion(hand_idx, pos))
            else:
                actions.append(Action.play_minion(hand_idx, -1))

        elif card.is_spell:
            # Phase 2: generate one untargeted action per spell.
            # Targeted spells will be expanded in Phase 3 when SpellEffect is wired.
            actions.append(Action.play_spell(hand_idx))

        elif card.is_weapon:
            actions.append(Action.play_weapon(hand_idx))

    # ------------------------------------------------------------------
    # 2. Attack actions
    # ------------------------------------------------------------------
    # Build indexed defender list in one pass — avoids O(n) list.index() calls.
    taunt_with_idx: list[tuple[int, MinionInstance]] = []
    any_valid_with_idx: list[tuple[int, MinionInstance]] = []
    for def_idx, m in enumerate(ip.board):
        if m.stealth or m.immune:
            continue
        any_valid_with_idx.append((def_idx, m))
        if m.taunt:
            taunt_with_idx.append((def_idx, m))

    # Taunt forces attackers onto taunted minions only
    valid_targets_with_idx = taunt_with_idx if taunt_with_idx else any_valid_with_idx
    hero_is_attackable: bool = (not bool(taunt_with_idx)) and (not ip.hero.immune)

    # Minion attacks
    for atk_idx, minion in enumerate(ap.board):
        if not minion.can_attack:
            continue
        for def_idx, _ in valid_targets_with_idx:
            actions.append(Action.attack(
                attacker_is_hero=False, attacker_idx=atk_idx,
                defender_is_hero=False, defender_idx=def_idx,
            ))
        # Rush minions can't attack heroes on the turn they're played
        if hero_is_attackable and not minion.has_rush:
            actions.append(Action.attack(
                attacker_is_hero=False, attacker_idx=atk_idx,
                defender_is_hero=True, defender_idx=-1,
            ))

    # Hero attacks
    if ap.hero.can_attack:
        for def_idx, _ in valid_targets_with_idx:
            actions.append(Action.attack(
                attacker_is_hero=True, attacker_idx=-1,
                defender_is_hero=False, defender_idx=def_idx,
            ))
        if hero_is_attackable:
            actions.append(Action.attack(
                attacker_is_hero=True, attacker_idx=-1,
                defender_is_hero=True, defender_idx=-1,
            ))

    # ------------------------------------------------------------------
    # 3. Hero power
    # ------------------------------------------------------------------
    if (not ap.hero.hero_power_used
            and ap.mana >= ap.hero.hero_power_cost):
        # Phase 2: generate one untargeted hero power action.
        # Targeted hero powers (Mage, Priest) will be expanded in Phase 3.
        actions.append(Action.use_hero_power())

    # ------------------------------------------------------------------
    # 4. End turn (always legal)
    # ------------------------------------------------------------------
    actions.append(Action.end_turn())

    return actions


# ---------------------------------------------------------------------------
# Action execution
# ---------------------------------------------------------------------------


def apply_action(state: GameState, action: Action) -> None:
    """
    Execute an action, mutating state in place.

    Imports rules functions here to avoid circular imports at module level.
    """
    from hs_solver.rules import (
        attack,
        end_turn,
        play_minion,
        play_spell,
        use_hero_power,
    )

    ap = state.active_player
    ip = state.inactive_player
    t = action.type

    if t == ActionType.END_TURN:
        end_turn(state)

    elif t == ActionType.PLAY_MINION:
        card = ap.hand[action.hand_idx]
        play_minion(state, card, position=action.board_pos)

    elif t == ActionType.PLAY_SPELL:
        card = ap.hand[action.hand_idx]
        # Phase 2: no effect resolver wired. Spell pays mana, enters graveyard.
        play_spell(state, card, effect=None)

    elif t == ActionType.PLAY_WEAPON:
        card = ap.hand[action.hand_idx]
        _apply_play_weapon(state, card)

    elif t == ActionType.ATTACK:
        # Actions from get_legal_actions are pre-validated — call combat
        # resolvers directly to bypass the redundant check_attack pass.
        from hs_solver.combat import (
            resolve_hero_vs_hero,
            resolve_hero_vs_minion,
            resolve_minion_vs_hero,
            resolve_minion_vs_minion,
        )
        if action.attacker_is_hero:
            if action.defender_is_hero:
                resolve_hero_vs_hero(state, ap.hero, ip.hero)
            else:
                resolve_hero_vs_minion(state, ap.hero, ip.board[action.defender_idx])
        else:
            attacker = ap.board[action.attacker_idx]
            if action.defender_is_hero:
                resolve_minion_vs_hero(state, attacker, ip.hero)
            else:
                resolve_minion_vs_minion(state, attacker, ip.board[action.defender_idx])

    elif t == ActionType.USE_HERO_POWER:
        # Resolve target reference if provided
        target = None
        if action.target_owner != -1:
            tgt_player = state.players[action.target_owner]
            if action.target_is_hero:
                target = tgt_player.hero
            elif action.target_idx >= 0:
                target = tgt_player.board[action.target_idx]
        use_hero_power(state, target)


def _apply_play_weapon(state: GameState, card) -> None:
    """Equip a weapon card. Minimal implementation for Phase 2."""
    from hs_solver.rules import check_play_spell  # reuse mana/hand checks
    from hs_solver.card import CardType

    ap = state.active_player
    if card not in ap.hand:
        raise ValueError(f"{card.name} is not in hand.")
    if ap.mana < card.cost:
        raise ValueError(f"Not enough mana for {card.name}.")
    if card.card_type != CardType.WEAPON:
        raise ValueError(f"{card.name} is not a weapon.")

    ap.spend_mana(card.cost)
    ap.hand.remove(card)
    # Equip: attack from card.attack, durability from card.durability
    ap.hero.equip_weapon(
        attack=card.attack or 0,
        durability=card.durability or 2,
    )
