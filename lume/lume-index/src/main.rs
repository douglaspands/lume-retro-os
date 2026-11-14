//! lume-index command line (lume-launcher D4):
//!
//! ```text
//! lume-index [--tile WxH] [--force] [--progress] [SYSTEM...]   scan (all systems by default)
//! lume-index --touch SYSTEM PATH [--core CORE --slots 1,auto]  after a game
//! lume-index --favorite SYSTEM PATH on|off
//! ```
//!
//! Paths come from LUME_STORAGE, LUME_CATALOG and LUME_SHARE (lume_core::paths). The scan
//! ends with one line on stderr and in events.log (category `index`) with the number of
//! games per system, never a game name:
//! `index OK scan systems=16 games=52 added=2 failed=0 ms=410 nes=40 snes=12`.

use std::process::ExitCode;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use lume_core::log;
use lume_index::{thumbs::Tile, Ctx, DEFAULT_TILE, PROG};

fn usage() -> ExitCode {
    eprintln!("usage: lume-index [--tile WxH] [--force] [--progress] [SYSTEM...]");
    eprintln!("       lume-index --touch SYSTEM PATH [--core CORE --slots SLOT,...]");
    eprintln!("       lume-index --favorite SYSTEM PATH on|off");
    ExitCode::from(2)
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let loaded = match lume_core::catalog::load_all(PROG, false) {
        Ok(l) => l,
        Err(e) => {
            log::line(PROG, &format!("catalog not loaded: {e}"));
            return ExitCode::FAILURE;
        }
    };
    let mut ctx = Ctx { storage: lume_core::paths::storage(), catalog: loaded.catalog, tile: DEFAULT_TILE };

    match args.first().map(String::as_str) {
        Some("--touch") if args.len() == 3 || (args.len() == 7 && args[3] == "--core" && args[5] == "--slots") => {
            let now = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
            if args.len() == 7 {
                // the save state slots this game changed, with the core that wrote them
                let key = lume_index::gamelist::normalize(&args[2], &ctx.roms().join(&args[1]));
                let slots: Vec<&str> = args[6].split(',').filter(|s| !s.is_empty()).collect();
                if let Err(e) = lume_core::states::record(&ctx.card(), &args[1], &key, &args[4], &slots) {
                    log::line(PROG, &format!("state slots not recorded: {e}"));
                }
            }
            return report(lume_index::touch(&ctx, &args[1], &args[2], now));
        }
        Some("--favorite") if args.len() == 4 => {
            let on = match args[3].as_str() {
                "on" => true,
                "off" => false,
                _ => return usage(),
            };
            return report(lume_index::set_favorite(&ctx, &args[1], &args[2], on));
        }
        Some("--touch" | "--favorite") => return usage(),
        _ => {}
    }

    let (mut force, mut progress, mut ids) = (false, false, Vec::new());
    let mut it = args.into_iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "--force" => force = true,
            "--progress" => progress = true,
            "--tile" => match it.next().as_deref().and_then(Tile::parse) {
                Some(t) => ctx.tile = t,
                None => return usage(),
            },
            s if s.starts_with('-') => return usage(),
            _ => ids.push(a),
        }
    }
    let start = Instant::now();
    let results = lume_index::update_all(&ctx, &ids, force, |i, n, id| {
        if progress {
            println!("progress {i} {n} {id}");
        }
    });
    let mut counts = Vec::new();
    let (mut total, mut added, mut failed) = (0, 0, 0);
    for (id, r) in &results {
        match r {
            Ok(r) => {
                total += r.games;
                added += r.added;
                if r.games > 0 {
                    counts.push(format!("{id}={}", r.games));
                }
            }
            Err(e) => {
                failed += 1;
                log::line(PROG, &format!("{id}: {e}"));
            }
        }
    }
    let summary = format!(
        "scan systems={} games={total} added={added} failed={failed} ms={} {}",
        results.len(),
        start.elapsed().as_millis(),
        counts.join(" ")
    );
    let summary = summary.trim_end();
    log::line(PROG, summary);
    // events.log: games per system only, never a name
    lume_core::events::append("index", failed == 0, summary);
    if failed > 0 {
        ExitCode::FAILURE
    } else {
        ExitCode::SUCCESS
    }
}

fn report(r: Result<(), String>) -> ExitCode {
    match r {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            log::line(PROG, &e);
            ExitCode::FAILURE
        }
    }
}
