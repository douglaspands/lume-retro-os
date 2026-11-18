//! The sleep protocol (openspec device-fixes D11, task 3.2): suspend and resume by the power
//! button. Frozen here and in docs/LAUNCHER.md ("Suspender") and docs/LOGS.md (`sleep`); the
//! input daemon (`aports/lume-input/input.c`) and the root service `lume-sleep` (package
//! `lume-power`, shell) mirror it and change together with this file.
//!
//! ```text
//!  power button tapped (let go before 1 s)  lume-input  -> request file  <dir>/suspend
//!                                           lume-input  -> clients       power_tap
//!  power button held 2 s                    lume-input  -> request file  <dir>/poweroff
//!                                           lume-input  -> clients       power_hold
//!  Suspend item of the launcher             lume-ui     -> request file  <dir>/suspend
//!
//!  lume-sleep (inotifyd on <dir>)           <dir>/phase    "suspend <seq>"
//!  lume-input relays to its clients         socket         "suspend <seq>"
//!  each client, once paused / not drawing   socket         "suspend_ok <seq>"
//!  lume-input, all answered or 2 s          <dir>/clients  "suspend <seq> ok|timeout <a>/<n>"
//!  lume-sleep: sound, clock, sync, light, Wi-Fi, governor, USB gadget off, /sys/power/state
//!  ... wake by the power button ...
//!  lume-sleep: the same steps backwards      <dir>/phase    "resume <seq>"
//!  lume-input drops the queued input, then   socket         "resume <seq>"
//! ```
//!
//! `<dir>` is `/run/lume/sleep` (`$LUME_SLEEP_DIR` in tests). Everything here is pure: parsing,
//! serializing, the reply wait with its deadline and the admission of a request; only
//! [`request_in`] and [`mode_of`] touch files.

use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

/// The request folder (root:game, 1770): `$LUME_SLEEP_DIR`, default `/run/lume/sleep`.
pub fn dir() -> PathBuf {
    std::env::var_os("LUME_SLEEP_DIR").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("/run/lume/sleep"))
}

/// How long lume-input waits for `suspend_ok <seq>` from every connected client.
pub const CLIENT_REPLY: Duration = Duration::from_secs(2);
/// How long lume-sleep waits for `<dir>/clients` of its sequence (CLIENT_REPLY plus a margin
/// for a busy or dead lume-input); past it the suspension goes on.
pub const SERVICE_WAIT: Duration = Duration::from_secs(3);
/// A `suspend` request this soon after the console is back is the waking press: dropped.
pub const WAKE_GUARD: Duration = Duration::from_secs(1);
/// The USB gadget is bound to the UDC again this long after the wake, in the background
/// (J1 on the GA36: without the unbind before `freeze` the musb never comes back).
pub const USB_REBIND_DELAY: Duration = Duration::from_secs(1);
/// The UDC file of the USB gadget: emptied before the suspension, its old content written
/// back after the wake (only when it was bound).
pub const UDC_FILE: &str = "/sys/kernel/config/usb_gadget/lume/UDC";
/// Tap and hold of the power button (lume-input, task 8.2).
pub const TAP_MAX: Duration = Duration::from_secs(1);
pub const HOLD: Duration = Duration::from_secs(2);

// ---- the input socket (lume-input <-> lume-run, lume-ui) ----

/// The sleep messages of the input daemon to its clients.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Notice {
    /// The power button was tapped. Informational: lume-input already made the request, the
    /// client never makes another one for it.
    PowerTap,
    /// The power button was held 2 s (the session is shutting down). Informational too.
    PowerHold,
    /// Pause and stop drawing, then answer [`suspend_ok`] with the same sequence.
    Suspend(u32),
    /// Back from the suspension: carry on (the game continues on its own). No answer.
    Resume(u32),
}

