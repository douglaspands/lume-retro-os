#!/usr/bin/env python3
"""A/B measurement of the core tuning on the console over the cable (game-experience-tuning
D6, task 5.1). The pure part (plan, commands, aggregation, criterion, report) is
lume_tool.tuning; this script only drives the console.

    .venv/bin/python tests/device/tuning_ab.py PLAN.toml --console ga36 --dry-run
    .venv/bin/python tests/device/tuning_ab.py PLAN.toml --console ga36 [--only CORE[:VARIANT]]

PLAN is a file of tests/device/tuning/ (or a bare name there). For every core: a baseline
(runs A, A) when docs/tuning/<console>.md has none for it (or with --rebaseline), then each
variant as A, B, A. One run:

1. put the saved user files back (RetroArch config, /run/lume/retroarch-extra.cfg, the core's
   .opt) and, for B, write the variant (keys appended to the extra config, options into the
   user's .opt);
2. open game N of the system through the `lume dev run` engine (lume_tool.dev_run: the
   launcher buttons, the `game OK <system> ... start` event; no game name crosses the cable)
   and check the core of that event is the planned one;
3. wait the warm-up (30 s), measure the window (120 s) with the on-console sampler, read the
   lume-logd metrics rows of the window;
4. close the game and put the saved files back.

At the end of each sequence the aggregated row goes to docs/tuning/<console>.md. The saved
files are put back on any error or Ctrl+C, and a save left by an interrupted run is put back
at the next start. The lume-power manual mode is refused (the normal profile is measured).

Core comparison (task 10.2, a plan entry whose variants are `core = "<name>"`): no separate
baseline; per game and core, A1 in the default core (the system's per-game options file
cleared), B in the variant's core through the launcher's per-game option (written on the
console from the index, the path never crosses the cable), A2. The launcher's options file is
saved with the rest and put back; our systems.d/zz-lume-tuning.toml offers the core to the
system during the sequence and is removed at the end. A core without its library is
`not-installed` (nothing runs); B without its start event, with start-failed, another core,
or ended before the measurement is over is `not-open` with the reason class (A2 skipped), and
the next sequence goes on. Results per game go to the private out/tuning/<console>-cores.jsonl;
the report gets the cores section aggregated by core and hardware family (families file:
--families, default var/roms_test/families.toml, out of git).
"""
from __future__ import annotations

import argparse
import datetime
import re
import sys
import time
from pathlib import Path

from lume_tool import dev, dev_run, scripts, tuning

REPO = Path(__file__).resolve().parents[2]
PLANS = REPO / "tests" / "device" / "tuning"
REPORTS = REPO / "docs" / "tuning"
RESULTS = REPO / "out" / "tuning"                       # private, out of git
FAMILIES = REPO / "var" / "roms_test" / "families.toml"   # private, kept by the user
WATCH_S = 5.0                                           # events polled during a warm-up
OPEN_TIMEOUT_S = 90.0                                   # the start event of a core run


def resolve_plan(ref: str) -> Path:
    if "/" not in ref and not ref.endswith(".toml"):
        return PLANS / f"{ref}.toml"
    return Path(ref)


def _events_from_now(ctx: dev_run.Context) -> None:
    """Only the events written from now on count (what dev_run.run_script does first). The
    line offset alone is not enough: a card log with old lines past the offset (J1, 2026-11-20:
    an end of a game of the boot before was read as the end of the game just opened) would
    match, so the current boot and console time are kept too (see _game_events)."""
    try:
        ctx.start_lines = ctx.seen = int(ctx.run(dev_run.count_command()).strip() or 0)
    except (dev.DevError, ValueError):
        ctx.start_lines = ctx.seen = 0
    ctx.seen_lines = set(dev_run.read_pending(ctx))
    try:
        boot, now = ctx.run(NOW_COMMAND).split()
    except (dev.DevError, ValueError):
        boot, now = "", ""
    ctx.events_boot, ctx.events_since = boot, now


# the boot number and the console time, as the event lines write them
NOW_COMMAND = "cat /storage/logs/.boot 2>/dev/null || echo -; date +%Y-%m-%dT%H:%M:%S"


