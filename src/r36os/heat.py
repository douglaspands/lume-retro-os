"""Heat guard for the build PC (design D15).

A thread samples the processor temperature (and the NVMe one) every 2 s during a build.
When the CPU reaches the limit, or the NVMe gets close to its own limit, the build
containers are paused with `podman pause` and resumed when the CPU has cooled 10 degrees
below the limit. If the CPU stays above 92 degrees for 60 s while paused, the guard kills the
containers and the build aborts with the reading and the sensor.

Only the processor's own hwmon is trusted (`k10temp` Tctl, `zenpower`, `coretemp` Package):
auxiliary motherboard inputs (e.g. `nct6798` AUXTIN*) read garbage with nothing wired.

The guard also has a log-only mode: it samples and records, and never pauses.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping, TextIO

HWMON_ROOT = Path("/sys/class/hwmon")
ENV_SENSOR = "R36OS_TEMP_SENSOR"
ENV_MAX = "R36OS_TEMP_MAX"
DEFAULT_MAX = 85.0
RESUME_DELTA = 10.0       # resume when CPU <= max - 10
NVME_MARGIN = 5.0         # pause when NVMe >= its max - 5
NVME_DEFAULT_MAX = 70.0   # used when the drive does not report crit/max
ABORT_TEMP = 92.0
ABORT_AFTER = 60.0        # seconds paused above ABORT_TEMP
INTERVAL = 2.0
# Label every build/pkg container carries (Container.argv) so the guard can find them.
BUILD_LABEL = "r36os.build=1"

# hwmon name -> accepted input labels, in order of preference.
CPU_CHIPS: dict[str, tuple[str, ...]] = {
    "k10temp": ("Tctl", "Tdie"),
    "zenpower": ("Tctl", "Tdie"),
    "coretemp": ("Package id 0",),
}


class HeatError(RuntimeError):
    """Base class for heat guard errors."""


class SensorNotFound(HeatError):
    pass


class HeatAbort(HeatError):
    pass


@dataclass(frozen=True)
class Sensor:
    chip: str          # hwmon `name`
    label: str         # tempN_label, or the input file name when unlabelled
    path: Path         # tempN_input
    crit: float | None = None

    def read(self) -> float:
        return int(self.path.read_text().strip()) / 1000.0

    def __str__(self) -> str:
        return f"{self.chip} {self.label} ({self.path})"


def _read_milli(path: Path) -> float | None:
    try:
        return int(path.read_text().strip()) / 1000.0
    except (OSError, ValueError):
        return None


def scan(root: Path = HWMON_ROOT) -> list[Sensor]:
    """All temperature inputs under the hwmon root."""
    sensors: list[Sensor] = []
    if not root.is_dir():
        return sensors
    for hw in sorted(root.iterdir()):
        try:
            chip = (hw / "name").read_text().strip()
        except OSError:
            continue
        for inp in sorted(hw.glob("temp*_input")):
            stem = inp.name[: -len("_input")]
            lab = hw / f"{stem}_label"
            try:
                label = lab.read_text().strip() if lab.exists() else stem
            except OSError:
                label = stem
            crit = _read_milli(hw / f"{stem}_crit")
            if crit is None:
                crit = _read_milli(hw / f"{stem}_max")
            sensors.append(Sensor(chip, label, inp, crit))
    return sensors


def _match(sensors: Iterable[Sensor], spec: str) -> Sensor | None:
    """`R36OS_TEMP_SENSOR`: a tempN_input path, `chip:label` or `chip`."""
    sensors = list(sensors)
    p = Path(spec)
    if p.is_absolute():
        for s in sensors:
            if s.path == p:
                return s
        if p.exists():
            return Sensor("custom", p.name, p)
        return None
    chip, _, label = spec.partition(":")
    for s in sensors:
        if s.chip == chip and (not label or s.label == label):
            return s
    return None


def find_cpu(sensors: list[Sensor], env: Mapping[str, str]) -> Sensor:
    spec = env.get(ENV_SENSOR, "").strip()
    if spec:
        s = _match(sensors, spec)
        if s is None:
            raise SensorNotFound(f"{ENV_SENSOR}={spec!r} matches no temperature input; "
                                 + _how_to_choose(sensors))
        return s
    for chip, labels in CPU_CHIPS.items():
        for label in labels:
            for s in sensors:
                if s.chip == chip and s.label == label:
                    return s
        # zenpower/k10temp without the usual label: first input of the chip
        for s in sensors:
            if s.chip == chip and chip != "coretemp":
                return s
    raise SensorNotFound("no processor temperature sensor found (k10temp, zenpower or "
                         "coretemp); " + _how_to_choose(sensors))


def _how_to_choose(sensors: list[Sensor]) -> str:
    lines = [f"set {ENV_SENSOR} to 'chip:label' or to a tempN_input path, e.g. "
             f"{ENV_SENSOR}=k10temp:Tctl"]
    if sensors:
        lines.append("available inputs:")
        lines += [f"  {s.chip}:{s.label}  {s.path}" for s in sensors]
    return "\n".join(lines)


def find_nvme(sensors: list[Sensor]) -> list[Sensor]:
    return [s for s in sensors if s.chip == "nvme" and s.label == "Composite"]


def temp_max(env: Mapping[str, str]) -> float:
    raw = env.get(ENV_MAX, "").strip()
    if not raw:
        return DEFAULT_MAX
    try:
        return float(raw)
    except ValueError:
        raise HeatError(f"{ENV_MAX}={raw!r} is not a temperature in degrees C") from None


@dataclass
class HeatSummary:
    cpu_sensor: str
    max_cpu: float | None = None
    max_nvme: float | None = None
    time_above: float = 0.0
    time_paused: float = 0.0
    pauses: int = 0
    samples: int = 0

    def lines(self) -> list[str]:
        def t(v: float | None) -> str:
            return "n/a" if v is None else f"{v:.1f} C"
        return [
            f"heat: max CPU {t(self.max_cpu)} ({self.cpu_sensor}), max NVMe {t(self.max_nvme)}",
            f"heat: above limit {self.time_above:.0f} s, paused {self.time_paused:.0f} s "
            f"({self.pauses} pauses)",
        ]


def _podman(args: list[str]) -> None:
    subprocess.run(["podman", *args], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def build_containers() -> list[str]:
    """Running build containers (carrying BUILD_LABEL)."""
    r = subprocess.run(["podman", "ps", "-q", "--filter", f"label={BUILD_LABEL}"],
                       check=False, capture_output=True, text=True)
    return r.stdout.split()


@dataclass
class HeatGuard:
    """Samples the sensors and pauses/resumes the build containers.

    Every side effect is injectable: `containers` lists the containers to act on,
    `runner` runs a podman command (args without "podman"), `clock` is monotonic seconds.
    Call `step()` for one sample (tests) or `start()`/`stop()` for the background thread.
    """

    cpu: Sensor
    nvme: list[Sensor] = field(default_factory=list)
    limit: float = DEFAULT_MAX
    log_only: bool = False
    interval: float = INTERVAL
    containers: Callable[[], list[str]] = build_containers
    runner: Callable[[list[str]], None] = _podman
    clock: Callable[[], float] = time.monotonic
    out: TextIO | None = None

    def __post_init__(self) -> None:
        self.summary = HeatSummary(str(self.cpu))
        self.paused: list[str] = []
        self.paused_since: float | None = None
        self.error: HeatAbort | None = None
        self.reported = False   # summary lines already handed to a StageTimer
        self._last: float | None = None
        self._above = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # --- output ---------------------------------------------------------------
    def _say(self, msg: str) -> None:
        print(msg, file=self.out or sys.stdout, flush=True)

    def nvme_limit(self, s: Sensor) -> float:
        return (s.crit if s.crit is not None else NVME_DEFAULT_MAX) - NVME_MARGIN

    def start_line(self) -> str:
        cpu = self.cpu.read()
        parts = [f"heat guard: CPU {cpu:.1f} C from {self.cpu}, limit {self.limit:.0f} C"]
        for s in self.nvme:
            parts.append(f"NVMe {s.read():.1f} C from {s} (pause at {self.nvme_limit(s):.1f} C)")
        if self.log_only:
            parts.append("log only, never pauses")
        return "; ".join(parts)

    # --- one sample -----------------------------------------------------------
    def step(self) -> None:
        if self.error is not None:
            return
        now = self.clock()
        if self._last is not None:
            dt = now - self._last
            if self._above:
                self.summary.time_above += dt
            if self.paused_since is not None:
                self.summary.time_paused += dt
        self._last = now

        cpu = self.cpu.read()
        s = self.summary
        s.samples += 1
        s.max_cpu = cpu if s.max_cpu is None else max(s.max_cpu, cpu)
        nvme_hot: list[str] = []
        nvme_cool = True
        for n in self.nvme:
            try:
                v = n.read()
            except (OSError, ValueError):
                continue
            s.max_nvme = v if s.max_nvme is None else max(s.max_nvme, v)
            if v >= self.nvme_limit(n):
                nvme_hot.append(f"NVMe {v:.1f} C ({n})")
            if v > self.nvme_limit(n) - RESUME_DELTA:
                nvme_cool = False
        self._above = cpu >= self.limit

        if self.log_only:
            return

        if self.paused_since is None:
            if cpu >= self.limit or nvme_hot:
                why = [f"CPU {cpu:.1f} C ({self.cpu})"] + nvme_hot
                self._pause(now, ", ".join(why))
            return

        # paused
        if cpu > ABORT_TEMP and now - self.paused_since >= ABORT_AFTER:
            self._abort(cpu)
            return
        if cpu <= self.limit - RESUME_DELTA and nvme_cool:
            self._resume(cpu)

    def _pause(self, now: float, why: str) -> None:
        names = list(self.containers())
        self._say(f"heat guard: {why} >= limit, pausing {len(names)} build containers")
        if names:
            self.runner(["pause", *names])
        self.paused = names
        self.paused_since = now
        self.summary.pauses += 1

    def _resume(self, cpu: float) -> None:
        self._say(f"heat guard: CPU {cpu:.1f} C, resuming the build containers")
        if self.paused:
            self.runner(["unpause", *self.paused])
        self.paused = []
        self.paused_since = None

    def _abort(self, cpu: float) -> None:
        self.error = HeatAbort(
            f"heat guard: CPU at {cpu:.1f} C (sensor {self.cpu}) still above {ABORT_TEMP:.0f} C "
            f"after {ABORT_AFTER:.0f} s with the build paused; check the cooling. "
            "Build aborted.")
        self._say(str(self.error))
        if self.paused:
            # a paused container cannot take a signal: unpause, then kill at once
            self.runner(["unpause", *self.paused])
            self.runner(["kill", *self.paused])
        self.paused = []
        self.paused_since = None

    # --- thread ---------------------------------------------------------------
    def _loop(self) -> None:
        while True:
            try:
                self.step()
            except Exception as e:  # a failing sensor must not take the build down
                self._say(f"heat guard: sampling failed: {e}")
            if self.error is not None or self._stop.wait(self.interval):
                return

    def start(self) -> "HeatGuard":
        self._say(self.start_line())
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="r36os-heat", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> HeatSummary:
        """Stops sampling, resumes anything still paused and returns the summary."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        if self.paused:
            self._resume(self.cpu.read())
        return self.summary

    def check(self) -> None:
        """Raises HeatAbort if the guard aborted the build."""
        if self.error is not None:
            raise self.error

    def __enter__(self) -> "HeatGuard":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()
        if exc[0] is None:
            self.check()


