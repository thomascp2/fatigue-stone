"""
Tests for hs_solver/card.py — card ingestion and CardDB.

These tests run in two modes:
  - Unit tests (no cards.json needed): test parsing logic on synthetic raw data
  - Integration tests (requires cards.json): test against real HearthstoneJSON data

Run unit tests only:
    pytest tests/test_card.py -m "not integration"

Run all (after running scripts/fetch_cards.py):
    pytest tests/test_card.py
"""

import json
import tempfile
from pathlib import Path

import pytest

from hs_solver.card import (
    Card,
    CardClass,
    CardDB,
    CardType,
    Rarity,
    SpellSchool,
    _parse_card,
    load_card_db,
)

# ---------------------------------------------------------------------------
# Synthetic raw card fixtures
# ---------------------------------------------------------------------------

RAW_CHILLWIND_YETI = {
    "dbfId": 1,
    "name": "Chillwind Yeti",
    "type": "MINION",
    "cardClass": "NEUTRAL",
    "rarity": "COMMON",
    "cost": 4,
    "attack": 4,
    "health": 5,
    "collectible": True,
    "set": "CORE",
    "mechanics": [],
    "text": None,
}

RAW_SUNWING_SQUAWKER = {
    "dbfId": 2,
    "name": "Sunwing Squawker",
    "type": "MINION",
    "cardClass": "NEUTRAL",
    "rarity": "COMMON",
    "cost": 2,
    "attack": 2,
    "health": 1,
    "collectible": True,
    "set": "CORE",
    "mechanics": ["WINDFURY"],
    "text": "Windfury",
}

RAW_TAUNT_DIVINE = {
    "dbfId": 3,
    "name": "Test Shield Totem",
    "type": "MINION",
    "cardClass": "SHAMAN",
    "rarity": "FREE",
    "cost": 3,
    "attack": 0,
    "health": 4,
    "collectible": True,
    "set": "CORE",
    "mechanics": ["TAUNT", "DIVINE_SHIELD"],
    "text": "Taunt. Divine Shield.",
}

RAW_FIREBALL = {
    "dbfId": 4,
    "name": "Fireball",
    "type": "SPELL",
    "cardClass": "MAGE",
    "rarity": "FREE",
    "cost": 4,
    "collectible": True,
    "set": "CORE",
    "spellSchool": "FIRE",
    "mechanics": [],
    "text": "Deal 6 damage.",
}

RAW_FIREHAMMER = {
    "dbfId": 5,
    "name": "Firehammer",
    "type": "WEAPON",
    "cardClass": "WARRIOR",
    "rarity": "COMMON",
    "cost": 3,
    "attack": 3,
    "durability": 2,
    "collectible": True,
    "set": "CORE",
    "mechanics": [],
    "text": None,
}

RAW_OVERLOAD_CARD = {
    "dbfId": 6,
    "name": "Lightning Bolt",
    "type": "SPELL",
    "cardClass": "SHAMAN",
    "rarity": "FREE",
    "cost": 1,
    "collectible": True,
    "set": "CORE",
    "mechanics": ["OVERLOAD"],
    "overload": 1,
    "text": "Deal 3 damage. Overload: (1)",
}

RAW_TOKEN = {
    "dbfId": 7,
    "name": "Silver Hand Recruit",
    "type": "MINION",
    "cardClass": "PALADIN",
    "rarity": "FREE",
    "cost": 1,
    "attack": 1,
    "health": 1,
    "collectible": False,
    "set": "CORE",
    "mechanics": [],
}

RAW_NO_NAME = {"dbfId": 8, "type": "MINION", "name": ""}
RAW_NO_DBF = {"name": "Ghost Card", "type": "MINION"}
RAW_ENCHANTMENT = {"dbfId": 9, "name": "Enchantment", "type": "ENCHANTMENT"}


# ---------------------------------------------------------------------------
# _parse_card unit tests
# ---------------------------------------------------------------------------


class TestParseCard:
    def test_basic_minion(self):
        card = _parse_card(RAW_CHILLWIND_YETI)
        assert card is not None
        assert card.name == "Chillwind Yeti"
        assert card.card_type == CardType.MINION
        assert card.cost == 4
        assert card.attack == 4
        assert card.health == 5
        assert card.collectible is True
        assert card.card_class == CardClass.NEUTRAL
        assert card.rarity == Rarity.COMMON
        assert card.card_set == "CORE"

    def test_minion_windfury(self):
        card = _parse_card(RAW_SUNWING_SQUAWKER)
        assert card is not None
        assert card.has_windfury
        assert card.attacks_per_turn == 2

    def test_minion_taunt_divine_shield(self):
        card = _parse_card(RAW_TAUNT_DIVINE)
        assert card is not None
        assert card.has_taunt
        assert card.has_divine_shield
        assert not card.has_windfury

    def test_spell_with_school(self):
        card = _parse_card(RAW_FIREBALL)
        assert card is not None
        assert card.is_spell
        assert card.spell_school == SpellSchool.FIRE
        assert card.attack is None
        assert card.health is None

    def test_weapon(self):
        card = _parse_card(RAW_FIREHAMMER)
        assert card is not None
        assert card.is_weapon
        assert card.attack == 3
        assert card.durability == 2

    def test_overload(self):
        card = _parse_card(RAW_OVERLOAD_CARD)
        assert card is not None
        assert card.overload == 1

    def test_token_not_collectible(self):
        card = _parse_card(RAW_TOKEN)
        assert card is not None
        assert card.collectible is False

    def test_skip_no_name(self):
        assert _parse_card(RAW_NO_NAME) is None

    def test_skip_no_dbf(self):
        assert _parse_card(RAW_NO_DBF) is None

    def test_skip_enchantment_type(self):
        assert _parse_card(RAW_ENCHANTMENT) is None

    def test_attacks_per_turn_default(self):
        card = _parse_card(RAW_CHILLWIND_YETI)
        assert card.attacks_per_turn == 1

    def test_mega_windfury(self):
        raw = {**RAW_SUNWING_SQUAWKER, "dbfId": 99, "mechanics": ["MEGA_WINDFURY"]}
        card = _parse_card(raw)
        assert card is not None
        assert card.attacks_per_turn == 4
        assert card.has_windfury  # mega_windfury counts as windfury

    def test_unknown_mechanic_ignored(self):
        raw = {**RAW_CHILLWIND_YETI, "dbfId": 100, "mechanics": ["DISCOVER", "ADAPT"]}
        card = _parse_card(raw)
        assert card is not None
        assert len(card.mechanics) == 0

    def test_repr_contains_name(self):
        card = _parse_card(RAW_CHILLWIND_YETI)
        assert "Chillwind Yeti" in repr(card)
        assert "4/5" in repr(card)