def _is_current(ctx: dev_run.Context, line: str) -> bool:
    """A cut event line of this boot written at or after _events_from_now."""
    boot = getattr(ctx, "events_boot", "")
    since = getattr(ctx, "events_since", "")
    parts = line.split()
    if len(parts) < 2 or not boot or boot == "-" or not since:
        return True
    return parts[1] == boot and parts[0] >= since


def open_game(ctx: dev_run.Context, core: tuning.CorePlan) -> None:
    """The open_game step of `lume dev run`, keeping the start event to check the core."""
    step = scripts.Step("open the game", "open_game", 90.0,
                        {"system": core.system, "position": core.position})
    _events_from_now(ctx)
    try:
        ctx.open_game(core.system, core.position)
        line = dev_run.wait_event(ctx, step, dev_run.opened_pattern(core.system),
                                  dev_run.GAME_CATEGORY,
                                  dev_run.start_failed_pattern(core.system))
    except (dev.DevError, dev_run.StepFailed) as e:
        raise tuning.TuningError(f"open game {core.position} of {core.system}: {e}") from None
    ctx.last_system = core.system
    opened = tuning.started_core(line)
    if core.process == "retroarch" and opened != core.core:
        raise tuning.TuningError(f"game {core.position} of {core.system} opened with core "
                                 f"{opened}, not {core.core}")


def close_game(ctx: dev_run.Context) -> None:
    step = scripts.Step("close the game", "close_game", 60.0, {})
    _events_from_now(ctx)
    try:
        dev_run.do_close_game(ctx, step)
    except dev_run.StepFailed as e:
        raise tuning.TuningError(f"close the game: {e}") from None


# --- core comparison (task 10.2) --------------------------------------------------------

class NotOpened(Exception):
    """B did not open in its core; the message is the reason class (no log line)."""


def _game_events(ctx: dev_run.Context) -> list[str]:
    """The new lume-run/logd lines of the `game` category (cut at content=)."""
    try:
        lines = dev_run.read_new_events(ctx)
    except dev.DevError as e:
        raise tuning.TuningError(f"events of the console: {e}") from None
    return [ln for ln in lines
            if len(ln.split()) >= 3 and ln.split()[2] == dev_run.GAME_CATEGORY
            and _is_current(ctx, ln)]


def watch_warmup(ctx: dev_run.Context, system: str, seconds: float) -> str | None:
    """The warm-up of a comparison run, watching the events: the cut end line when the game
    ended before it was over, None when it is still running."""
    pattern = re.compile(dev_run.closed_pattern(system))
    end = ctx.now() + seconds
    while True:
        left = end - ctx.now()
        if left <= 0:
            return None
        ctx.sleep(min(WATCH_S, left))
        for line in _game_events(ctx):
            if pattern.search(line):
                return line


def open_core(ctx: dev_run.Context, core: tuning.CorePlan, expected: str, warmup: int) -> None:
    """Open game N in `expected` and survive the warm-up; NotOpened(reason) otherwise. The
    launcher's own failures (no index, position past the games) stay a TuningError. The start
    and the end of a game that fails at once may come in the same poll: both are seen."""
    _events_from_now(ctx)
    try:
        ctx.open_game(core.system, core.position)
    except dev.DevError as e:
        raise tuning.TuningError(f"open game {core.position} of {core.system}: {e}") from None
    ctx.last_system = core.system
    opened = re.compile(dev_run.opened_pattern(core.system))
    failed = re.compile(dev_run.start_failed_pattern(core.system))
    closed = re.compile(dev_run.closed_pattern(core.system))
    deadline = ctx.now() + OPEN_TIMEOUT_S
    start, rest = None, []
    while start is None:
        lines = _game_events(ctx)
        for i, line in enumerate(lines):
            if failed.search(line):
                raise NotOpened("start-failed")
            if opened.search(line):
                start, rest = line, lines[i + 1:]
                break
        if start is None:
            if ctx.now() >= deadline:
                raise NotOpened("timeout")
            ctx.sleep(dev_run.POLL_S)
    ended = next((ln for ln in rest if closed.search(ln)), None)
    if tuning.started_core(start) != expected:
        if ended is None:
            close_game(ctx)
        raise NotOpened("other-core")
    if ended is None:
        ended = watch_warmup(ctx, core.system, warmup)
    if ended is not None:
        raise NotOpened(tuning.exit_class(ended))


