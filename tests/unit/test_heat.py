"""Heat guard (design D15): sensor choice, pause/resume/abort and the summary."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from r36os import heat


def _chip(root: Path, idx: int, name: str, inputs: dict[int, tuple[str | None, float]],
          crit: dict[int, float] | None = None) -> Path:
    hw = root / f"hwmon{idx}"
    hw.mkdir(parents=True)
    (hw / "name").write_text(name + "\n")
    for n, (label, temp) in inputs.items():
        (hw / f"temp{n}_input").write_text(f"{int(temp * 1000)}\n")
        if label is not None:
            (hw / f"temp{n}_label").write_text(label + "\n")
    for n, c in (crit or {}).items():
        (hw / f"temp{n}_crit").write_text(f"{int(c * 1000)}\n")
    return hw


@pytest.fixture
def hwmon(tmp_path: Path) -> Path:
    root = tmp_path / "hwmon"
    _chip(root, 0, "nvme", {1: ("Composite", 28.0), 2: ("Sensor 1", 30.0)}, {1: 89.85})
    _chip(root, 1, "nct6798", {1: ("SYSTIN", 35.0), 4: ("AUXTIN0", 90.0),
                               7: ("AUXTIN3", 97.0)})
    _chip(root, 2, "k10temp", {1: ("Tctl", 37.0), 3: ("Tccd1", 35.0)})
    return root


def _set(sensor: heat.Sensor, temp: float) -> None:
    sensor.path.write_text(f"{int(temp * 1000)}\n")


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class Runner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> None:
        self.calls.append(list(args))


def _guard(hwmon: Path, **kw) -> tuple[heat.HeatGuard, Clock, Runner, io.StringIO]:
    clock, runner, out = Clock(), Runner(), io.StringIO()
    g = heat.guard_from_env(root=hwmon, env=kw.pop("env", {}), clock=clock, runner=runner,
                            containers=lambda: ["c1", "c2"], out=out, **kw)
    return g, clock, runner, out


def test_picks_k10temp_tctl_and_ignores_aux_inputs(hwmon: Path) -> None:
    sensors = heat.scan(hwmon)
    cpu = heat.find_cpu(sensors, {})
    assert (cpu.chip, cpu.label, cpu.read()) == ("k10temp", "Tctl", 37.0)
    nvme = heat.find_nvme(sensors)
    assert [(s.label, s.crit) for s in nvme] == [("Composite", 89.85)]


def test_aux_input_at_97_never_pauses(hwmon: Path) -> None:
    g, clock, runner, _ = _guard(hwmon)
    for _ in range(5):
        g.step()
        clock.t += 2
    assert runner.calls == []
    assert g.summary.max_cpu == 37.0


def test_coretemp_package_is_used_on_intel(tmp_path: Path) -> None:
    root = tmp_path / "hwmon"
    _chip(root, 0, "coretemp", {1: ("Package id 0", 50.0), 2: ("Core 0", 48.0)})
    cpu = heat.find_cpu(heat.scan(root), {})
    assert (cpu.chip, cpu.label) == ("coretemp", "Package id 0")


def test_zenpower_is_used(tmp_path: Path) -> None:
    root = tmp_path / "hwmon"
    _chip(root, 0, "zenpower", {1: ("Tdie", 44.0), 2: ("Tctl", 44.0)})
    assert heat.find_cpu(heat.scan(root), {}).chip == "zenpower"


def test_missing_cpu_sensor_fails_and_says_how_to_choose(tmp_path: Path) -> None:
    root = tmp_path / "hwmon"
    _chip(root, 0, "nct6798", {7: ("AUXTIN3", 97.0)})
    with pytest.raises(heat.SensorNotFound) as e:
        heat.guard_from_env(root=root, env={})
    msg = str(e.value)
    assert "R36OS_TEMP_SENSOR" in msg
    assert "nct6798:AUXTIN3" in msg


def test_env_sensor_chooses_another_input(hwmon: Path) -> None:
    sensors = heat.scan(hwmon)
    s = heat.find_cpu(sensors, {"R36OS_TEMP_SENSOR": "nct6798:SYSTIN"})
    assert (s.chip, s.label) == ("nct6798", "SYSTIN")
    path = str(hwmon / "hwmon2" / "temp3_input")
    assert heat.find_cpu(sensors, {"R36OS_TEMP_SENSOR": path}).label == "Tccd1"
    with pytest.raises(heat.SensorNotFound):
        heat.find_cpu(sensors, {"R36OS_TEMP_SENSOR": "nope:x"})


def test_temp_max_from_env() -> None:
    assert heat.temp_max({}) == 85.0
    assert heat.temp_max({"R36OS_TEMP_MAX": "80"}) == 80.0
    with pytest.raises(heat.HeatError):
        heat.temp_max({"R36OS_TEMP_MAX": "hot"})


def test_start_line_names_sensor_and_reading(hwmon: Path) -> None:
    g, *_ = _guard(hwmon)
    line = g.start_line()
    assert "CPU 37.0 C" in line and "k10temp Tctl" in line
    assert "NVMe 28.0 C" in line and "84.8" in line


def test_pause_at_limit_and_resume_ten_below(hwmon: Path) -> None:
    g, clock, runner, out = _guard(hwmon)
    g.step()
    _set(g.cpu, 85.0)
    clock.t = 2
    g.step()
    assert runner.calls == [["pause", "c1", "c2"]]
    assert "pausing 2 build containers" in out.getvalue()
    _set(g.cpu, 76.0)          # above max - 10: stays paused
    clock.t = 4
    g.step()
    assert len(runner.calls) == 1
    _set(g.cpu, 75.0)
    clock.t = 6
    g.step()
    assert runner.calls[-1] == ["unpause", "c1", "c2"]
    assert g.summary.time_paused == 4.0
    assert g.summary.time_above == 2.0   # only the 85 C sample, from 2 s to 4 s
    assert g.summary.pauses == 1
    assert g.summary.max_cpu == 85.0


def test_custom_limit(hwmon: Path) -> None:
    g, clock, runner, _ = _guard(hwmon, env={"R36OS_TEMP_MAX": "70"})
    _set(g.cpu, 70.0)
    g.step()
    assert runner.calls == [["pause", "c1", "c2"]]


def test_nvme_near_its_max_pauses(hwmon: Path) -> None:
    g, clock, runner, _ = _guard(hwmon)
    nvme = g.nvme[0]
    _set(nvme, 84.0)
    g.step()
    assert runner.calls == []
    _set(nvme, 85.0)           # crit 89.85 - 5 = 84.85
    clock.t = 2
    g.step()
    assert runner.calls == [["pause", "c1", "c2"]]
    _set(nvme, 80.0)           # CPU cool but NVMe still within 10 of its limit
    clock.t = 4
    g.step()
    assert len(runner.calls) == 1
    _set(nvme, 70.0)
    clock.t = 6
    g.step()
    assert runner.calls[-1] == ["unpause", "c1", "c2"]
    assert g.summary.max_nvme == 85.0


def test_abort_when_hot_after_60s_paused(hwmon: Path) -> None:
    g, clock, runner, out = _guard(hwmon)
    _set(g.cpu, 93.0)
    g.step()                   # pauses at t=0
    for t in range(2, 60, 2):
        clock.t = t
        g.step()
        assert g.error is None
    clock.t = 60
    g.step()
    assert g.error is not None
    assert runner.calls[-2:] == [["unpause", "c1", "c2"], ["kill", "c1", "c2"]]
    with pytest.raises(heat.HeatAbort) as e:
        g.check()
    assert "93.0 C" in str(e.value) and "k10temp Tctl" in str(e.value)


def test_no_abort_when_paused_but_below_92(hwmon: Path) -> None:
    g, clock, runner, _ = _guard(hwmon)
    _set(g.cpu, 90.0)
    for t in range(0, 200, 2):
        clock.t = t
        g.step()
    g.check()
    assert runner.calls == [["pause", "c1", "c2"]]
    assert g.summary.time_paused == 198.0


def test_log_only_records_and_never_pauses(hwmon: Path) -> None:
    g, clock, runner, _ = _guard(hwmon, log_only=True)
    _set(g.cpu, 95.0)
    for t in range(0, 120, 2):
        clock.t = t
        g.step()
    assert runner.calls == []
    g.check()
    s = g.summary
    assert s.max_cpu == 95.0 and s.max_nvme == 28.0
    assert s.time_above == 118.0 and s.time_paused == 0.0
    assert "log only" in g.start_line()


def test_stop_resumes_paused_containers_and_returns_summary(hwmon: Path) -> None:
    g, clock, runner, _ = _guard(hwmon)
    _set(g.cpu, 88.0)
    g.step()
    summary = g.stop()
    assert runner.calls[-1] == ["unpause", "c1", "c2"]
    lines = summary.lines()
    assert "max CPU 88.0 C" in lines[0] and "max NVMe 28.0 C" in lines[0]
    assert "paused" in lines[1]


def test_thread_samples_and_stops(hwmon: Path) -> None:
    g, clock, runner, out = _guard(hwmon, interval=0.01)
    with g:
        pass
    assert g.summary.samples >= 1
    assert out.getvalue().startswith("heat guard: CPU 37.0 C")