impl Notice {
    /// The message as it goes on the socket (one packet, no newline).
    pub fn line(&self) -> String {
        match self {
            Notice::PowerTap => "power_tap".into(),
            Notice::PowerHold => "power_hold".into(),
            Notice::Suspend(s) => format!("suspend {s}"),
            Notice::Resume(s) => format!("resume {s}"),
        }
    }

    /// One socket message; None when it is not a sleep message (or a broken one).
    pub fn parse(msg: &str) -> Option<Notice> {
        let msg = msg.trim();
        let (word, rest) = msg.split_once(' ').map(|(w, r)| (w, r.trim())).unwrap_or((msg, ""));
        match (word, rest) {
            ("power_tap", "") => Some(Notice::PowerTap),
            ("power_hold", "") => Some(Notice::PowerHold),
            ("suspend", s) => parse_seq(s).map(Notice::Suspend),
            ("resume", s) => parse_seq(s).map(Notice::Resume),
            _ => None,
        }
    }
}

/// A sequence number: a positive decimal integer, nothing else.
fn parse_seq(s: &str) -> Option<u32> {
    if s.is_empty() || !s.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    s.parse().ok().filter(|&n| n > 0)
}

/// The client's answer to `suspend <seq>` (client -> daemon).
pub fn suspend_ok(seq: u32) -> String {
    format!("suspend_ok {seq}")
}

/// Reads a client's answer (the daemon side; lume-input mirrors it in C).
pub fn parse_suspend_ok(msg: &str) -> Option<u32> {
    let rest = msg.trim().strip_prefix("suspend_ok ")?;
    parse_seq(rest.trim())
}

// ---- the request files in <dir> ----

/// A request to lume-sleep: an empty file named after the verb, created in [`dir`].
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Request {
    /// lume-input on `power_tap`; lume-ui on its Suspend item.
    Suspend,
    /// lume-input on `power_hold`: the session shuts down (the path of the Power off item).
    Poweroff,
}

impl Request {
    pub fn name(self) -> &'static str {
        match self {
            Request::Suspend => "suspend",
            Request::Poweroff => "poweroff",
        }
    }
}

/// The outcome of making a request.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Made {
    Created,
    /// The same request is still waiting for lume-sleep: nothing new was made.
    AlreadyPending,
}

/// Creates the request file in `dir` (never truncates one already there). A missing folder is
/// an error: lume-sleep is not running and nobody would read the request.
pub fn request_in(dir: &Path, req: Request) -> std::io::Result<Made> {
    match std::fs::OpenOptions::new().write(true).create_new(true).open(dir.join(req.name())) {
        Ok(_) => Ok(Made::Created),
        Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => Ok(Made::AlreadyPending),
        Err(e) => Err(e),
    }
}

/// [`request_in`] the default folder.
pub fn request(req: Request) -> std::io::Result<Made> {
    request_in(&dir(), req)
}

/// What lume-sleep makes of a name that appeared in its folder.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Entry {
    Request(Request),
    /// Its own files and lume-input's (`phase`, `clients`, `status`) and hidden names (temporary
    /// files of the atomic writes, the lock): not requests, left alone.
    Own,
    /// Anything else: deleted, with `sleep FAIL refused request: <name>` (name sanitized).
    Refused(String),
}

pub const OWN_FILES: [&str; 3] = ["phase", "clients", "status"];

pub fn classify(name: &str) -> Entry {
    match name {
        "suspend" => Entry::Request(Request::Suspend),
        "poweroff" => Entry::Request(Request::Poweroff),
        n if OWN_FILES.contains(&n) || n.starts_with('.') => Entry::Own,
        n => Entry::Refused(sanitize(n)),
    }
}

/// A file name as it may go in a log line: letters, digits, `.`, `_` and `-`, others as `?`,
/// at most 32 characters.
pub fn sanitize(name: &str) -> String {
    name.chars()
        .take(32)
        .map(|c| if c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | '-') { c } else { '?' })
        .collect()
}

// ---- lume-sleep -> lume-input: <dir>/phase ----

