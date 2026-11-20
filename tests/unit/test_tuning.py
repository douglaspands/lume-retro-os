"""A/B measurement of the core tuning (game-experience-tuning 5.1, lume_tool.tuning and
tests/device/tuning_ab.py): plan, sequences, remote commands, aggregation of recorded
(synthetic) samples, the spec's acceptance criterion and the report that refuses game names
and paths. No console: the remote commands that touch files run against a fake root."""
from __future__ import annotations

import importlib.util
import subprocess
import tomllib
from pathlib import Path

import pytest

from lume_tool import tuning
from lume_tool.tuning import RunMetrics, TuningError

REPO = Path(__file__).resolve().parents[2]


# --- recorded samples (synthetic: what the sampler and lume-logd print on a console) ---

# One window of the sampler: pid 812, 120 s, two DRM fds of the same client (dup) and one
# of another client, the GA36 time_in_state, the RetroArch stream sampled each second.
SAMPLER_OUT = """\
pid 812
shm 0 3
snap start 1000.00
flips 41 6000
flips 41 6000
flips 42 10
tis policy0 648000 100
tis policy0 1008000 200
pcm 1000.01 /proc/asound/card0/pcm0p/sub0/status
| state: RUNNING
| owner_pid   : 812
| trigger_time: 970.100000000
| tstamp      : 1000.010000000
| delay       : 1500
| avail       : 548
| avail_max   : 1100
| -----
| hw_ptr      : 1440000
| appl_ptr    : 1441500
pcm 1001.02 /proc/asound/card0/pcm0p/sub0/status
| state: RUNNING
| owner_pid   : 812
| trigger_time: 970.100000000
| hw_ptr      : 1488000
pcm 1002.03 /proc/asound/card0/pcm0p/sub0/status
| state: XRUN
| owner_pid   : 812
| trigger_time: 970.100000000
| hw_ptr      : 1536000
pcm 1003.04 /proc/asound/card0/pcm0p/sub0/status
| state: RUNNING
| owner_pid   : 812
| trigger_time: 1002.500000000
| hw_ptr      : 24000
pcm 1004.05 /proc/asound/card0/pcm0p/sub0/status
| state: RUNNING
| owner_pid   : 812
| trigger_time: 1002.500000000
| hw_ptr      : 72000
pcm 1004.05 /proc/asound/card1/pcm0p/sub0/status
| closed
snap end 1120.00
flips 41 12600
flips 41 12600
flips 42 10
tis policy0 648000 6100
tis policy0 1008000 6200
"""

# lume-logd rows of the same window as metrics_command prints them (allowed columns only)
METRICS_OUT = """\
@header uptime_s,temp_cpu_thermal_c,freq_policy0_mhz,cpu0_pct,cpu1_pct,frontend,fps,fps_nominal
1005,50.0,1008,40,10,game,59.7,59.73
1010,51.0,648,42,12,game,59.8,59.73
1010,51.0,648,42,12,game,59.8,59.73
1015,52.0,1008,38,8,game,59.6,59.73
"""


def window_text(pid=812, flips=(0, 6600), tis=((648000, 0, 6000), (1008000, 0, 6000)),
                pcm=(), t=(1000.0, 1120.0), shm=()) -> str:
    """Sampler output with the given counters; pcm = [(uptime, state, trigger, hw_ptr)]."""
    lines = [f"pid {pid}"] + [f"shm {k} 1" for k in shm] + [f"snap start {t[0]}"]
    lines.append(f"flips 1 {flips[0]}")
    lines += [f"tis policy0 {khz} {a}" for khz, a, _ in tis]
    for up, state, trig, hw in pcm:
        lines += [f"pcm {up} /proc/asound/card0/pcm0p/sub0/status", f"| state: {state}",
                  f"| owner_pid   : {pid}", f"| trigger_time: {trig}", f"| hw_ptr      : {hw}"]
    lines += [f"snap end {t[1]}", f"flips 1 {flips[1]}"]
    lines += [f"tis policy0 {khz} {b}" for khz, _, b in tis]
    return "\n".join(lines) + "\n"


def run_metrics(drawn=55.0, speed=1.0, audio=0, clock=900.0, temp=50.0, cpu=(40.0, 10.0),
                source="alsa-status") -> RunMetrics:
    return RunMetrics(120.0, drawn, 59.73 * speed if speed is not None else None, 59.73, speed,
                      audio, source, clock, tuple(cpu), temp, 24)


# --- plan -----------------------------------------------------------------------------

PLAN = {
    "consoles": ["ga36", "r36s"],
    "core": [
        {"core": "fceumm", "system": "nes", "position": 1,
         "variant": [{"name": "threaded-off", "retroarch": {"video_threaded": False}},
                     {"name": "sound-high", "options": {"fceumm_sndquality": "High"}}]},
        {"core": "gpsp", "system": "gba", "position": 2},
    ],
}


def test_plan_reads_cores_and_variants():
    plan = tuning.validate_plan(PLAN)
    fce = plan.cores[0]
    assert (fce.core, fce.system, fce.position, fce.process) == ("fceumm", "nes", 1, "retroarch")
    assert fce.variants[0].retroarch == (("video_threaded", "false"),)
    assert fce.variants[1].change() == "opt:fceumm_sndquality=High"


@pytest.mark.parametrize("patch", [
    {"core": [{"core": "fceumm", "system": "nes", "position": 1, "game": "x"}]},
    {"core": [{"core": "fceumm", "system": "nes", "position": 1, "rom": "x"}]},
    {"core": [{"core": "fceumm", "system": "nes", "position": 0}]},
    {"core": [{"core": "fceumm", "system": "nes", "position": 1,
               "variant": [{"name": "Some Game.nes", "retroarch": {"a": "1"}}]}]},
    {"core": [{"core": "fceumm", "system": "nes", "position": 1,
               "variant": [{"name": "v.zip", "retroarch": {"a": "1"}}]}]},
    {"core": [{"core": "fceumm", "system": "nes", "position": 1,
               "variant": [{"name": "v", "options": {"bios": "/storage/bios/x.bin"}}]}]},
    {"core": [{"core": "fceumm", "system": "nes", "position": 1,
               "variant": [{"name": "v"}]}]},
    {"core": [{"core": "fceumm", "system": "nes", "position": 1,
               "variant": [{"name": "baseline", "retroarch": {"a": "1"}}]}]},
    {"core": [{"core": "love", "system": "love", "position": 1, "process": "love",
               "variant": [{"name": "v", "retroarch": {"a": "1"}}]}]},
    {"consoles": ["ps2"]},
])
def test_plan_refuses_names_paths_and_bad_fields(patch):
    with pytest.raises((TuningError, ValueError)):
        tuning.validate_plan({**PLAN, **patch})


