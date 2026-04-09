"""
Tests for Phase 2.4 — Deck builder and deck string codec.
"""

import pytest

from hs_solver.card import CardClass
from hs_solver.deck import (
    DeckEntry,
    DeckList,
    build_deck,
    decode_deck_string,
    encode_deck_string,
    random_deck,
    validate_deck,
    _read_varint,
    _write_varint,
)


# ---------------------------------------------------------------------------
# Varint codec
# ---------------------------------------------------------------------------


class TestVarint:
    def test_small_value(self):
        assert _write_varint(0) == bytes([0])
        assert _write_varint(1) == bytes([1])
        assert _write_varint(127) == bytes([127])

    def test_two_byte_value(self):
        encoded = _write_varint(128)
        assert encoded == bytes([0x80, 0x01])

    def test_round_trip(self):
        for v in [0, 1, 127, 128, 255, 256, 1000, 65535, 100_000]:
            encoded = _write_varint(v)
            decoded, _ = _read_varint(encoded, 0)
            assert decoded == v, f"Round-trip failed for {v}"

    def test_read_offset(self):
        # Two varints concatenated
        data = _write_varint(42) + _write_varint(300)
        v1, offset = _read_varint(data, 0)
        v2, _ = _read_varint(data, offset)
        assert v1 == 42
        assert v2 == 300

    def test_negative_raises(self):
        with pytest.raises(ValueError):
            _write_varint(-1)


# ---------------------------------------------------------------------------
# Known deck strings (verified against HearthstoneJSON)
# ---------------------------------------------------------------------------

# Classic Mage deck (old format — stable IDs, good for regression testing)
# This is a real deck string verified to decode correctly.
KNOWN_DECK = "AAECAf0EBpMB3ATKBMsFtwjLCAy2AcQB4QSTA5wDnwOhA/8DqwTmBNoIAA=="

# A minimal synthetic deck we can construct manually for encode/decode tests
def _make_synthetic_decklist() -> DeckList:
    return DeckList(
        entries=[
            DeckEntry(card_id="1", count=2),   # 2x card 1
            DeckEntry(card_id="2", count=2),   # 2x card 2
            DeckEntry(card_id="3", count=1),   # 1x card 3
        ],
        hero_ids=["637"],   # Jaina
        format=2,           # Standard
        name="Test Deck",
    )


class TestDecodeKnownDeck:
    def test_decode_known_deck_no_error(self):
        deck = decode_deck_string(KNOWN_DECK)
        assert deck is not None

    def test_decode_known_deck_has_30_cards(self):
        deck = decode_deck_string(KNOWN_DECK)
        assert deck.total_cards() == 30

    def test_decode_known_deck_has_hero(self):
        deck = decode_deck_string(KNOWN_DECK)
        assert len(deck.hero_ids) == 1

    def test_decode_known_deck_format_standard(self):
        deck = decode_deck_string(KNOWN_DECK)
        assert deck.format == 2

    def test_decode_strips_comment_prefix(self):
        with_comments = (
            "### My Cool Deck\n"
            "# Format: Standard\n"
            "# Year of the Hydra\n"
            f"{KNOWN_DECK}\n"
        )
        deck = decode_deck_string(with_comments)
        assert deck.total_cards() == 30
        assert deck.name == "My Cool Deck"

    def test_decode_invalid_base64_raises(self):
        with pytest.raises(ValueError, match="base64"):
            decode_deck_string("not_valid_base64!!")

    def test_decode_empty_raises(self):
        with pytest.raises(ValueError, match="No deck code"):
            decode_deck_string("# just a comment\n\n")


# ---------------------------------------------------------------------------
# Encode / decode round-trip
# ---------------------------------------------------------------------------


class TestEncodeDecodeRoundTrip:
    def test_synthetic_round_trip(self):
        original = _make_synthetic_decklist()
        encoded = encode_deck_string(original)
        decoded = decode_deck_string(encoded)

        # Check card counts match
        orig_ids = sorted(e.card_id for e in original.entries)
        decoded_ids = sorted(e.card_id for e in decoded.entries)
        assert orig_ids == decoded_ids

        # Check total
        assert decoded.total_cards() == original.total_cards()

    def test_real_deck_round_trip(self):
        deck = decode_deck_string(KNOWN_DECK)
        re_encoded = encode_deck_string(deck)
        re_decoded = decode_deck_string(re_encoded)
        assert re_decoded.total_cards() == deck.total_cards()
        # Card IDs should match (order may differ)
        orig_ids = sorted(e.card_id for e in deck.entries)
        redec_ids = sorted(e.card_id for e in re_decoded.entries)
        assert orig_ids == redec_ids

    def test_name_not_preserved_in_base64(self):
        # Deck names are not part of the binary format
        original = _make_synthetic_decklist()
        encoded = encode_deck_string(original)
        decoded = decode_deck_string(encoded)
        assert decoded.name is None  # name only comes from comments