/// The content of `<dir>/phase` (root, written by rename, one line).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Phase {
    Suspend(u32),
    Resume(u32),
}

impl Phase {
    pub fn line(&self) -> String {
        match self {
            Phase::Suspend(s) => format!("suspend {s}\n"),
            Phase::Resume(s) => format!("resume {s}\n"),
        }
    }

    pub fn parse(text: &str) -> Option<Phase> {
        match Notice::parse(text)? {
            Notice::Suspend(s) => Some(Phase::Suspend(s)),
            Notice::Resume(s) => Some(Phase::Resume(s)),
            _ => None,
        }
    }

    /// The socket message lume-input relays for this phase.
    pub fn notice(&self) -> Notice {
        match *self {
            Phase::Suspend(s) => Notice::Suspend(s),
            Phase::Resume(s) => Notice::Resume(s),
        }
    }
}

// ---- lume-input -> lume-sleep: <dir>/clients ----

/// The content of `<dir>/clients`: how the clients answered `suspend <seq>`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Clients {
    pub seq: u32,
    /// The deadline passed before every client answered.
    pub timed_out: bool,
    pub answered: u32,
    pub total: u32,
}

impl Clients {
    pub fn line(&self) -> String {
        let how = if self.timed_out { "timeout" } else { "ok" };
        format!("suspend {} {how} {}/{}\n", self.seq, self.answered, self.total)
    }

    pub fn parse(text: &str) -> Option<Clients> {
        let w: Vec<&str> = text.split_whitespace().collect();
        let [verb, seq, how, count] = w.as_slice() else { return None };
        if *verb != "suspend" {
            return None;
        }
        let seq = parse_seq(seq)?;
        let timed_out = match *how {
            "ok" => false,
            "timeout" => true,
            _ => return None,
        };
        let (a, n) = count.split_once('/')?;
        let (answered, total): (u32, u32) = (a.parse().ok()?, n.parse().ok()?);
        // "ok" means everyone answered; "timeout" means someone did not
        if answered > total || timed_out == (answered == total) {
            return None;
        }
        Some(Clients { seq, timed_out, answered, total })
    }
}

/// Client of the input socket, as lume-input knows it (its file descriptor).
pub type ClientId = i32;

/// lume-input's wait for the answers to `suspend <seq>`, with the deadline [`CLIENT_REPLY`].
/// The clients are the ones connected when the notice went out; one that disconnects is no
/// longer awaited (it cannot draw nor play any more).
#[derive(Debug, Clone)]
pub struct ReplyWait {
    seq: u32,
    deadline: Instant,
    waiting: BTreeSet<ClientId>,
    answered: u32,
    total: u32,
}

impl ReplyWait {
    pub fn new(seq: u32, clients: impl IntoIterator<Item = ClientId>, now: Instant) -> ReplyWait {
        let waiting: BTreeSet<ClientId> = clients.into_iter().collect();
        let total = waiting.len() as u32;
        ReplyWait { seq, deadline: now + CLIENT_REPLY, waiting, answered: 0, total }
    }

    /// An answer `suspend_ok <seq>` of `client`; true when it counted. Another sequence, a
    /// second answer or a client that was not asked is ignored.
    pub fn answer(&mut self, client: ClientId, seq: u32) -> bool {
        if seq != self.seq || !self.waiting.remove(&client) {
            return false;
        }
        self.answered += 1;
        true
    }

    /// The client hung up: it is not awaited nor counted any more.
    pub fn gone(&mut self, client: ClientId) {
        if self.waiting.remove(&client) {
            self.total -= 1;
        }
    }

    pub fn deadline(&self) -> Instant {
        self.deadline
    }

    /// Some(the `clients` file) once everyone answered or the deadline passed.
    pub fn outcome(&self, now: Instant) -> Option<Clients> {
        let done = self.waiting.is_empty();
        if !done && now < self.deadline {
            return None;
        }
        Some(Clients { seq: self.seq, timed_out: !done, answered: self.answered, total: self.total })
    }
}

