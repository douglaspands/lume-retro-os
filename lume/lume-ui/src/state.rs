//! Where the interface was when it left for a game (lume-launcher D1, task 7.7):
//! `$XDG_RUNTIME_DIR/lume/state`, one `key=value` per line. The game is kept by its system and
//! gamelist path, not by its position, so a new index (a scan meanwhile) still finds it.

use std::path::Path;

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct State {
    /// dock | grid | settings
    pub screen: String,
    /// favorites | recent | settings | sys:<id>
    pub dock: String,
    /// favorites | recent | sys:<id> (the grid)
    pub list: String,
    pub game_system: String,
    pub game_path: String,
    pub filter: String,
    pub settings: usize,
}

impl State {
    pub fn to_text(&self) -> String {
        format!(
            "screen={}\ndock={}\nlist={}\ngame_system={}\ngame_path={}\nfilter={}\nsettings={}\n",
            self.screen, self.dock, self.list, self.game_system, self.game_path, self.filter, self.settings
        )
    }

    pub fn parse(text: &str) -> State {
        let mut s = State::default();
        for line in text.lines() {
            let Some((k, v)) = line.split_once('=') else { continue };
            match k {
                "screen" => s.screen = v.into(),
                "dock" => s.dock = v.into(),
                "list" => s.list = v.into(),
                "game_system" => s.game_system = v.into(),
                "game_path" => s.game_path = v.into(),
                "filter" => s.filter = v.into(),
                "settings" => s.settings = v.parse().unwrap_or(0),
                _ => {}
            }
        }
        s
    }

    pub fn load(runtime: &Path) -> Option<State> {
        std::fs::read_to_string(runtime.join("state")).ok().map(|t| State::parse(&t))
    }

    pub fn save(&self, runtime: &Path) -> std::io::Result<()> {
        if [&self.game_path, &self.filter].iter().any(|v| v.contains('\n')) {
            return Ok(());
        }
        lume_core::atomic::write(&runtime.join("state"), self.to_text().as_bytes())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trip() {
        let s = State {
            screen: "grid".into(),
            dock: "sys:nes".into(),
            list: "sys:nes".into(),
            game_system: "nes".into(),
            game_path: "sub/A = B.nes".into(),
            filter: "super bros".into(),
            settings: 3,
        };
        assert_eq!(State::parse(&s.to_text()), s);
    }
}
