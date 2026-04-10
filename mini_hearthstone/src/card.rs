// card.rs — defines what a "card" is in our game.
//
// In Rust, we use `struct` to bundle related data together and
// `enum` to represent a value that can be one of several variants.

// `#[derive(...)]` automatically generates common trait implementations.
// Clone  — lets us copy a Card with `.clone()` instead of moving ownership.
// Debug  — lets us print a Card with `{:?}` for debugging.
// PartialEq — lets us compare Cards with `==`.
#[derive(Clone, Debug, PartialEq)]
pub enum CardKind {
    // A Minion has attack and health values.
    // The `u8` type is an unsigned 8-bit integer (0–255), perfect for small numbers.
    Minion { attack: u8, health: u8 },

    // A Spell has an effect string we'll interpret in game.rs.
    // `String` is heap-allocated text that owns its data.
    Spell { effect: String },
}

// The Card struct holds everything we need to know about a card.
#[derive(Clone, Debug, PartialEq)]
pub struct Card {
    pub name: String,   // `pub` means other modules can read this field.
    pub cost: u8,       // Mana cost (1–4).
    pub kind: CardKind, // What kind of card this is (Minion or Spell).
}

// `impl Card` is where we add methods that belong to Card.
impl Card {
    // A constructor — by convention called `new`.
    // `&str` is a string slice (borrowed text); we convert it to String with `.to_string()`.
    pub fn new_minion(name: &str, cost: u8, attack: u8, health: u8) -> Self {
        // `Self` refers to the type being implemented — here that's `Card`.
        Card {
            name: name.to_string(),
            cost,
            kind: CardKind::Minion { attack, health },
        }
    }

    pub fn new_spell(name: &str, cost: u8, effect: &str) -> Self {
        Card {
            name: name.to_string(),
            cost,
            kind: CardKind::Spell {
                effect: effect.to_string(),
            },
        }
    }

    // A helper so callers can quickly see if a card is a minion.
    pub fn is_minion(&self) -> bool {
        // Pattern matching with `matches!` — cleaner than a full `match` block
        // when we only care about one variant.
        matches!(self.kind, CardKind::Minion { .. })
    }

    // Return a short description string for display purposes.
    pub fn description(&self) -> String {
        match &self.kind {
            CardKind::Minion { attack, health } => {
                format!("[Minion {}/{}]", attack, health)
            }
            CardKind::Spell { effect } => {
                format!("[Spell: {}]", effect)
            }
        }
    }
}

// build_deck() returns a Vec<Card> — a growable list of Cards on the heap.
// Every player gets their own copy of this deck (we .clone() it at game start).
pub fn build_deck() -> Vec<Card> {
    // `vec![]` is a macro that creates a Vec and pushes items in one shot.
    vec![
        // --- MINIONS ---
        // Cheap, small minions — good to play early.
        Card::new_minion("Squire",         1, 1, 2),
        Card::new_minion("River Crocolisk",1, 2, 1),
        Card::new_minion("Bloodfen Raptor",2, 3, 2),
        Card::new_minion("Frostwolf Grunt",2, 2, 2),
        Card::new_minion("Ironfur Grizzly",3, 3, 3),
        Card::new_minion("Chillwind Yeti", 4, 4, 5),
        Card::new_minion("Oasis Snapjaw",  4, 2, 7),
        Card::new_minion("Shieldbearer",   1, 0, 4),
        Card::new_minion("Murloc Raider",  1, 2, 1),
        Card::new_minion("Gnomish Inventor",4, 2, 4),

        // --- SPELLS ---
        // Effects are short strings we pattern-match on in game.rs.
        Card::new_spell("Fireball",       3, "deal 3 damage to enemy hero"),
        Card::new_spell("Arcane Missiles",1, "deal 1 damage to all enemy minions"),
        Card::new_spell("Holy Smite",     1, "deal 2 damage to enemy hero"),
        Card::new_spell("Whirlwind",      2, "deal 1 damage to all minions"),
        Card::new_spell("Flamestrike",    4, "deal 4 damage to all enemy minions"),
    ]
    // That's 15 cards total — a nice small deck for quick games.
}