// ---- lume-sleep: <dir>/status and the admission of a request ----

/// The depth of the suspension of a console.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    /// s2idle: `freeze` to `/sys/power/state`. GA36 (2.3, J1: 10 of 10 wakes).
    Freeze,
    /// suspend to RAM: `deep` to `/sys/power/mem_sleep`, then `mem` to `/sys/power/state`.
    /// Only with 10 of 10 wakes measured on that console.
    Mem,
}

impl Mode {
    pub fn as_str(self) -> &'static str {
        match self {
            Mode::Freeze => "freeze",
            Mode::Mem => "mem",
        }
    }

    pub fn parse(s: &str) -> Option<Mode> {
        match s {
            "freeze" => Some(Mode::Freeze),
            "mem" => Some(Mode::Mem),
            _ => None,
        }
    }

    /// What goes to `/sys/power/mem_sleep` before the suspension (None: left as it is).
    pub fn mem_sleep(self) -> Option<&'static str> {
        match self {
            Mode::Freeze => None,
            Mode::Mem => Some("deep"),
        }
    }

    /// What goes to `/sys/power/state`.
    pub fn state(self) -> &'static str {
        self.as_str()
    }
}

/// The default of a console without a measured mode (the R36S until its J1, the VM).
pub const DEFAULT_MODE: Mode = Mode::Freeze;

/// The folder of the per-console files `<board>.conf` (package lume-power).
pub fn mode_dir() -> PathBuf {
    std::env::var_os("LUME_SLEEP_CONF").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("/usr/share/lume/sleep"))
}

/// Reads `<board>.conf`: `#` comments, blank lines and the line `mode freeze|mem`. The last
/// valid `mode` line wins; no file, no line or a bad value gives [`DEFAULT_MODE`].
pub fn parse_mode_conf(text: &str) -> Mode {
    let mut mode = DEFAULT_MODE;
    for line in text.lines() {
        let line = line.split('#').next().unwrap_or("").trim();
        let mut w = line.split_whitespace();
        if let (Some("mode"), Some(v), None) = (w.next(), w.next(), w.next()) {
            if let Some(m) = Mode::parse(v) {
                mode = m;
            }
        }
    }
    mode
}

/// The mode of the console `board` (`/etc/lume/board`: ga36, r36s, vm).
pub fn mode_of(board: &str) -> Mode {
    std::fs::read_to_string(mode_dir().join(format!("{board}.conf"))).map(|t| parse_mode_conf(&t)).unwrap_or(DEFAULT_MODE)
}

/// The content of `<dir>/status` (root, by rename): where lume-sleep is.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Status {
    Awake,
    /// Steps 1 to 4 (clients, sound and clock, sync and light, governor, USB).
    Suspending(u32),
    /// The write to `/sys/power/state` is under way (the console sleeps in it).
    Suspended(u32, Mode),
    /// The steps backwards, up to `phase resume`.
    Resuming(u32),
    /// The session is shutting down: nothing else runs.
    Poweroff,
}

impl Status {
    pub fn line(&self) -> String {
        match self {
            Status::Awake => "awake\n".into(),
            Status::Suspending(s) => format!("suspending {s}\n"),
            Status::Suspended(s, m) => format!("suspended {s} {}\n", m.as_str()),
            Status::Resuming(s) => format!("resuming {s}\n"),
            Status::Poweroff => "poweroff\n".into(),
        }
    }

    pub fn parse(text: &str) -> Option<Status> {
        let w: Vec<&str> = text.split_whitespace().collect();
        Some(match w.as_slice() {
            ["awake"] => Status::Awake,
            ["suspending", s] => Status::Suspending(parse_seq(s)?),
            ["suspended", s, m] => Status::Suspended(parse_seq(s)?, Mode::parse(m)?),
            ["resuming", s] => Status::Resuming(parse_seq(s)?),
            ["poweroff"] => Status::Poweroff,
            _ => return None,
        })
    }
}

