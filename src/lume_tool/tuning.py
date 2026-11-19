"""A/B measurement of the core tuning (game-experience-tuning D6, task 5.1): the pure part.

The device driver is tests/device/tuning_ab.py; everything it decides lives here, so the unit
tests (tests/unit/test_tuning.py) cover it without a console:

- the plan file (TOML, tests/device/tuning/*.toml): cores, the game N of a system, variants;
- the sequence of runs for a console (baseline A, A; each variant A, B, A), printable as a
  dry run;
- the remote commands: the sampler of one measurement window, the lume-logd metrics rows of
  that window, saving / applying / restoring the user's RetroArch config, the extra config
  and the core options;
- parsing those outputs into one aggregate per run;
- the acceptance criterion of the spec (core-tuning, "Ajuste aceito só com ganho medido");
- the report docs/tuning/<console>.md: one aggregated row per core and variant, which refuses
  anything that looks like a game name or a path.

Where each metric comes from (one run = the measurement window after the warm-up):

| metric            | source                                                              |
|-------------------|---------------------------------------------------------------------|
| drawn frames/s    | sampler: `drm-page-flips` of the game process fdinfo (kernel patch  |
|                   | 0036), end - start over the window, one count per drm-client-id     |
| core speed        | lume-logd metrics: mean `fps` (GET_STATUS frame counter, RetroArch  |
|                   | patch 0004) over `fps_nominal`                                      |
| audio failures    | sampler: /proc/asound/card*/pcm*p/sub*/status of the game's stream, |
|                   | once a second (see AUDIO SOURCE below)                              |
| mean clock        | sampler: cpufreq `stats/time_in_state` end - start (exact, time     |
|                   | weighted); lume-logd `freq_*_mhz` mean when the stats are missing   |
| CPU per core      | lume-logd metrics: mean `cpu<N>_pct`                                |
| temperature       | lume-logd metrics: mean of each `temp_*_c`, the hottest zone        |

AUDIO SOURCE (fixed by this task): the ALSA `status` of the playback substream, not the
RetroArch log. RetroArch's ALSA driver (audio/drivers/alsa.c, v1.22.2, alsa_write) recovers an
underrun with `snd_pcm_recover(pcm, err, 1)`, the silent mode, and logs nothing, so the log has
no trace of it. The kernel has no xrun counter in that file either: `xrun_counter` is printed
only with CONFIG_SND_PCM_XRUN_DEBUG, which needs CONFIG_SND_DEBUG, off in both kernels. What
the file does show: each recovery prepares the stream again, which puts `hw_ptr` back to 0
(pcm_lib.c, snd_pcm_lib_ioctl_reset on a stream that is not running) and the next start sets
a new `trigger_time` (pcm_native.c, snd_pcm_post_start). So one sample a second counts the
seconds with at least one underrun: a state XRUN, a new trigger_time or a hw_ptr that went
back, on the stream owned by the game process. A kernel with `xrun_counter` is used as is
(exact count). Through dmix (alsa-lib shared memory key 0x0056a4d5) the hardware stream never
underruns, so the metric is then reported as not measured and no variant is accepted on it.
"""
from __future__ import annotations

import re
import shlex
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from lume_tool import scripts

CONSOLES = ("ga36", "r36s", "vm")
WARMUP_S = 30
MEASURE_S = 120

# on the console
GAME_HOME = "/home/game"
USER_CFG = f"{GAME_HOME}/.config/retroarch/retroarch.cfg"
OPT_ROOT = f"{GAME_HOME}/.config/retroarch/config"
EXTRA_CFG = "/run/lume/retroarch-extra.cfg"
INFO_DIR = "/usr/share/lume/libretro-info"
SAVE_DIR = "/run/lume/tuning"
LOGS_RAM = "/run/lume/logs"
LOGS_DIR = "/storage/logs"
POWER_STATE = "/run/lume/power.state"
DMIX_IPC_KEY = 0x0056A4D5          # alsa-lib dmix default ipc_key (5678293)

# acceptance (spec: full core speed, continuous sound, a gain beyond the noise)
SPEED_FULL = 0.99                  # core fps / nominal fps
# smallest difference that counts, even when the two A runs agree exactly
FLOOR = {"drawn_fps": 0.3, "clock_mhz": 10.0, "temp_c": 0.5, "speed": 0.005, "cpu_total": 2.0}
# metric -> +1 when higher is better, -1 when lower is better
DIRECTION = {"drawn_fps": +1, "clock_mhz": -1, "temp_c": -1, "speed": +1, "cpu_total": -1}
GAIN_METRICS = ("drawn_fps", "clock_mhz", "temp_c")      # the spec's "melhora" metrics
GUARD_METRICS = ("drawn_fps", "clock_mhz", "temp_c", "speed", "cpu_total")
LABEL_PT = {"drawn_fps": "quadros/s", "clock_mhz": "clock", "temp_c": "temperatura",
            "speed": "velocidade", "cpu_total": "CPU"}

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.+-]{0,39}$")
CORE_RE = re.compile(r"^[a-z0-9_]{1,40}$")
KEY_RE = re.compile(r"^[A-Za-z0-9_]{1,80}$")
# option values may have spaces and parentheses (genesis_plus_gx: "nuked (ym2612)")
VALUE_RE = re.compile(r"^[A-Za-z0-9_.+:%() -]{0,40}$")
CHANGE_SEP = "; "
PROCESSES = ("retroarch", "love")
BASELINE = "baseline"


