//! The environment of a game (game-experience-tuning D5), built in the parent before the
//! spawn: lume-run's own environment without `LANG`, `LANGUAGE`, `LC_*` and `TZ`, then
//! - `LANG` and `LANGUAGE` of the launcher's language (`settings.toml`, read for every game);
//! - `TZ=:<zoneinfo>/<zone of /etc/timezone>`, as lume-logd does, only when the zone file
//!   exists;
//! - the runner's variables (`env=` lines of the launch file), last: they win over the above.
//!
//! `LC_ALL` is never added: musl without musl-locales keeps English messages and the `.`
//! decimal point, so logs and scripts that read command output do not change.
//!
//! Paths (defaults in parentheses): the settings file is `ROMS/system/lume/settings.toml`
//! under LUME_STORAGE (/storage); TIMEZONE_FILE (/etc/timezone) and ZONEINFO_DIR
//! (/usr/share/zoneinfo), the same variables as lume-logd.

use std::ffi::OsString;
use std::os::unix::ffi::OsStringExt;
use std::path::{Path, PathBuf};

/// One variable as raw bytes (the inherited environment need not be UTF-8).
pub type Var = (Vec<u8>, Vec<u8>);

/// `LANG` and `LANGUAGE` of a launcher language; unknown or missing is English.
pub fn locale(lang: &str) -> (&'static str, &'static str) {
    match lang {
        "pt" => ("pt_BR.UTF-8", "pt_BR:pt"),
        "es" => ("es_ES.UTF-8", "es_ES:es"),
        _ => ("en_US.UTF-8", "en_US:en"),
    }
}

/// `TZ` for the zone named in `tz_file` (first line), when it is a zone name and its file
/// exists under `zoneinfo`; the same rules as lume-logd's tz_follow.
pub fn zone_tz(tz_file: &Path, zoneinfo: &Path) -> Option<String> {
    let text = std::fs::read_to_string(tz_file).ok()?;
    let zone = text.lines().next()?.trim();
    if zone.is_empty() || zone.contains("..") || !zone.chars().all(|c| c.is_ascii_alphanumeric() || "/_+-".contains(c)) {
        return None;
    }
    let file = zoneinfo.join(zone);
    file.is_file().then(|| format!(":{}", file.display()))
}

/// Inherited variables the game environment drops (replaced by the system's own values).
fn dropped(name: &[u8]) -> bool {
    name == b"LANG" || name == b"LANGUAGE" || name == b"TZ" || name.starts_with(b"LC_")
}

fn set(env: &mut Vec<Var>, name: &[u8], value: &[u8]) {
    match env.iter_mut().find(|(n, _)| n == name) {
        Some(v) => v.1 = value.to_vec(),
        None => env.push((name.to_vec(), value.to_vec())),
    }
}

/// The game environment from its parts (pure: the tests feed it directly).
pub fn build(inherited: impl IntoIterator<Item = (OsString, OsString)>, lang: &str, tz: Option<&str>, runner: &[(String, String)]) -> Vec<Var> {
    let mut env: Vec<Var> = Vec::new();
    for (k, v) in inherited {
        let (k, v) = (k.into_vec(), v.into_vec());
        if !dropped(&k) {
            set(&mut env, &k, &v);
        }
    }
    let (l, language) = locale(lang);
    set(&mut env, b"LANG", l.as_bytes());
    set(&mut env, b"LANGUAGE", language.as_bytes());
    if let Some(tz) = tz {
        set(&mut env, b"TZ", tz.as_bytes());
    }
    for (k, v) in runner {
        set(&mut env, k.as_bytes(), v.as_bytes());
    }
    env
}

fn env_path(var: &str, default: &str) -> PathBuf {
    std::env::var_os(var).map(PathBuf::from).unwrap_or_else(|| PathBuf::from(default))
}

