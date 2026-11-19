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
"""
from __future__ import annotations

import argparse
import datetime
import sys
import time
from pathlib import Path

from lume_tool import dev, dev_run, scripts, tuning

REPO = Path(__file__).resolve().parents[2]
PLANS = REPO / "tests" / "device" / "tuning"
REPORTS = REPO / "docs" / "tuning"


def resolve_plan(ref: str) -> Path:
    if "/" not in ref and not ref.endswith(".toml"):
        return PLANS / f"{ref}.toml"
    return Path(ref)


def _events_from_now(ctx: dev_run.Context) -> None:
    """Only the events written from now on count (what dev_run.run_script does first)."""
    try:
        ctx.start_lines = ctx.seen = int(ctx.run(dev_run.count_command()).strip() or 0)
    except (dev.DevError, ValueError):
        ctx.start_lines = ctx.seen = 0
    ctx.seen_lines = set(dev_run.read_pending(ctx))


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


def one_run(ctx: dev_run.Context, console: str, seq: tuning.Sequence, run: tuning.Run,
            warmup: int, measure: int) -> tuning.RunMetrics:
    core = seq.core
    print(f"  {run.label}: {run.variant.change() if run.variant else 'as is'}", flush=True)
    ctx.run(tuning.restore_command(keep=True) + "true")
    if run.variant:
        ctx.run(tuning.apply_command(core.core, run.variant))
    open_game(ctx, core)
    try:
        ctx.sleep(warmup)
        window = tuning.parse_window(ctx.run(tuning.sampler_command(core.process, measure)))
        rows = tuning.parse_metrics(ctx.run(tuning.metrics_command(window.t0, window.t1)))
    finally:
        close_game(ctx)
        ctx.run(tuning.restore_command(keep=True) + "true")
    m = tuning.aggregate(window, rows)
    print(f"     drawn {tuning._f(m.drawn_fps)} fps, speed {tuning._pct(m.speed)}, audio "
          f"{m.audio_failures if m.audio_failures is not None else '-'} ({m.audio_source}), "
          f"clock {tuning._f(m.clock_mhz, 0)} MHz, temp {tuning._f(m.temp_c)} C, "
          f"{m.samples} logd rows", flush=True)
    return m


def run_sequences(host: str, console: str, seqs: list[tuning.Sequence], report: Path,
                  warmup: int, measure: int) -> int:
    ctx = dev_run.Context(host, console=console)
    manual = ctx.run(tuning.power_check_command()).strip()
    if manual:
        raise tuning.TuningError(f"lume-power is in manual mode ({manual}); run "
                                 f"`lume-power auto` on the console first")
    build = ctx.run(tuning.build_id_command()).strip() or "-"
    for n, seq in enumerate(seqs, 1):
        print(f"{n}/{len(seqs)} {seq.core.core} {seq.name}", flush=True)
        ctx.run(tuning.save_command(seq.core.core))
        try:
            results = [one_run(ctx, console, seq, r, warmup, measure) for r in seq.runs]
        finally:
            ctx.run(tuning.restore_command(keep=False) + "true")
        date = datetime.date.today().isoformat()
        if seq.variant is None:
            row = tuning.baseline_row(date, build, seq.core, *results)
        else:
            row = tuning.variant_row(date, build, seq.core, seq.variant, *results)
        tuning.append_row(report, console, row)
        print(f"  -> {row.decision}", flush=True)
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
    args = ap.parse_args(argv)
    try:
        plan = tuning.load_plan(resolve_plan(args.plan))
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
        if args.dry_run:
            return 0
        started = time.monotonic()
        rc = run_sequences(host, console, seqs, report, args.warmup, args.measure)
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