class TuningError(ValueError):
    """An invalid plan, an unusable measurement or a refused report row."""


# --- plan -------------------------------------------------------------------------------

@dataclass(frozen=True)
class Variant:
    name: str
    retroarch: tuple[tuple[str, str], ...] = ()   # keys for /run/lume/retroarch-extra.cfg
    options: tuple[tuple[str, str], ...] = ()     # core options for the user's .opt

    def change(self) -> str:
        """The change as written in the report: `ra:key=value; opt:key=value`."""
        parts = [f"ra:{k}={v}" for k, v in self.retroarch]
        parts += [f"opt:{k}={v}" for k, v in self.options]
        return CHANGE_SEP.join(parts) or "-"


@dataclass(frozen=True)
class CorePlan:
    core: str
    system: str
    position: int
    process: str = "retroarch"
    variants: tuple[Variant, ...] = ()


@dataclass(frozen=True)
class Plan:
    consoles: tuple[str, ...]
    cores: tuple[CorePlan, ...]
    description: str = ""


def _ident(value, what: str, pattern: re.Pattern) -> str:
    if not isinstance(value, str) or not pattern.match(value):
        raise TuningError(f"{what}: {value!r} is not allowed (pattern {pattern.pattern})")
    if value.lower().endswith(scripts.ROM_EXTENSIONS):
        raise TuningError(f"{what}: {value!r} looks like a ROM file")
    return value


def _pairs(table, where: str) -> tuple[tuple[str, str], ...]:
    if table is None:
        return ()
    if not isinstance(table, dict):
        raise TuningError(f"{where}: must be a table of key = \"value\"")
    out = []
    for k, v in table.items():
        _ident(k, f"{where} key", KEY_RE)
        if isinstance(v, bool):
            v = "true" if v else "false"
        if isinstance(v, (int, float)):
            v = str(v)
        _ident(v, f"{where} value of {k}", VALUE_RE)
        out.append((k, v))
    return tuple(out)


def validate_plan(data: dict) -> Plan:
    scripts._walk_forbidden(data, "plan")     # no game, rom, path, content or title keys
    unknown = set(data) - {"description", "consoles", "core"}
    if unknown:
        raise TuningError(f"unknown top-level field(s): {', '.join(sorted(unknown))}")
    consoles = data.get("consoles")
    if (not isinstance(consoles, list) or not consoles
            or any(c not in CONSOLES for c in consoles) or len(set(consoles)) != len(consoles)):
        raise TuningError(f"`consoles` must be a non-empty list from: {', '.join(CONSOLES)}")
    desc = data.get("description", "")
    if not isinstance(desc, str):
        raise TuningError("`description` must be a string")
    cores = data.get("core")
    if not isinstance(cores, list) or not cores:
        raise TuningError("a plan needs at least one [[core]]")
    out, seen = [], set()
    for i, c in enumerate(cores, 1):
        where = f"core {i}"
        if not isinstance(c, dict):
            raise TuningError(f"{where}: must be a table")
        unknown = set(c) - {"core", "system", "position", "process", "variant"}
        if unknown:
            raise TuningError(f"{where}: unknown field(s): {', '.join(sorted(unknown))}")
        core = _ident(c.get("core"), f"{where} core", CORE_RE)
        system = _ident(c.get("system"), f"{where} system", CORE_RE)
        pos = c.get("position")
        if isinstance(pos, bool) or not isinstance(pos, int) or pos < 1:
            raise TuningError(f"{where}: `position` must be an integer >= 1")
        process = c.get("process", "retroarch")
        if process not in PROCESSES:
            raise TuningError(f"{where}: `process` must be one of {', '.join(PROCESSES)}")
        if core in seen:
            raise TuningError(f"{where}: core {core} appears twice")
        seen.add(core)
        variants, names = [], set()
        for j, v in enumerate(c.get("variant", []) or [], 1):
            vw = f"{where} variant {j}"
            if not isinstance(v, dict):
                raise TuningError(f"{vw}: must be a table")
            unknown = set(v) - {"name", "retroarch", "options"}
            if unknown:
                raise TuningError(f"{vw}: unknown field(s): {', '.join(sorted(unknown))}")
            name = _ident(v.get("name"), f"{vw} name", NAME_RE)
            if name == BASELINE or name in names:
                raise TuningError(f"{vw}: name {name} is reserved or repeated")
            names.add(name)
            ra = _pairs(v.get("retroarch"), f"{vw} retroarch")
            opts = _pairs(v.get("options"), f"{vw} options")
            if not ra and not opts:
                raise TuningError(f"{vw}: a variant changes at least one key or option")
            if process != "retroarch":
                raise TuningError(f"{vw}: variants of the {process} runner are not supported "
                                  f"yet (baseline only)")
            variants.append(Variant(name, ra, opts))
        out.append(CorePlan(core, system, pos, process, tuple(variants)))
    return Plan(tuple(consoles), tuple(out), desc)


