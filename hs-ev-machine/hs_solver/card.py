"""
Card data model and ingestion from HearthstoneJSON.

HearthstoneJSON schema reference:
  https://hearthstonejson.com/docs/cards.html

We normalize the raw JSON into a clean Card dataclass, keeping only fields
relevant to our simulation scope (Phase 1-2). Edge-case mechanics are
acknowledged but not modeled yet.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CardType(str, Enum):
    MINION = "MINION"
    SPELL = "SPELL"
    WEAPON = "WEAPON"
    HERO = "HERO"
    HERO_POWER = "HERO_POWER"
    LOCATION = "LOCATION"
    UNKNOWN = "UNKNOWN"


class CardClass(str, Enum):
    NEUTRAL = "NEUTRAL"
    DRUID = "DRUID"
    HUNTER = "HUNTER"
    MAGE = "MAGE"
    PALADIN = "PALADIN"
    PRIEST = "PRIEST"
    ROGUE = "ROGUE"
    SHAMAN = "SHAMAN"
    WARLOCK = "WARLOCK"
    WARRIOR = "WARRIOR"
    DEMONHUNTER = "DEMONHUNTER"
    DEATHKNIGHT = "DEATHKNIGHT"
    UNKNOWN = "UNKNOWN"


class Rarity(str, Enum):
    FREE = "FREE"
    COMMON = "COMMON"
    RARE = "RARE"
    EPIC = "EPIC"
    LEGENDARY = "LEGENDARY"
    UNKNOWN = "UNKNOWN"


class SpellSchool(str, Enum):
    ARCANE = "ARCANE"
    FIRE = "FIRE"
    FROST = "FROST"
    NATURE = "NATURE"
    HOLY = "HOLY"
    SHADOW = "SHADOW"
    FEL = "FEL"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Keyword mechanics we model in Phase 1-2
# ---------------------------------------------------------------------------

MODELED_MECHANICS = {
    "TAUNT",
    "DIVINE_SHIELD",
    "CHARGE",
    "RUSH",
    "WINDFURY",
    "MEGA_WINDFURY",   # attacks 4x — treat as windfury extension
    "POISONOUS",
    "LIFESTEAL",
    "STEALTH",
    "CANT_ATTACK",
    "IMMUNE",
    "FREEZE",          # on attack or battlecry spell
    "SILENCED",        # runtime state, not a card keyword
    "DEATHRATTLE",     # flag only — effects handled per-card later
    "BATTLECRY",       # flag only
    "OVERLOAD",        # overload crystal count stored separately
}


# ---------------------------------------------------------------------------
# Card dataclass
# ---------------------------------------------------------------------------


@dataclass
class Card:
    """
    Normalized representation of a Hearthstone card.

    Only fields used by the simulation engine are kept. Fields like artist,
    flavor text, and collectibility are discarded at ingestion time.
    """

    # Identity
    id: str                            # dbfId as string (stable across patches)
    name: str
    card_type: CardType
    card_class: CardClass
    rarity: Rarity

    # Cost
    cost: int = 0                      # mana cost; 0 for uncollectible tokens

    # Minion stats (None for spells/weapons)
    attack: Optional[int] = None
    health: Optional[int] = None
    durability: Optional[int] = None   # weapon durability

    # Spell subtype
    spell_school: Optional[SpellSchool] = None

    # Keywords (modeled set only)
    mechanics: set[str] = field(default_factory=set)

    # Overload crystal count (SHAMAN mechanic)
    overload: int = 0

    # Raw text for later NLP / manual effect mapping
    text: Optional[str] = None

    # Collectible flag — tokens are False
    collectible: bool = True

    # Set / expansion tag (e.g. "CORE", "TITANS", etc.)
    card_set: Optional[str] = None

    # ---------------------------------------------------------------------------
    # Convenience properties
    # ---------------------------------------------------------------------------

    @property
    def is_minion(self) -> bool:
        return self.card_type == CardType.MINION

    @property
    def is_spell(self) -> bool:
        return self.card_type == CardType.SPELL

    @property
    def is_weapon(self) -> bool:
        return self.card_type == CardType.WEAPON

    @property
    def has_taunt(self) -> bool:
        return "TAUNT" in self.mechanics

    @property
    def has_divine_shield(self) -> bool:
        return "DIVINE_SHIELD" in self.mechanics

    @property
    def has_charge(self) -> bool:
        return "CHARGE" in self.mechanics

    @property
    def has_rush(self) -> bool:
        return "RUSH" in self.mechanics

    @property
    def has_windfury(self) -> bool:
        return "WINDFURY" in self.mechanics or "MEGA_WINDFURY" in self.mechanics

    @property
    def has_poisonous(self) -> bool:
        return "POISONOUS" in self.mechanics

    @property
    def has_lifesteal(self) -> bool:
        return "LIFESTEAL" in self.mechanics

    @property
    def has_stealth(self) -> bool:
        return "STEALTH" in self.mechanics

    @property
    def has_deathrattle(self) -> bool:
        return "DEATHRATTLE" in self.mechanics

    @property
    def has_battlecry(self) -> bool:
        return "BATTLECRY" in self.mechanics

    @property
    def attacks_per_turn(self) -> int:
        """How many times this minion can attack in a single turn."""
        if "MEGA_WINDFURY" in self.mechanics:
            return 4
        if "WINDFURY" in self.mechanics:
            return 2
        return 1

    def __repr__(self) -> str:
        parts = [f"{self.name!r}({self.cost}"]
        if self.is_minion and self.attack is not None and self.health is not None:
            parts.append(f" {self.attack}/{self.health}")
        parts.append(")")
        mech_flags = sorted(self.mechanics & MODELED_MECHANICS)
        if mech_flags:
            parts.append(f" [{', '.join(mech_flags)}]")
        return "Card<" + "".join(parts) + ">"


# ---------------------------------------------------------------------------
# Ingestion — raw HearthstoneJSON → Card objects
# ---------------------------------------------------------------------------

# Map HearthstoneJSON mechanic strings to our canonical names.
# Keys are what appears in the raw JSON; values are what we store.
_MECHANIC_MAP: dict[str, str] = {
    "TAUNT": "TAUNT",
    "DIVINE_SHIELD": "DIVINE_SHIELD",
    "CHARGE": "CHARGE",
    "RUSH": "RUSH",
    "WINDFURY": "WINDFURY",
    "MEGA_WINDFURY": "MEGA_WINDFURY",
    "POISONOUS": "POISONOUS",
    "LIFESTEAL": "LIFESTEAL",
    "STEALTH": "STEALTH",
    "CANT_ATTACK": "CANT_ATTACK",
    "IMMUNE": "IMMUNE",
    "FREEZE": "FREEZE",
    "DEATHRATTLE": "DEATHRATTLE",
    "BATTLECRY": "BATTLECRY",
    "OVERLOAD": "OVERLOAD",   # presence flag; value stored in overload field
}


def _parse_card(raw: dict) -> Optional[Card]:
    """
    Convert one raw HearthstoneJSON entry into a Card.

    Returns None for entries we cannot use (e.g., missing name, unknown type).
    """
    # Skip entries without a name or dbfId
    name = raw.get("name", "").strip()
    dbf_id = raw.get("dbfId")
    if not name or dbf_id is None:
        return None

    card_id = str(dbf_id)

    # Card type
    raw_type = raw.get("type", "")
    try:
        card_type = CardType(raw_type)
    except ValueError:
        card_type = CardType.UNKNOWN

    # Skip types we never simulate (enchantments, abilities, etc.)
    if card_type not in {
        CardType.MINION, CardType.SPELL, CardType.WEAPON,
        CardType.HERO, CardType.HERO_POWER, CardType.LOCATION,
    }:
        return None

    # Card class
    raw_class = raw.get("cardClass", raw.get("classes", ["NEUTRAL"]))
    if isinstance(raw_class, list):
        # Multi-class cards: take first class for now
        raw_class = raw_class[0] if raw_class else "NEUTRAL"
    try:
        card_class = CardClass(raw_class)
    except ValueError:
        card_class = CardClass.UNKNOWN

    # Rarity
    try:
        rarity = Rarity(raw.get("rarity", "FREE"))
    except ValueError:
        rarity = Rarity.UNKNOWN

    # Spell school
    spell_school: Optional[SpellSchool] = None
    if raw.get("spellSchool"):
        try:
            spell_school = SpellSchool(raw["spellSchool"])
        except ValueError:
            spell_school = SpellSchool.UNKNOWN

    # Mechanics
    raw_mechanics: list[str] = raw.get("mechanics", [])
    mechanics: set[str] = set()
    for m in raw_mechanics:
        canonical = _MECHANIC_MAP.get(m)
        if canonical and canonical in MODELED_MECHANICS:
            mechanics.add(canonical)

    # Overload value
    overload = int(raw.get("overload", 0))

    return Card(
        id=card_id,
        name=name,
        card_type=card_type,
        card_class=card_class,
        rarity=rarity,
        cost=int(raw.get("cost", 0)),
        attack=raw.get("attack"),
        health=raw.get("health"),
        durability=raw.get("durability"),
        spell_school=spell_school,
        mechanics=mechanics,
        overload=overload,
        text=raw.get("text"),
        collectible=bool(raw.get("collectible", False)),
        card_set=raw.get("set"),
    )


# ---------------------------------------------------------------------------
# Card database
# ---------------------------------------------------------------------------


class CardDB:
    """
    In-memory card database loaded from HearthstoneJSON.

    Access cards by dbfId (string) or by name.
    """

    def __init__(self, cards: list[Card]) -> None:
        self._by_id: dict[str, Card] = {c.id: c for c in cards}
        # Name lookup — last-one-wins if duplicates (shouldn't happen for collectibles)
        self._by_name: dict[str, Card] = {c.name.lower(): c for c in cards}

    def __len__(self) -> int:
        return len(self._by_id)

    def get_by_id(self, card_id: str) -> Optional[Card]:
        return self._by_id.get(str(card_id))

    def get_by_name(self, name: str) -> Optional[Card]:
        return self._by_name.get(name.lower())

    def collectible(self) -> list[Card]:
        return [c for c in self._by_id.values() if c.collectible]

    def by_class(self, card_class: CardClass) -> list[Card]:
        return [
            c for c in self._by_id.values()
            if c.collectible and c.card_class in (card_class, CardClass.NEUTRAL)
        ]

    def minions(self, collectible_only: bool = True) -> list[Card]:
        return [
            c for c in self._by_id.values()
            if c.is_minion and (not collectible_only or c.collectible)
        ]

    def __repr__(self) -> str:
        return f"CardDB({len(self)} cards, {len(self.collectible())} collectible)"


def load_card_db(path: Optional[Path] = None) -> CardDB:
    """
    Load CardDB from a HearthstoneJSON dump.

    Args:
        path: Path to cards.json. Defaults to data/cards.json in project root.
    """
    if path is None:
        path = Path(__file__).parent.parent / "data" / "cards.json"

    if not path.exists():
        raise FileNotFoundError(
            f"Card data not found at {path}. "
            "Run: python scripts/fetch_cards.py"
        )

    raw_cards: list[dict] = json.loads(path.read_text(encoding="utf-8"))
    cards: list[Card] = []
    skipped = 0

    for raw in raw_cards:
        card = _parse_card(raw)
        if card is not None:
            cards.append(card)
        else:
            skipped += 1

    print(f"Loaded {len(cards):,} cards ({skipped:,} skipped) from {path}")
    return CardDB(cards)
