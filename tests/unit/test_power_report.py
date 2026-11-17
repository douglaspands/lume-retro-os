import io
import tarfile

from r36os import power_report as pr

SECRET = "Secret Game Title"
ROM_PATH = "/roms/nes/secret-game.nes"

NEW_HEADER = ("time,uptime_s,temp_cpu_thermal_c,freq_policy0_mhz,cpu0_pct,cpu1_pct,"
              "bat_ma,bat_status,frontend,core,content,fps,fps_nominal,logd_cpu_pct,"
              "sugov0_cpu_pct")
NEW_METRICS = "\n".join([
    NEW_HEADER,
    f"2026-11-17T10:00:05,5,50.0,648,10,20,300,Discharging,launcher,,,,,1.0,2.0",
    f"2026-11-17T10:00:10,10,52.0,648,10,20,310,Discharging,launcher,,,,,1.0,2.0",
    f"2026-11-17T10:00:15,15,55.0,1008,40,60,600,Discharging,game,nes,{SECRET},60,60,0.5,1.0",
    f"2026-11-17T10:00:20,20,61.5,1200,60,80,620,Discharging,game,nes,{SECRET},54,60,0.5,1.0",
    f"2026-11-17T10:00:25,25,60.0,1200,60,80,-1,Charging,game,nes,{SECRET},57,60,0.5,1.0",
    "2026-11-17T10:00:3",     # truncated last line
]) + "\n"

# an old sample file: no fps, no logd/sugov, no bat columns
OLD_METRICS = ("time,uptime_s,temp_cpu_thermal_c,freq_policy0_mhz,cpu0_pct,frontend,core,content\n"
               f"2026-11-10T09:00:05,5,45.0,600,30,game,snes,{SECRET}\n"
               f"2026-11-10T09:00:10,10,47.0,600,50,game,snes,{SECRET}\n")

EVENTS = [
    "2026-11-10T08:59:00 4 boot OK started: ga36 kernel 6.1",
    "2026-11-17T10:00:00 5 power OK profile: menu -> menu",
    "2026-11-17T10:00:12 5 power OK profile: game nes fceumm -> light",
    "2026-11-17T10:00:13 5 power OK shutdown: battery critical",
    "2026-11-17T10:00:14 5 power FAIL profile: game -> bogus: clock not in table",
    f"2026-11-17T10:00:21 5 game FAIL slow: core=fceumm content={SECRET} path={ROM_PATH}",
    f"2026-11-17T10:00:22 5 game OK opened: core=FCEUmm content={SECRET}",
    "garbage line",
]


def source(since_metrics=None):
    src = pr.Source(events=EVENTS)
    src.metrics = {4: OLD_METRICS, 5: NEW_METRICS}
    return src


def rows_by_key(rows):
    return {(r["scenario"], r["system"], r["profile"]): r for r in rows}


def test_groups_by_scenario_system_profile():
    rows = rows_by_key(pr.build_report(source()))
    assert set(rows) == {("menu", "-", "menu"), ("game", "nes", "light"),
                         ("game", "snes", "-")}
    game = rows[("game", "nes", "light")]
    assert game["samples"] == 3
    assert game["bat_ma"] == 610          # the Charging sample is excluded
    assert round(game["fps_pct"], 1) == 95.0   # (100 + 90 + 95) / 3
    assert game["slow"] == 1
    assert game["temp_max_c"] == 61.5
    assert round(game["clock_mhz"]) == 1136
    assert game["cpu_cores_pct"] == "53/73"
    assert round(game["busiest_mean_pct"]) == 73
    assert game["logd_cpu_pct"] == 0.5 and game["sugov_cpu_pct"] == 1.0


def test_old_samples_without_new_columns():
    rows = rows_by_key(pr.build_report(source()))
    old = rows[("game", "snes", "-")]
    assert old["samples"] == 2
    assert old["bat_ma"] is None and old["fps_pct"] is None
    assert old["logd_cpu_pct"] is None and old["sugov_cpu_pct"] is None
    assert old["clock_mhz"] == 600 and old["temp_max_c"] == 47.0
    assert old["slow"] == 0


def test_since_skips_older_boots():
    rows = pr.build_report(source(), since=5)
    assert all(r["system"] != "snes" for r in rows)


def test_idle_from_power_events():
    src = pr.Source(events=["2026-11-17T10:00:00 5 power OK profile: idle -> idle"],
                    metrics={5: NEW_METRICS})
    assert ("idle", "-", "idle") in rows_by_key(pr.build_report(src))


def test_no_game_name_or_path_in_output():
    rows = pr.build_report(source())
    out = pr.render_table(rows) + pr.render_csv(rows)
    assert SECRET not in out and "secret" not in out.lower()
    assert ROM_PATH not in out and ".nes" not in out


def test_content_as_core_label_is_rejected():
    text = NEW_HEADER + "\n" + f"2026-11-17T10:00:15,15,55,1008,1,1,1,Discharging,game,{SECRET},x,60,60,,\n"
    rows = pr.build_report(pr.Source(metrics={5: text}))
    assert rows[0]["system"] == "-" and SECRET not in pr.render_csv(rows)


def test_render_csv_header_and_empty_cells():
    csv_text = pr.render_csv(pr.build_report(source()))
    lines = csv_text.splitlines()
    assert lines[0].split(",") == pr.COLUMNS
    assert any(line.startswith("game,snes,-,2,,") for line in lines)


def test_load_dir_reads_rotated_events_and_metrics(tmp_path):
    (tmp_path / "metrics").mkdir()
    (tmp_path / "metrics" / "boot-5.csv").write_text(NEW_METRICS)
    (tmp_path / "events.1.log").write_text(EVENTS[0] + "\n")
    (tmp_path / "events.log").write_text("\n".join(EVENTS[1:]) + "\n")
    src = pr.load_dir(tmp_path)
    assert src.events[0] == EVENTS[0] and list(src.metrics) == [5]
    assert pr.build_report(src)


def test_load_tar_matches_load_dir():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, body in {"events.log": "\n".join(EVENTS), "metrics/boot-5.csv": NEW_METRICS}.items():
            data = body.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    src = pr.load_tar(buf.getvalue())
    assert src.events == EVENTS and src.metrics == {5: NEW_METRICS}


def test_main_from_dir_writes_csv(tmp_path, capsys):
    logs = tmp_path / "logs"
    (logs / "metrics").mkdir(parents=True)
    (logs / "metrics" / "boot-5.csv").write_text(NEW_METRICS)
    (logs / "events.log").write_text("\n".join(EVENTS) + "\n")
    out = tmp_path / "cache"
    assert pr.main_power_report(None, None, None, logs, out_dir=out) == 0
    assert len(list(out.glob("power-report-*.csv"))) == 1
    assert SECRET not in capsys.readouterr().out


def test_main_from_missing_dir_fails(tmp_path, capsys):
    assert pr.main_power_report(None, None, None, tmp_path / "nope") == 1