def core_run(ctx: dev_run.Context, seq: tuning.Sequence, run: tuning.Run, warmup: int,
             measure: int) -> tuning.RunMetrics:
    """One run of a core comparison: A in the default core (per-game options cleared), B in
    the variant's core for this game only. A that does not open is an error of the whole
    measurement; B that does not open raises NotOpened."""
    core = seq.core
    alt = run.variant.core if run.variant else None
    print(f"  {run.label}: core {alt or core.core}", flush=True)
    ctx.run(tuning.restore_command(keep=True) + "true")
    if alt:
        tuning.expect_applied(ctx.run(tuning.game_core_command(core.system, core.position,
                                                               alt)), "per-game core")
    else:
        tuning.expect_applied(ctx.run(tuning.default_core_command(core.system)),
                              "per-game options")
    try:
        try:
            open_core(ctx, core, alt or core.core, warmup)
        except NotOpened as e:
            if alt:
                raise
            raise tuning.TuningError(f"game {core.position} of {core.system} did not stay "
                                     f"open in its default core ({e})") from None
        try:
            window = tuning.parse_window(ctx.run(tuning.sampler_command(core.process,
                                                                        measure)))
        except (tuning.TuningError, dev.DevError):
            if alt:
                raise NotOpened("ended-early") from None
            raise
        rows = tuning.parse_metrics(ctx.run(tuning.metrics_command(window.t0, window.t1)))
        close_game(ctx)
    finally:
        ctx.run(tuning.restore_command(keep=True) + "true")
    m = tuning.aggregate(window, rows)
    print(f"     drawn {tuning._f(m.drawn_fps)} fps, speed {tuning._pct(m.speed)}, clock "
          f"{tuning._f(m.clock_mhz, 0)} MHz", flush=True)
    return m


def run_core_group(ctx: dev_run.Context, group: list[tuning.Sequence], build: str, warmup: int,
                   measure: int) -> list[tuning.CoreResult]:
    """Every alternative core of one game in a row: A1 in the default core, a B per installed
    alternative, A2 in the default core (user, 2026-11-20: the default is measured once before
    and once after, not around each alternative). A B that does not open is `not-open` and
    the next alternative runs; with no alternative opened, A2 is skipped. Every file comes
    back at the end, also on an error or Ctrl+C."""
    first = group[0]
    core = first.core
    date = datetime.date.today().isoformat()

    def result(alt, status, reason="", a=(), b=None):
        return tuning.CoreResult(date, build, core.system, core.position, core.core, alt,
                                 status, reason, tuple(a), b)
    out: dict[str, tuning.CoreResult] = {}
    alts = []
    for seq in group:
        alt = seq.variant.core
        if ctx.run(tuning.core_installed_command(alt)).strip() != tuning.INSTALLED:
            print(f"  core {alt} is not installed", flush=True)
            out[alt] = result(alt, tuning.NOT_INSTALLED)
        else:
            alts.append(seq)
    if not alts:
        return [out[s.variant.core] for s in group]
    ctx.run(tuning.save_command(core.core, games_system=core.system))
    opened: dict[str, tuning.RunMetrics] = {}
    try:
        tuning.expect_applied(ctx.run(tuning.card_cores_command(
            core.system, [s.variant.core for s in alts])), "systems.d file")
        a1 = core_run(ctx, first, tuning.Run("A1", None), warmup, measure)
        for seq in alts:
            alt = seq.variant.core
            try:
                opened[alt] = core_run(ctx, seq, tuning.Run("B", seq.variant), warmup, measure)
            except NotOpened as e:
                print(f"  -> {alt} does not open ({e})", flush=True)
                out[alt] = result(alt, tuning.NOT_OPEN, str(e), (a1,))
        a2 = core_run(ctx, first, tuning.Run("A2", None), warmup, measure) if opened else None
    finally:
        ctx.run(tuning.restore_command(keep=False) + "true")
    for alt, b in opened.items():
        out[alt] = result(alt, tuning.OPENED, "", (a1, a2), b)
    return [out[s.variant.core] for s in group]


