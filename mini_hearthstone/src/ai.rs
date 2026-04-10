// ai.rs — simple greedy AI logic.
//
// The AI doesn't "think ahead" — it just makes locally reasonable choices:
//   1. Play the most expensive card it can afford (fills the board fast).
//   2. Attack with every ready minion, targeting enemy minions first
//      (to clear the board) and the hero if nothing else is left.
//
// We return a Vec<String> of log messages so game.rs can print them all at
// once after the AI's turn — letting the human read what happened.

use crate::player::{Minion, Player};
use crate::card::CardKind;
use crate::game::apply_spell; // We share spell resolution with the human path.

pub fn ai_take_turn(ai: &mut Player, human: &mut Player) -> Vec<String> {
    // Vec::new() — start with an empty log.
    let mut log: Vec<String> = Vec::new();

    // ── Play phase ────────────────────────────────────────────────────────────
    // Keep trying to play cards until we can't afford anything or board is full.
    // We use a loop label `'play` so we can `continue` the outer loop from
    // inside the inner loop.
    'play: loop {
        // Find the index of the highest-cost card we can still afford.
        // `enumerate()` gives us (index, &card) pairs.
        // We collect the indices of playable cards, then pick the best one.
        let best_index: Option<usize> = {
            let mut best: Option<(usize, u8)> = None; // (index, cost)
            for (i, card) in ai.hand.iter().enumerate() {
                if ai.can_play(card) {
                    match best {
                        None => best = Some((i, card.cost)),
                        Some((_, best_cost)) if card.cost > best_cost => {
                            best = Some((i, card.cost));
                        }
                        _ => {}
                    }
                }
            }
            best.map(|(i, _)| i) // extract just the index
        };

        match best_index {
            None => break 'play, // nothing playable — stop trying
            Some(idx) => {
                // Clone the card name for the log message before play_card
                // consumes (moves) the card out of the hand.
                let card_name = ai.hand[idx].name.clone();
                let card_kind = ai.hand[idx].kind.clone();

                // play_card removes the card from hand, deducts mana,
                // and (for minions) puts a Minion on the board.
                let played_card = ai.play_card(idx);

                match card_kind {
                    CardKind::Minion { .. } => {
                        log.push(format!("  AI plays minion: {}", card_name));
                    }
                    CardKind::Spell { .. } => {
                        log.push(format!("  AI casts spell: {}", card_name));
                        // apply_spell needs mutable access to both players.
                        // We pass `ai` as caster and `human` as opponent.
                        let spell_log = apply_spell(ai, human, &played_card);
                        log.extend(spell_log);
                    }
                }

                // After each card, loop back and see if we can play another.
                continue 'play;
            }
        }
    }

    // ── Attack phase ──────────────────────────────────────────────────────────
    // Attack with every minion that can attack.
    // We iterate by index because we may modify the boards inside the loop.
    //
    // Important: after each attack the board may shrink (dead minions removed),
    // so we re-check bounds carefully.
    let mut attacker_idx = 0;
    while attacker_idx < ai.board.len() {
        if !ai.board[attacker_idx].can_attack {
            attacker_idx += 1;
            continue;
        }

        // Does the human have any minions to attack?
        if !human.board.is_empty() {
            // Attack the first enemy minion (index 0 — simple but functional).
            let attacker_atk = ai.board[attacker_idx].attack;
            let defender_atk = human.board[0].attack;

            let attacker_name = ai.board[attacker_idx].name.clone();
            let defender_name = human.board[0].name.clone();

            // Both minions deal damage to each other simultaneously.
            ai.board[attacker_idx].health -= defender_atk as i32;
            human.board[0].health -= attacker_atk as i32;

            log.push(format!(
                "  AI's {} attacks your {} ({} dmg / {} dmg)",
                attacker_name, defender_name, attacker_atk, defender_atk
            ));

            // Remove dead minions.
            // `retain` keeps only elements where the closure returns true.
            // This is idiomatic Rust — much cleaner than a manual loop+remove.
            if human.board[0].health <= 0 {
                log.push(format!("  Your {} dies!", defender_name));
            }
            human.board.retain(|m: &Minion| m.health > 0);

            if ai.board[attacker_idx].health <= 0 {
                log.push(format!("  AI's {} dies!", attacker_name));
            }
            // Check if the attacker died before incrementing index.
            let attacker_died = ai.board[attacker_idx].health <= 0;
            ai.board.retain(|m: &Minion| m.health > 0);

            // If attacker died, `retain` shifted elements left — don't increment.
            if !attacker_died {
                attacker_idx += 1;
            }
        } else {
            // No enemy minions — hit the hero directly.
            let damage = ai.board[attacker_idx].attack;
            human.hero_health -= damage as i32;
            log.push(format!(
                "  AI's {} attacks your hero for {} damage! (Your HP: {})",
                ai.board[attacker_idx].name, damage, human.hero_health
            ));
            ai.board[attacker_idx].can_attack = false; // used for this turn
            attacker_idx += 1;
        }
    }

    log
}
