"""
Phase 2.4 — Deck Builder Interface

Handles loading and saving Hearthstone decklists in the official copy/paste
format (base64-encoded binary using variable-length integers).

The deck string format (reverse-engineered, widely documented):
  bytes: [0x00][version varint][format varint]
         [n_heroes varint][hero_id varints...]
         [n_singles varint][single_id varints...]
         [n_doubles varint][double_id varints...]
         [n_multi varint]([count varint][id varint]...)
  then base64-encoded.

References:
  - https://hearthsim.info/docs/deckstrings/
  - HearthstoneJSON uses dbfId as the canonical card ID

Usage:
    from hs_solver.deck import decode_deck_string, build_deck
    from hs_solver.card import load_card_db

    db = load_card_db()
    deck = decode_deck_string("AAECAa0G...")
    cards = build_deck(db, deck)
"""

from __future__ import annotations

import base64
import random
from dataclasses import dataclass, field
from typing import Optional

from hs_solver.card import Card, CardDB, CardClass


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STANDARD_DECK_SIZE = 30
MAX_COPIES = 2          # max copies of any non-legendary card
MAX_COPIES_LEGENDARY = 1

FORMAT_WILD = 1
FORMAT_STANDARD = 2
FORMAT_CLASSIC = 3
FORMAT_TWIST = 4


# ---------------------------------------------------------------------------
# DeckList: parsed representation of a deck code
# ---------------------------------------------------------------------------


@dataclass
class DeckEntry:
    card_id: str   # dbfId as string
    count: int     # 1 or 2


@dataclass
class DeckList:
    """
    Parsed representation of a Hearthstone deck code.
    Does NOT require CardDB — just stores IDs and counts.
    """
    entries: list[DeckEntry] = field(default_factory=list)
    hero_ids: list[str] = field(default_factory=list)
    format: int = FORMAT_STANDARD
    name: Optional[str] = None

    def total_cards(self) -> int:
        return sum(e.count for e in self.entries)

    def is_valid(self) -> bool:
        return self.total_cards() == STANDARD_DECK_SIZE

    def to_id_list(self) -> list[str]:
        """Expand to a flat list of card IDs (with duplicates for 2-ofs)."""
        result = []
        for e in self.entries:
            result.extend([e.card_id] * e.count)
        return result

    def __repr__(self) -> str:
        return (
            f"DeckList({self.total_cards()} cards, "
            f"format={self.format}, "
            f"name={self.name!r})"
        )


# ---------------------------------------------------------------------------
# Varint codec
# ---------------------------------------------------------------------------


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    """
    Read a variable-length integer from bytes at offset.
    Returns (value, new_offset).
    """
    value = 0
    shift = 0
    while True:
        if offset >= len(data):
            raise ValueError(f"Unexpected end of deck data at offset {offset}")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            break
        shift += 7
    return value, offset


def _write_varint(value: int) -> bytes:
    """Encode an integer as a variable-length byte sequence."""
    if value < 0:
        raise ValueError(f"Cannot varint-encode negative value: {value}")
    buf = []
    while value > 0x7F:
        buf.append((value & 0x7F) | 0x80)
        value >>= 7
    buf.append(value & 0x7F)
    return bytes(buf)


# ---------------------------------------------------------------------------
# Decode
# ---------------------------------------------------------------------------


def decode_deck_string(deck_string: str) -> DeckList:
    """
    Decode a Hearthstone deck export string into a DeckList.

    The deck string may be just the base64 code, or it may be prefixed
    with comment lines (e.g., from the in-game copy). We strip comments.

    Args:
        deck_string: Raw deck string (from HS copy-paste or hs-deck-encoder).

    Returns:
        DeckList with entries, hero_ids, and format.

    Raises:
        ValueError: If the deck string is malformed.
    """
    name: Optional[str] = None
    code_line = ""

    for line in deck_string.strip().splitlines():
        line = line.strip()
        if line.startswith("###"):
            name = line.lstrip("#").strip()
        elif line.startswith("#") or not line:
            continue
        else:
            # First non-comment, non-empty line is the base64 code
            code_line = line
            break

    if not code_line:
        raise ValueError("No deck code found in input.")

    try:
        data = base64.b64decode(code_line)
    except Exception as e:
        raise ValueError(f"Invalid base64 in deck string: {e}")

    offset = 0

    # Reserved byte
    if len(data) < 1 or data[offset] != 0x00:
        raise ValueError("Invalid deck string: missing 0x00 reserved byte.")
    offset += 1

    # Version
    _version, offset = _read_varint(data, offset)

    # Format
    fmt, offset = _read_varint(data, offset)

    # Heroes
    n_heroes, offset = _read_varint(data, offset)
    hero_ids = []
    for _ in range(n_heroes):
        hero_id, offset = _read_varint(data, offset)
        hero_ids.append(str(hero_id))

    # 1-copy cards
    n_singles, offset = _read_varint(data, offset)
    entries: list[DeckEntry] = []
    for _ in range(n_singles):
        card_id, offset = _read_varint(data, offset)
        entries.append(DeckEntry(card_id=str(card_id), count=1))

    # 2-copy cards
    n_doubles, offset = _read_varint(data, offset)
    for _ in range(n_doubles):
        card_id, offset = _read_varint(data, offset)
        entries.append(DeckEntry(card_id=str(card_id), count=2))

    # n-copy cards (Twist format allows >2 copies; usually empty)
    if offset < len(data):
        n_multi, offset = _read_varint(data, offset)
        for _ in range(n_multi):
            count, offset = _read_varint(data, offset)
            card_id, offset = _read_varint(data, offset)
            entries.append(DeckEntry(card_id=str(card_id), count=count))

    return DeckList(entries=entries, hero_ids=hero_ids, format=fmt, name=name)