def core_groups(seqs: list[tuning.Sequence]) -> list[list[tuning.Sequence]]:
    """Consecutive core-comparison sequences of the same game, together."""
    groups: list[list[tuning.Sequence]] = []
    for seq in seqs:
        if groups and groups[-1][0].core is seq.core:
            groups[-1].append(seq)
        else:
            groups.append([seq])
    return groups


def one_run(ctx: dev_run.Context, console: str, seq: tuning.Sequence, run: tuning.Run,
            warmup: int, measure: int, next_env: tuple | None = None) -> tuning.RunMetrics:
    """One run. A LÖVE run (task 7.4) never writes its own variables: the launcher reads the
    runners once, when it starts again after the previous game, so the card's runner file of
    THIS run was written before the previous game closed, and this run writes the one of the
    next run (`next_env`; empty: back as saved) before it closes."""
    core = seq.core
    love = core.process == "love"
    print(f"  {run.label}: {run.variant.change() if run.variant else 'as is'}", flush=True)
    ctx.run(tuning.restore_command(keep=True, keep_runner=love) + "true")
    if run.variant and not love:
        ctx.run(tuning.apply_command(core.core, run.variant))
    open_game(ctx, core)
    try:
        ctx.sleep(warmup)
        window = tuning.parse_window(ctx.run(tuning.sampler_command(core.process, measure)))
        rows = tuning.parse_metrics(ctx.run(tuning.metrics_command(window.t0, window.t1)))
    finally:
        if love and next_env is not None:
            tuning.expect_applied(ctx.run(tuning.runner_next_command(next_env)),
                                  "runner of the next run")
        close_game(ctx)
        ctx.run(tuning.restore_command(keep=True, keep_runner=love) + "true")
    m = tuning.aggregate(window, rows)
    print(f"     drawn {tuning._f(m.drawn_fps)} fps, speed {tuning._pct(m.speed)}, audio "
          f"{m.audio_failures if m.audio_failures is not None else '-'} ({m.audio_source}), "
          f"clock {tuning._f(m.clock_mhz, 0)} MHz, temp {tuning._f(m.temp_c)} C, "
          f"{m.samples} logd rows", flush=True)
    return m


def run_config_group(ctx: dev_run.Context, console: str, group: list[tuning.Sequence],
                     report: Path, build: str, warmup: int, measure: int, tag: str) -> None:
    """The configuration variants of one core and game in a row (user, 2026-11-20): A1 as
    is, a B per variant, A2 as is; every variant row uses the same A1 and A2. A baseline
    sequence (A, A) runs alone. The files come back after every run and at the end."""
    date = datetime.date.today().isoformat()
    first = group[0]
    if first.variant is None:
        print(f"{tag} {first.core.core} baseline", flush=True)
        ctx.run(tuning.save_command(first.core.core))
        try:
            runs = [one_run(ctx, console, first, r, warmup, measure) for r in first.runs]
        finally:
            ctx.run(tuning.restore_command(keep=False) + "true")
        row = tuning.baseline_row(date, build, first.core, *runs)
        tuning.append_row(report, console, row)
        print(f"  -> {row.decision}", flush=True)
        if len(group) > 1:
            run_config_group(ctx, console, group[1:], report, build, warmup, measure, tag)
        return
    print(f"{tag} {first.core.core} {first.core.system} game #{first.core.position}: "
          f"{', '.join(s.name for s in group)}", flush=True)
    ctx.run(tuning.save_command(first.core.core))
    # the variables of the run that follows each run (LÖVE only, see one_run): A1, the Bs, A2
    envs = [()] + [s.variant.env for s in group] + [()]
    try:
        a1 = one_run(ctx, console, first, tuning.Run("A1", None), warmup, measure, envs[1])
        bs = [one_run(ctx, console, s, tuning.Run("B", s.variant), warmup, measure, envs[i + 2])
              for i, s in enumerate(group)]
        a2 = one_run(ctx, console, first, tuning.Run("A2", None), warmup, measure, None)
    finally:
        ctx.run(tuning.restore_command(keep=False) + "true")
    if any(s.also_baseline for s in group):
        # the two A runs are the core's baseline, written before the variant rows
        tuning.append_row(report, console, tuning.baseline_row(date, build, first.core, a1, a2))
    for s, b in zip(group, bs):
        row = tuning.variant_row(date, build, s.core, s.variant, a1, b, a2)
        tuning.append_row(report, console, row)
        print(f"  {s.name} -> {row.decision}", flush=True)