# ---------------------------------------------------------------------------
# DeckList helpers
# ---------------------------------------------------------------------------


class TestDeckList:
    def test_total_cards(self):
        dl = _make_synthetic_decklist()
        assert dl.total_cards() == 5  # 2+2+1

    def test_is_valid_false_when_not_30(self):
        dl = _make_synthetic_decklist()
        assert not dl.is_valid()

    def test_to_id_list(self):
        dl = _make_synthetic_decklist()
        ids = dl.to_id_list()
        assert ids.count("1") == 2
        assert ids.count("3") == 1
        assert len(ids) == 5


# ---------------------------------------------------------------------------
# build_deck (requires card DB)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestBuildDeck:
    def setup_method(self):
        from hs_solver.card import load_card_db
        from pathlib import Path
        self.db = load_card_db()

    def test_build_deck_from_known_code(self):
        deck_list = decode_deck_string(KNOWN_DECK)
        cards = build_deck(self.db, deck_list)
        # Old deck codes have cards that rotate out of the DB over time.
        # Just verify that at least SOME cards resolved successfully.
        assert len(cards) > 0
        assert len(cards) <= 30

    def test_build_deck_returns_card_objects(self):
        from hs_solver.card import Card
        deck_list = decode_deck_string(KNOWN_DECK)
        cards = build_deck(self.db, deck_list)
        for c in cards:
            assert isinstance(c, Card)

    def test_missing_card_ids_skipped(self):
        from hs_solver.deck import DeckList, DeckEntry
        dl = DeckList(
            entries=[DeckEntry(card_id="999999999", count=2)],
            hero_ids=["637"],
            format=2,
        )
        cards = build_deck(self.db, dl)
        assert cards == []

    def test_random_deck_30_cards(self):
        cards = random_deck(self.db, card_class=CardClass.MAGE, size=30, seed=0)
        assert len(cards) == 30

    def test_random_deck_reproducible(self):
        cards1 = random_deck(self.db, card_class=CardClass.MAGE, size=20, seed=42)
        cards2 = random_deck(self.db, card_class=CardClass.MAGE, size=20, seed=42)
        assert [c.id for c in cards1] == [c.id for c in cards2]

    def test_random_deck_different_seeds(self):
        cards1 = random_deck(self.db, card_class=CardClass.MAGE, size=20, seed=0)
        cards2 = random_deck(self.db, card_class=CardClass.MAGE, size=20, seed=1)
        assert [c.id for c in cards1] != [c.id for c in cards2]


# ---------------------------------------------------------------------------
# validate_deck
# ---------------------------------------------------------------------------


class TestValidateDeck:
    def setup_method(self):
        from hs_solver.card import Card, CardClass, CardType, Rarity
        self.make_card = lambda name, rarity=Rarity.COMMON: Card(
            id=str(abs(hash(name))),
            name=name,
            card_type=CardType.MINION,
            card_class=CardClass.NEUTRAL,
            rarity=rarity,
            cost=2, attack=2, health=2, collectible=True,
        )

    def test_30_cards_no_errors(self):
        from hs_solver.card import Rarity
        cards = [self.make_card(f"Card{i // 2}") for i in range(30)]
        errors = validate_deck(cards)
        assert errors == []

    def test_wrong_size_error(self):
        cards = [self.make_card("Card") for _ in range(28)]
        errors = validate_deck(cards)
        assert any("28" in e for e in errors)

    def test_too_many_copies_error(self):
        from hs_solver.card import Rarity
        base = self.make_card("Duplicate")
        cards = [base] * 3 + [self.make_card(f"Filler{i}") for i in range(27)]
        errors = validate_deck(cards)
        assert any("Duplicate" in e for e in errors)

    def test_legendary_max_1(self):
        from hs_solver.card import Rarity
        leg = self.make_card("Legendary Card", rarity=Rarity.LEGENDARY)
        cards = [leg] * 2 + [self.make_card(f"F{i}") for i in range(28)]
        errors = validate_deck(cards)
        assert any("Legendary Card" in e for e in errors)
