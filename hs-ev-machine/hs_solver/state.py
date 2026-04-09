"""
Phase 1.2 — Game State Model

Represents a complete Hearthstone game state: two players, their heroes,
hands, boards, decks, mana, and turn metadata.

Design notes:
- All state is mutable in place (no immutable tree) — MCTS clones via copy.deepcopy
- Board is a list of MinionInstance (not Card); each minion on board is a live
  entity with current HP, attack state, divine shield pop, etc.
- We track player index (0 or 1) for the active player to keep logic simple
- Fatigue starts at 1 and increments each time a player draws from an empty deck
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from hs_solver.card import Card, CardType


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_BOARD_SIZE = 7
MAX_HAND_SIZE = 10
MAX_MANA = 10


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class GamePhase(Enum):
    """Current phase within a turn."""
    MAIN = auto()       # normal actions (play card, attack, use hero power)
    END = auto()        # end-of-turn effects resolving
    GAME_OVER = auto()


class PlayerID(int, Enum):
    P1 = 0
    P2 = 1

    @property
    def opponent(self) -> "PlayerID":
        return PlayerID.P2 if self == PlayerID.P1 else PlayerID.P1


# ---------------------------------------------------------------------------
# MinionInstance — a card on the board with live state
# ---------------------------------------------------------------------------


@dataclass
class MinionInstance:
    """
    A minion in play. Wraps the base Card definition and adds runtime state.

    Attributes that differ from the base card:
      current_health  — may differ from card.health after damage
      current_attack  — may differ after buffs/debuffs
      divine_shield   — True until first damage hit pops it
      attacks_used    — number of attacks taken this turn (reset on turn start)
      exhausted       — can't attack (summoned this turn without Charge/Rush,
                        or already attacked max times)
      silenced        — all text/mechanics stripped
      frozen          — can't attack next turn
      taunt           — may be overridden by silence
      stealth         — can't be targeted (cleared on attack)
      immune          — takes no damage and can't be targeted
      poisonous       — kills anything it damages
      lifesteal       — controller gains life equal to damage dealt
    """

    card: Card
    owner: PlayerID

    # Mutable combat stats (start as card base values)
    current_attack: int = field(init=False)
    current_health: int = field(init=False)
    max_health: int = field(init=False)

    # Runtime flags
    divine_shield: bool = field(init=False)
    exhausted: bool = True        # True by default; cleared if Charge/Rush
    attacks_used: int = 0
    frozen: bool = False
    silenced: bool = False
    taunt: bool = field(init=False)
    stealth: bool = field(init=False)
    immune: bool = False
    poisonous: bool = field(init=False)
    lifesteal: bool = field(init=False)

    # Unique ID for targeting (set by game state on summon)
    instance_id: int = -1

    def __post_init__(self):
        self.current_attack = self.card.attack or 0
        self.current_health = self.card.health or 1
        self.max_health = self.card.health or 1
        self.divine_shield = self.card.has_divine_shield
        self.taunt = self.card.has_taunt
        self.stealth = self.card.has_stealth
        self.poisonous = self.card.has_poisonous
        self.lifesteal = self.card.has_lifesteal

        # Charge → ready to attack immediately; Rush → can attack minions only
        if self.card.has_charge:
            self.exhausted = False
        # Rush: not exhausted but can only attack minions (enforced in action gen)
        elif self.card.has_rush:
            self.exhausted = False

    @property
    def has_rush(self) -> bool:
        return (not self.silenced) and self.card.has_rush and (not self.card.has_charge)

    @property
    def is_alive(self) -> bool:
        return self.current_health > 0

    @property
    def can_attack(self) -> bool:
        if self.exhausted:
            return False
        if self.frozen:
            return False
        if self.current_attack <= 0:
            return False
        max_attacks = self.card.attacks_per_turn
        return self.attacks_used < max_attacks

    def take_damage(self, amount: int) -> int:
        """
        Apply damage to this minion, respecting divine shield.
        Returns actual damage dealt (0 if divine shield absorbed).
        """
        if self.immune:
            return 0
        if amount <= 0:
            return 0
        if self.divine_shield:
            self.divine_shield = False
            return 0
        self.current_health -= amount
        return amount

    def heal(self, amount: int) -> None:
        """Restore health up to max_health."""
        self.current_health = min(self.max_health, self.current_health + amount)

    def silence(self) -> None:
        """Strip all text effects and keywords."""
        self.silenced = True
        self.taunt = False
        self.divine_shield = False
        self.stealth = False
        self.poisonous = False
        self.lifesteal = False
        self.frozen = False
        self.immune = False
        # Attack/health are NOT reset by silence (only text effects are removed)

    def refresh_for_turn(self) -> None:
        """Called at start of owner's turn."""
        self.attacks_used = 0
        self.exhausted = False
        self.frozen = False

    def __repr__(self) -> str:
        flags = []
        if self.taunt: flags.append("T")
        if self.divine_shield: flags.append("DS")
        if self.exhausted: flags.append("X")
        if self.frozen: flags.append("F")
        if self.stealth: flags.append("ST")
        if self.silenced: flags.append("SIL")
        flag_str = f"[{','.join(flags)}]" if flags else ""
        return (
            f"Minion<{self.card.name} "
            f"{self.current_attack}/{self.current_health}{flag_str} "
            f"#{self.instance_id}>"
        )


