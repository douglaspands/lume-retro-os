//! Log lines of the launcher: one English line on stderr, prefixed with the program name.
//! The session sends the frontend's stderr to the session log (docs/LOGS.md).

/// Writes `lume-<prog>: <msg>` to stderr.
pub fn line(prog: &str, msg: &str) {
    eprintln!("{prog}: {msg}");
}
