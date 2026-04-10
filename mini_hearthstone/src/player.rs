// player.rs — defines the Minion and Player structs plus their behaviour.
//
// Ownership quick-primer:
//   Every value in Rust has exactly one owner.  When you pass a value to a
//   function, ownership moves unless you either borrow (`&`) or clone it.
//   `&mut self` in a method means "borrow this Player mutably — I can change it
//   but I don't take ownership."

use crate::card::{Card, CardKind}; // `crate::` means "root of this project".

// ─── Minion ──────────────────────────────────────────────────────────────────

// A Minion is the in-play version of a Minion card.
// It tracks current health (which can go down in combat) separately from the
// card's printed value.
#[derive(Clone, Debug)]
pub struct Minion {
    pub name: String,
    pub attack: u8,
    pub health: i32, // i32 so health can go negative (makes death-check easy).
    // can_attack starts false when a minion is played (summoning sickness)
    // and becomes true at the start of the owner's next turn.
    pub can_attack: bool,
}

impl Minion {
    pub fn from_card(card: &Card) -> Option<Self> {
        // We only call this when we KNOW the card is a Minion, but we return
        // Option<Self> to be safe.  `if let` destructures the enum variant.
        if let CardKind::Minion { attack, health } = card.kind {
            Some(Minion {
                name: card.name.clone(), // clone the String so we own a copy
                attack,
                health: health as i32, // cast u8 → i32
                can_attack: false,     // summoning sickness!
            })
        } else {
            None // card wasn't a Minion
        }
    }
}

// ─── Player ──────────────────────────────────────────────────────────────────

#[derive(Clone, Debug)]
pub struct Player {
    pub name: String,
    pub hero_health: i32,
    pub mana: u8,
    pub max_mana: u8,
    // Vec<T> is a heap-allocated growable array — Rust's equivalent of a list.
    pub deck: Vec<Card>,
    pub hand: Vec<Card>,
    pub board: Vec<Minion>, // minions currently in play
}

impl Player {
    // Associated function (no `self`) — acts like a constructor.
    pub fn new(name: &str, deck: Vec<Card>) -> Self {
        Player {
            name: name.to_string(),
            hero_health: 20,
            mana: 0,
            max_mana: 0,
            deck,
            hand: Vec::new(),  // empty Vec — no cards in hand yet
            board: Vec::new(), // empty board — no minions yet
        }
    }

    // Called at the beginning of this player's turn.
    // `&mut self` — we're borrowing self mutably so we can change fields.
    pub fn start_turn(&mut self) {
        // Gain one mana crystal, capped at 5.
        if self.max_mana < 5 {
            self.max_mana += 1;
        }
        // Refill mana to the new maximum.
        self.mana = self.max_mana;

        // Wake up minions that had summoning sickness.
        // `iter_mut()` gives us mutable references to each element.
        for minion in self.board.iter_mut() {
            minion.can_attack = true;
        }

        // Draw one card for the turn.
        self.draw_card();
    }

    // Draw one card from the deck into the hand.
    pub fn draw_card(&mut self) {
        // `self.deck.pop()` removes and returns the last element as Option<Card>.
        // Option is either Some(value) or None — Rust forces us to handle both.
        if let Some(card) = self.deck.pop() {
            if self.hand.len() < 5 {
                // There's room — add the card to hand.
                self.hand.push(card);
            } else {
                // Hand is full — the card is "burned" (discarded).
                println!(
                    "  [{}'s hand is full! {} is burned.]",
                    self.name, card.name
                );
            }
        } else {
            // Deck is empty — in many card games this deals fatigue damage,
            // but here we just skip silently.
            println!("  [{} has no cards left to draw.]", self.name);
        }
    }

    // Can this player afford and legally play this card?
    pub fn can_play(&self, card: &Card) -> bool {
        // Check mana first.
        if card.cost > self.mana {
            return false;
        }
        // If it's a minion, the board must have room.
        if card.is_minion() && self.board.len() >= 3 {
            return false;
        }
        true
    }

    // Remove a card at `index` from hand and put a minion on the board.
    // Spell effects are handled in game.rs because they need access to both
    // players — this function just removes the card and deducts mana.
    // Returns the card that was played so the caller can inspect its kind.
    pub fn play_card(&mut self, index: usize) -> Card {
        // `Vec::remove(i)` removes the element at index i and shifts the rest.
        // This is O(n) but fine for our small hand sizes.
        let card = self.hand.remove(index);

        // Deduct mana cost.
        self.mana -= card.cost;

        // If it's a minion, put it on the board immediately.
        if let Some(minion) = Minion::from_card(&card) {
            self.board.push(minion);
        }

        // Return the card so the caller can resolve spell effects.
        card
    }
}
