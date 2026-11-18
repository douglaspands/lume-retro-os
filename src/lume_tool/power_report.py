"""`lume power report`: summarise the card's metrics and events (game-governor D14).

Reads `ROMS/logs/` (`events.log` + rotated copies, `metrics/boot-<n>.csv`, formats in
docs/LOGS.md) over the USB cable, or from a local copy of that folder (`--from-dir`), and
groups the samples by scenario, system and power profile:

- scenario: from the `frontend` column (`launcher` -> menu, `game`/`paused` -> game), with
  `idle` taken from the `power OK profile: idle -> <profile>` events;
- profile: the last `power OK profile: <scenario> -> <profile>` event before the sample
  (`-` for sessions without the power service: the kernel default governor).

Output is a table on the terminal and a CSV in `cache/`. Game names and ROM paths are never
read into the report: the `content` column and the detail of the events are ignored, and
every label that reaches the output is checked against a strict pattern.
"""

from __future__ import annotations

import bisect
import csv
import io
import re
import statistics
import subprocess
import sys
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from lume_tool.paths import REPO_ROOT

REMOTE_LOGS = "/storage/logs"
_LABEL = re.compile(r"^[a-z0-9][a-z0-9_.+-]{0,23}$")
_EVENT = re.compile(r"^(\S+)\s+(\d+)\s+(\w+)\s+(OK|FAIL)\s*(.*)$")
_PROFILE = re.compile(r"^profile:\s*(\S+)[^>]*->\s*(\S+)")
_METRICS_NAME = re.compile(r"boot-(\d+)\.csv$")

COLUMNS = ["scenario", "system", "profile", "samples", "bat_ma", "fps_pct", "slow",
           "cpu_cores_pct", "busiest_mean_pct", "busiest_p90_pct", "clock_mhz",
           "temp_max_c", "logd_cpu_pct", "sugov_cpu_pct"]


class ReportError(RuntimeError):
    pass


@dataclass
class Source:
    """What the report needs from ROMS/logs: event lines and metrics text by boot number."""

    events: list[str] = field(default_factory=list)
    metrics: dict[int, str] = field(default_factory=dict)


# --- sources ---------------------------------------------------------------------------

def _events_order(name: str) -> int:
    m = re.match(r"events\.(\d+)\.log$", name)
    return -int(m.group(1)) if m else 1      # events.3.log first (oldest), events.log last


def load_dir(root: Path) -> Source:
    """A local copy of ROMS/logs (or the mounted card)."""
    root = Path(root)
    if not root.is_dir():
        raise ReportError(f"not a directory: {root}")
    src = Source()
    for f in sorted(root.glob("events*.log"), key=lambda p: _events_order(p.name)):
        src.events += f.read_text(errors="replace").splitlines()
    for f in (root / "metrics").glob("boot-*.csv"):
        if m := _METRICS_NAME.search(f.name):
            src.metrics[int(m.group(1))] = f.read_text(errors="replace")
    return src


def load_tar(data: bytes) -> Source:
    """A tar stream of ROMS/logs (what the cable fetch produces)."""
    src = Source()
    events: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tf:
        for m in tf.getmembers():
            if not m.isfile():
                continue
            base = Path(m.name).name
            body = tf.extractfile(m).read().decode(errors="replace")
            if re.match(r"events(\.\d+)?\.log$", base):
                events[base] = body
            elif mm := _METRICS_NAME.search(base):
                src.metrics[int(mm.group(1))] = body
    for name in sorted(events, key=_events_order):
        src.events += events[name].splitlines()
    return src


def load_cable(host: str, console: str | None) -> Source:
    """Fetch ROMS/logs over the cable (root over ssh, as `lume dev`)."""
    from lume_tool import dev

    try:
        dev.which_console(host, console)
        cmd = f"cd {REMOTE_LOGS} && tar cf - events*.log metrics 2>/dev/null"
        r = subprocess.run(dev.ssh_argv(host, cmd), stdin=subprocess.DEVNULL,
                           capture_output=True)
    except dev.DevError as e:
        raise ReportError(str(e)) from e
    except dev.PushError as e:
        raise ReportError(str(e)) from e
    if r.returncode != 0 and not r.stdout:
        raise ReportError(f"could not read {REMOTE_LOGS} on the console "
                          f"({r.returncode}): {r.stderr.decode(errors='replace').strip()}")
    return load_tar(r.stdout)