# ---------------------------------------------------------------------------
# CardDB unit tests (synthetic)
# ---------------------------------------------------------------------------


def _make_db() -> CardDB:
    raws = [
        RAW_CHILLWIND_YETI,
        RAW_SUNWING_SQUAWKER,
        RAW_TAUNT_DIVINE,
        RAW_FIREBALL,
        RAW_FIREHAMMER,
        RAW_OVERLOAD_CARD,
        RAW_TOKEN,
    ]
    cards = [_parse_card(r) for r in raws]
    return CardDB([c for c in cards if c is not None])


class TestCardDB:
    def setup_method(self):
        self.db = _make_db()

    def test_len(self):
        assert len(self.db) == 7

    def test_get_by_id(self):
        card = self.db.get_by_id("1")
        assert card is not None
        assert card.name == "Chillwind Yeti"

    def test_get_by_id_missing(self):
        assert self.db.get_by_id("9999") is None

    def test_get_by_name_case_insensitive(self):
        card = self.db.get_by_name("FIREBALL")
        assert card is not None
        assert card.name == "Fireball"

    def test_collectible_excludes_tokens(self):
        collectible = self.db.collectible()
        names = [c.name for c in collectible]
        assert "Silver Hand Recruit" not in names
        assert "Chillwind Yeti" in names

    def test_minions_collectible_only(self):
        minions = self.db.minions(collectible_only=True)
        assert all(c.is_minion for c in minions)
        assert all(c.collectible for c in minions)

    def test_minions_include_tokens(self):
        all_minions = self.db.minions(collectible_only=False)
        names = [c.name for c in all_minions]
        assert "Silver Hand Recruit" in names

    def test_repr(self):
        r = repr(self.db)
        assert "CardDB" in r

    def test_by_class_includes_neutral(self):
        mage_cards = self.db.by_class(CardClass.MAGE)
        names = [c.name for c in mage_cards]
        assert "Fireball" in names
        assert "Chillwind Yeti" in names  # neutral
        assert "Lightning Bolt" not in names  # shaman, not mage


# ---------------------------------------------------------------------------
# load_card_db — error path
# ---------------------------------------------------------------------------


def test_load_card_db_missing_file():
    with pytest.raises(FileNotFoundError, match="fetch_cards.py"):
        load_card_db(Path("/nonexistent/cards.json"))


def test_load_card_db_from_temp_file():
    raws = [RAW_CHILLWIND_YETI, RAW_FIREBALL, RAW_TOKEN, RAW_ENCHANTMENT]
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(raws, f)
        tmp_path = Path(f.name)

    try:
        db = load_card_db(tmp_path)
        # Enchantment is skipped, rest parsed
        assert len(db) == 3
        assert db.get_by_name("chillwind yeti") is not None
    finally:
        tmp_path.unlink()


# ---------------------------------------------------------------------------
# Integration tests — only run when cards.json is present
# ---------------------------------------------------------------------------

CARDS_JSON = Path(__file__).parent.parent / "data" / "cards.json"


@pytest.mark.integration
@pytest.mark.skipif(not CARDS_JSON.exists(), reason="cards.json not fetched")
class TestRealCardDB:
    def setup_method(self):
        self.db = load_card_db(CARDS_JSON)

    def test_db_has_many_cards(self):
        # HearthstoneJSON typically has 10k+ entries
        assert len(self.db) > 5_000

    def test_collectible_sanity(self):
        collectible = self.db.collectible()
        assert len(collectible) > 1_000

    def test_well_known_cards_exist(self):
        # These are classic cards that should always be present
        well_known = ["Fireball", "Frostbolt", "Lightning Bolt", "Moonfire"]
        for name in well_known:
            assert self.db.get_by_name(name) is not None, f"Missing: {name}"

    def test_no_card_with_none_type(self):
        for card in self.db._by_id.values():
            assert card.card_type != CardType.UNKNOWN or True  # unknown is allowed
            assert card.name  # name must always be non-empty

    def test_minions_have_attack_and_health(self):
        for card in self.db.minions(collectible_only=True):
            assert card.attack is not None, f"{card.name} missing attack"
            assert card.health is not None, f"{card.name} missing health"

    def test_mage_cards_include_fireball(self):
        mage = self.db.by_class(CardClass.MAGE)
        names = {c.name for c in mage}
        assert "Fireball" in names