# ---------------------------------------------------------------------------
# Encode
# ---------------------------------------------------------------------------


def encode_deck_string(deck_list: DeckList) -> str:
    """
    Encode a DeckList back into a Hearthstone deck export string.

    Args:
        deck_list: DeckList to encode.

    Returns:
        Base64-encoded deck string compatible with in-game import.
    """
    singles = [e for e in deck_list.entries if e.count == 1]
    doubles = [e for e in deck_list.entries if e.count == 2]
    multis = [e for e in deck_list.entries if e.count > 2]

    buf = bytearray()
    buf.append(0x00)                          # reserved
    buf += _write_varint(1)                   # version
    buf += _write_varint(deck_list.format)    # format

    # Heroes
    buf += _write_varint(len(deck_list.hero_ids))
    for hid in deck_list.hero_ids:
        buf += _write_varint(int(hid))

    # Singles
    buf += _write_varint(len(singles))
    for e in sorted(singles, key=lambda x: int(x.card_id)):
        buf += _write_varint(int(e.card_id))

    # Doubles
    buf += _write_varint(len(doubles))
    for e in sorted(doubles, key=lambda x: int(x.card_id)):
        buf += _write_varint(int(e.card_id))

    # Multi-copies
    buf += _write_varint(len(multis))
    for e in sorted(multis, key=lambda x: int(x.card_id)):
        buf += _write_varint(e.count)
        buf += _write_varint(int(e.card_id))

    return base64.b64encode(bytes(buf)).decode("ascii")


# ---------------------------------------------------------------------------
# Build a playable deck from a DeckList + CardDB
# ---------------------------------------------------------------------------


def build_deck(card_db: CardDB, deck_list: DeckList) -> list[Card]:
    """
    Resolve a DeckList against a CardDB to produce a list of Card objects.

    Cards not found in the DB are skipped with a warning (handles rotated sets).

    Args:
        card_db:   Loaded CardDB.
        deck_list: Parsed deck list.

    Returns:
        Flat list of Card objects (with duplicates for 2-of copies).
        May be shorter than 30 if some cards are missing from the DB.
    """
    deck: list[Card] = []
    missing = []

    for entry in deck_list.entries:
        card = card_db.get_by_id(entry.card_id)
        if card is None:
            missing.append(entry.card_id)
            continue
        for _ in range(entry.count):
            deck.append(card)

    if missing:
        print(f"Warning: {len(missing)} card ID(s) not found in DB: {missing[:5]}"
              f"{'...' if len(missing) > 5 else ''}")

    return deck


# ---------------------------------------------------------------------------
# Random deck builder (for simulation / benchmarking)
# ---------------------------------------------------------------------------


def random_deck(
    card_db: CardDB,
    card_class: Optional[CardClass] = None,
    size: int = STANDARD_DECK_SIZE,
    seed: Optional[int] = None,
) -> list[Card]:
    """
    Build a random (not tournament-legal) deck for simulation and benchmarking.

    Picks from collectible minions and spells. If card_class is given, picks
    from that class + neutrals. Tries to add 2 copies of each card until size
    is reached.

    Args:
        card_db:    Loaded CardDB.
        card_class: Optional class filter.
        size:       Target deck size (default 30).
        seed:       RNG seed for reproducibility.

    Returns:
        A shuffled list of Card objects of length `size` (or fewer if the
        pool is exhausted).
    """
    rng = random.Random(seed)

    if card_class is not None:
        pool = card_db.by_class(card_class)
    else:
        pool = card_db.collectible()

    # Restrict to minions and spells only (weapons are fine too)
    pool = [c for c in pool if c.is_minion or c.is_spell or c.is_weapon]

    if not pool:
        return []

    rng.shuffle(pool)
    deck: list[Card] = []

    for card in pool:
        if len(deck) >= size:
            break
        copies = 1 if card.rarity and card.rarity.value == "LEGENDARY" else 2
        copies = min(copies, size - len(deck))
        deck.extend([card] * copies)

    rng.shuffle(deck)
    return deck[:size]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_deck(deck: list[Card]) -> list[str]:
    """
    Check a list of Cards for tournament legality.

    Returns a list of violation messages (empty if the deck is valid).
    Does NOT check set rotation (Standard/Wild) — that requires knowing
    the current format's allowed sets.
    """
    errors: list[str] = []

    if len(deck) != STANDARD_DECK_SIZE:
        errors.append(f"Deck has {len(deck)} cards, expected {STANDARD_DECK_SIZE}.")

    from collections import Counter
    counts = Counter(c.id for c in deck)
    names = {c.id: c.name for c in deck}
    rarities = {c.id: c.rarity for c in deck}

    for card_id, count in counts.items():
        limit = MAX_COPIES_LEGENDARY if rarities[card_id].value == "LEGENDARY" else MAX_COPIES
        if count > limit:
            errors.append(
                f"{names[card_id]}: {count} copies (max {limit})."
            )

    return errors