# --- parsing ---------------------------------------------------------------------------

@dataclass
class Event:
    time: str
    boot: int
    category: str
    status: str
    detail: str


def parse_events(lines: list[str]) -> list[Event]:
    out = []
    for line in lines:
        if m := _EVENT.match(line.strip()):
            out.append(Event(m[1], int(m[2]), m[3], m[4], m[5]))
    return out


def _num(s: str | None) -> float | None:
    try:
        return float(s) if s not in (None, "") else None
    except ValueError:
        return None


def _label(s: str | None, default: str = "-") -> str:
    """Only a short lowercase identifier may reach the output (never a game name)."""
    s = (s or "").strip().lower()
    return s if _LABEL.match(s) else default


def _scenario(frontend: str) -> str:
    return {"launcher": "menu", "menu": "menu", "game": "game", "paused": "game",
            "no_answer": "game"}.get(frontend, "other")


def _percentile(values: list[float], pct: float) -> float:
    s = sorted(values)
    k = (len(s) - 1) * pct / 100
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


@dataclass
class Sample:
    time: str
    scenario: str
    system: str
    profile: str
    row: dict[str, str]


def read_samples(boot: int, text: str, events: list[Event]) -> list[Sample]:
    prof = sorted((e.time, _label(m[1]), _label(m[2]))
                  for e in events if e.boot == boot and e.category == "power"
                  and e.status == "OK" and (m := _PROFILE.match(e.detail)))
    keys = [p[0] for p in prof]
    samples = []
    for row in csv.DictReader(io.StringIO(text)):
        t = row.get("time") or ""
        if not t or None in row or row.get("frontend") is None:   # truncated last line
            continue
        i = bisect.bisect_right(keys, t) - 1
        ev_scen, profile = (prof[i][1], prof[i][2]) if i >= 0 else ("-", "-")
        scen = _scenario(row.get("frontend", ""))
        if scen == "menu" and ev_scen == "idle":
            scen = "idle"
        system = _label(row.get("core")) if scen == "game" else "-"
        samples.append(Sample(t, scen, system, profile, row))
    return samples


def _mean(v: list[float]) -> float | None:
    return statistics.fmean(v) if v else None


def _group_cpu_cost(rows: list[dict[str, str]], prefix: str) -> float | None:
    vals = []
    for r in rows:
        for k, v in r.items():
            if k and k.startswith(prefix) and k.endswith("_cpu_pct") and (x := _num(v)) is not None:
                vals.append(x)
    return _mean(vals)


def summarise(samples: list[Sample], slow: dict[tuple[str, str, str], int]) -> list[dict]:
    groups: dict[tuple[str, str, str], list[Sample]] = {}
    for s in samples:
        groups.setdefault((s.scenario, s.system, s.profile), []).append(s)
    for key in slow:
        groups.setdefault(key, [])
    out = []
    for key in sorted(groups):
        ss = groups[key]
        rows = [s.row for s in ss]
        cur = [abs(x) for r in rows if r.get("bat_status") != "Charging"
               and (x := _num(r.get("bat_ma"))) is not None]
        fps = [100 * f / n for r in rows
               if (f := _num(r.get("fps"))) is not None
               and (n := _num(r.get("fps_nominal"))) and n > 0]
        cores: dict[str, list[float]] = {}
        clocks: list[float] = []
        temps: list[float] = []
        for r in rows:
            for k, v in r.items():
                if not k or (x := _num(v)) is None:
                    continue
                if re.fullmatch(r"cpu\d+_pct", k):
                    cores.setdefault(k, []).append(x)
                elif re.fullmatch(r"freq_\w+_mhz", k):
                    clocks.append(x)
                elif re.fullmatch(r"temp_\w+_c", k):
                    temps.append(x)
        names = sorted(cores, key=lambda c: int(c[3:-4]))
        means = [statistics.fmean(cores[c]) for c in names]
        if names:
            top = max(names, key=lambda c: statistics.fmean(cores[c]))
            busiest = (statistics.fmean(cores[top]), _percentile(cores[top], 90))
        else:
            busiest = (None, None)
        out.append({
            "scenario": key[0], "system": key[1], "profile": key[2], "samples": len(ss),
            "bat_ma": _mean(cur), "fps_pct": _mean(fps), "slow": slow.get(key, 0),
            "cpu_cores_pct": "/".join(f"{m:.0f}" for m in means) if means else None,
            "busiest_mean_pct": busiest[0], "busiest_p90_pct": busiest[1],
            "clock_mhz": _mean(clocks), "temp_max_c": max(temps) if temps else None,
            "logd_cpu_pct": _group_cpu_cost(rows, "logd"),
            "sugov_cpu_pct": _group_cpu_cost(rows, "sugov"),
        })
    return out