/// The environment of the next game: the language and the zone read now (a change made in
/// the interface counts from the next game on).
pub fn for_game(runner: &[(String, String)]) -> Vec<Var> {
    let lang = lume_core::gametext::language(&lume_core::paths::card());
    let tz = zone_tz(&env_path("TIMEZONE_FILE", "/etc/timezone"), &env_path("ZONEINFO_DIR", "/usr/share/zoneinfo"));
    build(std::env::vars_os(), &lang, tz.as_deref(), runner)
}

/// The value of `name` in a built environment.
pub fn get<'a>(env: &'a [Var], name: &str) -> Option<&'a [u8]> {
    env.iter().find(|(n, _)| n == name.as_bytes()).map(|(_, v)| v.as_slice())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn os(pairs: &[(&str, &str)]) -> Vec<(OsString, OsString)> {
        pairs.iter().map(|(k, v)| (OsString::from(k), OsString::from(v))).collect()
    }

    fn text(env: &[Var], name: &str) -> Option<String> {
        get(env, name).map(|v| String::from_utf8_lossy(v).into_owned())
    }

    #[test]
    fn languages_map_to_locales() {
        assert_eq!(locale("en"), ("en_US.UTF-8", "en_US:en"));
        assert_eq!(locale("pt"), ("pt_BR.UTF-8", "pt_BR:pt"));
        assert_eq!(locale("es"), ("es_ES.UTF-8", "es_ES:es"));
        assert_eq!(locale(""), locale("en"));
        assert_eq!(locale("xx"), locale("en"));
    }

    #[test]
    fn inherited_locale_and_zone_are_replaced_and_the_runner_wins() {
        let inh = os(&[("PATH", "/bin"), ("LANG", "C"), ("LANGUAGE", "fr"), ("LC_ALL", "C"), ("LC_CTYPE", "C.UTF-8"),
                       ("TZ", "UTC0"), ("LCX", "kept"), ("SDL_X", "old")]);
        let runner = [("SDL_X".to_string(), "new".to_string()), ("LANG".to_string(), "C.UTF-8".to_string())];
        let env = build(inh.clone(), "pt", Some(":/z/America/Sao_Paulo"), &runner);
        assert_eq!(text(&env, "PATH").as_deref(), Some("/bin"));
        assert_eq!(text(&env, "LCX").as_deref(), Some("kept"));
        assert_eq!(text(&env, "LANGUAGE").as_deref(), Some("pt_BR:pt"));
        assert_eq!(text(&env, "TZ").as_deref(), Some(":/z/America/Sao_Paulo"));
        assert_eq!(text(&env, "LC_ALL"), None);
        assert_eq!(text(&env, "LC_CTYPE"), None);
        // the runner's variables come last and win, with no duplicates
        assert_eq!(text(&env, "SDL_X").as_deref(), Some("new"));
        assert_eq!(text(&env, "LANG").as_deref(), Some("C.UTF-8"));
        assert_eq!(env.iter().filter(|(n, _)| n == b"LANG").count(), 1);
        // no zone: the inherited TZ is gone all the same
        let env = build(inh, "es", None, &[]);
        assert_eq!(text(&env, "TZ"), None);
        assert_eq!(text(&env, "LANG").as_deref(), Some("es_ES.UTF-8"));
    }

    #[test]
    fn zone_follows_lume_logd_rules() {
        let dir = std::env::temp_dir().join(format!("lume-run-gameenv-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(dir.join("zoneinfo/Test")).unwrap();
        std::fs::write(dir.join("zoneinfo/Test/Plus3"), "").unwrap();
        let (tzf, zi) = (dir.join("timezone"), dir.join("zoneinfo"));
        assert_eq!(zone_tz(&tzf, &zi), None);
        std::fs::write(&tzf, "Test/Plus3\n").unwrap();
        assert_eq!(zone_tz(&tzf, &zi), Some(format!(":{}/Test/Plus3", zi.display())));
        for bad in ["../../etc/passwd\n", "Test/None\n", "Test/Plus3;x\n", "\n", "Test\n"] {
            std::fs::write(&tzf, bad).unwrap();
            assert_eq!(zone_tz(&tzf, &zi), None, "{bad:?}");
        }
        let _ = std::fs::remove_dir_all(&dir);
    }
}