def load_plan(path: str | Path) -> Plan:
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise TuningError(f"{path}: bad TOML: {e}") from None
    except scripts.ScriptError as e:
        raise TuningError(f"{path}: {e}") from None
    try:
        return validate_plan(data)
    except (TuningError, scripts.ScriptError) as e:
        raise TuningError(f"{path}: {e}") from None


# --- sequences of runs -----------------------------------------------------------------

@dataclass(frozen=True)
class Run:
    label: str                      # A1, B, A2
    variant: Variant | None         # None = the configuration as it is (A)


@dataclass(frozen=True)
class Sequence:
    core: CorePlan
    variant: Variant | None         # None = baseline
    runs: tuple[Run, ...]

    @property
    def name(self) -> str:
        return self.variant.name if self.variant else BASELINE


def build_sequences(plan: Plan, console: str, baselines: set[str], rebaseline: bool = False,
                    only: str | None = None) -> list[Sequence]:
    """The measurement sequences for `console`. A core gets a baseline (A, A) when the report
    has none for it (`baselines`, the cores with one) or with `rebaseline`; every variant is
    A, B, A, after the baseline. `only` is `core` or `core:variant`."""
    if console not in plan.consoles:
        raise TuningError(f"plan is for {', '.join(plan.consoles)}, not {console}")
    want_core, _, want_variant = (only or "").partition(":")
    out = []
    for c in plan.cores:
        if want_core and c.core != want_core:
            continue
        if rebaseline or c.core not in baselines:
            if not want_variant or want_variant == BASELINE:
                out.append(Sequence(c, None, (Run("A1", None), Run("A2", None))))
        for v in c.variants:
            if want_variant and v.name != want_variant:
                continue
            out.append(Sequence(c, v, (Run("A1", None), Run("B", v), Run("A2", None))))
    if only and not out:
        raise TuningError(f"nothing in the plan matches {only}")
    return out


def format_sequences(seqs: list[Sequence], console: str, warmup: int = WARMUP_S,
                     measure: int = MEASURE_S) -> str:
    """The dry-run text: one block per sequence, one line per run (no game names: the game
    is the position in the system's list)."""
    lines = [f"console {console}: {len(seqs)} sequence(s), "
             f"{sum(len(s.runs) for s in seqs)} run(s) of {warmup}+{measure} s"]
    for n, s in enumerate(seqs, 1):
        c = s.core
        lines.append(f"{n}. {c.core} {s.name}: system {c.system} game #{c.position}"
                     f" ({c.process})")
        for r in s.runs:
            what = f"apply {r.variant.change()}" if r.variant else "configuration as is"
            lines.append(f"   {r.label}: {what}; open; wait {warmup} s; measure "
                         f"{measure} s; close; restore")
    return "\n".join(lines)


def started_core(line: str) -> str | None:
    """The core of a lume-run start event, already cut at ` content=`:
    `<time> <boot> game OK <system> <runner> <core> start`."""
    parts = line.split()
    if len(parts) >= 8 and parts[2] == "game" and parts[-1] == "start":
        return parts[6]
    return None


# --- remote commands ------------------------------------------------------------------

def power_check_command() -> str:
    """Prints `manual <profile>` when lume-power is in manual mode (the measurement wants
    the normal governor profile), nothing otherwise."""
    return f"grep '^manual ' {POWER_STATE} 2>/dev/null; true"


def build_id_command() -> str:
    return "b=$(sed -n 's/^build: //p' /boot/VERSION 2>/dev/null | head -n 1); echo \"${b:--}\""


def _opt_vars(core: str) -> str:
    # the folder of the core options is the corename of the core's .info (RetroArch)
    return (f"n=$(sed -n 's/^corename *= *\"\\(.*\\)\"/\\1/p' {INFO_DIR}/{core}_libretro.info"
            f" 2>/dev/null | head -n 1); [ -n \"$n\" ] || n={core}; "
            f"opt=\"{OPT_ROOT}/$n/$n.opt\"; ")


def save_command(core: str) -> str:
    """Save in RAM the user's RetroArch config, the extra config and the core's options:
    `<tag>` is the copy (missing when the file did not exist) and `<tag>.path` the original
    path. A save left by an interrupted run is put back first, so the originals are never
    lost, whatever core that run measured."""
    return (restore_command(keep=False) +
            f"mkdir -p {SAVE_DIR}; " + _opt_vars(core) +
            f"for p in cfg:{USER_CFG} extra:{EXTRA_CFG} \"opt:$opt\"; do "
            "t=${p%%:*}; f=${p#*:}; "
            f"printf '%s\\n' \"$f\" > {SAVE_DIR}/$t.path; "
            f"if [ -f \"$f\" ]; then cp -p \"$f\" {SAVE_DIR}/$t; fi; "
            "done; echo saved")


