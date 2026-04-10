// game.rs — the central coordinator that owns both players and drives the loop.
//
// Key Rust concept: the `Game` struct owns both Players.  When we need to pass
// both to a function, we can't borrow `self.human` and `self.ai` mutably at
// the same time through `&mut self` — Rust's borrow checker would reject it.
// We work around this by taking both fields out as explicit `&mut` refs using
// destructuring, or by passing them as separate parameters to free functions.

use std::io::{self, BufRead, Write}; // BufRead for stdin lines, Write for flush

use rand::seq::SliceRandom;   // SliceRandom adds .shuffle() to Vec
use rand::SeedableRng;        // SeedableRng lets us build an RNG from a seed
use rand::rngs::SmallRng;     // SmallRng: fast, seedable, no OS entropy needed

use crate::ai::ai_take_turn;
use crate::card::{build_deck, Card, CardKind};
use crate::player::Player;

// ─── Spell resolution (free function, not a method) ──────────────────────────
//
// Making this a free function (not a method on Game) means we can call it from
// ai.rs too without needing a &mut Game — solving the double-borrow problem.
//
// Returns a Vec<String> of messages so callers can print them.
pub fn apply_spell(caster: &mut Player, opponent: &mut Player, card: &Card) -> Vec<String> {
    let mut log: Vec<String> = Vec::new();

    // Extract the effect string from the card.  We only call this for spells,
    // so the `if let` will always match — but Rust makes us handle it.
    let effect = if let CardKind::Spell { effect } = &card.kind {
        effect.clone()
    } else {
        return log; // not a spell — nothing to do
    };

    // Match on the effect string.  We use `as_str()` to compare against &str
    // literals — Rust won't let us match String directly against &str without it.
    match effect.as_str() {
        "deal 3 damage to enemy hero" => {
            opponent.hero_health -= 3;
            log.push(format!("  {} deals 3 damage to {}'s hero! (HP: {})",
                card.name, opponent.name, opponent.hero_health));
        }
        "deal 2 damage to enemy hero" => {
            opponent.hero_health -= 2;
            log.push(format!("  {} deals 2 damage to {}'s hero! (HP: {})",
                card.name, opponent.name, opponent.hero_health));
        }
        "deal 1 damage to all enemy minions" => {
            for m in opponent.board.iter_mut() {
                m.health -= 1;
            }
            let died: Vec<String> = opponent.board.iter()
                .filter(|m| m.health <= 0)
                .map(|m| m.name.clone())
                .collect();
            opponent.board.retain(|m| m.health > 0);
            log.push(format!("  {} deals 1 damage to all of {}'s minions.", card.name, opponent.name));
            for name in died {
                log.push(format!("  {}'s {} dies!", opponent.name, name));
            }
        }
        "deal 1 damage to all minions" => {
            // Whirlwind — hits EVERYONE including your own minions.
            for m in caster.board.iter_mut() {
                m.health -= 1;
            }
            for m in opponent.board.iter_mut() {
                m.health -= 1;
            }
            let caster_died: Vec<String> = caster.board.iter()
                .filter(|m| m.health <= 0)
                .map(|m| m.name.clone())
                .collect();
            let opp_died: Vec<String> = opponent.board.iter()
                .filter(|m| m.health <= 0)
                .map(|m| m.name.clone())
                .collect();
            caster.board.retain(|m| m.health > 0);
            opponent.board.retain(|m| m.health > 0);
            log.push(format!("  {} deals 1 damage to ALL minions!", card.name));
            for name in caster_died {
                log.push(format!("  {}'s {} dies!", caster.name, name));
            }
            for name in opp_died {
                log.push(format!("  {}'s {} dies!", opponent.name, name));
            }
        }
        "deal 4 damage to all enemy minions" => {
            for m in opponent.board.iter_mut() {
                m.health -= 4;
            }
            let died: Vec<String> = opponent.board.iter()
                .filter(|m| m.health <= 0)
                .map(|m| m.name.clone())
                .collect();
            opponent.board.retain(|m| m.health > 0);
            log.push(format!("  {} deals 4 damage to all of {}'s minions!", card.name, opponent.name));
            for name in died {
                log.push(format!("  {}'s {} dies!", opponent.name, name));
            }
        }
        other => {
            // Unknown effect — shouldn't happen, but handle gracefully.
            log.push(format!("  [Unknown spell effect: {}]", other));
        }
    }

    log
}