def run_sequences(host: str, console: str, seqs: list[tuning.Sequence], report: Path,
                  warmup: int, measure: int, results: Path | None = None,
                  families: dict | None = None, ctx: dev_run.Context | None = None) -> int:
    ctx = ctx or dev_run.Context(host, console=console)
    manual = ctx.run(tuning.power_check_command()).strip()
    if manual:
        raise tuning.TuningError(f"lume-power is in manual mode ({manual}); run "
                                 f"`lume-power auto` on the console first")
    build = ctx.run(tuning.build_id_command()).strip() or "-"
    results = results or RESULTS / f"{console}-cores.jsonl"
    compared = False
    groups = core_groups(seqs)
    for n, group in enumerate(groups, 1):
        seq = group[0]
        if seq.core.compares_cores:
            alts = ", ".join(s.variant.core for s in group)
            print(f"{n}/{len(groups)} {seq.core.system} game #{seq.core.position}: "
                  f"{seq.core.core} against {alts}", flush=True)
            for res in run_core_group(ctx, group, build, warmup, measure):
                tuning.save_result(results, res)
            tuning.write_cores_section(report, console, tuning.load_results(results),
                                       families or {})
            compared = True
            continue
        run_config_group(ctx, console, group, report, build, warmup, measure,
                         f"{n}/{len(groups)}")
    if compared:
        # private: positions only, on the PC; the choice per game goes to the user's card
        print(f"fastest core at full speed per game (from {results}):")
        for (system, pos), core in tuning.picks(tuning.load_results(results)).items():
            print(f"  {system} #{pos}: {core}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("plan", help="plan file (tests/device/tuning/<name>.toml or a path)")
    ap.add_argument("--console", choices=tuning.CONSOLES,
                    help="required for --dry-run; otherwise checked against the cable")
    ap.add_argument("--host", default=None)
    ap.add_argument("--dry-run", action="store_true", help="print the runs, touch nothing")
    ap.add_argument("--only", help="CORE or CORE:VARIANT (CORE:baseline for the baseline)")
    ap.add_argument("--rebaseline", action="store_true", help="measure the baseline again")
    ap.add_argument("--warmup", type=int, default=tuning.WARMUP_S)
    ap.add_argument("--measure", type=int, default=tuning.MEASURE_S)
    ap.add_argument("--report-dir", type=Path, default=REPORTS)
    ap.add_argument("--results", type=Path, default=None,
                    help="private results of a core comparison (default "
                         "out/tuning/<console>-cores.jsonl)")
    ap.add_argument("--families", type=Path, default=FAMILIES,
                    help="private file position -> hardware family (default "
                         "var/roms_test/families.toml; absent = group by core only)")
    args = ap.parse_args(argv)
    try:
        plan = tuning.load_plan(resolve_plan(args.plan))
        # only a core comparison reads the private families file
        families = (tuning.load_families(args.families)
                    if any(c.compares_cores for c in plan.cores) else {})
        if args.dry_run:
            if not args.console:
                raise tuning.TuningError("--dry-run needs --console")
            console = args.console
        else:
            host = args.host or dev.CONSOLE_ADDR
            console = dev.which_console(host, args.console)
        report = args.report_dir / f"{console}.md"
        text = report.read_text(encoding="utf-8") if report.exists() else ""
        seqs = tuning.build_sequences(plan, console, tuning.baselines_in(text),
                                      args.rebaseline, args.only)
        print(tuning.format_sequences(seqs, console, args.warmup, args.measure), flush=True)
        if any(s.core.compares_cores for s in seqs):
            print("core comparison: report grouped by "
                  f"{'core and hardware family' if families else 'core only (no families file)'}")
        if args.dry_run:
            return 0
        started = time.monotonic()
        rc = run_sequences(host, console, seqs, report, args.warmup, args.measure,
                           args.results, families)
        print(f"done in {(time.monotonic() - started) / 60:.0f} min; report: {report}")
        return rc
    except (tuning.TuningError, dev.DevError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted (the saved files were put back)", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