/// What lume-sleep does with a request (the file is deleted in every case).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Verdict {
    Run,
    /// A sequence or the shutdown is under way: the second request is dropped without running
    /// (kernel log only, no event).
    Busy,
    /// A `suspend` within [`WAKE_GUARD`] of the wake: the press that woke the console.
    WakePress,
}

/// The admission of a request. `since_awake` is the time since the status went back to
/// `awake` (None: never suspended in this boot).
pub fn admit(req: Request, status: Status, since_awake: Option<Duration>) -> Verdict {
    match (req, status) {
        (_, Status::Poweroff) => Verdict::Busy,
        (Request::Poweroff, _) => Verdict::Run,
        (Request::Suspend, Status::Awake) => match since_awake {
            Some(t) if t < WAKE_GUARD => Verdict::WakePress,
            _ => Verdict::Run,
        },
        (Request::Suspend, _) => Verdict::Busy,
    }
}

// ---- events.log: category `sleep` ----

/// A step of the sequence, as named in `sleep FAIL <step>: <reason>`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Step {
    Clients,
    Audio,
    Clock,
    Sync,
    Backlight,
    Wifi,
    Governor,
    Usb,
}

impl Step {
    pub const ALL: [Step; 8] =
        [Step::Clients, Step::Audio, Step::Clock, Step::Sync, Step::Backlight, Step::Wifi, Step::Governor, Step::Usb];

    pub fn as_str(self) -> &'static str {
        match self {
            Step::Clients => "clients",
            Step::Audio => "audio",
            Step::Clock => "clock",
            Step::Sync => "sync",
            Step::Backlight => "backlight",
            Step::Wifi => "wifi",
            Step::Governor => "governor",
            Step::Usb => "usb",
        }
    }

    pub fn parse(s: &str) -> Option<Step> {
        Step::ALL.into_iter().find(|x| x.as_str() == s)
    }
}

/// One line of the category `sleep` (the `<OK|FAIL> <detail>` part).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Event {
    /// `OK suspend <mode>`: just before the write to `/sys/power/state`.
    Suspend(Mode),
    /// `OK resume after <s>`: whole seconds asleep, by `/proc/uptime` (it counts the time
    /// suspended).
    Resume(u64),
    /// `FAIL suspend <mode>: <reason>`: the kernel refused; the steps went back and the screen
    /// is on again.
    SuspendFailed(Mode, String),
    /// `FAIL <step>: <reason>`: one step failed and the sequence went on.
    StepFailed(Step, String),
    /// `OK poweroff: power button held`.
    Poweroff,
    /// `FAIL refused request: <name>`.
    Refused(String),
}

impl Event {
    pub fn ok(&self) -> bool {
        matches!(self, Event::Suspend(_) | Event::Resume(_) | Event::Poweroff)
    }

    pub fn detail(&self) -> String {
        match self {
            Event::Suspend(m) => format!("suspend {}", m.as_str()),
            Event::Resume(s) => format!("resume after {s}"),
            Event::SuspendFailed(m, why) => format!("suspend {}: {}", m.as_str(), one_line(why)),
            Event::StepFailed(step, why) => format!("{}: {}", step.as_str(), one_line(why)),
            Event::Poweroff => "poweroff: power button held".into(),
            Event::Refused(name) => format!("refused request: {}", sanitize(name)),
        }
    }

