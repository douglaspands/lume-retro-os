//! Index watcher (lume-launcher D4): inotify on cache/index/ for the GEN file that
//! lume-index rewrites (temporary + rename) after a scan; `changed` runs on each new
//! generation. The folder may not exist yet on a new card: then it waits for it.

use std::path::Path;

pub fn gen(dir: &Path, mut changed: impl FnMut()) {
    loop {
        if !dir.exists() {
            std::thread::sleep(std::time::Duration::from_secs(5));
            continue;
        }
        let fd = unsafe { libc::inotify_init1(libc::IN_CLOEXEC) };
        if fd < 0 {
            return;
        }
        let c = std::ffi::CString::new(dir.as_os_str().as_encoded_bytes()).unwrap();
        if unsafe { libc::inotify_add_watch(fd, c.as_ptr(), libc::IN_MOVED_TO | libc::IN_CLOSE_WRITE | libc::IN_DELETE_SELF) } < 0 {
            unsafe { libc::close(fd) };
            return;
        }
        let mut buf = [0u8; 4096];
        loop {
            let n = unsafe { libc::read(fd, buf.as_mut_ptr().cast(), buf.len()) };
            if n <= 0 {
                break;
            }
            let mut at = 0usize;
            let mut gone = false;
            while at + 16 <= n as usize {
                let mask = u32::from_ne_bytes(buf[at + 4..at + 8].try_into().unwrap());
                let len = u32::from_ne_bytes(buf[at + 12..at + 16].try_into().unwrap()) as usize;
                let name = &buf[at + 16..at + 16 + len];
                let name = name.split(|b| *b == 0).next().unwrap_or(&[]);
                if mask & libc::IN_DELETE_SELF != 0 {
                    gone = true;
                } else if name == b"GEN" {
                    changed();
                }
                at += 16 + len;
            }
            if gone {
                break;
            }
        }
        unsafe { libc::close(fd) };
    }
}
