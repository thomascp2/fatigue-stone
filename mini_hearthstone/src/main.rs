// main.rs — entry point for Mini-Hearthstone.
//
// `mod` tells the Rust compiler that these files exist as sub-modules of
// this crate (project).  Think of each `mod` as "include this file's code
// and give it the name shown."
mod card;   // src/card.rs
mod player; // src/player.rs
mod ai;     // src/ai.rs
mod game;   // src/game.rs

use game::Game;

// Every Rust program starts at `fn main()`.
fn main() {
    // Game::new() builds two shuffled decks and deals opening hands.
    // `mut` means we're allowed to modify `game` — required because
    // game.run() calls &mut self methods that change game state.
    let mut game = Game::new();

    // Hand control to the game loop.  It runs until one hero reaches 0 HP.
    game.run();
}
