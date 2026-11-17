//! The Lume menu over a game and the chord hint (lume-hud-actions D10, D13): pure state, so
//! the paths of the D10 figure are unit tests. lume-run owns it; what the menu asks for comes
//! back as `Effect`s that main.rs carries out (pause, the runner's actions, the polite quit).
//!
//! ```text
//!  closed --Fn tap--> list --A on Reset/End--> confirm (focus on No)
//!    ^                 |  |                       |       |
//!    |<--B or Fn tap---+  +--A on Back--> closed  |       |
//!    |<--A on <App> menu: closes and sends app_menu        |
//!    |<--Yes: reset (back to the game) or the polite quit; No/B: list
//! ```
//!
//! The drawing is a text line (`LUME_MENU title|item|...|focus`, `LUME_HINT b\tl|...`) for
//! RetroArch's widgets (patch 0012), the reserve path of D14 while the system-drawn menu
//! (lume-menu) waits for its proof on the consoles.

use lume_core::gametext::{text, Text};
use lume_core::input::{HoldEntry, Nav};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Item {
    Back,
    Reset,
    AppMenu,
    End,
    ForceClose,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum State {
    Closed,
    List { focus: usize },
    /// Reset or End waiting for Yes; `yes` is the focus (false: No, the default)
    Confirm { item: Item, yes: bool },
}

/// What lume-run does for the menu.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Effect {
    /// pause the game (the runner's pause, else SIGSTOP) and take the controls
    Open,
    /// give the controls back and unpause if the menu paused
    Close,
    /// unpause, then the runner's reset
    Reset,
    /// close, then the runner's app_menu
    AppMenu,
    /// unpause, then the polite quit of the runner
    Quit,
    /// SIGKILL to the game, no grace
    ForceClose,
}

pub struct Menu {
    pub state: State,
    /// what the runner declares: Reset and "<App> menu" only when it can do them
    has_reset: bool,
    has_app_menu: bool,
    /// the pause got no answer: "Force close" joins the list
    pub unresponsive: bool,
    lang: String,
    app: String,
    title: String,
}

impl Menu {
    pub fn new(lang: &str, app: &str, title: &str, has_reset: bool, has_app_menu: bool) -> Menu {
        Menu {
            state: State::Closed,
            has_reset,
            has_app_menu,
            unresponsive: false,
            lang: lang.into(),
            app: app.into(),
            title: title.into(),
        }
    }

    pub fn is_open(&self) -> bool {
        self.state != State::Closed
    }

    /// The order the user chose (2026-11-17): Back, End, Reset, then the app's own menu.
    pub fn items(&self) -> Vec<Item> {
        let mut v = vec![Item::Back, Item::End];
        if self.unresponsive {
            v.push(Item::ForceClose);
            return v;
        }
        if self.has_reset {
            v.push(Item::Reset);
        }
        if self.has_app_menu {
            v.push(Item::AppMenu);
        }
        v
    }

    /// The Fn tap: opens, or closes from any state.
    pub fn tap(&mut self) -> Vec<Effect> {
        if self.is_open() {
            self.state = State::Closed;
            vec![Effect::Close]
        } else {
            self.state = State::List { focus: 0 };
            vec![Effect::Open]
        }
    }

    /// The pause found the application silent: "Force close" appears, with the focus on it.
    pub fn set_unresponsive(&mut self) {
        self.unresponsive = true;
        if let State::List { .. } = self.state {
            let items = self.items();
            self.state = State::List { focus: items.iter().position(|i| *i == Item::ForceClose).unwrap_or(0) };
        }
    }

    pub fn nav(&mut self, n: Nav) -> Vec<Effect> {
        match self.state {
            State::Closed => vec![],
            State::List { focus } => {
                let items = self.items();
                let last = items.len() - 1;
                match n {
                    Nav::Up => self.state = State::List { focus: focus.saturating_sub(1) },
                    Nav::Down => self.state = State::List { focus: (focus + 1).min(last) },
                    Nav::B => {
                        self.state = State::Closed;
                        return vec![Effect::Close];
                    }
                    Nav::A => {
                        return match items[focus.min(last)] {
                            Item::Back => {
                                self.state = State::Closed;
                                vec![Effect::Close]
                            }
                            Item::AppMenu => {
                                self.state = State::Closed;
                                vec![Effect::Close, Effect::AppMenu]
                            }
                            Item::ForceClose => {
                                self.state = State::Closed;
                                vec![Effect::ForceClose]
                            }
                            item @ (Item::Reset | Item::End) => {
                                self.state = State::Confirm { item, yes: false };
                                vec![]
                            }
                        }
                    }
                    Nav::Left | Nav::Right => {}
                }
                vec![]
            }
            State::Confirm { item, yes } => match n {
                Nav::Left | Nav::Up => {
                    self.state = State::Confirm { item, yes: false };
                    vec![]
                }
                Nav::Right | Nav::Down => {
                    self.state = State::Confirm { item, yes: true };
                    vec![]
                }
                Nav::A if yes => {
                    self.state = State::Closed;
                    vec![if item == Item::Reset { Effect::Reset } else { Effect::Quit }]
                }
                Nav::A | Nav::B => {
                    // No (or back): the list again, on the item that asked
                    let focus = self.items().iter().position(|i| *i == item).unwrap_or(0);
                    self.state = State::List { focus };
                    vec![]
                }
            },
        }
    }