def restore_command(keep: bool = True) -> str:
    """Put the saved files back (one absent at the save is removed). With keep the save
    stays (between runs); without it is deleted (end of a sequence). Nothing to do when
    there is no save."""
    end = "" if keep else f"rm -rf {SAVE_DIR}; "
    return (f"if [ -d {SAVE_DIR} ]; then "
            f"for pf in {SAVE_DIR}/*.path; do [ -f \"$pf\" ] || continue; "
            "t=${pf%.path}; read -r f < \"$pf\"; [ -n \"$f\" ] || continue; "
            "if [ -f \"$t\" ]; then cp -p \"$t\" \"$f\"; else rm -f \"$f\"; fi; "
            f"done; {end}fi; ")


def apply_command(core: str, variant: Variant) -> str:
    """Write the variant: RetroArch keys appended to the extra config (the frontend merges it
    last, so they win), core options replacing the same keys in the user's .opt."""
    parts = []
    if variant.retroarch:
        body = "".join(f'{k} = "{v}"\n' for k, v in variant.retroarch)
        parts.append(f"printf '%s' {shlex.quote(body)} >> {EXTRA_CFG}; chmod 644 {EXTRA_CFG}; ")
    if variant.options:
        keys = "|".join(k for k, _ in variant.options)
        body = "".join(f'{k} = "{v}"\n' for k, v in variant.options)
        parts.append(
            _opt_vars(core) +
            "d=${opt%/*}; mkdir -p \"$d\"; chown game:game \"$d\" 2>/dev/null; "
            "touch \"$opt\"; "
            f"grep -Ev '^({keys})[[:space:]]*=' \"$opt\" > \"$opt.tmp\"; "
            f"printf '%s' {shlex.quote(body)} >> \"$opt.tmp\"; "
            "cat \"$opt.tmp\" > \"$opt\"; rm -f \"$opt.tmp\"; "
            "chown game:game \"$opt\" 2>/dev/null; ")
    return "".join(parts) + "echo applied"


SAMPLER = r"""
P=$(pidof __PROC__ | awk '{print $1}')
[ -n "$P" ] || { echo "error no __PROC__ process"; exit 3; }
echo "pid $P"
awk 'NR > 1 { print "shm", $1, $5 }' /proc/sysvipc/shm 2>/dev/null
snap() {
	read -r up rest < /proc/uptime
	echo "snap $1 $up"
	for fd in /proc/$P/fdinfo/*; do
		c=""; f=""
		while read -r k v; do
			case "$k" in drm-client-id:) c=$v ;; drm-page-flips:) f=$v ;; esac
		done < "$fd" 2>/dev/null
		[ -n "$f" ] && echo "flips ${c:-0} $f"
	done
	for p in /sys/devices/system/cpu/cpufreq/policy*; do
		[ -r "$p/stats/time_in_state" ] || continue
		while read -r k t; do echo "tis ${p##*/} $k $t"; done < "$p/stats/time_in_state"
	done
}
pcm() {
	read -r up rest < /proc/uptime
	for s in /proc/asound/card*/pcm*p/sub*/status; do
		[ -r "$s" ] || continue
		echo "pcm $up $s"
		while IFS= read -r l; do echo "| $l"; done < "$s"
	done
}
snap start
i=0
while [ $i -lt __SECONDS__ ]; do pcm; sleep 1; i=$((i + 1)); done
pcm
snap end
[ -d /proc/$P ] || echo "error process ended during the measurement"
"""


def sampler_command(process: str, seconds: int) -> str:
    """The measurement window, run on the console (blocks `seconds`). Prints only numbers,
    /proc paths and ALSA state names: nothing about the game."""
    if process not in PROCESSES:
        raise TuningError(f"unknown process {process}")
    return SAMPLER.replace("__PROC__", process).replace("__SECONDS__", str(int(seconds)))


METRIC_COLUMN = re.compile(r"^(uptime_s|frontend|fps|fps_nominal|temp_[A-Za-z0-9_]+_c|"
                           r"freq_[A-Za-z0-9_]+_mhz|cpu[0-9]+_pct)$")


