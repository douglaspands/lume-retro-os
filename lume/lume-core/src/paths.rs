//! Fixed paths of the image and of the ROMS card (lume-launcher D4-D6, docs/CATALOG.md).
//! Every path can be moved with an environment variable so tests and the VM can point the
//! programs at a fixture tree.

use std::path::PathBuf;

fn env_or(var: &str, default: &str) -> PathBuf {
    std::env::var_os(var).map(PathBuf::from).unwrap_or_else(|| PathBuf::from(default))
}

/// ROMS partition (`/storage`).
pub fn storage() -> PathBuf {
    env_or("LUME_STORAGE", "/storage")
}

/// Image data (`/usr/share/lume`): runners.d, themes, fonts, texts.
pub fn share() -> PathBuf {
    env_or("LUME_SHARE", "/usr/share/lume")
}

/// System catalog.
pub fn catalog() -> PathBuf {
    env_or("LUME_CATALOG", "/usr/share/lume/systems.json")
}

/// Folder of the libretro cores.
pub fn cores_dir() -> PathBuf {
    env_or("LUME_CORES", "/usr/lib/libretro")
}

/// Runtime folder of the launcher (`$XDG_RUNTIME_DIR/lume`): launch and state files.
pub fn runtime() -> PathBuf {
    match std::env::var_os("XDG_RUNTIME_DIR") {
        Some(d) => PathBuf::from(d).join("lume"),
        None => PathBuf::from("/tmp/lume"),
    }
}

/// Launcher folder on the card (`ROMS/system/lume`).
pub fn card() -> PathBuf {
    storage().join("system/lume")
}

pub fn roms() -> PathBuf {
    storage().join("roms")
}

/// Machine architecture as the catalog names it (`x86_64`, `aarch64`, `armv7`).
pub fn arch() -> String {
    if let Some(a) = std::env::var_os("LUME_ARCH") {
        return a.to_string_lossy().into_owned();
    }
    match std::env::consts::ARCH {
        "arm" => "armv7".into(),
        other => other.into(),
    }
}