def test_baseline_plan_file_is_valid():
    plan = tuning.load_plan(REPO / "tests/device/tuning/baseline.toml")
    assert {"fceumm", "gpsp", "pcsx_rearmed", "love"} <= {c.core for c in plan.cores}
    assert all(not c.variants for c in plan.cores)


# --- sequences / dry run ---------------------------------------------------------------

def test_sequences_take_the_baseline_from_the_first_aba_of_a_core_with_variants():
    # a core with variants needs no separate A, A: the A1 and A2 of its first A, B, A are the
    # baseline (user, 2026-11-20); a core without variants still gets A, A
    plan = tuning.validate_plan(PLAN)
    seqs = tuning.build_sequences(plan, "ga36", baselines=set())
    assert [(s.core.core, s.name, s.also_baseline) for s in seqs] == [
        ("fceumm", "threaded-off", True), ("fceumm", "sound-high", False),
        ("gpsp", "baseline", False)]
    assert [(r.label, r.variant is not None) for r in seqs[0].runs] == [
        ("A1", False), ("B", True), ("A2", False)]
    assert [r.label for r in seqs[2].runs] == ["A1", "A2"]


def test_sequences_skip_a_measured_baseline_and_filter():
    plan = tuning.validate_plan(PLAN)
    seqs = tuning.build_sequences(plan, "ga36", baselines={"fceumm", "gpsp"})
    assert [(s.name, s.also_baseline) for s in seqs] == [
        ("threaded-off", False), ("sound-high", False)]
    only = tuning.build_sequences(plan, "ga36", {"fceumm"}, only="fceumm:sound-high")
    assert [s.name for s in only] == ["sound-high"]
    again = tuning.build_sequences(plan, "ga36", {"fceumm"}, rebaseline=True, only="fceumm")
    assert [(s.name, s.also_baseline) for s in again] == [
        ("threaded-off", True), ("sound-high", False)]
    # asking for the baseline alone still measures A, A
    base = tuning.build_sequences(plan, "ga36", set(), only="fceumm:baseline")
    assert [(s.name, len(s.runs)) for s in base] == [("baseline", 2)]
    # a filtered variant of a core without a baseline carries it
    one = tuning.build_sequences(plan, "ga36", set(), only="fceumm:sound-high")
    assert [(s.name, s.also_baseline) for s in one] == [("sound-high", True)]
    with pytest.raises(TuningError):
        tuning.build_sequences(plan, "ga36", set(), only="nestopia")
    with pytest.raises(TuningError):
        tuning.build_sequences(plan, "vm", set())


def test_dry_run_text_names_no_game():
    plan = tuning.validate_plan(PLAN)
    text = tuning.format_sequences(tuning.build_sequences(plan, "ga36", set()), "ga36")
    assert "console ga36: 3 sequence(s), 8 run(s) of 30+120 s" in text
    assert "fceumm threaded-off: system nes game #1 (retroarch)" in text
    assert "A1 and A2 are also the baseline of the core (no separate A, A)" in text
    assert "B: apply ra:video_threaded=false; open; wait 30 s; measure 120 s" in text