def metrics_command(t0: float, t1: float) -> str:
    """The lume-logd metrics rows with t0 < uptime_s <= t1, only the allowed columns (an
    allow-list: `content`, the game name, never leaves the console). The RAM pending rows are
    read before the card file, so a flush in between only duplicates rows (removed by uptime
    on the PC) and never loses one."""
    cols = METRIC_COLUMN.pattern.replace("\\", "\\\\")
    return (f"n=$(cat {LOGS_RAM}/boot-n 2>/dev/null); "
            f"{{ cat {LOGS_RAM}/metrics.pending 2>/dev/null; "
            f"cat {LOGS_DIR}/metrics/boot-$n.csv 2>/dev/null; }} | "
            f"awk -F, -v a={t0:.2f} -v b={t1:.2f} -v hf={LOGS_RAM}/metrics.header '"
            "BEGIN { if ((getline l < hf) <= 0) exit 1; m = split(l, H, \",\"); "
            f"for (i = 1; i <= m; i++) {{ if (H[i] ~ /{cols}/) K[++k] = i; "
            "if (H[i] == \"uptime_s\") u = i } "
            "s = \"@header\"; for (j = 1; j <= k; j++) s = s (j > 1 ? \",\" : \" \") H[K[j]]; "
            "print s } "
            "NF != m || $u !~ /^[0-9.]+$/ { next } "
            "$u + 0 > a + 0 && $u + 0 <= b + 0 { s = \"\"; "
            "for (j = 1; j <= k; j++) s = s (j > 1 ? \",\" : \"\") $K[j]; print s }'")


# --- parsing and aggregation ----------------------------------------------------------

@dataclass
class PcmSample:
    uptime: float
    path: str
    fields: dict


@dataclass
class Window:
    pid: int
    t0: float
    t1: float
    flips0: dict = field(default_factory=dict)       # drm-client-id -> page flips
    flips1: dict = field(default_factory=dict)
    tis0: dict = field(default_factory=dict)         # (policy, khz) -> 10 ms ticks
    tis1: dict = field(default_factory=dict)
    pcm: list = field(default_factory=list)          # PcmSample
    shm_keys: set = field(default_factory=set)


def parse_window(text: str) -> Window:
    """Parse the sampler output; an `error` line or a missing snapshot is a TuningError."""
    pid = None
    snaps: dict[str, float] = {}
    cur = None
    w = Window(0, 0.0, 0.0)
    pcm: PcmSample | None = None
    for raw in text.splitlines():
        if raw.startswith("| "):
            if pcm is not None:
                line = raw[2:]
                if ":" in line:
                    k, _, v = line.partition(":")
                    pcm.fields[k.strip()] = v.strip()
                elif line.strip() == "closed":
                    pcm.fields["state"] = "CLOSED"
            continue
        parts = raw.split()
        if not parts:
            continue
        tag = parts[0]
        if tag == "error":
            raise TuningError("on the console: " + " ".join(parts[1:]))
        if tag == "pid" and len(parts) == 2:
            pid = int(parts[1])
        elif tag == "shm" and len(parts) == 3:
            try:
                w.shm_keys.add(int(parts[1]))
            except ValueError:
                pass
        elif tag == "snap" and len(parts) == 3:
            cur = parts[1]
            snaps[cur] = float(parts[2])
        elif tag == "flips" and len(parts) == 3 and cur:
            (w.flips0 if cur == "start" else w.flips1)[parts[1]] = int(parts[2])
        elif tag == "tis" and len(parts) == 4 and cur:
            (w.tis0 if cur == "start" else w.tis1)[(parts[1], int(parts[2]))] = int(parts[3])
        elif tag == "pcm" and len(parts) == 3:
            pcm = PcmSample(float(parts[1]), parts[2], {})
            w.pcm.append(pcm)
    if pid is None or "start" not in snaps or "end" not in snaps:
        raise TuningError("incomplete measurement (no process or no start/end snapshot)")
    w.pid, w.t0, w.t1 = pid, snaps["start"], snaps["end"]
    if w.t1 <= w.t0:
        raise TuningError("measurement window of zero length")
    return w


