"""A/B measurement of the core tuning (game-experience-tuning 5.1, lume_tool.tuning and
tests/device/tuning_ab.py): plan, sequences, remote commands, aggregation of recorded
(synthetic) samples, the spec's acceptance criterion and the report that refuses game names
and paths. No console: the remote commands that touch files run against a fake root."""
from __future__ import annotations

import importlib.util
import subprocess
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

def test_sequences_baseline_first_then_aba_per_variant():
    plan = tuning.validate_plan(PLAN)
    seqs = tuning.build_sequences(plan, "ga36", baselines=set())
    assert [(s.core.core, s.name) for s in seqs] == [
        ("fceumm", "baseline"), ("fceumm", "threaded-off"), ("fceumm", "sound-high"),
        ("gpsp", "baseline")]
    assert [r.label for r in seqs[0].runs] == ["A1", "A2"]
    assert [(r.label, r.variant is not None) for r in seqs[1].runs] == [
        ("A1", False), ("B", True), ("A2", False)]


def test_sequences_skip_a_measured_baseline_and_filter():
    plan = tuning.validate_plan(PLAN)
    seqs = tuning.build_sequences(plan, "ga36", baselines={"fceumm", "gpsp"})
    assert [s.name for s in seqs] == ["threaded-off", "sound-high"]
    only = tuning.build_sequences(plan, "ga36", {"fceumm"}, only="fceumm:sound-high")
    assert [s.name for s in only] == ["sound-high"]
    again = tuning.build_sequences(plan, "ga36", {"fceumm"}, rebaseline=True, only="fceumm")
    assert [s.name for s in again] == ["baseline", "threaded-off", "sound-high"]
    with pytest.raises(TuningError):
        tuning.build_sequences(plan, "ga36", set(), only="nestopia")
    with pytest.raises(TuningError):
        tuning.build_sequences(plan, "vm", set())


def test_dry_run_text_names_no_game():
    plan = tuning.validate_plan(PLAN)
    text = tuning.format_sequences(tuning.build_sequences(plan, "ga36", set()), "ga36")
    assert "console ga36: 4 sequence(s), 10 run(s) of 30+120 s" in text
    assert "fceumm threaded-off: system nes game #1 (retroarch)" in text
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
        assert text == tuning.report_header(console)       # header only, no measurement yet


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