    /// The `<OK|FAIL> <detail>` part of an events.log line of the category `sleep`.
    pub fn parse(status: &str, detail: &str) -> Option<Event> {
        let ok = match status {
            "OK" => true,
            "FAIL" => false,
            _ => return None,
        };
        let ev = if let Some(m) = detail.strip_prefix("suspend ") {
            match m.split_once(": ") {
                Some((m, why)) => Event::SuspendFailed(Mode::parse(m)?, why.into()),
                None => Event::Suspend(Mode::parse(m)?),
            }
        } else if let Some(s) = detail.strip_prefix("resume after ") {
            Event::Resume(s.parse().ok()?)
        } else if detail == "poweroff: power button held" {
            Event::Poweroff
        } else if let Some(n) = detail.strip_prefix("refused request: ") {
            Event::Refused(n.into())
        } else {
            let (step, why) = detail.split_once(": ")?;
            Event::StepFailed(Step::parse(step)?, why.into())
        };
        (ev.ok() == ok).then_some(ev)
    }
}

fn one_line(s: &str) -> String {
    s.split_whitespace().collect::<Vec<_>>().join(" ")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_notice_round_trips() {
        for n in [Notice::PowerTap, Notice::PowerHold, Notice::Suspend(1), Notice::Resume(42), Notice::Suspend(u32::MAX)] {
            assert_eq!(Notice::parse(&n.line()), Some(n), "{n:?}");
        }
        assert_eq!(Notice::PowerTap.line(), "power_tap");
        assert_eq!(Notice::PowerHold.line(), "power_hold");
        assert_eq!(Notice::Suspend(7).line(), "suspend 7");
        assert_eq!(Notice::Resume(7).line(), "resume 7");
        assert_eq!(Notice::parse("suspend 3\n"), Some(Notice::Suspend(3)));
    }

    #[test]
    fn broken_notices_are_not_sleep_messages() {
        for m in ["", "suspend", "resume", "suspend 0", "suspend -1", "suspend x", "suspend 1 2", "resume +3",
            "power_tap 1", "power_hold now", "POWER_TAP", "suspend 99999999999"] {
            assert_eq!(Notice::parse(m), None, "{m:?}");
        }
    }

    #[test]
    fn the_client_answer_carries_the_sequence() {
        assert_eq!(suspend_ok(5), "suspend_ok 5");
        assert_eq!(parse_suspend_ok(&suspend_ok(5)), Some(5));
        for m in ["suspend_ok", "suspend_ok 0", "suspend_ok x", "suspend 5", "resume_ok 5"] {
            assert_eq!(parse_suspend_ok(m), None, "{m:?}");
        }
    }

    #[test]
    fn phase_clients_and_status_round_trip() {
        for p in [Phase::Suspend(1), Phase::Resume(9)] {
            assert_eq!(Phase::parse(&p.line()), Some(p));
        }
        assert_eq!(Phase::Suspend(2).notice(), Notice::Suspend(2));
        assert_eq!(Phase::parse("power_tap"), None);

        let c = Clients { seq: 4, timed_out: false, answered: 1, total: 1 };
        assert_eq!(c.line(), "suspend 4 ok 1/1\n");
        assert_eq!(Clients::parse(&c.line()), Some(c));
        let c = Clients { seq: 4, timed_out: true, answered: 0, total: 1 };
        assert_eq!(c.line(), "suspend 4 timeout 0/1\n");
        assert_eq!(Clients::parse(&c.line()), Some(c));
        assert_eq!(Clients::parse("suspend 4 ok 0/0"), Some(Clients { seq: 4, timed_out: false, answered: 0, total: 0 }));
        for bad in ["suspend 4 ok 0/1", "suspend 4 timeout 1/1", "suspend 4 ok 2/1", "resume 4 ok 1/1", "suspend 0 ok 1/1", "suspend 4 ok"] {
            assert_eq!(Clients::parse(bad), None, "{bad:?}");
        }

        for s in [Status::Awake, Status::Suspending(3), Status::Suspended(3, Mode::Freeze), Status::Suspended(3, Mode::Mem),
            Status::Resuming(3), Status::Poweroff] {
            assert_eq!(Status::parse(&s.line()), Some(s), "{s:?}");
        }
        for bad in ["", "asleep", "suspended 3", "suspended 3 deep", "suspending"] {
            assert_eq!(Status::parse(bad), None, "{bad:?}");
        }
    }

    #[test]
    fn every_client_answering_ends_the_wait_before_the_deadline() {
        let t0 = Instant::now();
        let mut w = ReplyWait::new(3, [10, 11], t0);
        assert_eq!(w.outcome(t0), None);
        assert!(w.answer(10, 3));
        assert_eq!(w.outcome(t0), None);
        assert!(w.answer(11, 3));
        assert_eq!(w.outcome(t0), Some(Clients { seq: 3, timed_out: false, answered: 2, total: 2 }));
    }

    #[test]
    fn a_mute_client_does_not_hold_the_suspension_past_the_deadline() {
        let t0 = Instant::now();
        let mut w = ReplyWait::new(3, [10, 11], t0);
        assert!(w.answer(10, 3));
        assert_eq!(w.deadline(), t0 + CLIENT_REPLY);
        assert_eq!(w.outcome(t0 + CLIENT_REPLY - Duration::from_millis(1)), None);
        let out = w.outcome(t0 + CLIENT_REPLY).unwrap();
        assert_eq!(out, Clients { seq: 3, timed_out: true, answered: 1, total: 2 });
        assert_eq!(out.line(), "suspend 3 timeout 1/2\n");
    }

    #[test]
    fn stale_duplicate_and_unknown_answers_do_not_count() {
        let t0 = Instant::now();
        let mut w = ReplyWait::new(5, [10, 11], t0);
        assert!(!w.answer(10, 4), "an answer to an older sequence");
        assert!(w.answer(10, 5));
        assert!(!w.answer(10, 5), "the same client twice");
        assert!(!w.answer(99, 5), "a client that was not asked");
        assert_eq!(w.outcome(t0), None);
    }

    #[test]
    fn no_client_or_a_client_that_hangs_up_is_not_awaited() {
        let t0 = Instant::now();
        assert_eq!(ReplyWait::new(1, [], t0).outcome(t0), Some(Clients { seq: 1, timed_out: false, answered: 0, total: 0 }));
        let mut w = ReplyWait::new(2, [10, 11], t0);
        assert!(w.answer(10, 2));
        w.gone(11);
        w.gone(11);
        assert_eq!(w.outcome(t0), Some(Clients { seq: 2, timed_out: false, answered: 1, total: 1 }));
    }

    fn tmpdir(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("lume-sleep-test-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    #[test]
    fn a_request_made_twice_is_one_file() {
        let d = tmpdir("twice");
        assert_eq!(request_in(&d, Request::Suspend).unwrap(), Made::Created);
        assert_eq!(request_in(&d, Request::Suspend).unwrap(), Made::AlreadyPending);
        assert!(d.join("suspend").is_file());
        assert_eq!(request_in(&d, Request::Poweroff).unwrap(), Made::Created);
        let mut names: Vec<String> =
            std::fs::read_dir(&d).unwrap().map(|e| e.unwrap().file_name().to_string_lossy().into_owned()).collect();
        names.sort();
        assert_eq!(names, ["poweroff", "suspend"]);
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn a_request_without_the_service_is_an_error() {
        let d = tmpdir("noservice").join("absent");
        assert!(request_in(&d, Request::Suspend).is_err());
    }

    #[test]
    fn a_second_request_during_a_sequence_is_dropped() {
        for s in [Status::Suspending(1), Status::Suspended(1, Mode::Freeze), Status::Resuming(1)] {
            assert_eq!(admit(Request::Suspend, s, None), Verdict::Busy, "{s:?}");
        }
        assert_eq!(admit(Request::Suspend, Status::Poweroff, None), Verdict::Busy);
        assert_eq!(admit(Request::Poweroff, Status::Poweroff, None), Verdict::Busy);
        assert_eq!(admit(Request::Suspend, Status::Awake, None), Verdict::Run);
        assert_eq!(admit(Request::Poweroff, Status::Awake, None), Verdict::Run);
    }

    #[test]
    fn the_press_that_woke_the_console_does_not_suspend_it_again() {
        let just = Some(WAKE_GUARD - Duration::from_millis(1));
        assert_eq!(admit(Request::Suspend, Status::Awake, just), Verdict::WakePress);
        assert_eq!(admit(Request::Suspend, Status::Awake, Some(WAKE_GUARD)), Verdict::Run);
        // holding to power off right after the wake still works
        assert_eq!(admit(Request::Poweroff, Status::Awake, just), Verdict::Run);
    }

    #[test]
    fn names_in_the_folder() {
        assert_eq!(classify("suspend"), Entry::Request(Request::Suspend));
        assert_eq!(classify("poweroff"), Entry::Request(Request::Poweroff));
        for own in ["phase", "clients", "status", ".lock", ".phase.tmp"] {
            assert_eq!(classify(own), Entry::Own, "{own}");
        }
        assert_eq!(classify("reboot"), Entry::Refused("reboot".into()));
        assert_eq!(classify("a b\n$(x)"), Entry::Refused("a?b???x?".into()));
        assert_eq!(sanitize(&"x".repeat(40)).len(), 32);
        for r in [Request::Suspend, Request::Poweroff] {
            assert_eq!(classify(r.name()), Entry::Request(r));
        }
    }

    #[test]
    fn the_mode_of_each_console() {
        assert_eq!(parse_mode_conf("# GA36\nmode freeze\n"), Mode::Freeze);
        assert_eq!(parse_mode_conf("mode mem # measured 10/10\n"), Mode::Mem);
        assert_eq!(parse_mode_conf(""), DEFAULT_MODE);
        assert_eq!(parse_mode_conf("mode deep\nmode\nmode mem extra\n"), DEFAULT_MODE);
        assert_eq!(parse_mode_conf("mode mem\nmode bogus\n"), Mode::Mem);
        assert_eq!(Mode::Freeze.state(), "freeze");
        assert_eq!(Mode::Freeze.mem_sleep(), None);
        assert_eq!(Mode::Mem.state(), "mem");
        assert_eq!(Mode::Mem.mem_sleep(), Some("deep"));
    }

    #[test]
    fn the_image_files_give_freeze_on_both_consoles() {
        let share = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../aports/lume-power/files/usr/share/lume/sleep");
        for board in ["ga36", "r36s"] {
            let text = std::fs::read_to_string(share.join(format!("{board}.conf"))).unwrap();
            assert_eq!(parse_mode_conf(&text), Mode::Freeze, "{board}");
        }
    }

    #[test]
    fn every_event_round_trips() {
        let evs = [
            Event::Suspend(Mode::Freeze),
            Event::Suspend(Mode::Mem),
            Event::Resume(600),
            Event::SuspendFailed(Mode::Freeze, "write /sys/power/state failed (Device or resource busy)".into()),
            Event::StepFailed(Step::Usb, "UDC not rebound".into()),
            Event::StepFailed(Step::Clients, "0/1 answered within 2s".into()),
            Event::Poweroff,
            Event::Refused("reboot".into()),
        ];
        for e in evs {
            let status = if e.ok() { "OK" } else { "FAIL" };
            assert_eq!(Event::parse(status, &e.detail()), Some(e.clone()), "{e:?}");
        }
        assert_eq!(Event::Suspend(Mode::Freeze).detail(), "suspend freeze");
        assert_eq!(Event::Resume(600).detail(), "resume after 600");
        assert_eq!(Event::StepFailed(Step::Sync, "a\nb".into()).detail(), "sync: a b");
        assert_eq!(Event::parse("FAIL", "suspend freeze"), None);
        assert_eq!(Event::parse("OK", "usb: x"), None);
        assert_eq!(Event::parse("FAIL", "disk: x"), None);
    }
}
