//! Card maintenance request interface (openspec device-fixes D4/D5, docs/LAUNCHER.md).
//!
//! The launcher asks the `lume-card` service for work by creating a file named after the verb
//! in `/run/lume/card/` (folder of the group `game`); the service answers in
//! `/run/lume/card/status`. The last runs are kept on the card, by boot number (no clock):
//! `ROMS/system/card/last-trim`, `last-check` and the request `check-next-boot`.
//!
//! This module is the frozen contract: the service (writer of status and markers), the
//! initramfs (reader of `check-next-boot`) and the launcher panel (reader) agree on it.

use std::fs;
use std::io;
use std::path::PathBuf;

use crate::{atomic, paths};

/// A request the launcher can make. Any other file name in the request folder is refused.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Verb {
    /// `fstrim -v /storage`.
    Trim,
    /// Creates `ROMS/system/card/check-next-boot`.
    CheckNextBoot,
}

impl Verb {
    pub const ALL: [Verb; 2] = [Verb::Trim, Verb::CheckNextBoot];

    /// The file name of the request.
    pub fn name(self) -> &'static str {
        match self {
            Verb::Trim => "trim",
            Verb::CheckNextBoot => "check-next-boot",
        }
    }

    pub fn parse(name: &str) -> Option<Verb> {
        Verb::ALL.into_iter().find(|v| v.name() == name)
    }
}

/// Content of `/run/lume/card/status`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Status {
    /// `running`: a trim is in progress.
    Running,
    /// `ok <bytes>` after a trim (bytes trimmed), or a bare `ok` (no size: check request).
    Ok(Option<u64>),
    /// `fail <reason>`.
    Fail(String),
}

impl Status {
    /// Parses the file content; anything that is not one of the four formats is `None`.
    pub fn parse(text: &str) -> Option<Status> {
        let line = text.lines().next()?.trim();
        if line == "running" {
            return Some(Status::Running);
        }
        if line == "ok" {
            return Some(Status::Ok(None));
        }
        if let Some(rest) = line.strip_prefix("ok ") {
            return rest.trim().parse::<u64>().ok().map(|b| Status::Ok(Some(b)));
        }
        if let Some(rest) = line.strip_prefix("fail ") {
            let reason = rest.trim();
            return (!reason.is_empty()).then(|| Status::Fail(reason.to_string()));
        }
        None
    }

    /// The file content, with the final newline.
    pub fn render(&self) -> String {
        match self {
            Status::Running => "running\n".into(),
            Status::Ok(None) => "ok\n".into(),
            Status::Ok(Some(b)) => format!("ok {b}\n"),
            // the reason is one line
            Status::Fail(r) => format!("fail {}\n", r.replace(['\n', '\r'], " ").trim()),
        }
    }
}

/// Request folder: `$LUME_RUN/card` (default `/run/lume/card`).
pub fn request_dir() -> PathBuf {
    std::env::var_os("LUME_RUN").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("/run/lume")).join("card")
}

pub fn status_path() -> PathBuf {
    request_dir().join("status")
}

/// Marker folder on the card: `ROMS/system/card`.
pub fn marker_dir() -> PathBuf {
    paths::storage().join("system/card")
}

pub fn last_trim_path() -> PathBuf {
    marker_dir().join("last-trim")
}

pub fn last_check_path() -> PathBuf {
    marker_dir().join("last-check")
}

pub fn check_request_path() -> PathBuf {
    marker_dir().join("check-next-boot")
}

/// Boot number in a marker file: decimal text; anything else (empty, text, negative) is
/// ignored and reads as "never".
fn parse_boot(text: &str) -> Option<u64> {
    text.trim().parse().ok()
}

fn read_boot(path: PathBuf) -> Option<u64> {
    parse_boot(&fs::read_to_string(path).ok()?)
}

/// Boot of the last trim; `None` = never (missing or invalid file).
pub fn last_trim() -> Option<u64> {
    read_boot(last_trim_path())
}

/// Boot of the last check; `None` = never.
pub fn last_check() -> Option<u64> {
    read_boot(last_check_path())
}

/// Boot number written by the request `check-next-boot`; `None` = no request pending.
/// A file that exists with invalid content still is a pending request for the initramfs
/// (it tests existence); this reader only reports the number.
pub fn check_requested() -> Option<u64> {
    read_boot(check_request_path())
}

/// Current status; `None` when the file is missing or invalid.
pub fn read_status() -> Option<Status> {
    Status::parse(&fs::read_to_string(status_path()).ok()?)
}