// ─── Game struct ─────────────────────────────────────────────────────────────

pub struct Game {
    pub human: Player,
    pub ai: Player,
    pub turn: u32, // u32: unsigned 32-bit int — enough for any reasonable game
}

impl Game {
    // new() sets up a fresh game.
    pub fn new() -> Self {
        // We need a random number generator.  Because we're not using the OS
        // entropy features of rand, we seed SmallRng from the system clock.
        // std::time::SystemTime gives nanoseconds since the Unix epoch —
        // different every run, which is all we need for shuffling a deck.
        let seed = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.subsec_nanos()) // grab the sub-second nanos for variety
            .unwrap_or(42) as u64;     // fallback seed if clock fails

        // SmallRng::seed_from_u64 builds the RNG deterministically from that seed.
        let mut rng = SmallRng::seed_from_u64(seed);

        // Build separate deck copies for each player.
        let mut human_deck = build_deck();
        let mut ai_deck = build_deck();

        // SliceRandom::shuffle randomises the order in-place.
        human_deck.shuffle(&mut rng);
        ai_deck.shuffle(&mut rng);

        let mut human = Player::new("Hero", human_deck);
        let mut ai = Player::new("AI", ai_deck);

        // Deal opening hands — 3 cards each, drawn without a mana step.
        for _ in 0..3 {
            human.draw_card();
            ai.draw_card();
        }

