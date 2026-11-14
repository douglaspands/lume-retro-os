//! Atomic file writes on the ROMS card (lume-launcher D4, D6): a temporary file in the same
//! folder, fsync, rename over the old one and fsync of the folder. A power cut leaves the old
//! file or the new one whole, never a partial file.

use std::fs::{self, File, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};

fn tmp_path(path: &Path) -> PathBuf {
    let name = path.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
    path.with_file_name(format!(".{name}.tmp{}", std::process::id()))
}

/// Writes `data` to `path` atomically, creating the parent folder if needed.
pub fn write(path: &Path, data: &[u8]) -> io::Result<()> {
    let dir = path.parent().filter(|d| !d.as_os_str().is_empty()).unwrap_or(Path::new("."));
    fs::create_dir_all(dir)?;
    let tmp = tmp_path(path);
    let result = (|| {
        let mut f = OpenOptions::new().write(true).create(true).truncate(true).open(&tmp)?;
        f.write_all(data)?;
        f.sync_all()?;
        drop(f);
        fs::rename(&tmp, path)?;
        // exFAT and vfat accept fsync on a folder; a filesystem that refuses it still has
        // the rename, so the error is not fatal
        if let Ok(d) = File::open(dir) {
            let _ = d.sync_all();
        }
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&tmp);
    }
    result
}

/// Removes `path` if it exists, with fsync of the folder.
pub fn remove(path: &Path) -> io::Result<()> {
    match fs::remove_file(path) {
        Ok(()) => {
            if let Some(d) = path.parent().and_then(|d| File::open(d).ok()) {
                let _ = d.sync_all();
            }
            Ok(())
        }
        Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(e) => Err(e),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    fn tmpdir(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("lume-atomic-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&d);
        fs::create_dir_all(&d).unwrap();
        d
    }

    #[test]
    fn write_replaces_whole_file() {
        let d = tmpdir("replace");
        let p = d.join("sub/a.toml");
        write(&p, b"old").unwrap();
        write(&p, b"new contents").unwrap();
        assert_eq!(fs::read(&p).unwrap(), b"new contents");
        // no temporary left behind
        assert_eq!(fs::read_dir(d.join("sub")).unwrap().count(), 1);
    }

    #[test]
    fn interrupted_write_keeps_old_file() {
        // the rename cannot happen (folder made read-only after the first write): the old
        // file stays whole and the temporary is cleaned up
        let d = tmpdir("interrupted");
        let p = d.join("a.toml");
        write(&p, b"old").unwrap();
        fs::set_permissions(&d, fs::Permissions::from_mode(0o555)).unwrap();
        let r = write(&p, b"new");
        fs::set_permissions(&d, fs::Permissions::from_mode(0o755)).unwrap();
        if unsafe { libc::geteuid() } != 0 {
            assert!(r.is_err());
        }
        if r.is_err() {
            assert_eq!(fs::read(&p).unwrap(), b"old");
        }
        assert_eq!(fs::read_dir(&d).unwrap().count(), 1);
    }

    #[test]
    fn remove_missing_is_ok() {
        let d = tmpdir("remove");
        remove(&d.join("nope")).unwrap();
    }
}