# ---------------------------------------------------------------------------
# HeroInstance — represents a player's hero
# ---------------------------------------------------------------------------


@dataclass
class HeroInstance:
    """
    A player's hero with health, armor, weapon, and hero power state.
    """

    name: str
    owner: PlayerID
    health: int = 30
    max_health: int = 30
    armor: int = 0

    # Weapon (optional)
    weapon_attack: int = 0
    weapon_durability: int = 0

    # Hero power
    hero_power_used: bool = False
    hero_power_cost: int = 2

    # Attack per turn (from weapon or effect)
    attacks_used: int = 0
    frozen: bool = False
    immune: bool = False

    @property
    def attack(self) -> int:
        return self.weapon_attack

    @property
    def total_health(self) -> int:
        """HP + armor (used for win condition checks)."""
        return self.health + self.armor

    @property
    def is_alive(self) -> bool:
        return self.health > 0

    @property
    def can_attack(self) -> bool:
        return (
            self.weapon_attack > 0
            and self.attacks_used == 0
            and not self.frozen
        )

    def take_damage(self, amount: int) -> int:
        """Damage hero: armor absorbs first, then health. Returns actual health lost."""
        if self.immune or amount <= 0:
            return 0
        armor_absorbed = min(self.armor, amount)
        self.armor -= armor_absorbed
        health_lost = amount - armor_absorbed
        self.health -= health_lost
        return health_lost

    def heal(self, amount: int) -> None:
        self.health = min(self.max_health, self.health + amount)

    def use_weapon_attack(self) -> None:
        """Called after hero attacks with weapon."""
        self.attacks_used += 1
        if self.weapon_durability > 0:
            self.weapon_durability -= 1
            if self.weapon_durability == 0:
                self.weapon_attack = 0

    def equip_weapon(self, attack: int, durability: int) -> None:
        self.weapon_attack = attack
        self.weapon_durability = durability

    def refresh_for_turn(self) -> None:
        self.attacks_used = 0
        self.hero_power_used = False
        self.frozen = False

    def __repr__(self) -> str:
        parts = [f"Hero<{self.name} {self.health}HP"]
        if self.armor:
            parts.append(f"+{self.armor}armor")
        if self.weapon_attack:
            parts.append(f"weapon={self.weapon_attack}/{self.weapon_durability}")
        parts.append(">")
        return " ".join(parts)


# ---------------------------------------------------------------------------
# PlayerState — one side of the board
# ---------------------------------------------------------------------------