ENV_GUARD = "R36OS_TEMP_GUARD"   # "log" = sample and report only, never pause

# The guard running for this build, so the stage summary can include its lines.
ACTIVE: HeatGuard | None = None


def add_summary(timer) -> None:
    """Adds the heat lines to a StageTimer summary (once); a no-op without a guard."""
    g = ACTIVE
    if g is not None and not g.reported:
        g.reported = True
        for line in g.summary.lines():
            timer.add_line(line)


def guard_from_env(log_only: bool | None = None, root: Path = HWMON_ROOT,
                   env: Mapping[str, str] | None = None, **kw) -> HeatGuard:
    """Builds the guard for this PC; raises SensorNotFound before the build starts.

    Pauses by default; `R36OS_TEMP_GUARD=log` (or log_only=True) only samples and reports.
    """
    env = os.environ if env is None else env
    if log_only is None:
        mode = env.get(ENV_GUARD, "").strip().lower()
        if mode not in ("", "pause", "log"):
            raise HeatError(f"{ENV_GUARD}={mode!r} must be 'pause' or 'log'")
        log_only = mode == "log"
    sensors = scan(root)
    return HeatGuard(cpu=find_cpu(sensors, env), nvme=find_nvme(sensors),
                     limit=temp_max(env), log_only=log_only, **kw)