def build_report(src: Source, since: int | None = None) -> list[dict]:
    events = parse_events(src.events)
    all_samples: list[Sample] = []
    slow: dict[tuple[str, str, str], int] = {}
    for boot in sorted(src.metrics):
        if since is not None and boot < since:
            continue
        samples = read_samples(boot, src.metrics[boot], events)
        all_samples += samples
        times = [s.time for s in samples]
        for e in events:
            if e.boot != boot or e.category != "game" or e.status != "FAIL" \
                    or not e.detail.startswith("slow"):
                continue
            # the system of a slow event: the closest game sample at or before it
            i = bisect.bisect_right(times, e.time) - 1
            while i >= 0 and samples[i].scenario != "game":
                i -= 1
            key = ((samples[i].scenario, samples[i].system, samples[i].profile)
                   if i >= 0 else ("game", "-", "-"))
            slow[key] = slow.get(key, 0) + 1
    return summarise(all_samples, slow)


# --- output ----------------------------------------------------------------------------

def _fmt(v, nd: int = 0) -> str:
    if v is None:
        return "-"
    return f"{v:.{nd}f}" if isinstance(v, float) else str(v)


def format_row(r: dict) -> list[str]:
    nd = {"bat_ma": 0, "fps_pct": 1, "busiest_mean_pct": 0, "busiest_p90_pct": 0,
          "clock_mhz": 0, "temp_max_c": 1, "logd_cpu_pct": 1, "sugov_cpu_pct": 1}
    return [_fmt(r[c], nd.get(c, 0)) for c in COLUMNS]


def render_table(rows: list[dict]) -> str:
    if not rows:
        return "no samples"
    body = [COLUMNS] + [format_row(r) for r in rows]
    w = [max(len(line[i]) for line in body) for i in range(len(COLUMNS))]
    return "\n".join("  ".join(c.ljust(w[i]) for i, c in enumerate(line)).rstrip()
                     for line in body)


def render_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    wr = csv.writer(buf, lineterminator="\n")
    wr.writerow(COLUMNS)
    for r in rows:
        wr.writerow(["" if x == "-" and c in ("bat_ma", "fps_pct", "busiest_mean_pct",
                                              "busiest_p90_pct", "clock_mhz", "temp_max_c",
                                              "logd_cpu_pct", "sugov_cpu_pct", "cpu_cores_pct")
                     else x for c, x in zip(COLUMNS, format_row(r))])
    return buf.getvalue()


def main_power_report(since: int | None, console: str | None, host: str | None,
                      from_dir: Path | None, out_dir: Path | None = None) -> int:
    from lume_tool.push import CONSOLE_ADDR

    try:
        src = load_dir(from_dir) if from_dir else load_cable(host or CONSOLE_ADDR, console)
    except ReportError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    rows = build_report(src, since)
    print(render_table(rows))
    if rows:
        d = Path(out_dir) if out_dir else REPO_ROOT / "cache"
        d.mkdir(parents=True, exist_ok=True)
        dest = d / f"power-report-{time.strftime('%Y%m%dT%H%M%S')}.csv"
        dest.write_text(render_csv(rows))
        print(f"csv: {dest}", file=sys.stderr)
    return 0