@dataclass
class PlayerState:
    """
    Full state for one player: hero, hand, board, deck, mana.
    """

    player_id: PlayerID
    hero: HeroInstance

    # Deck: list of Cards (index 0 = top of deck)
    deck: list[Card] = field(default_factory=list)

    # Hand: list of Cards
    hand: list[Card] = field(default_factory=list)

    # Board: list of MinionInstances (left to right, max 7)
    board: list[MinionInstance] = field(default_factory=list)

    # Mana
    mana: int = 0
    max_mana: int = 0
    mana_locked: int = 0      # overloaded mana (locked next turn)
    mana_overloaded: int = 0  # mana overloaded this turn (set next turn)

    # Fatigue counter (starts at 1, increases each empty draw)
    fatigue: int = 0

    # Graveyard (minions that have died this game — needed for some effects later)
    graveyard: list[MinionInstance] = field(default_factory=list)

    @property
    def board_full(self) -> bool:
        return len(self.board) >= MAX_BOARD_SIZE

    @property
    def hand_full(self) -> bool:
        return len(self.hand) >= MAX_HAND_SIZE

    def gain_mana_crystal(self) -> None:
        """Add one mana crystal (up to MAX_MANA)."""
        if self.max_mana < MAX_MANA:
            self.max_mana += 1

    def refresh_mana(self) -> None:
        """
        Restore mana at start of turn.

        mana_overloaded accumulates during a player's turn when they play
        overload cards. At the START of their NEXT turn, those crystals are
        locked (unavailable). This single-pass design avoids an off-by-one
        that the two-variable (locked/overloaded) approach produces.
        """
        self.mana = max(0, self.max_mana - self.mana_overloaded)
        self.mana_locked = self.mana_overloaded   # informational only
        self.mana_overloaded = 0

    def spend_mana(self, amount: int) -> None:
        assert amount <= self.mana, f"Not enough mana: have {self.mana}, need {amount}"
        self.mana -= amount

    def draw_card(self) -> Optional[Card]:
        """
        Draw from top of deck. Returns None on empty deck (fatigue applied instead).
        """
        if not self.deck:
            self.fatigue += 1
            self.hero.take_damage(self.fatigue)
            return None

        card = self.deck.pop(0)
        if not self.hand_full:
            self.hand.append(card)
            return card
        else:
            # Overdraw — card is burned (discarded without entering hand)
            return None

    def shuffle_deck(self) -> None:
        random.shuffle(self.deck)

    def __repr__(self) -> str:
        return (
            f"Player{self.player_id.value}("
            f"mana={self.mana}/{self.max_mana}, "
            f"hand={len(self.hand)}, "
            f"deck={len(self.deck)}, "
            f"board={len(self.board)}, "
            f"hero={self.hero})"
        )


# ---------------------------------------------------------------------------
# GameState — top-level container
# ---------------------------------------------------------------------------

_instance_counter = 0


def _next_instance_id() -> int:
    global _instance_counter
    _instance_counter += 1
    return _instance_counter