def parse_metrics(text: str) -> list[dict]:
    """The rows printed by metrics_command, as dicts, deduplicated by uptime_s."""
    header = None
    rows, seen = [], set()
    for line in text.splitlines():
        if line.startswith("@header "):
            header = line[len("@header "):].split(",")
            continue
        if header is None or not line.strip():
            continue
        vals = line.split(",")
        if len(vals) != len(header):
            continue
        row = dict(zip(header, vals))
        up = row.get("uptime_s", "")
        if up in seen:
            continue
        seen.add(up)
        rows.append(row)
    return rows


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _mean(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def drawn_fps(w: Window) -> float | None:
    ids = set(w.flips0) & set(w.flips1)
    if not ids:
        return None
    flips = sum(max(0, w.flips1[i] - w.flips0[i]) for i in ids)
    return flips / (w.t1 - w.t0)


def mean_clock_mhz(w: Window) -> float | None:
    """Time-weighted mean clock from cpufreq time_in_state, the mean over policies."""
    per_policy: dict[str, list[tuple[int, int]]] = {}
    for (pol, khz), t1 in w.tis1.items():
        t0 = w.tis0.get((pol, khz))
        if t0 is not None:
            per_policy.setdefault(pol, []).append((khz, max(0, t1 - t0)))
    means = []
    for pairs in per_policy.values():
        total = sum(t for _, t in pairs)
        if total > 0:
            means.append(sum(k * t for k, t in pairs) / total / 1000.0)
    return _mean(means)


def audio_failures(w: Window) -> tuple[int | None, str]:
    """(count, source) of the game's playback stream in the window. `source` is
    `xrun_counter` (exact, debug kernels), `alsa-status` (seconds with an underrun) or, with
    count None, why it was not measured: `dmix` or `no-stream`."""
    if DMIX_IPC_KEY in w.shm_keys:
        return None, "dmix"
    by_path: dict[str, list[PcmSample]] = {}
    for s in w.pcm:
        if s.fields.get("owner_pid") == str(w.pid):
            by_path.setdefault(s.path, []).append(s)
    if not by_path:
        return None, "no-stream"
    if all("xrun_counter" in s.fields for ss in by_path.values() for s in ss):
        total = 0
        for ss in by_path.values():
            prev = None
            for s in ss:
                c = int(s.fields["xrun_counter"])
                if prev is not None:
                    total += c - prev if c >= prev else c   # reopened: counter from 0
                prev = c
        return total, "xrun_counter"
    count = 0
    for ss in by_path.values():
        ss = sorted(ss, key=lambda s: s.uptime)
        for prev, s in zip(ss, ss[1:]):
            hw, hw_prev = _num(s.fields.get("hw_ptr")), _num(prev.fields.get("hw_ptr"))
            if (s.fields.get("state") == "XRUN"
                    or s.fields.get("trigger_time") != prev.fields.get("trigger_time")
                    or (hw is not None and hw_prev is not None and hw < hw_prev)):
                count += 1
        if ss and ss[0].fields.get("state") == "XRUN":
            count += 1
    return count, "alsa-status"


@dataclass
class RunMetrics:
    seconds: float
    drawn_fps: float | None
    core_fps: float | None
    nominal_fps: float | None
    speed: float | None             # core_fps / nominal_fps
    audio_failures: int | None
    audio_source: str
    clock_mhz: float | None
    cpu_pct: tuple[float, ...]       # mean per core, cpu0 first
    temp_c: float | None             # hottest zone, mean over the window
    samples: int                     # lume-logd rows used

    @property
    def cpu_total(self) -> float | None:
        return sum(self.cpu_pct) if self.cpu_pct else None

    def value(self, metric: str) -> float | None:
        return self.cpu_total if metric == "cpu_total" else getattr(self, metric)


def aggregate(w: Window, rows: list[dict]) -> RunMetrics:
    """One run: the sampler window and the lume-logd rows of the same window."""
    game = [r for r in rows if r.get("frontend") == "game"] or rows
    core_fps = _mean(_num(r.get("fps")) for r in game)
    nominal = None
    for r in game:
        nominal = _num(r.get("fps_nominal")) or nominal
    speed = core_fps / nominal if core_fps is not None and nominal else None
    cols = list(game[0]) if game else []
    cpu = []
    for c in sorted((c for c in cols if re.match(r"^cpu\d+_pct$", c)),
                    key=lambda c: int(c[3:-4])):
        m = _mean(_num(r.get(c)) for r in game)
        cpu.append(round(m, 1) if m is not None else 0.0)
    temps = [_mean(_num(r.get(c)) for r in game) for c in cols if re.match(r"^temp_.+_c$", c)]
    temps = [t for t in temps if t is not None]
    clock = mean_clock_mhz(w)
    if clock is None:
        freqs = [_mean(_num(r.get(c)) for r in game) for c in cols if re.match(r"^freq_.+_mhz$", c)]
        clock = _mean(freqs)
    audio, source = audio_failures(w)
    return RunMetrics(round(w.t1 - w.t0, 2), drawn_fps(w), core_fps, nominal, speed, audio,
                      source, clock, tuple(cpu), max(temps) if temps else None, len(game))


# --- decision -------------------------------------------------------------------------

@dataclass
class Decision:
    accepted: bool | None           # None = not decided (base row or inconclusive)
    text: str                       # report text (Portuguese)
    gains: tuple[str, ...] = ()
    losses: tuple[str, ...] = ()


def noise(a1: RunMetrics, a2: RunMetrics) -> dict[str, float | None]:
    """The variation between the two identical runs, per metric."""
    out = {}
    for m in GUARD_METRICS:
        x, y = a1.value(m), a2.value(m)
        out[m] = abs(x - y) if x is not None and y is not None else None
    return out


def mean_of(a1: RunMetrics, a2: RunMetrics, metric: str) -> float | None:
    x, y = a1.value(metric), a2.value(metric)
    return (x + y) / 2 if x is not None and y is not None else None


def decide(a1: RunMetrics, b: RunMetrics, a2: RunMetrics) -> Decision:
    """The spec's rule: B keeps the full core speed and the continuous sound (no more audio
    failures than the better A), improves drawn frames, mean clock or temperature beyond
    the noise, and makes no metric worse beyond the noise. The noise of a metric is the
    difference between the two A runs, never less than its FLOOR."""
    nz = noise(a1, a2)
    gains, losses = [], []
    for m in GUARD_METRICS:
        ref, val = mean_of(a1, a2, m), b.value(m)
        if ref is None or val is None:
            continue
        margin = max(nz[m] or 0.0, FLOOR[m])
        delta = (val - ref) * DIRECTION[m]
        if delta > margin and m in GAIN_METRICS:
            gains.append(m)
        elif delta < -margin:
            losses.append(m)
    reasons = []
    if b.speed is not None and b.speed < SPEED_FULL:
        reasons.append(f"sem velocidade cheia ({b.speed * 100:.1f}%)")
    if b.audio_failures is None or a1.audio_failures is None or a2.audio_failures is None:
        return Decision(None, f"inconclusivo: falhas de áudio não medidas ({b.audio_source})",
                        tuple(gains), tuple(losses))
    if b.audio_failures > min(a1.audio_failures, a2.audio_failures):
        reasons.append("falhas de áudio")
    if losses:
        reasons.append("piora: " + ", ".join(LABEL_PT[m] for m in losses))
    if not gains:
        reasons.append("sem ganho acima do ruído")
    if reasons:
        return Decision(False, "recusado: " + "; ".join(reasons), tuple(gains), tuple(losses))
    return Decision(True, "aceito: " + ", ".join(LABEL_PT[m] for m in gains),
                    tuple(gains), tuple(losses))


# --- report ---------------------------------------------------------------------------

COLUMNS = ("data", "imagem", "core", "sistema", "jogo", "variante", "mudança", "execuções",
           "quadros/s", "velocidade", "falhas de áudio", "clock MHz", "CPU por núcleo %",
           "temp °C", "ruído A1-A2", "decisão")
CONSOLE_TITLE = {"ga36": "GA36", "r36s": "R36S", "vm": "VM (x86, só emulador)"}

REPORT_HEAD = """# Afinação dos cores: {title}

Relatório da medição A/B (change `game-experience-tuning`, D6; método em
[`README.md`](README.md)). Uma linha agregada por core e variante, gravada por
`tests/device/tuning_ab.py`; nenhum nome de jogo nem caminho: o jogo é a posição na lista do
sistema no conjunto de teste (`var/roms_test/`).

- **execuções:** `A,A` na linha de base (`baseline`); `A,B,A` numa variante, com os valores
  de B e, entre parênteses, a diferença para a média dos dois A.
- **quadros/s:** quadros mostrados no painel (`drm-page-flips` do fdinfo do DRM);
  **velocidade:** FPS do core (`GET_STATUS`) sobre o FPS nominal; **falhas de áudio:** segundos
  com underrun no `status` do ALSA (entre parênteses, os dois A); **clock:** média ponderada
  pelo tempo do `time_in_state` do cpufreq; **CPU por núcleo** e **temp** (zona mais quente):
  médias das amostras do `lume-logd`.
- **ruído A1-A2:** diferença entre os dois A em cada métrica; uma variante só é aceita com ganho
  acima dele e sem piora acima dele (regra completa no `README.md`).

"""


def report_header(console: str) -> str:
    if console not in CONSOLES:
        raise TuningError(f"unknown console {console}")
    head = REPORT_HEAD.format(title=CONSOLE_TITLE[console])
    return (head + "| " + " | ".join(COLUMNS) + " |\n"
            + "|" + "|".join("---" for _ in COLUMNS) + "|\n")


@dataclass
class Row:
    date: str
    build: str
    core: str
    system: str
    position: int
    variant: str
    change: str
    runs: str
    cells: dict                     # the metric columns, already formatted
    decision: str


FORBIDDEN_TEXT = re.compile(r"[/\\|`<>\[\]]")


def check_row_privacy(row: Row) -> None:
    """Refuse a row that could carry a game name or a path: fixed patterns for the
    identifiers, and no path separator, ROM extension, markup or table break anywhere."""
    _ident(row.core, "core", CORE_RE)
    _ident(row.system, "system", CORE_RE)
    if row.variant != BASELINE:
        _ident(row.variant, "variant", NAME_RE)
    if isinstance(row.position, bool) or not isinstance(row.position, int) or row.position < 1:
        raise TuningError("position must be an integer >= 1")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", row.date):
        raise TuningError(f"date {row.date!r} is not YYYY-MM-DD")
    if not re.match(r"^[A-Za-z0-9_.:+-]{1,40}$", row.build):
        raise TuningError(f"build {row.build!r} is not allowed")
    if row.change != "-":
        for tok in row.change.split(CHANGE_SEP):
            kind, _, kv = tok.partition(":")
            k, eq, v = kv.partition("=")
            if kind not in ("ra", "opt") or not eq:
                raise TuningError(f"change {tok!r} is not ra:key=value or opt:key=value")
            _ident(k, "change key", KEY_RE)
            _ident(v, "change value", VALUE_RE)
    for text in (row.runs, row.decision, *row.cells.values()):
        if FORBIDDEN_TEXT.search(text) or "\n" in text:
            raise TuningError(f"cell {text!r} has a forbidden character")
        for word in re.split(r"[\s,;()]+", text):
            if word.lower().endswith(scripts.ROM_EXTENSIONS):
                raise TuningError(f"cell {text!r} looks like it names a ROM file")


def format_row(row: Row) -> str:
    check_row_privacy(row)
    vals = [row.date, row.build, row.core, row.system, f"#{row.position}", row.variant,
            row.change, row.runs]
    vals += [row.cells[c] for c in COLUMNS[8:15]]
    vals.append(row.decision)
    return "| " + " | ".join(vals) + " |"


def parse_report(text: str) -> list[dict]:
    """The data rows of a report, as dicts by column name."""
    out = []
    for line in text.splitlines():
        if not line.startswith("| ") or line.startswith("| data |"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        if len(cells) == len(COLUMNS):
            out.append(dict(zip(COLUMNS, cells)))
    return out


def baselines_in(text: str) -> set[str]:
    return {r["core"] for r in parse_report(text) if r["variante"] == BASELINE}


def append_row(path: Path, console: str, row: Row) -> None:
    """Append one row to docs/tuning/<console>.md (created with its header). A variant row
    needs a baseline row of the same core in that file first (spec: no tuning without a
    baseline on that console)."""
    line = format_row(row)
    text = path.read_text(encoding="utf-8") if path.exists() else report_header(console)
    if row.variant != BASELINE and row.core not in baselines_in(text):
        raise TuningError(f"no baseline of {row.core} in {path.name}: measure it first")
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text + line + "\n", encoding="utf-8")


def _f(x: float | None, nd: int = 1) -> str:
    return "-" if x is None else f"{x:.{nd}f}"


def _d(x: float | None, ref: float | None, nd: int = 1) -> str:
    if x is None:
        return "-"
    if ref is None:
        return _f(x, nd)
    return f"{x:.{nd}f} ({x - ref:+.{nd}f})"


def _pct(x: float | None) -> str:
    return "-" if x is None else f"{x * 100:.1f}%"


def _noise_text(nz: dict) -> str:
    parts = []
    for m, label, nd in (("drawn_fps", "quadros", 1), ("speed", "vel", 1),
                         ("clock_mhz", "MHz", 0), ("temp_c", "°C", 1), ("cpu_total", "CPU", 1)):
        v = nz.get(m)
        if v is not None:
            parts.append(f"{label} {v * 100:.1f}%" if m == "speed" else f"{label} {v:.{nd}f}")
    return "; ".join(parts) or "-"


def baseline_row(date: str, build: str, core: CorePlan, a1: RunMetrics,
                 a2: RunMetrics) -> Row:
    def avg(m):
        return mean_of(a1, a2, m)
    cpu = tuple(round((x + y) / 2, 1) for x, y in zip(a1.cpu_pct, a2.cpu_pct))
    audio = ("-" if a1.audio_failures is None or a2.audio_failures is None
             else f"{a1.audio_failures} e {a2.audio_failures}")
    cells = {
        "quadros/s": _f(avg("drawn_fps")),
        "velocidade": _pct(avg("speed")),
        "falhas de áudio": audio,
        "clock MHz": _f(avg("clock_mhz"), 0),
        "CPU por núcleo %": " ".join(f"{c:.0f}" for c in cpu) or "-",
        "temp °C": _f(avg("temp_c")),
        "ruído A1-A2": _noise_text(noise(a1, a2)),
    }
    return Row(date, build, core.core, core.system, core.position, BASELINE, "-", "A,A",
               cells, "base")


def variant_row(date: str, build: str, core: CorePlan, variant: Variant, a1: RunMetrics,
                b: RunMetrics, a2: RunMetrics) -> Row:
    dec = decide(a1, b, a2)
    audio_b = "-" if b.audio_failures is None else str(b.audio_failures)
    audio_a = ("" if a1.audio_failures is None or a2.audio_failures is None
               else f" (A {a1.audio_failures} e {a2.audio_failures})")
    speed_ref = mean_of(a1, a2, "speed")
    speed = "-" if b.speed is None else (
        _pct(b.speed) + ("" if speed_ref is None else f" ({(b.speed - speed_ref) * 100:+.1f})"))
    cells = {
        "quadros/s": _d(b.drawn_fps, mean_of(a1, a2, "drawn_fps")),
        "velocidade": speed,
        "falhas de áudio": audio_b + audio_a,
        "clock MHz": _d(b.clock_mhz, mean_of(a1, a2, "clock_mhz"), 0),
        "CPU por núcleo %": " ".join(f"{c:.0f}" for c in b.cpu_pct) or "-",
        "temp °C": _d(b.temp_c, mean_of(a1, a2, "temp_c")),
        "ruído A1-A2": _noise_text(noise(a1, a2)),
    }
    return Row(date, build, core.core, core.system, core.position, variant.name,
               variant.change(), "A,B,A", cells, dec.text)