    fn label(&self, i: Item) -> String {
        let t = match i {
            Item::Back => Text::BackToGame,
            Item::Reset => Text::Reset,
            Item::AppMenu => Text::AppMenu,
            Item::End => Text::EndGame,
            Item::ForceClose => Text::ForceClose,
        };
        text(&self.lang, t, &self.app)
    }

    /// The argument of `LUME_MENU`: `title|item|...|focus`; empty when closed (hides it).
    pub fn draw_text(&self) -> String {
        let title = if self.unresponsive {
            text(&self.lang, Text::NotResponding, &self.app)
        } else {
            self.title.replace('|', "/")
        };
        match self.state {
            State::Closed => String::new(),
            State::List { focus } => {
                let mut parts = vec![title];
                parts.extend(self.items().into_iter().map(|i| self.label(i)));
                parts.push(focus.to_string());
                parts.join("|")
            }
            State::Confirm { item, yes } => {
                let q = if item == Item::Reset { Text::ConfirmReset } else { Text::ConfirmEnd };
                [
                    text(&self.lang, q, &self.app),
                    text(&self.lang, Text::No, &self.app),
                    text(&self.lang, Text::Yes, &self.app),
                    (yes as u8).to_string(),
                ]
                .join("|")
            }
        }
    }
}

/// The hint of the chords (D13): the entries of the daemon's table whose action this runner
/// can do (`declared`), in the table's order, plus Fn+Start; `button\tname` joined by `|`.
pub fn hint_text(lang: &str, app: &str, table: &[HoldEntry], declared: &dyn Fn(&str) -> bool) -> String {
    let mut lines = Vec::new();
    for e in table {
        let t = match e.action.as_str() {
            "app_menu" if declared("app_menu") => text(lang, Text::AppMenu, app),
            "save_state" if declared("save_state") => text(lang, Text::SaveState, ""),
            "load_state" if declared("load_state") => text(lang, Text::LoadState, ""),
            "screenshot" if declared("screenshot") => text(lang, Text::Screenshot, ""),
            "hud" if declared("hud") => text(lang, Text::StatusBar, ""),
            "quit" => text(lang, Text::EndGame, ""),
            _ => continue,
        };
        lines.push(format!("Fn+{}\t{t}", e.button));
    }
    lines.join("|")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ra() -> Menu {
        Menu::new("en", "RetroArch", "Alpha", true, true)
    }

    #[test]
    fn tap_opens_and_closes_from_any_state() {
        let mut m = ra();
        assert_eq!(m.tap(), [Effect::Open]);
        assert_eq!(m.state, State::List { focus: 0 });
        assert_eq!(m.tap(), [Effect::Close]);
        m.tap();
        m.nav(Nav::Down);
        m.nav(Nav::A); // End -> confirm
        assert!(matches!(m.state, State::Confirm { .. }));
        assert_eq!(m.tap(), [Effect::Close]);
        assert_eq!(m.state, State::Closed);
    }

    #[test]
    fn list_paths() {
        let mut m = ra();
        m.tap();
        // the user's order (2026-11-17): Back, End, Reset, the app's menu last
        assert_eq!(m.items(), [Item::Back, Item::End, Item::Reset, Item::AppMenu]);
        // A on Back closes
        assert_eq!(m.nav(Nav::A), [Effect::Close]);
        // B closes
        m.tap();
        assert_eq!(m.nav(Nav::B), [Effect::Close]);
        // A on the app menu: closes, then app_menu
        m.tap();
        m.nav(Nav::Down);
        m.nav(Nav::Down);
        m.nav(Nav::Down);
        assert_eq!(m.nav(Nav::A), [Effect::Close, Effect::AppMenu]);
        // the focus stops at both ends
        m.tap();
        m.nav(Nav::Up);
        assert_eq!(m.state, State::List { focus: 0 });
        for _ in 0..9 {
            m.nav(Nav::Down);
        }
        assert_eq!(m.state, State::List { focus: 3 });
    }

    #[test]
    fn reset_and_end_ask_with_no_in_focus() {
        let mut m = ra();
        m.tap();
        m.nav(Nav::Down);
        m.nav(Nav::Down);
        assert!(m.nav(Nav::A).is_empty());
        assert_eq!(m.state, State::Confirm { item: Item::Reset, yes: false });
        // A without moving the focus is No: back to the list, nothing reset
        assert!(m.nav(Nav::A).is_empty());
        assert_eq!(m.state, State::List { focus: 2 });
        m.nav(Nav::A);
        m.nav(Nav::Right);
        assert_eq!(m.nav(Nav::A), [Effect::Reset]);
        assert_eq!(m.state, State::Closed);
        // End: B is No, Yes quits
        m.tap();
        m.nav(Nav::Down);
        m.nav(Nav::A);
        assert_eq!(m.state, State::Confirm { item: Item::End, yes: false });
        m.nav(Nav::B);
        assert_eq!(m.state, State::List { focus: 1 });
        m.nav(Nav::A);
        m.nav(Nav::Down);
        m.nav(Nav::Left);
        assert!(m.nav(Nav::A).is_empty(), "Left went back to No");
        m.nav(Nav::A);
        m.nav(Nav::Right);
        assert_eq!(m.nav(Nav::A), [Effect::Quit]);
    }

    #[test]
    fn native_runner_has_only_back_and_end() {
        let mut m = Menu::new("pt", "Sh", "x", false, false);
        m.tap();
        assert_eq!(m.items(), [Item::Back, Item::End]);
        assert_eq!(m.draw_text(), "x|Voltar ao jogo|Encerrar jogo|0");
    }

    #[test]
    fn silent_app_gets_force_close() {
        let mut m = ra();
        m.tap();
        m.set_unresponsive();
        assert_eq!(m.items(), [Item::Back, Item::End, Item::ForceClose]);
        assert_eq!(m.state, State::List { focus: 2 });
        assert_eq!(m.draw_text(), "RetroArch is not responding|Back to game|End game|Force close|2");
        assert_eq!(m.nav(Nav::A), [Effect::ForceClose]);
    }

    #[test]
    fn draw_text_in_three_languages() {
        for (lang, line) in [
            ("en", "Alpha|Back to game|End game|Reset|RetroArch menu|0"),
            ("pt", "Alpha|Voltar ao jogo|Encerrar jogo|Reiniciar|Menu do RetroArch|0"),
            ("es", "Alpha|Volver al juego|Salir del juego|Reiniciar|Menú de RetroArch|0"),
        ] {
            let mut m = Menu::new(lang, "RetroArch", "Alpha", true, true);
            assert_eq!(m.draw_text(), "");
            m.tap();
            assert_eq!(m.draw_text(), line);
        }
        let mut m = Menu::new("pt", "RetroArch", "A|B", true, true);
        m.tap();
        m.nav(Nav::Down);
        m.nav(Nav::Down);
        m.nav(Nav::A);
        assert_eq!(m.draw_text(), "Reiniciar o jogo?|Não|Sim|0");
        assert!(Menu::new("en", "R", "A|B", false, false).title.contains('|'));
    }

    fn table() -> Vec<HoldEntry> {
        "B=app_menu R1=save_state L1=load_state Y=screenshot X=hud Start=quit Vol=brightness"
            .split(' ')
            .map(|p| {
                let (b, a) = p.split_once('=').unwrap();
                HoldEntry { button: b.into(), action: a.into() }
            })
            .collect()
    }

    #[test]
    fn hint_lists_what_the_runner_declares_and_fn_start() {
        let all = hint_text("en", "RetroArch", &table(), &|_| true);
        assert_eq!(
            all,
            "Fn+B\tRetroArch menu|Fn+R1\tSave state|Fn+L1\tLoad state|Fn+Y\tScreenshot|Fn+X\tStatus bar|Fn+Start\tEnd game"
        );
        let only_menu = hint_text("pt", "RetroArch", &table(), &|a| a == "app_menu");
        assert_eq!(only_menu, "Fn+B\tMenu do RetroArch|Fn+Start\tEncerrar jogo");
        assert_eq!(hint_text("es", "RetroArch", &table(), &|_| false), "Fn+Start\tSalir del juego");
    }
}