@dataclass
class GameState:
    """
    Complete game state for one Hearthstone game.

    Convention:
      active_player_id  — whose turn it is
      players[0]        — Player 1
      players[1]        — Player 2
      turn              — starts at 1, increments after both players have gone
    """

    players: list[PlayerState]
    active_player_id: PlayerID = PlayerID.P1
    turn: int = 1
    phase: GamePhase = GamePhase.MAIN

    # Coin flip: P1 goes first (no coin), P2 gets The Coin in hand
    # This is handled at setup, not in GameState itself.

    @property
    def active_player(self) -> PlayerState:
        return self.players[self.active_player_id]

    @property
    def inactive_player(self) -> PlayerState:
        return self.players[1 - self.active_player_id]

    @property
    def winner(self) -> Optional[PlayerID]:
        """Return winning PlayerID if game is over, else None."""
        p1_dead = not self.players[0].hero.is_alive
        p2_dead = not self.players[1].hero.is_alive
        if p1_dead and p2_dead:
            # Simultaneous death → active player loses (they attacked)
            return self.active_player_id.opponent
        if p1_dead:
            return PlayerID.P2
        if p2_dead:
            return PlayerID.P1
        return None

    @property
    def is_game_over(self) -> bool:
        # Phase is set GAME_OVER eagerly by process_deaths and start_turn —
        # that path short-circuits here (O(1) enum check).
        # Two direct health comparisons as a safety net for tests / edge cases
        # where hero health was mutated outside those paths. Stays O(1).
        return (
            self.phase == GamePhase.GAME_OVER
            or self.players[0].hero.health <= 0
            or self.players[1].hero.health <= 0
        )

    def summon_minion(self, card: Card, owner: PlayerID, position: int = -1) -> MinionInstance:
        """
        Create a MinionInstance and place it on the owner's board.

        Args:
            card: The card to summon.
            owner: Which player owns the minion.
            position: Board index to insert at. -1 = rightmost.

        Returns:
            The new MinionInstance (already on board).
        """
        player = self.players[owner]
        assert not player.board_full, "Board is full"
        assert card.is_minion, f"{card.name} is not a minion"

        minion = MinionInstance(card=card, owner=owner)
        minion.instance_id = _next_instance_id()

        if position < 0 or position >= len(player.board):
            player.board.append(minion)
        else:
            player.board.insert(position, minion)

        return minion

    def remove_minion(self, minion: MinionInstance) -> None:
        """Remove a dead minion from the board and add it to graveyard."""
        player = self.players[minion.owner]
        if minion in player.board:
            player.board.remove(minion)
            player.graveyard.append(minion)

    def start_turn(self) -> None:
        """
        Transition to the active player's turn:
        - Gain mana crystal
        - Refresh mana (with overload)
        - Draw a card (may cause fatigue damage)
        - Refresh hero and minions
        """
        ap = self.active_player
        ap.gain_mana_crystal()
        ap.refresh_mana()
        ap.draw_card()
        # Fatigue may have killed the hero — set GAME_OVER eagerly so
        # is_game_over is a simple phase check rather than recomputing winner.
        if not ap.hero.is_alive:
            self.phase = GamePhase.GAME_OVER
            return
        ap.hero.refresh_for_turn()
        for minion in ap.board:
            minion.refresh_for_turn()
        self.phase = GamePhase.MAIN

    def end_turn(self) -> None:
        """
        End the active player's turn and swap to opponent.
        Freeze minions that didn't attack, then switch active player.
        """
        self.phase = GamePhase.END
        # Freeze minions that were frozen this turn (they can't attack next turn)
        # (Freeze application happens in rules/combat; here we just swap)
        next_player = self.active_player_id.opponent
        self.active_player_id = next_player
        # Increment turn counter after P2's turn completes
        if next_player == PlayerID.P1:
            self.turn += 1
        self.start_turn()  # sets phase = GAME_OVER on fatigue death

    def clone(self) -> "GameState":
        """
        Fast copy of this game state for tree search.

        Shares immutable Card references (no deepcopy of card data).
        Only MinionInstance, HeroInstance, and PlayerState fields are copied.
        ~5-8x faster than copy.deepcopy on typical mid-game states.
        """
        return GameState(
            players=[_clone_player(p) for p in self.players],
            active_player_id=self.active_player_id,
            turn=self.turn,
            phase=self.phase,
        )

    def __repr__(self) -> str:
        return (
            f"GameState(turn={self.turn}, "
            f"active=P{self.active_player_id.value + 1}, "
            f"phase={self.phase.name}, "
            f"P1={self.players[0]}, "
            f"P2={self.players[1]})"
        )


# ---------------------------------------------------------------------------
# Fast clone helpers (avoid deepcopy of immutable Card objects)
# ---------------------------------------------------------------------------


