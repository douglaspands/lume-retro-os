//! The lume-index command as the service and lume-run call it (tasks 5.5 and 6.4).

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

fn repo() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn card(name: &str) -> PathBuf {
    let root = std::env::temp_dir().join(format!("lume-cli-{name}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(root.join("storage/roms/nes")).unwrap();
    fs::create_dir_all(root.join("run/logs")).unwrap();
    fs::write(root.join("run/logs/boot-n"), "7\n").unwrap();
    fs::write(root.join("storage/roms/nes/Very Secret Title.nes"), b"x").unwrap();
    root
}

fn index(root: &Path, args: &[&str]) -> std::process::Output {
    Command::new(env!("CARGO_BIN_EXE_lume-index"))
        .args(args)
        .env("LUME_STORAGE", root.join("storage"))
        .env("LUME_CATALOG", repo().join("aports/lume-games/files/usr/share/r36os/systems.json"))
        .env("LUME_SHARE", repo().join("aports/lume-games/files/usr/share/lume"))
        .env("R36OS_RUN", root.join("run"))
        .output()
        .unwrap()
}

#[test]
fn scan_event_has_counts_and_no_names() {
    let root = card("event");
    let out = index(&root, &["nes", "snes"]);
    assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
    let ev = fs::read_to_string(root.join("run/logs/events.pending")).unwrap();
    let line = ev.lines().next().unwrap();
    let f: Vec<&str> = line.splitn(5, ' ').collect();
    assert_eq!(&f[1..4], ["7", "index", "OK"]);
    assert!(f[4].starts_with("scan systems=2 games=1 added=1 failed=0 ms="), "{line}");
    assert!(f[4].ends_with(" nes=1"), "{line}");
    assert!(!ev.contains("Secret"));
}

#[test]
fn touch_records_state_slots_and_usage_errors() {
    let root = card("touch");
    assert!(index(&root, &[]).status.success());
    let out = index(&root, &["--touch", "nes", "./Very Secret Title.nes", "--core", "fceumm", "--slots", "1,auto"]);
    assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
    let reg = fs::read_to_string(root.join("storage/system/lume/states/nes.toml")).unwrap();
    assert!(reg.contains("[\"Very Secret Title.nes\"]"), "{reg}");
    assert!(reg.contains("1 = \"fceumm\"") || reg.contains("\"1\" = \"fceumm\""), "{reg}");
    let gl = fs::read_to_string(root.join("storage/roms/nes/gamelist.xml")).unwrap();
    assert!(gl.contains("<playcount>1</playcount>"));
    assert_eq!(index(&root, &["--touch", "nes"]).status.code(), Some(2));
    assert_eq!(index(&root, &["--favorite", "nes", "x", "maybe"]).status.code(), Some(2));
    assert_eq!(index(&root, &["--tile", "bad"]).status.code(), Some(2));
}
