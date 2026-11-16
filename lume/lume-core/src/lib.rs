//! Shared code of the lume-launcher (openspec change lume-launcher, D2).
//!
//! Nothing here knows SDL, the theme or the screen: it is the data side (catalog, runners,
//! per-game options, settings, paths) that the interface, the indexer and the supervisor
//! share.

pub mod atomic;
pub mod catalog;
pub mod events;
pub mod log;
pub mod options;
pub mod paths;
pub mod runner;
pub mod settings;
pub mod states;
pub mod text;