/// Launcher side: asks the service for `verb` (creates the empty request file).
pub fn request(verb: Verb) -> io::Result<()> {
    let dir = request_dir();
    fs::create_dir_all(&dir)?;
    fs::write(dir.join(verb.name()), b"")
}

/// Service side: publishes the status.
pub fn write_status(status: &Status) -> io::Result<()> {
    atomic::write(&status_path(), status.render().as_bytes())
}

/// Service side: records the boot of the last trim.
pub fn write_last_trim(boot: u64) -> io::Result<()> {
    atomic::write(&last_trim_path(), format!("{boot}\n").as_bytes())
}

/// Boot that consumed the check request records its number.
pub fn write_last_check(boot: u64) -> io::Result<()> {
    atomic::write(&last_check_path(), format!("{boot}\n").as_bytes())
}

/// Service side: leaves the request for the next boot, with the boot that made it.
pub fn write_check_request(boot: u64) -> io::Result<()> {
    atomic::write(&check_request_path(), format!("{boot}\n").as_bytes())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn verbs_round_trip_and_unknown_is_refused() {
        for v in Verb::ALL {
            assert_eq!(Verb::parse(v.name()), Some(v));
        }
        assert_eq!(Verb::parse("trim"), Some(Verb::Trim));
        assert_eq!(Verb::parse("check-next-boot"), Some(Verb::CheckNextBoot));
        assert_eq!(Verb::parse("status"), None);
        assert_eq!(Verb::parse("rm"), None);
        assert_eq!(Verb::parse(""), None);
    }

    #[test]
    fn status_every_state() {
        assert_eq!(Status::parse("running\n"), Some(Status::Running));
        assert_eq!(Status::parse("running"), Some(Status::Running));
        assert_eq!(Status::parse("ok 1048576\n"), Some(Status::Ok(Some(1048576))));
        assert_eq!(Status::parse("ok\n"), Some(Status::Ok(None)));
        assert_eq!(Status::parse("fail not supported\n"), Some(Status::Fail("not supported".into())));
    }

    #[test]
    fn status_invalid_is_ignored() {
        for bad in ["", "\n", "done", "ok abc", "ok -5", "ok 1 2", "fail", "fail \n", "runningx", "OK"] {
            assert_eq!(Status::parse(bad), None, "{bad:?}");
        }
    }

    #[test]
    fn status_render_parses_back() {
        for s in [Status::Running, Status::Ok(None), Status::Ok(Some(42)), Status::Fail("a b".into())] {
            assert_eq!(Status::parse(&s.render()), Some(s));
        }
        assert_eq!(Status::Fail("two\nlines".into()).render(), "fail two lines\n");
    }

    #[test]
    fn boot_markers() {
        assert_eq!(parse_boot("150\n"), Some(150));
        assert_eq!(parse_boot(" 7 "), Some(7));
        assert_eq!(parse_boot(""), None);
        assert_eq!(parse_boot("abc"), None);
        assert_eq!(parse_boot("-3"), None);
    }

    // One test touches the environment (LUME_RUN, LUME_STORAGE), so the files are exercised
    // in a single sequence.
    #[test]
    fn files_round_trip_and_missing_is_never() {
        let d = std::env::temp_dir().join(format!("lume-cardreq-{}", std::process::id()));
        let _ = fs::remove_dir_all(&d);
        fs::create_dir_all(&d).unwrap();
        std::env::set_var("LUME_RUN", d.join("run"));
        std::env::set_var("LUME_STORAGE", d.join("storage"));

        // nothing exists: never, no status, no request
        assert_eq!(last_trim(), None);
        assert_eq!(last_check(), None);
        assert_eq!(check_requested(), None);
        assert_eq!(read_status(), None);

        write_last_trim(150).unwrap();
        write_last_check(151).unwrap();
        write_check_request(152).unwrap();
        assert_eq!(last_trim(), Some(150));
        assert_eq!(last_check(), Some(151));
        assert_eq!(check_requested(), Some(152));
        assert!(d.join("storage/system/card/last-trim").is_file());

        write_status(&Status::Running).unwrap();
        assert_eq!(read_status(), Some(Status::Running));
        write_status(&Status::Ok(Some(4096))).unwrap();
        assert_eq!(read_status(), Some(Status::Ok(Some(4096))));

        // invalid content reads as never / no status
        fs::write(last_trim_path(), "garbage").unwrap();
        fs::write(status_path(), "???").unwrap();
        assert_eq!(last_trim(), None);
        assert_eq!(read_status(), None);

        request(Verb::Trim).unwrap();
        assert!(d.join("run/card/trim").is_file());

        let _ = fs::remove_dir_all(&d);
    }
}