        Game { human, ai, turn: 1 }
    }

    // Check if anyone has won.  Returns Some(name) or None.
    // `Option<String>` — either there's a winner name or there isn't.
    pub fn check_winner(&self) -> Option<String> {
        if self.human.hero_health <= 0 && self.ai.hero_health <= 0 {
            return Some("Nobody (tie!)".to_string());
        }
        if self.human.hero_health <= 0 {
            return Some(self.ai.name.clone());
        }
        if self.ai.hero_health <= 0 {
            return Some("You".to_string()); // human player wins
        }
        None // game not over
    }

    // ── Display ──────────────────────────────────────────────────────────────

    pub fn print_state(&self) {
        println!();
        println!("╔══════════════════════════════════════╗");
        println!("║           GAME STATE                 ║");
        println!("╚══════════════════════════════════════╝");

        // AI info (opponent — show board but not hand)
        println!("  [AI] HP: {}  Mana: {}/{}  Hand: {} card(s)  Deck: {}",
            self.ai.hero_health,
            self.ai.mana,
            self.ai.max_mana,
            self.ai.hand.len(),
            self.ai.deck.len());

        print!("  AI Board: ");
        if self.ai.board.is_empty() {
            print!("(empty)");
        } else {
            for m in &self.ai.board {
                let ready = if m.can_attack { "*" } else { "z" };
                print!("[{}{}  {}/{}]  ", m.name, ready, m.attack, m.health);
            }
        }
        println!();

        println!("  ----------------------------------------");

        // Human board
        print!("  Your Board: ");
        if self.human.board.is_empty() {
            print!("(empty)");
        } else {
            for (i, m) in self.human.board.iter().enumerate() {
                let ready = if m.can_attack { "*" } else { "z" };
                print!("[{}] {}{}  {}/{}   ", i, m.name, ready, m.attack, m.health);
            }
        }
        println!();

        // Human hand — show all cards with index so the player can pick
        println!("  Your Hand:");
        if self.human.hand.is_empty() {
            println!("    (empty)");
        } else {
            for (i, card) in self.human.hand.iter().enumerate() {
                println!("    [{}] {} (cost {}) {}",
                    i, card.name, card.cost, card.description());
            }
        }

        println!("  [You] HP: {}  Mana: {}/{}  Deck: {}",
            self.human.hero_health,
            self.human.mana,
            self.human.max_mana,
            self.human.deck.len());
        println!();
    }

    // ── Human phases ─────────────────────────────────────────────────────────

    // Ask the human which cards to play.
    pub fn human_play_phase(&mut self) {
        println!("--- Play Phase ---");
        println!("  Commands: 'play N' to play card N from your hand, 'done' to skip.");

        let stdin = io::stdin();
        // We need to lock stdin for line-by-line reading.
        let mut lines = stdin.lock().lines();

        loop {
            self.print_state();

            print!("  > ");
            // Flush stdout so the prompt appears before we wait for input.
            // io::stdout().flush() returns a Result — `unwrap()` panics on error
            // which is fine for a prototype.
            io::stdout().flush().unwrap();

            // Read one line.  `.lines()` returns `Option<Result<String>>`.
            // We `unwrap` both layers for simplicity.
            let line = match lines.next() {
                Some(Ok(l)) => l.trim().to_string(),
                _ => break,
            };

            if line == "done" || line.is_empty() {
                break;
            }

            // Parse "play N"
            // `.split_whitespace()` splits on any whitespace and skips empties.
            let parts: Vec<&str> = line.split_whitespace().collect();
            if parts.len() == 2 && parts[0] == "play" {
                // `str::parse::<usize>()` returns Result<usize, _>.
                match parts[1].parse::<usize>() {
                    Ok(idx) if idx < self.human.hand.len() => {
                        let card = &self.human.hand[idx];
                        if !self.human.can_play(card) {
                            println!("  Can't play that card (not enough mana or board full).");
                            continue;
                        }
                        // Clone the card name before we move it.
                        let card_name = self.human.hand[idx].name.clone();
                        let card_kind = self.human.hand[idx].kind.clone();

                        // play_card removes the card from hand and handles minions.
                        let played = self.human.play_card(idx);
                        println!("  You play {}!", card_name);

                        if let CardKind::Spell { .. } = card_kind {
                            // Spell — resolve effect.  We need &mut to both players.
                            // Rust won't let us borrow self.human and self.ai
                            // mutably at the same time via self, so we use a
                            // free function and pass them directly.
                            let logs = apply_spell(&mut self.human, &mut self.ai, &played);
                            for msg in logs {
                                println!("{}", msg);
                            }
                            // Check for AI death after spell.
                            if let Some(winner) = self.check_winner() {
                                println!("\n*** {} wins! ***\n", winner);
                                return;
                            }
                        }
                    }
                    Ok(_) => println!("  No card at that index."),
                    Err(_) => println!("  Invalid input, try again."),
                }
            } else {
                println!("  Invalid input, try again. (Use 'play N' or 'done')");
            }
        }
    }

    // Ask the human which minions to attack with.
    pub fn human_attack_phase(&mut self) {
        println!("--- Attack Phase ---");
        println!("  Commands: 'attack N hero' or 'attack N M' (your minion N attacks enemy minion M), 'done'.");

        let stdin = io::stdin();
        let mut lines = stdin.lock().lines();

        loop {
            // Show the board so the player can see indices.
            println!();
            print!("  Your Board: ");
            if self.human.board.is_empty() {
                println!("(empty)  — nothing to attack with.");
                break;
            }
            for (i, m) in self.human.board.iter().enumerate() {
                let ready = if m.can_attack { "READY" } else { "sick" };
                print!("[{}] {} ({})  {}/{}   ", i, m.name, ready, m.attack, m.health);
            }
            println!();

            print!("  AI Board:   ");
            if self.ai.board.is_empty() {
                println!("(empty)");
            } else {
                for (i, m) in self.ai.board.iter().enumerate() {
                    print!("[{}] {}  {}/{}   ", i, m.name, m.attack, m.health);
                }
                println!();
            }

            print!("  > ");
            io::stdout().flush().unwrap();

            let line = match lines.next() {
                Some(Ok(l)) => l.trim().to_string(),
                _ => break,
            };

            if line == "done" || line.is_empty() {
                break;
            }

            let parts: Vec<&str> = line.split_whitespace().collect();

            // "attack N hero"
            if parts.len() == 3 && parts[0] == "attack" && parts[2] == "hero" {
                match parts[1].parse::<usize>() {
                    Ok(att_idx) if att_idx < self.human.board.len() => {
                        if !self.human.board[att_idx].can_attack {
                            println!("  That minion has summoning sickness and can't attack yet.");
                            continue;
                        }
                        let dmg = self.human.board[att_idx].attack;
                        let name = self.human.board[att_idx].name.clone();
                        self.ai.hero_health -= dmg as i32;
                        self.human.board[att_idx].can_attack = false;
                        println!("  {} attacks the AI hero for {} damage! (AI HP: {})",
                            name, dmg, self.ai.hero_health);
                        if let Some(winner) = self.check_winner() {
                            println!("\n*** {} wins! ***\n", winner);
                            return;
                        }
                    }
                    Ok(_) => println!("  No minion at that index."),
                    Err(_) => println!("  Invalid input, try again."),
                }
            }
            // "attack N M"
            else if parts.len() == 3 && parts[0] == "attack" {
                let att_r = parts[1].parse::<usize>();
                let def_r = parts[2].parse::<usize>();
                match (att_r, def_r) {
                    (Ok(att_idx), Ok(def_idx))
                        if att_idx < self.human.board.len()
                            && def_idx < self.ai.board.len() =>
                    {
                        if !self.human.board[att_idx].can_attack {
                            println!("  That minion has summoning sickness and can't attack yet.");
                            continue;
                        }
                        let att_dmg = self.human.board[att_idx].attack;
                        let def_dmg = self.ai.board[def_idx].attack;
                        let att_name = self.human.board[att_idx].name.clone();
                        let def_name = self.ai.board[def_idx].name.clone();

                        // Simultaneous damage
                        self.human.board[att_idx].health -= def_dmg as i32;
                        self.ai.board[def_idx].health -= att_dmg as i32;
                        self.human.board[att_idx].can_attack = false;

                        println!("  {} attacks {} ({} dmg / {} dmg)",
                            att_name, def_name, att_dmg, def_dmg);

                        // Report deaths before removing
                        if self.human.board[att_idx].health <= 0 {
                            println!("  Your {} dies!", att_name);
                        }
                        if self.ai.board[def_idx].health <= 0 {
                            println!("  AI's {} dies!", def_name);
                        }

                        // Clean up dead minions from both boards
                        self.human.board.retain(|m| m.health > 0);
                        self.ai.board.retain(|m| m.health > 0);
                    }
                    _ => println!("  Invalid indices, try again."),
                }
            } else {
                println!("  Invalid input, try again. (Use 'attack N hero' or 'attack N M')");
            }
        }
    }

    // ── Main game loop ────────────────────────────────────────────────────────

    pub fn run(&mut self) {
        println!();
        println!("╔══════════════════════════════════════╗");
        println!("║       MINI-HEARTHSTONE  v0.1         ║");
        println!("║   Reduce the AI hero to 0 HP to win  ║");
        println!("╚══════════════════════════════════════╝");
        println!();
        println!("  Both heroes start at 20 HP.");
        println!("  Mana starts at 0 and gains 1 per turn (max 5).");
        println!("  Board holds up to 3 minions per side.");
        println!("  New minions have summoning sickness (can't attack the turn they're played).");
        println!("  * = can attack,  z = summoning sickness");
        println!();

        // The game loop runs until someone wins.
        loop {
            // ── Human turn ───────────────────────────────────────────────────
            println!("=== TURN {} — Your Turn ===", self.turn);

            // start_turn increments mana, wakes minions, draws a card.
            self.human.start_turn();
            println!("  You draw a card.  Mana: {}/{}", self.human.mana, self.human.max_mana);

            // Play cards.
            self.human_play_phase();
            if let Some(winner) = self.check_winner() {
                println!("\n*** {} wins! ***\n", winner);
                break;
            }

            // Attack with minions.
            self.human_attack_phase();
            if let Some(winner) = self.check_winner() {
                println!("\n*** {} wins! ***\n", winner);
                break;
            }

            println!("--- End of your turn ---");

            // ── AI turn ──────────────────────────────────────────────────────
            println!();
            println!("=== TURN {} — AI Turn ===", self.turn);

            self.ai.start_turn();
            println!("  AI draws a card.  Mana: {}/{}", self.ai.mana, self.ai.max_mana);

            // ai_take_turn needs mutable access to both players independently.
            // We pass them as separate &mut references — Rust allows this because
            // the borrow checker can see they're different fields.
            let ai_log = ai_take_turn(&mut self.ai, &mut self.human);

            // Print everything the AI did.
            for msg in ai_log {
                println!("{}", msg);
            }

            if let Some(winner) = self.check_winner() {
                println!("\n*** {} wins! ***\n", winner);
                break;
            }

            println!("--- End of AI turn ---");
            println!();

            // Advance turn counter.
            self.turn += 1;
        }

        // Final state summary.
        println!("Final state:");
        println!("  Your HP:  {}", self.human.hero_health);
        println!("  AI HP:    {}", self.ai.hero_health);
        println!("Thanks for playing Mini-Hearthstone!");
    }
}