def _clone_hero(h: HeroInstance) -> HeroInstance:
    """Shallow-field copy of a HeroInstance (no nested objects to worry about)."""
    new_h: HeroInstance = object.__new__(HeroInstance)
    new_h.name = h.name
    new_h.owner = h.owner
    new_h.health = h.health
    new_h.max_health = h.max_health
    new_h.armor = h.armor
    new_h.weapon_attack = h.weapon_attack
    new_h.weapon_durability = h.weapon_durability
    new_h.hero_power_used = h.hero_power_used
    new_h.hero_power_cost = h.hero_power_cost
    new_h.attacks_used = h.attacks_used
    new_h.frozen = h.frozen
    new_h.immune = h.immune
    return new_h


def _clone_minion(m: MinionInstance) -> MinionInstance:
    """
    Copy a MinionInstance, sharing the underlying Card (immutable template).
    All runtime-mutable fields are independently copied.
    """
    new_m: MinionInstance = object.__new__(MinionInstance)
    new_m.card = m.card          # immutable template — shared reference is safe
    new_m.owner = m.owner
    new_m.current_attack = m.current_attack
    new_m.current_health = m.current_health
    new_m.max_health = m.max_health
    new_m.divine_shield = m.divine_shield
    new_m.exhausted = m.exhausted
    new_m.attacks_used = m.attacks_used
    new_m.frozen = m.frozen
    new_m.silenced = m.silenced
    new_m.taunt = m.taunt
    new_m.stealth = m.stealth
    new_m.immune = m.immune
    new_m.poisonous = m.poisonous
    new_m.lifesteal = m.lifesteal
    new_m.instance_id = m.instance_id
    return new_m


def _clone_player(p: PlayerState) -> PlayerState:
    """Copy a PlayerState, cloning mutable entities and shallow-copying card lists."""
    new_p: PlayerState = object.__new__(PlayerState)
    new_p.player_id = p.player_id
    new_p.hero = _clone_hero(p.hero)
    new_p.deck = list(p.deck)        # Cards are immutable — shallow copy ok
    new_p.hand = list(p.hand)
    new_p.board = [_clone_minion(m) for m in p.board]
    new_p.graveyard = [_clone_minion(m) for m in p.graveyard]
    new_p.mana = p.mana
    new_p.max_mana = p.max_mana
    new_p.mana_locked = p.mana_locked
    new_p.mana_overloaded = p.mana_overloaded
    new_p.fatigue = p.fatigue
    return new_p


# ---------------------------------------------------------------------------
# Factory — build a fresh game state from two decklists
# ---------------------------------------------------------------------------


def new_game(deck1: list[Card], deck2: list[Card],
             hero1_name: str = "Jaina",
             hero2_name: str = "Rexxar") -> GameState:
    """
    Create a fresh GameState with shuffled decks and opening hands drawn.

    P1 draws 3 cards; P2 draws 4 cards (The Coin is NOT implemented yet —
    add in Phase 2 deck builder).

    Turn 1 mana is set to 1 (gained when start_turn() is called on first turn).
    We call start_turn() so P1 is ready to act immediately.
    """
    p1 = PlayerState(
        player_id=PlayerID.P1,
        hero=HeroInstance(name=hero1_name, owner=PlayerID.P1),
        deck=list(deck1),
    )
    p2 = PlayerState(
        player_id=PlayerID.P2,
        hero=HeroInstance(name=hero2_name, owner=PlayerID.P2),
        deck=list(deck2),
    )

    p1.shuffle_deck()
    p2.shuffle_deck()

    # Mulligan draw (simplified: just draw opening hand, no redraw)
    for _ in range(3):
        p1.draw_card()
    for _ in range(4):
        p2.draw_card()

    state = GameState(players=[p1, p2], active_player_id=PlayerID.P1, turn=1)

    # Start P1's first turn (gains 1 mana crystal, draws 1 card)
    state.start_turn()
    return state