def test_dry_run_script_prints_the_plan(tmp_path, capsys):
    spec = importlib.util.spec_from_file_location("tuning_ab", REPO / "tests/device/tuning_ab.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["baseline", "--console", "ga36", "--dry-run",
                     "--report-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "1. fceumm baseline: system nes game #1" in out
    assert mod.main(["baseline", "--dry-run"]) == 1           # no console given


# --- parsing and aggregation of recorded samples ----------------------------------------

def test_parse_window_counters_and_pcm():
    w = tuning.parse_window(SAMPLER_OUT)
    assert (w.pid, w.t0, w.t1) == (812, 1000.0, 1120.0)
    assert w.flips0 == {"41": 6000, "42": 10} and w.flips1["41"] == 12600
    assert len(w.pcm) == 6 and w.pcm[0].fields["owner_pid"] == "812"
    assert w.pcm[-1].fields == {"state": "CLOSED"}


def test_parse_window_refuses_errors_and_incomplete_output():
    with pytest.raises(TuningError, match="no retroarch process"):
        tuning.parse_window("error no retroarch process\n")
    with pytest.raises(TuningError, match="incomplete"):
        tuning.parse_window("pid 1\nsnap start 5\n")


def test_aggregate_recorded_window():
    m = tuning.aggregate(tuning.parse_window(SAMPLER_OUT),
                         tuning.parse_metrics(METRICS_OUT))
    assert m.seconds == 120.0
    assert m.drawn_fps == pytest.approx(6600 / 120)           # one client counted once
    # time_in_state: 6000 ticks at 648 MHz, 6000 at 1008 MHz
    assert m.clock_mhz == pytest.approx(828.0)
    assert m.core_fps == pytest.approx(59.7) and m.speed == pytest.approx(59.7 / 59.73)
    assert m.cpu_pct == (40.0, 10.0) and m.cpu_total == 50.0
    assert m.temp_c == pytest.approx(51.0)
    assert m.samples == 3                                      # duplicate row dropped
    # XRUN seen at 1002, then the new trigger_time and the hw_ptr back at 1003: 2 seconds
    assert (m.audio_failures, m.audio_source) == (2, "alsa-status")


def test_clock_falls_back_to_logd_frequency():
    w = tuning.parse_window(window_text(tis=()))
    m = tuning.aggregate(w, tuning.parse_metrics(METRICS_OUT))
    assert m.clock_mhz == pytest.approx((1008 + 648 + 1008) / 3)


def test_audio_continuous_stream_has_no_failure():
    pcm = [(1000 + i, "RUNNING", "990.5", 48000 * i) for i in range(5)]
    assert tuning.audio_failures(tuning.parse_window(window_text(pcm=pcm))) == (0, "alsa-status")


def test_audio_uses_xrun_counter_when_the_kernel_has_it():
    text = window_text() + "".join(
        f"pcm {1000 + i} /proc/asound/card0/pcm0p/sub0/status\n| state: RUNNING\n"
        f"| owner_pid   : 812\n| trigger_time: 1.0\n| hw_ptr      : {i}\n"
        f"| xrun_counter: {c}\n" for i, c in enumerate((3, 3, 5, 9)))
    assert tuning.audio_failures(tuning.parse_window(text)) == (6, "xrun_counter")


def test_audio_not_measured_through_dmix_or_without_the_stream():
    pcm = [(1000, "RUNNING", "1.0", 10)]
    w = tuning.parse_window(window_text(pcm=pcm, shm=(tuning.DMIX_IPC_KEY,)))
    assert tuning.audio_failures(w) == (None, "dmix")
    other = tuning.parse_window(window_text(pcm=pcm).replace("owner_pid   : 812",
                                                              "owner_pid   : 77"))
    assert tuning.audio_failures(other) == (None, "no-stream")


# --- acceptance criterion (spec core-tuning, "Ajuste aceito só com ganho medido") ---------

def test_lower_clock_at_full_speed_is_accepted():
    # spec scenario "Clock menor com a mesma velocidade"
    d = tuning.decide(run_metrics(clock=1000), run_metrics(clock=900), run_metrics(clock=990))
    assert d.accepted is True and d.gains == ("clock_mhz",)
    assert d.text == "aceito: clock"


def test_more_frames_with_audio_failures_is_refused():
    # spec scenario "Ganho de um lado, perda do outro"
    d = tuning.decide(run_metrics(drawn=48), run_metrics(drawn=55, audio=3), run_metrics(drawn=48.2))
    assert d.accepted is False and "falhas de áudio" in d.text
    assert "drawn_fps" in d.gains


def test_gain_within_the_noise_is_refused():
    # the two A differ by 60 MHz: a 40 MHz drop is noise
    d = tuning.decide(run_metrics(clock=1000), run_metrics(clock=930), run_metrics(clock=940))
    assert d.accepted is False and d.text == "recusado: sem ganho acima do ruído"


def test_gain_below_the_floor_is_refused_even_without_noise():
    d = tuning.decide(run_metrics(clock=1000), run_metrics(clock=995), run_metrics(clock=1000))
    assert d.accepted is False


def test_loss_of_full_speed_is_refused():
    d = tuning.decide(run_metrics(), run_metrics(clock=700, speed=0.95), run_metrics())
    assert d.accepted is False
    assert "sem velocidade cheia (95.0%)" in d.text and "piora: velocidade" in d.text


def test_gain_with_another_metric_worse_is_refused():
    d = tuning.decide(run_metrics(temp=50), run_metrics(temp=48, clock=1000),
                      run_metrics(temp=50.2))
    assert d.accepted is False and d.gains == ("temp_c",) and d.losses == ("clock_mhz",)
    assert "piora: clock" in d.text


def test_cpu_rise_beyond_noise_is_a_loss():
    d = tuning.decide(run_metrics(cpu=(40, 10)), run_metrics(clock=800, cpu=(60, 10)),
                      run_metrics(cpu=(41, 10)))
    assert d.accepted is False and d.losses == ("cpu_total",)


def test_baseline_audio_failures_do_not_block_a_variant_that_keeps_them():
    d = tuning.decide(run_metrics(audio=2, drawn=48), run_metrics(audio=2, drawn=55),
                      run_metrics(audio=4, drawn=48))
    assert d.accepted is True and d.gains == ("drawn_fps",)


def test_unmeasured_audio_is_inconclusive():
    d = tuning.decide(run_metrics(), run_metrics(clock=700, audio=None, source="dmix"),
                      run_metrics())
    assert d.accepted is None and d.text.startswith("inconclusivo")


# --- report ---------------------------------------------------------------------------

def core_plan(core="fceumm", system="nes", position=1):
    return tuning.CorePlan(core, system, position)


def test_report_files_have_the_generated_header():
    for console in ("ga36", "r36s"):
        text = (REPO / f"docs/tuning/{console}.md").read_text(encoding="utf-8")
        assert text.startswith(tuning.report_header(console))  # measured rows follow it


def test_rows_are_appended_and_parsed(tmp_path):
    report = tmp_path / "ga36.md"
    a1, a2 = run_metrics(clock=1000), run_metrics(clock=990)
    tuning.append_row(report, "ga36", tuning.baseline_row("2026-11-20", "b123", core_plan(), a1, a2))
    v = tuning.Variant("threaded-off", (("video_threaded", "false"),))
    tuning.append_row(report, "ga36", tuning.variant_row(
        "2026-11-20", "b123", core_plan(), v, a1, run_metrics(clock=900), a2))
    rows = tuning.parse_report(report.read_text(encoding="utf-8"))
    assert [(r["core"], r["variante"], r["execuções"], r["decisão"]) for r in rows] == [
        ("fceumm", "baseline", "A,A", "base"),
        ("fceumm", "threaded-off", "A,B,A", "aceito: clock")]
    assert rows[0]["jogo"] == "#1" and rows[0]["clock MHz"] == "995"
    assert rows[1]["clock MHz"] == "900 (-95)" and rows[1]["mudança"] == "ra:video_threaded=false"
    assert rows[1]["falhas de áudio"] == "0 (A 0 e 0)"
    assert rows[1]["ruído A1-A2"].startswith("quadros 0.0; vel 0.0%; MHz 10")
    assert tuning.baselines_in(report.read_text(encoding="utf-8")) == {"fceumm"}


def test_variant_row_without_baseline_is_refused(tmp_path):
    # spec scenario "Ajuste sem base"
    v = tuning.Variant("threaded-off", (("video_threaded", "false"),))
    row = tuning.variant_row("2026-11-20", "b1", core_plan(), v, run_metrics(),
                             run_metrics(clock=800), run_metrics())
    with pytest.raises(TuningError, match="no baseline of fceumm"):
        tuning.append_row(tmp_path / "ga36.md", "ga36", row)


@pytest.mark.parametrize("field,value", [
    ("variant", "Super Game (USA).sfc"),
    ("variant", "../roms/snes"),
    ("system", "/storage/roms/nes"),
    ("core", "fceumm/nes"),
    ("change", "opt:bios=/storage/bios/scph1001.bin"),
    ("change", "ra:video_threaded=false; game.nes"),
    ("decision", "aceito: /storage/roms/nes/some game.nes"),
    ("decision", "base | injected | column"),
    ("cells", {"quadros/s": "Some Game.zip"}),
    ("build", "/boot/VERSION"),
    ("position", 0),
])
def test_report_refuses_game_names_and_paths(field, value, tmp_path):
    row = tuning.baseline_row("2026-11-20", "b1", core_plan(), run_metrics(), run_metrics())
    if field == "cells":
        row.cells.update(value)
    else:
        setattr(row, field, value)
    with pytest.raises(TuningError):
        tuning.append_row(tmp_path / "ga36.md", "ga36", row)
    assert not (tmp_path / "ga36.md").exists()


def test_started_core_from_the_cut_start_event():
    assert tuning.started_core("2026-11-20T10:00:00 51 game OK nes retroarch fceumm start") == "fceumm"
    assert tuning.started_core("2026-11-20T10:00:00 51 game OK nes retroarch fceumm exit=0 "
                               "end=quit secs=3") is None


# --- remote commands against a fake root ----------------------------------------------

@pytest.fixture
def fake_root(tmp_path, monkeypatch):
    home = tmp_path / "home/game/.config/retroarch"
    (home / "config/FCE Ultra").mkdir(parents=True)
    info = tmp_path / "info"
    info.mkdir()
    (info / "fceumm_libretro.info").write_text('display_name = "x"\ncorename = "FCE Ultra"\n')
    monkeypatch.setattr(tuning, "USER_CFG", str(home / "retroarch.cfg"))
    monkeypatch.setattr(tuning, "OPT_ROOT", str(home / "config"))
    monkeypatch.setattr(tuning, "EXTRA_CFG", str(tmp_path / "run/retroarch-extra.cfg"))
    monkeypatch.setattr(tuning, "INFO_DIR", str(info))
    monkeypatch.setattr(tuning, "SAVE_DIR", str(tmp_path / "run/tuning"))
    monkeypatch.setattr(tuning, "LOGS_RAM", str(tmp_path / "run/logs"))
    monkeypatch.setattr(tuning, "LOGS_DIR", str(tmp_path / "storage/logs"))
    (tmp_path / "run").mkdir()
    return tmp_path, home


def sh(cmd: str) -> str:
    r = subprocess.run(["sh", "-c", cmd], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_variant_is_applied_and_every_file_comes_back(fake_root):
    root, home = fake_root
    cfg, opt = home / "retroarch.cfg", home / "config/FCE Ultra/FCE Ultra.opt"
    extra = root / "run/retroarch-extra.cfg"
    cfg.write_text('video_threaded = "true"\nuser_key = "1"\n')
    opt.write_text('fceumm_sndquality = "Low"\nfceumm_palette = "default"\n')
    v = tuning.Variant("v", (("video_threaded", "false"),),
                       (("fceumm_sndquality", "High"), ("fceumm_overscan_h", "enabled")))
    assert sh(tuning.save_command("fceumm")).strip() == "saved"
    assert sh(tuning.apply_command("fceumm", v)).strip() == "applied"
    assert extra.read_text() == 'video_threaded = "false"\n'
    assert opt.read_text() == ('fceumm_palette = "default"\nfceumm_sndquality = "High"\n'
                               'fceumm_overscan_h = "enabled"\n')
    cfg.write_text('video_threaded = "false"\nuser_key = "1"\n')   # the frontend merged it
    sh(tuning.restore_command(keep=True))
    assert cfg.read_text() == 'video_threaded = "true"\nuser_key = "1"\n'
    assert opt.read_text() == 'fceumm_sndquality = "Low"\nfceumm_palette = "default"\n'
    assert not extra.exists()                                    # it did not exist before
    assert (root / "run/tuning").is_dir()
    sh(tuning.restore_command(keep=False))
    assert not (root / "run/tuning").exists()


def test_an_interrupted_save_is_put_back_before_a_new_one(fake_root):
    root, home = fake_root
    extra = root / "run/retroarch-extra.cfg"
    extra.write_text('video_refresh_rate = "60.0"\n')            # a kernel experiment's key
    sh(tuning.save_command("fceumm"))
    sh(tuning.apply_command("fceumm", tuning.Variant("v", (("audio_latency", "96"),))))
    assert extra.read_text() == 'video_refresh_rate = "60.0"\naudio_latency = "96"\n'
    sh(tuning.save_command("gpsp"))                              # crash, then another core
    assert extra.read_text() == 'video_refresh_rate = "60.0"\n'
    sh(tuning.restore_command(keep=False))
    assert extra.read_text() == 'video_refresh_rate = "60.0"\n'


def test_options_file_is_created_and_removed_when_absent(fake_root):
    root, home = fake_root
    opt = home / "config/FCE Ultra/FCE Ultra.opt"
    sh(tuning.save_command("fceumm"))
    sh(tuning.apply_command("fceumm", tuning.Variant("v", (), (("fceumm_sndquality", "High"),))))
    assert opt.read_text() == 'fceumm_sndquality = "High"\n'
    sh(tuning.restore_command(keep=False))
    assert not opt.exists()


def test_metrics_command_keeps_only_allowed_columns_of_the_window(fake_root):
    root, _ = fake_root
    ram, logs = root / "run/logs", root / "storage/logs/metrics"
    ram.mkdir(parents=True)
    logs.mkdir(parents=True)
    header = ("time,uptime_s,temp_cpu_thermal_c,freq_policy0_mhz,cpu0_pct,cpu1_pct,mem_avail_mb,"
              "frontend,core,content,fps,fps_nominal,lume_ui_rss_kb\n")
    (ram / "metrics.header").write_text(header)
    (ram / "boot-n").write_text("7\n")
    row = "2026-11-20T10:00:{s:02d},{u},50,1008,40,10,300,game,nes,Secret Game; Part 2,59.7,59.73,\n"
    (logs / "boot-7.csv").write_text(header + row.format(s=0, u=995) + row.format(s=5, u=1000)
                                     + row.format(s=10, u=1005))
    (ram / "metrics.pending").write_text(row.format(s=15, u=1010) + row.format(s=20, u=1125))
    out = sh(tuning.metrics_command(1000.0, 1120.0))
    assert "Secret" not in out and "nes" not in out
    rows = tuning.parse_metrics(out)
    assert [r["uptime_s"] for r in rows] == ["1010", "1005"]
    assert set(rows[0]) == {"uptime_s", "temp_cpu_thermal_c", "freq_policy0_mhz", "cpu0_pct",
                            "cpu1_pct", "frontend", "fps", "fps_nominal"}


def test_sampler_is_valid_sh_and_names_the_process():
    cmd = tuning.sampler_command("retroarch", 120)
    assert "pidof retroarch" in cmd and "-lt 120" in cmd
    subprocess.run(["sh", "-n", "-c", cmd], check=True)
    with pytest.raises(TuningError):
        tuning.sampler_command("bash", 1)


# --- core comparison (task 10.2) --------------------------------------------------------

CORE_PLAN = {
    "consoles": ["ga36"],
    "core": [{"core": "fbneo", "system": "arcade", "positions": [1, 2],
              "variant": [{"core": "mame2003_plus"}, {"name": "m2000", "core": "mame2000"}]}],
}


def test_core_plan_expands_positions_and_names_variants_by_core():
    plan = tuning.validate_plan(CORE_PLAN)
    assert [(c.core, c.position) for c in plan.cores] == [("fbneo", 1), ("fbneo", 2)]
    assert all(c.compares_cores for c in plan.cores)
    v = plan.cores[0].variants
    assert [(x.name, x.core, x.change()) for x in v] == [
        ("mame2003_plus", "mame2003_plus", "core:mame2003_plus"),
        ("m2000", "mame2000", "core:mame2000")]


@pytest.mark.parametrize("entry", [
    {"core": "fbneo", "system": "arcade", "position": 1,
     "variant": [{"core": "mame2000", "retroarch": {"a": "1"}}]},          # core + keys
    {"core": "fbneo", "system": "arcade", "position": 1,
     "variant": [{"core": "fbneo"}]},                                        # the default
    {"core": "fbneo", "system": "arcade", "position": 1,
     "variant": [{"core": "mame2000"}, {"name": "k", "retroarch": {"a": "1"}}]},   # mixed
    {"core": "fbneo", "system": "arcade", "position": 1, "positions": [2]},
    {"core": "fbneo", "system": "arcade", "positions": [1, 1]},
    {"core": "fbneo", "system": "arcade", "positions": []},
    {"core": "fbneo", "system": "arcade", "position": 1,
     "variant": [{"core": "mame-2000"}]},
    {"core": "fbneo", "system": "arcade", "position": 1,
     "variant": [{"core": "x.zip"}]},
])
def test_core_plan_refusals(entry):
    with pytest.raises(TuningError):
        tuning.validate_plan({"consoles": ["ga36"], "core": [entry]})


def test_same_core_on_the_same_game_twice_is_refused():
    with pytest.raises(TuningError, match="appears twice"):
        tuning.validate_plan({"consoles": ["ga36"], "core": [
            {"core": "fbneo", "system": "arcade", "positions": [1, 2]},
            {"core": "fbneo", "system": "arcade", "position": 2}]})


def test_arcade_cores_plan_file_is_valid():
    plan = tuning.load_plan(REPO / "tests/device/tuning/arcade-cores.toml")
    assert [c.position for c in plan.cores] == list(range(1, 9))
    assert {c.core for c in plan.cores} == {"fbneo"} and plan.cores[0].system == "arcade"
    assert [v.core for v in plan.cores[0].variants] == ["fbalpha2012", "mame2003_plus",
                                                         "mame2000"]
    seqs = tuning.build_sequences(plan, "ga36", baselines=set())
    assert len(seqs) == 24 and all(s.name != tuning.BASELINE for s in seqs)


def test_core_comparison_has_no_baseline_sequence_and_dry_run_text():
    plan = tuning.validate_plan(CORE_PLAN)
    seqs = tuning.build_sequences(plan, "ga36", baselines=set())
    assert [(s.core.position, s.name) for s in seqs] == [
        (1, "mame2003_plus"), (1, "m2000"), (2, "mame2003_plus"), (2, "m2000")]
    assert [r.label for r in seqs[0].runs] == ["A1", "B", "A2"]
    assert [s.name for s in tuning.build_sequences(plan, "ga36", set(), only="fbneo:m2000")] \
        == ["m2000", "m2000"]
    text = tuning.format_sequences(seqs, "ga36")
    # grouped: the default core once before and once after the alternatives of each game
    assert "console ga36: 4 sequence(s), 8 run(s) of 30+120 s, at most 24 min" in text
    assert "1. fbneo mame2003_plus: system arcade game #1 (retroarch)" in text
    assert "check: core mame2003_plus installed" in text
    assert "A1: default core fbneo (per-game options cleared); open; wait 30 s" in text
    assert "B: core mame2003_plus for this game only (launcher per-game option)" in text


def test_core_plan_dry_run_through_the_script(tmp_path, capsys):
    mod = load_script()
    assert mod.main(["arcade-cores", "--console", "ga36", "--dry-run",
                     "--report-dir", str(tmp_path),
                     "--families", str(tmp_path / "none.toml")]) == 0
    out = capsys.readouterr().out
    assert "console ga36: 24 sequence(s), 40 run(s)" in out
    assert "core comparison: report grouped by core only (no families file)" in out


def load_script():
    spec = importlib.util.spec_from_file_location("tuning_ab", REPO / "tests/device/tuning_ab.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# the launcher index (lume-index index.rs): 32-byte header, 32-byte records sorted by name,
# then the string table; and paths that need escaping in a TOML key
GAME_PATHS = ["./alpha.zip", './Quote "B" \\ back.zip', "./sub/gamma.zip"]


def write_index(path: Path, paths=GAME_PATHS) -> None:
    import struct
    strings, records = b"", b""
    for i, p in enumerate(paths):
        name = f"Game {i}".encode()
        raw = p.encode()
        noff = len(strings)
        strings += name
        poff = len(strings)
        strings += raw
        records += struct.pack("<8I", noff, len(name), poff, len(raw), 0, 0, 0, 0xFFFFFFFF)
    head = b"LUMEIDX1" + struct.pack("<IIQII", len(paths), len(strings), 0, 0, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(head + records + strings)


@pytest.fixture
def card(fake_root, monkeypatch):
    root, home = fake_root
    lume = root / "storage/system/lume"
    monkeypatch.setattr(tuning, "INDEX_DIR", str(lume / "cache/index"))
    monkeypatch.setattr(tuning, "GAMES_DIR", str(lume / "games"))
    monkeypatch.setattr(tuning, "TUNING_SYSTEMS", str(lume / "systems.d/zz-lume-tuning.toml"))
    monkeypatch.setattr(tuning, "CORES_DIR", str(root / "libretro"))
    write_index(lume / "cache/index/arcade.bin")
    return root, lume


@pytest.mark.parametrize("position", [1, 2, 3])
def test_game_core_is_written_for_the_game_path_and_never_printed(card, position):
    import tomllib
    root, lume = card
    out = sh(tuning.game_core_command("arcade", position, "mame2000"))
    assert out.strip() == "applied"
    assert "alpha" not in out and "Quote" not in out and "gamma" not in out
    games = tomllib.loads((lume / "games/arcade.toml").read_text())
    # the key the launcher looks up: the index path of game N (options::game)
    assert games == {GAME_PATHS[position - 1]: {
        "emulator": {"runner": "retroarch", "core": "mame2000"}}}


def test_game_core_past_the_index_is_an_error_without_a_path(card):
    root, lume = card
    out = sh(tuning.game_core_command("arcade", 4, "mame2000"))
    assert out.strip() == "error game 4 of arcade is not in the launcher index"
    with pytest.raises(TuningError, match="not in the launcher index"):
        tuning.expect_applied(out, "per-game core")
    assert not (lume / "games/arcade.toml").exists()
    out = sh(tuning.game_core_command("nes", 1, "fceumm"))         # no index at all
    assert out.startswith("error ")


def test_per_game_option_is_applied_and_given_back(card):
    root, lume = card
    games = lume / "games/arcade.toml"
    games.parent.mkdir(parents=True)
    original = '["./alpha.zip"]\naspect = "4:3"\n'
    games.write_text(original)
    assert sh(tuning.save_command("fbneo", games_system="arcade")).strip() == "saved"
    sh(tuning.card_cores_command("arcade", ["mame2000"]))
    systems = lume / "systems.d/zz-lume-tuning.toml"
    import tomllib
    assert tomllib.loads(systems.read_text()) == {"system": [
        {"id": "arcade", "emulators": [{"runner": "retroarch", "core": "mame2000"}]}]}
    # A: no per-game option; B: only the measured game in the other core
    assert sh(tuning.default_core_command("arcade")).strip() == "applied"
    assert not games.exists()
    sh(tuning.restore_command(keep=True))
    assert games.read_text() == original
    sh(tuning.game_core_command("arcade", 2, "mame2000"))
    assert "mame2000" in games.read_text()
    sh(tuning.restore_command(keep=True))                        # between runs
    assert games.read_text() == original and systems.exists()
    sh(tuning.restore_command(keep=False))                       # end of the sequence
    assert games.read_text() == original and not systems.exists()
    assert not (root / "run/tuning").exists()


def test_interrupted_comparison_is_given_back_at_the_next_save(card):
    root, lume = card
    games = lume / "games/arcade.toml"
    sh(tuning.save_command("fbneo", games_system="arcade"))     # no games file before
    sh(tuning.card_cores_command("arcade", ["mame2000"]))
    sh(tuning.game_core_command("arcade", 1, "mame2000"))
    assert games.exists()
    sh(tuning.save_command("fceumm"))                            # crash, then another plan
    assert not games.exists()
    assert not (lume / "systems.d/zz-lume-tuning.toml").exists()


def test_core_installed_command(card):
    root, _ = card
    assert sh(tuning.core_installed_command("mame2000")).strip() == tuning.MISSING
    (root / "libretro").mkdir()
    (root / "libretro/mame2000_libretro.so").write_bytes(b"\x7fELF")
    assert sh(tuning.core_installed_command("mame2000")).strip() == tuning.INSTALLED
    with pytest.raises(TuningError):
        tuning.core_installed_command("../x")


def test_exit_class_keeps_only_the_code_and_the_way_it_ended():
    line = "2026-11-20T10:00:00 51 game FAIL arcade retroarch mame2000 exit=1 end=normal secs=2"
    assert tuning.exit_class(line) == "exit=1 end=normal"
    assert tuning.exit_class("2026-11-20T10:00:00 51 game FAIL arcade x y z") == "ended"


# --- results, picks and the report by core and family ----------------------------------

def core_result(pos, core, status=tuning.OPENED, b=None, a=None, reason=""):
    a = a if a is not None else (run_metrics(clock=1000, drawn=50), run_metrics(clock=990,
                                                                                drawn=50))
    return tuning.CoreResult("2026-11-20", "b42", "arcade", pos, "fbneo", core, status,
                             reason, a if status != tuning.NOT_INSTALLED else (), b)


RESULTS = [
    core_result(1, "mame2003_plus", b=run_metrics(clock=700, drawn=60)),
    core_result(1, "mame2000", tuning.NOT_OPEN, a=(run_metrics(clock=1000, drawn=50),),
                reason="exit=1 end=normal"),
    core_result(2, "mame2003_plus", b=run_metrics(clock=800, speed=0.9, drawn=45)),
    core_result(2, "mame2000", b=run_metrics(clock=900, drawn=52)),
    core_result(1, "fbalpha2012", tuning.NOT_INSTALLED),
    core_result(2, "fbalpha2012", tuning.NOT_INSTALLED),
]


def test_results_round_trip_through_the_private_file(tmp_path):
    path = tmp_path / "out/ga36-cores.jsonl"
    for r in RESULTS:
        tuning.save_result(path, r)
    with path.open("a") as f:
        f.write('{"broken": \n')                                 # an interrupted write
    back = tuning.load_results(path)
    assert back == RESULTS
    with pytest.raises(TuningError):
        tuning.save_result(path, core_result(1, "mame2000", reason="Some Game (USA)"))


def test_pick_is_the_lowest_clock_at_full_speed():
    chosen = tuning.picks(RESULTS)
    assert chosen == {("arcade", 1): "mame2003_plus", ("arcade", 2): "mame2000"}
    # nothing at full speed: the highest core speed
    slow = [core_result(3, "mame2000", b=run_metrics(speed=0.8),
                        a=(run_metrics(speed=0.7), run_metrics(speed=0.7)))]
    assert tuning.picks(slow) == {("arcade", 3): "mame2000"}


def test_latest_measurement_replaces_the_old_one():
    old = core_result(1, "mame2000", tuning.NOT_OPEN, reason="timeout")
    new = core_result(1, "mame2000", b=run_metrics(clock=600))
    assert tuning.latest_results([old, new]) == [new]


def test_families_file_format(tmp_path):
    f = tmp_path / "families.toml"
    f.write_text('[arcade]\n1 = "cps1"\n2 = "neogeo"\n')
    fam = tuning.load_families(f)
    assert fam == {"arcade": {1: "cps1", 2: "neogeo"}}
    assert tuning.family_of(fam, "arcade", 2) == "neogeo"
    assert tuning.family_of(fam, "arcade", 5) == tuning.UNKNOWN_FAMILY
    assert tuning.family_of({}, "arcade", 1) == tuning.NO_FAMILY
    assert tuning.load_families(tmp_path / "absent.toml") == {}
    for bad in ('[arcade]\nx = "cps1"\n', '[arcade]\n1 = "Some Game.zip"\n',
                '[arcade]\n1 = "a/b"\n', 'arcade = 3\n'):
        f.write_text(bad)
        with pytest.raises(TuningError):
            tuning.load_families(f)


def test_report_section_by_core_and_family_has_no_game(tmp_path):
    report = tmp_path / "ga36.md"
    fam = {"arcade": {1: "cps1", 2: "neogeo"}}
    tuning.write_cores_section(report, "ga36", RESULTS, fam)
    text = report.read_text()
    assert text.startswith(tuning.report_header("ga36"))
    rows = {(r["core"], r["família"]): r for r in tuning.parse_cores_section(text)}
    assert set(rows) == {("fbneo", "cps1"), ("fbneo", "neogeo"), ("mame2003_plus", "cps1"),
                         ("mame2003_plus", "neogeo"), ("mame2000", "cps1"),
                         ("mame2000", "neogeo"), ("fbalpha2012", "cps1"),
                         ("fbalpha2012", "neogeo")}
    m1 = rows[("mame2000", "cps1")]
    assert (m1["jogos"], m1["abrem"], m1["velocidade cheia"]) == ("1", "0 de 1", "0 de 1")
    # against the mean of every A run of that game (1000, 990 and 1000 MHz)
    assert rows[("mame2003_plus", "cps1")]["contra o padrão"] == "clock -297; quadros +10.0"
    assert rows[("mame2003_plus", "cps1")]["escolhido em"] == "1"
    assert rows[("mame2003_plus", "neogeo")]["velocidade cheia"] == "0 de 1"
    assert rows[("fbalpha2012", "neogeo")]["abrem"] == "não instalado"
    assert rows[("fbneo", "cps1")]["contra o padrão"] == "padrão"
    for word in ("Quote", "gamma", ".zip", "#1", "#2", "exit=1"):
        assert word not in text.split(tuning.CORES_BEGIN)[1]
    assert tuning.parse_report(text) == []                       # not A/B rows


def test_report_section_without_families_groups_by_core(tmp_path):
    report = tmp_path / "ga36.md"
    tuning.write_cores_section(report, "ga36", RESULTS, {})
    rows = tuning.parse_cores_section(report.read_text())
    assert {r["família"] for r in rows} == {tuning.NO_FAMILY}
    m3 = next(r for r in rows if r["core"] == "mame2003_plus")
    assert (m3["jogos"], m3["abrem"], m3["velocidade cheia"]) == ("2", "2 de 2", "1 de 2")


def test_ab_rows_and_the_cores_section_live_together(tmp_path):
    report = tmp_path / "ga36.md"
    tuning.write_cores_section(report, "ga36", RESULTS[:1], {})
    a1, a2 = run_metrics(clock=1000), run_metrics(clock=990)
    tuning.append_row(report, "ga36", tuning.baseline_row("2026-11-20", "b1", core_plan(),
                                                          a1, a2))
    tuning.write_cores_section(report, "ga36", RESULTS, {})     # rewritten, rows kept
    text = report.read_text()
    assert [r["variante"] for r in tuning.parse_report(text)] == ["baseline"]
    assert text.index("| fceumm |") < text.index(tuning.CORES_BEGIN)
    assert text.count(tuning.CORES_BEGIN) == 1 and len(tuning.parse_cores_section(text)) == 4


def test_report_section_refuses_a_name_in_a_family():
    with pytest.raises(TuningError):
        tuning.cores_section(RESULTS, {"arcade": {1: "Some Game.zip"}})


# --- the driver: B that does not open does not stop the measurement ---------------------

class EventConsole:
    """events.log and the other answers of the console for open_core / run_sequences."""

    def __init__(self):
        self.lines = []
        self.commands = []

    def __call__(self, cmd):
        from lume_tool import dev_run
        self.commands.append(cmd)
        if cmd == dev_run.pending_command():
            return ""
        if cmd == dev_run.count_command():
            return f"{len(self.lines)}\n"
        if "-v s=" in cmd:
            skip = int(cmd.split("-v s=")[1].split()[0])
            return "\n".join(self.lines[skip:] + [f"{dev_run.COUNT_MARK}{len(self.lines)}"])
        if cmd == tuning.power_check_command():
            return ""
        if cmd == tuning.build_id_command():
            return "b42\n"
        if "date +%Y" in cmd:                       # tuning_ab.NOW_COMMAND
            return getattr(self, "now_answer", "-\nT\n")
        if "_libretro.so ]" in cmd:
            return tuning.MISSING + "\n" if "fbalpha2012" in cmd else tuning.INSTALLED + "\n"
        return "saved applied\n"


def event_ctx(console, on_open):
    from lume_tool import dev_run

    class Clock:
        t = 0.0
    clock = Clock()

    def sleep(s):
        clock.t += s
    return dev_run.Context("h", run=console, keys=lambda s: None, sleep=sleep,
                           now=lambda: clock.t, open_game=lambda s, p: on_open(),
                           close_game=lambda: console.lines.append(
                               "T 1 game OK arcade retroarch x exit=0 end=quit-combo secs=9"))


@pytest.mark.parametrize("events,reason", [
    (["T 1 game FAIL arcade retroarch mame2000 start-failed no core"], "start-failed"),
    ([], "timeout"),
    (["T 1 game OK arcade retroarch fbneo start"], "other-core"),
    (["T 1 game OK arcade retroarch mame2000 start",
      "T 2 game FAIL arcade retroarch mame2000 exit=1 end=normal secs=1"], "exit=1 end=normal"),
])
def test_open_core_reports_why_b_did_not_open(events, reason):
    mod = load_script()
    console = EventConsole()
    ctx = event_ctx(console, lambda: console.lines.extend(events))
    with pytest.raises(mod.NotOpened, match=f"^{reason}$"):
        mod.open_core(ctx, tuning.CorePlan("fbneo", "arcade", 1), "mame2000", 30)


def test_alternatives_of_one_game_are_one_group():
    # user, 2026-11-20: the default core is measured once before and once after all the
    # alternatives of a game, not around each one
    mod = load_script()
    plan = tuning.validate_plan(tomllib.loads(
        (REPO / "tests/device/tuning/arcade-cores.toml").read_text(encoding="utf-8")))
    groups = mod.core_groups(tuning.build_sequences(plan, "ga36", set()))
    assert len(groups) == 8
    assert all(len(g) == 3 and len({id(s.core) for s in g}) == 1 for g in groups)
    assert [s.variant.core for s in groups[0]] == ["fbalpha2012", "mame2003_plus", "mame2000"]


def test_an_old_end_of_another_boot_is_not_the_end_of_the_game_just_opened():
    # J1, 2026-11-20: the card log had the end of a game of the boot before past the line
    # offset, and the comparison stopped at once with "did not stay open"
    mod = load_script()
    console = EventConsole()
    console.now_answer = "225\n2026-11-20T00:09:20\n"
    ctx = event_ctx(console, lambda: console.lines.extend([
        "2026-11-19T22:28:23 223 game OK arcade retroarch fbneo exit=0 end=menu-quit secs=57",
        "2026-11-20T00:09:10 225 game OK arcade retroarch fbneo exit=0 end=menu-quit secs=5",
        "2026-11-20T00:09:21 225 game OK arcade retroarch mame2000 start"]))
    mod.open_core(ctx, tuning.CorePlan("fbneo", "arcade", 1), "mame2000", 30)


def test_open_core_passes_when_the_game_stays_open():
    mod = load_script()
    console = EventConsole()
    ctx = event_ctx(console, lambda: console.lines.append(
        "T 1 game OK arcade retroarch mame2000 start"))
    mod.open_core(ctx, tuning.CorePlan("fbneo", "arcade", 1), "mame2000", 30)


def test_not_open_and_not_installed_do_not_stop_the_sequence(tmp_path, monkeypatch, capsys):
    mod = load_script()
    plan = tuning.validate_plan({"consoles": ["ga36"], "core": [
        {"core": "fbneo", "system": "arcade", "positions": [1, 2],
         "variant": [{"core": "mame2000"}, {"core": "fbalpha2012"}]}]})
    seqs = tuning.build_sequences(plan, "ga36", set())
    console = EventConsole()
    runs = []

    def fake_run(ctx, seq, run, warmup, measure):
        runs.append((seq.core.position, run.label, run.variant.core if run.variant else None))
        if run.variant and seq.core.position == 1:
            raise mod.NotOpened("exit=1 end=normal")
        return run_metrics(clock=800 if run.variant else 1000)
    monkeypatch.setattr(mod, "core_run", fake_run)
    report, results = tmp_path / "ga36.md", tmp_path / "out/ga36-cores.jsonl"
    rc = mod.run_sequences("h", "ga36", seqs, report, 30, 120, results,
                           {"arcade": {1: "cps1", 2: "neogeo"}}, ctx=event_ctx(console, None))
    assert rc == 0
    # game 1: A1, B (does not open), no A2; fbalpha2012 is not installed: nothing runs
    assert runs == [(1, "A1", None), (1, "B", "mame2000"),
                    (2, "A1", None), (2, "B", "mame2000"), (2, "A2", None)]
    got = [(r.position, r.core, r.status, r.reason) for r in tuning.load_results(results)]
    assert got == [(1, "mame2000", "not-open", "exit=1 end=normal"),
                   (1, "fbalpha2012", "not-installed", ""),
                   (2, "mame2000", "opened", ""),
                   (2, "fbalpha2012", "not-installed", "")]
    # every opened sequence is given back: one final restore per installed core
    assert sum(1 for c in console.commands if "rm -f " + tuning.TUNING_SYSTEMS in c
               and c.startswith("if [ -d")) >= 2
    rows = {(r["core"], r["família"]): r for r in tuning.parse_cores_section(report.read_text())}
    assert rows[("mame2000", "cps1")]["abrem"] == "0 de 1"
    assert rows[("mame2000", "neogeo")]["abrem"] == "1 de 1"
    assert rows[("fbalpha2012", "cps1")]["abrem"] == "não instalado"
    out = capsys.readouterr().out
    assert "-> mame2000 does not open (exit=1 end=normal)" in out
    assert "core fbalpha2012 is not installed" in out
    assert "arcade #2: mame2000" in out and "arcade #1: fbneo" in out
