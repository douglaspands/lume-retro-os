//! The protocol of the input daemon's socket, `/run/lume/input.sock` (lume-hud-actions D2,
//! D11, D13). SOCK_SEQPACKET, one message per packet; the header of
//! `aports/lume-input/input.c` describes the same protocol and both change together.
//!
//! ```text
//! daemon -> client   quit | app_menu | save_state | load_state | screenshot | hud
//!                    fn_tap | fn_hold <button>=<action>... | fn_release
//!                    volume | brightness
//!                    nav up|down|left|right|a|b          (only to the capturing client)
//! client -> daemon   tap KEY_<name> | capture on | capture off
//! ```
//!
//! Unknown messages come from a newer daemon and are ignored by the reader (`parse` gives
//! None).

/// A chord action, by name (the profile's `chord <code> <action>`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Action {
    Quit,
    AppMenu,
    SaveState,
    LoadState,
    Screenshot,
    Hud,
}

impl Action {
    pub const ALL: [Action; 6] =
        [Action::AppMenu, Action::SaveState, Action::LoadState, Action::Screenshot, Action::Hud, Action::Quit];

    pub fn as_str(self) -> &'static str {
        match self {
            Action::Quit => "quit",
            Action::AppMenu => "app_menu",
            Action::SaveState => "save_state",
            Action::LoadState => "load_state",
            Action::Screenshot => "screenshot",
            Action::Hud => "hud",
        }
    }

    pub fn parse(s: &str) -> Option<Action> {
        Action::ALL.into_iter().find(|a| a.as_str() == s)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Nav {
    Up,
    Down,
    Left,
    Right,
    A,
    B,
}

/// One entry of the `fn_hold` table: the short name of the button (the glyph on the screen:
/// `B`, `R1`, `Start`, `Vol`) and the action's name as the daemon sent it (an action this
/// side does not know yet, like `brightness`, is kept as text).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct HoldEntry {
    pub button: String,
    pub action: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Message {
    Action(Action),
    FnTap,
    FnHold(Vec<HoldEntry>),
    FnRelease,
    Volume,
    Brightness,
    Nav(Nav),
}

/// A message of the daemon; None for an unknown one (ignored).
pub fn parse(msg: &str) -> Option<Message> {
    let msg = msg.trim();
    let (word, rest) = match msg.split_once(' ') {
        Some((w, r)) => (w, r.trim()),
        None => (msg, ""),
    };
    Some(match (word, rest) {
        ("fn_tap", "") => Message::FnTap,
        ("fn_release", "") => Message::FnRelease,
        ("volume", "") => Message::Volume,
        ("brightness", "") => Message::Brightness,
        ("fn_hold", table) => Message::FnHold(
            table
                .split_whitespace()
                .filter_map(|pair| {
                    let (b, a) = pair.split_once('=')?;
                    (!b.is_empty() && !a.is_empty()).then(|| HoldEntry { button: b.into(), action: a.into() })
                })
                .collect(),
        ),
        ("nav", dir) => Message::Nav(match dir {
            "up" => Nav::Up,
            "down" => Nav::Down,
            "left" => Nav::Left,
            "right" => Nav::Right,
            "a" => Nav::A,
            "b" => Nav::B,
            _ => return None,
        }),
        (w, "") => Message::Action(Action::parse(w)?),
        _ => return None,
    })
}

/// `tap KEY_<name>`: a press and a release of a keyboard key on the virtual device (a runner
/// action `key:KEY_F2`). Only `KEY_` followed by capitals, digits or `_` is accepted here;
/// the daemon also refuses names out of its table.
pub fn tap(key: &str) -> Result<String, String> {
    if is_key_name(key) {
        Ok(format!("tap {key}"))
    } else {
        Err(format!("{key:?} is not a KEY_ code"))
    }
}

pub fn is_key_name(key: &str) -> bool {
    key.strip_prefix("KEY_")
        .is_some_and(|n| !n.is_empty() && n.chars().all(|c| c.is_ascii_uppercase() || c.is_ascii_digit() || c == '_'))
}

pub const CAPTURE_ON: &str = "capture on";
pub const CAPTURE_OFF: &str = "capture off";

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn valid_messages() {
        assert_eq!(parse("quit"), Some(Message::Action(Action::Quit)));
        assert_eq!(parse("save_state\n"), Some(Message::Action(Action::SaveState)));
        for a in Action::ALL {
            assert_eq!(parse(a.as_str()), Some(Message::Action(a)));
        }
        assert_eq!(parse("fn_tap"), Some(Message::FnTap));
        assert_eq!(parse("fn_release"), Some(Message::FnRelease));
        assert_eq!(parse("volume"), Some(Message::Volume));
        assert_eq!(parse("brightness"), Some(Message::Brightness));
        assert_eq!(parse("nav up"), Some(Message::Nav(Nav::Up)));
        assert_eq!(parse("nav b"), Some(Message::Nav(Nav::B)));
    }

    #[test]
    fn fn_hold_reads_the_table_in_pairs() {
        let m = parse("fn_hold B=app_menu R1=save_state Start=quit Vol=brightness").unwrap();
        let Message::FnHold(t) = m else { panic!() };
        let pairs: Vec<(&str, &str)> = t.iter().map(|e| (e.button.as_str(), e.action.as_str())).collect();
        assert_eq!(pairs, [("B", "app_menu"), ("R1", "save_state"), ("Start", "quit"), ("Vol", "brightness")]);
        // broken pairs are skipped, an empty table is still a hold
        let Some(Message::FnHold(t)) = parse("fn_hold B= =x Y=screenshot junk") else { panic!() };
        assert_eq!(t, [HoldEntry { button: "Y".into(), action: "screenshot".into() }]);
        assert_eq!(parse("fn_hold"), Some(Message::FnHold(vec![])));
    }

    #[test]
    fn unknown_messages_are_ignored() {
        for m in ["", "reboot", "nav sideways", "quit now", "fn_tap 2", "QUIT"] {
            assert_eq!(parse(m), None, "{m:?}");
        }
    }

    #[test]
    fn tap_takes_only_key_codes() {
        assert_eq!(tap("KEY_F2").unwrap(), "tap KEY_F2");
        assert_eq!(tap("KEY_RIGHTSHIFT").unwrap(), "tap KEY_RIGHTSHIFT");
        for bad in ["BTN_A", "KEY_", "key_f2", "KEY_F2 x", "60", ""] {
            assert!(tap(bad).is_err(), "{bad:?}");
        }
    }
}
