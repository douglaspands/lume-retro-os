//! Save state slots changed by one game (lume-launcher D7, "registro do lume"). RetroArch
//! writes `states/<content folder>/<game>.state` (slot 0), `.state<N>` and `.state.auto`,
//! with no core in the path. lume-run compares the mtimes of `<prefix>.state*` before and
//! after the game and hands the changed slots to `lume-index --touch`, which records the core.

use std::collections::BTreeMap;
use std::os::unix::fs::MetadataExt;
use std::path::Path;

pub type Snapshot = BTreeMap<String, (i64, i64, u64)>;

/// Slot name of a state file name for `base` (`0`, `3`, `auto`), None for other files.
pub fn slot_of(file: &str, base: &str) -> Option<String> {
    let rest = file.strip_prefix(base)?.strip_prefix(".state")?;
    match rest {
        "" => Some("0".into()),
        ".auto" => Some("auto".into()),
        n if !n.is_empty() && n.len() <= 3 && n.chars().all(|c| c.is_ascii_digit()) => Some(n.trim_start_matches('0').to_string()).map(|s| if s.is_empty() { "0".into() } else { s }),
        _ => None,
    }
}

/// mtime and size of every slot of `prefix` (`/storage/states/snes/Game`); empty prefix or
/// missing folder: nothing.
pub fn snapshot(prefix: &str) -> Snapshot {
    let mut out = Snapshot::new();
    if prefix.is_empty() {
        return out;
    }
    let p = Path::new(prefix);
    let (Some(dir), Some(base)) = (p.parent(), p.file_name().map(|b| b.to_string_lossy().into_owned())) else { return out };
    let Ok(entries) = std::fs::read_dir(dir) else { return out };
    for e in entries.flatten() {
        let name = e.file_name().to_string_lossy().into_owned();
        if let (Some(slot), Ok(m)) = (slot_of(&name, &base), e.metadata()) {
            out.insert(slot, (m.mtime(), m.mtime_nsec(), m.len()));
        }
    }
    out
}

/// Slots new or changed since `before`, in slot order.
pub fn changed(prefix: &str, before: &Snapshot) -> Vec<String> {
    snapshot(prefix).into_iter().filter(|(slot, key)| before.get(slot) != Some(key)).map(|(slot, _)| slot).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn slot_names() {
        assert_eq!(slot_of("Game.state", "Game").as_deref(), Some("0"));
        assert_eq!(slot_of("Game.state3", "Game").as_deref(), Some("3"));
        assert_eq!(slot_of("Game.state.auto", "Game").as_deref(), Some("auto"));
        assert_eq!(slot_of("Game.state3.png", "Game"), None);
        assert_eq!(slot_of("Game 2.state", "Game"), None);
        assert_eq!(slot_of("Game.srm", "Game"), None);
    }

    #[test]
    fn only_the_changed_slot() {
        let d = std::env::temp_dir().join(format!("lume-states-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        std::fs::write(d.join("My Game.state1"), b"one").unwrap();
        std::fs::write(d.join("My Game.state2"), b"two").unwrap();
        std::fs::write(d.join("Other.state3"), b"x").unwrap();
        let prefix = d.join("My Game").to_string_lossy().into_owned();
        let before = snapshot(&prefix);
        assert_eq!(before.len(), 2);
        std::fs::write(d.join("My Game.state2"), b"two, longer").unwrap();
        std::fs::write(d.join("My Game.state.auto"), b"a").unwrap();
        assert_eq!(changed(&prefix, &before), ["2", "auto"]);
        assert!(snapshot("").is_empty());
    }
}
