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
  anything that looks like a game name or a path;
- the core comparison (task 10.2): a `core = "<name>"` variant swaps the core of one game
  through the launcher's per-game option, written and put back on the console; whether B
  opened, the private results per game (out of git) and the report section aggregated by core
  and hardware family.

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

import json
import re
import shlex
import tomllib
from dataclasses import asdict, dataclass, field
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
# the launcher's folder on the card (lume-core paths::card) and the cores (paths::cores_dir)
CARD = "/storage/system/lume"
INDEX_DIR = f"{CARD}/cache/index"          # lume-index: <system>.bin, records sorted for the grid
GAMES_DIR = f"{CARD}/games"                # options::Options, per-game exceptions by path
TUNING_SYSTEMS = f"{CARD}/systems.d/zz-lume-tuning.toml"   # our own file, never the user's
CORES_DIR = "/usr/lib/libretro"
RUN_OVERHEAD_S = 30                        # open, close and restore of one run (dry-run estimate)
DMIX_IPC_KEY = 0x0056A4D5          # alsa-lib dmix default ipc_key (5678293)

# acceptance (spec: full core speed, continuous sound, a gain beyond the noise)
SPEED_FULL = 0.99                  # core fps / nominal fps
# smallest difference that counts, even when the two A runs agree exactly
FLOOR = {"drawn_fps": 0.3, "clock_mhz": 10.0, "temp_c": 0.5, "speed": 0.005, "cpu_total": 2.0}
# metric -> +1 when higher is better, -1 when lower is better
DIRECTION = {"drawn_fps": +1, "clock_mhz": -1, "temp_c": -1, "speed": +1, "cpu_total": -1}
GAIN_METRICS = ("drawn_fps", "clock_mhz", "temp_c")      # the spec's "melhora" metrics
GUARD_METRICS = ("drawn_fps", "clock_mhz", "temp_c", "speed", "cpu_total")
LABEL_PT = {"drawn_fps": "quadros por segundo", "clock_mhz": "clock", "temp_c": "temperatura",
            "speed": "velocidade", "cpu_total": "CPU"}

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.+-]{0,39}$")
CORE_RE = re.compile(r"^[a-z0-9_]{1,40}$")
# core option keys may carry hyphens (fbneo-frameskip-type, mame2003-plus_...)
KEY_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,79}$")
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
    core: str | None = None                       # another core for this game (task 10.2)
    env: tuple[tuple[str, str], ...] = ()         # [runner.env] of a native runner (task 7.4)

    def change(self) -> str:
        """The change as written in the report: `ra:key=value; opt:key=value`,
        `env:NAME=value` or `core:<name>`."""
        parts = [f"ra:{k}={v}" for k, v in self.retroarch]
        parts += [f"opt:{k}={v}" for k, v in self.options]
        parts += [f"env:{k}={v}" for k, v in self.env]
        if self.core:
            parts.append(f"core:{self.core}")
        return CHANGE_SEP.join(parts) or "-"


@dataclass(frozen=True)
class CorePlan:
    core: str
    system: str
    position: int
    process: str = "retroarch"
    variants: tuple[Variant, ...] = ()

    @property
    def compares_cores(self) -> bool:
        """Every variant swaps the core (task 10.2): the A runs of each sequence are the
        game's reference in the default core, so no separate baseline sequence."""
        return bool(self.variants) and all(v.core for v in self.variants)


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
        unknown = set(c) - {"core", "system", "position", "positions", "process", "variant"}
        if unknown:
            raise TuningError(f"{where}: unknown field(s): {', '.join(sorted(unknown))}")
        core = _ident(c.get("core"), f"{where} core", CORE_RE)
        system = _ident(c.get("system"), f"{where} system", CORE_RE)
        positions = _positions(c, where)
        process = c.get("process", "retroarch")
        if process not in PROCESSES:
            raise TuningError(f"{where}: `process` must be one of {', '.join(PROCESSES)}")
        variants, names = [], set()
        for j, v in enumerate(c.get("variant", []) or [], 1):
            vw = f"{where} variant {j}"
            if not isinstance(v, dict):
                raise TuningError(f"{vw}: must be a table")
            unknown = set(v) - {"name", "retroarch", "options", "core", "env"}
            if unknown:
                raise TuningError(f"{vw}: unknown field(s): {', '.join(sorted(unknown))}")
            env = _pairs(v.get("env"), f"{vw} env")
            alt = v.get("core")
            if alt is not None:
                alt = _ident(alt, f"{vw} core", CORE_RE)
            name = _ident(v.get("name", alt), f"{vw} name", NAME_RE)
            if name == BASELINE or name in names:
                raise TuningError(f"{vw}: name {name} is reserved or repeated")
            names.add(name)
            ra = _pairs(v.get("retroarch"), f"{vw} retroarch")
            opts = _pairs(v.get("options"), f"{vw} options")
            if alt is not None and (ra or opts):
                raise TuningError(f"{vw}: a core variant changes only the core")
            if alt == core:
                raise TuningError(f"{vw}: core {alt} is already the default of this entry")
            if not ra and not opts and alt is None and not env:
                raise TuningError(f"{vw}: a variant changes at least one key, option, "
                                  f"variable or core")
            # a native runner (LÖVE) takes only environment variables; RetroArch never does
            if process != "retroarch" and (ra or opts or alt is not None):
                raise TuningError(f"{vw}: the {process} runner takes only `env` variants")
            if process == "retroarch" and env:
                raise TuningError(f"{vw}: `env` is for a native runner (process = \"love\")")
            variants.append(Variant(name, ra, opts, alt, env))
        if variants and any(v.core for v in variants) and not all(v.core for v in variants):
            raise TuningError(f"{where}: core variants and key/option variants go in separate "
                              f"entries")
        for pos in positions:
            key = (core, system, pos)
            if key in seen:
                raise TuningError(f"{where}: core {core} on game {pos} of {system} appears "
                                  f"twice")
            seen.add(key)
            out.append(CorePlan(core, system, pos, process, tuple(variants)))
    return Plan(tuple(consoles), tuple(out), desc)


def _positions(c: dict, where: str) -> list[int]:
    """`position = N` or `positions = [N, ...]` (one entry per game, task 10.2)."""
    if ("position" in c) == ("positions" in c):
        raise TuningError(f"{where}: give exactly one of `position` or `positions`")
    raw = [c["position"]] if "position" in c else c["positions"]
    if not isinstance(raw, list) or not raw:
        raise TuningError(f"{where}: `positions` must be a non-empty list")
    for pos in raw:
        if isinstance(pos, bool) or not isinstance(pos, int) or pos < 1:
            raise TuningError(f"{where}: a position must be an integer >= 1")
    if len(set(raw)) != len(raw):
        raise TuningError(f"{where}: a position appears twice")
    return raw


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
    # the A1 and A2 of this A, B, A sequence are also the core's baseline (written before the
    # variant row), so a core with variants needs no separate A, A sequence (user, 2026-11-20)
    also_baseline: bool = False

    @property
    def name(self) -> str:
        return self.variant.name if self.variant else BASELINE


def build_sequences(plan: Plan, console: str, baselines: set[str], rebaseline: bool = False,
                    only: str | None = None) -> list[Sequence]:
    """The measurement sequences for `console`. A core needs a baseline when the report has
    none for it (`baselines`, the cores with one) or with `rebaseline`: a core with variants
    takes it from the A1 and A2 of its first A, B, A sequence (`also_baseline`); a core with
    none (or `only` asking for the baseline) gets a separate A, A. Every variant is A, B, A.
    `only` is `core` or `core:variant`."""
    if console not in plan.consoles:
        raise TuningError(f"plan is for {', '.join(plan.consoles)}, not {console}")
    want_core, _, want_variant = (only or "").partition(":")
    out = []
    for c in plan.cores:
        if want_core and c.core != want_core:
            continue
        needs_base = not c.compares_cores and (rebaseline or c.core not in baselines)
        variants = [v for v in c.variants if not want_variant or v.name == want_variant]
        if needs_base and (want_variant == BASELINE or not variants):
            if not want_variant or want_variant == BASELINE:
                out.append(Sequence(c, None, (Run("A1", None), Run("A2", None))))
            needs_base = False
        for v in variants:
            out.append(Sequence(c, v, (Run("A1", None), Run("B", v), Run("A2", None)),
                                also_baseline=needs_base))
            needs_base = False
    if only and not out:
        raise TuningError(f"nothing in the plan matches {only}")
    return out


def format_sequences(seqs: list[Sequence], console: str, warmup: int = WARMUP_S,
                     measure: int = MEASURE_S) -> str:
    """The dry-run text: one block per sequence, one line per run (no game names: the game
    is the position in the system's list)."""
    # the variants of one core and game run as a group (tuning_ab.run_core_group and
    # run_config_group): the default once before and once after, a B per variant; a separate
    # baseline is A, A
    games = {id(s.core) for s in seqs if s.variant is not None}
    runs = (sum(len(s.runs) for s in seqs if s.variant is None)
            + sum(1 for s in seqs if s.variant is not None) + 2 * len(games))
    lines = [f"console {console}: {len(seqs)} sequence(s), {runs} run(s) of {warmup}+{measure}"
             f" s, at most {round(runs * (warmup + measure + RUN_OVERHEAD_S) / 60)} min"]
    for n, s in enumerate(seqs, 1):
        c = s.core
        lines.append(f"{n}. {c.core} {s.name}: system {c.system} game #{c.position}"
                     f" ({c.process})")
        if s.also_baseline:
            lines.append("   A1 and A2 are also the baseline of the core (no separate A, A)")
        if s.variant is not None and s.variant.core:
            lines.append(f"   check: core {s.variant.core} installed, else the sequence is "
                         f"\"not installed\"")
        for r in s.runs:
            if r.variant is not None and r.variant.core:
                what = (f"core {r.variant.core} for this game only (launcher per-game option)"
                        f"; open, not opening = \"does not open\" and A2 is skipped")
            elif r.variant:
                what = f"apply {r.variant.change()}; open"
            elif c.compares_cores:
                what = f"default core {c.core} (per-game options cleared); open"
            else:
                what = "configuration as is; open"
            lines.append(f"   {r.label}: {what}; wait {warmup} s; measure "
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
    # the folder of the core options is the corename of the core's .info (RetroArch); a _lume
    # build keeps the upstream library_name, which names the folder, and only its .info
    # corename has the " (Lume)" suffix (GA36, 2026-11-20): dropped, as frontends/retroarch does
    strip = ' n="${n% (*)}";' if core.endswith("_lume") else ""
    return (f"n=$(sed -n 's/^corename *= *\"\\(.*\\)\"/\\1/p' {INFO_DIR}/{core}_libretro.info"
            f" 2>/dev/null | head -n 1);{strip} [ -n \"$n\" ] || n={core}; "
            f"opt=\"{OPT_ROOT}/$n/$n.opt\"; ")


# the card's own runner files win over the image's with the same id (lume-core runner.rs)
CARD_RUNNERS = f"{CARD}/runners.d"
IMAGE_RUNNERS = "/usr/share/lume/runners.d"


def save_command(core: str, games_system: str | None = None) -> str:
    """Save in RAM the user's RetroArch config, the extra config and the core's options:
    `<tag>` is the copy (missing when the file did not exist) and `<tag>.path` the original
    path. With `games_system` (a core comparison, task 10.2) the launcher's per-game options
    file of that system is saved too. A save left by an interrupted run is put back first, so
    the originals are never lost, whatever core that run measured."""
    games = ""
    if games_system is not None:
        _ident(games_system, "system", CORE_RE)
        games = f" games:{GAMES_DIR}/{games_system}.toml"
    # the card's LÖVE runner file too: an env variant (task 7.4) writes it for its B run
    runner = f" runner:{CARD_RUNNERS}/love.toml"
    return (restore_command(keep=False) +
            f"mkdir -p {SAVE_DIR}; " + _opt_vars(core) +
            f"for p in cfg:{USER_CFG} extra:{EXTRA_CFG} \"opt:$opt\"{games}{runner}; do "
            "t=${p%%:*}; f=${p#*:}; "
            f"printf '%s\\n' \"$f\" > {SAVE_DIR}/$t.path; "
            f"if [ -f \"$f\" ]; then cp -p \"$f\" {SAVE_DIR}/$t; fi; "
            "done; echo saved")


def restore_command(keep: bool = True, keep_runner: bool = False) -> str:
    """Put the saved files back (one absent at the save is removed). With keep the save
    stays (between runs); without it is deleted (end of a sequence), and so is the tuning
    systems.d file of a core comparison. Nothing to do when there is no save. With
    keep_runner the card's LÖVE runner file is left as it is (between the runs of a LÖVE
    group: it already holds the next run's variables, see runner_next_command)."""
    end = "" if keep else f"rm -rf {SAVE_DIR}; "
    tail = "" if keep else f"rm -f {TUNING_SYSTEMS}; "
    skip = 'case "$pf" in */runner.path) continue;; esac; ' if keep_runner else ""
    return (f"if [ -d {SAVE_DIR} ]; then "
            f"for pf in {SAVE_DIR}/*.path; do [ -f \"$pf\" ] || continue; {skip}"
            "t=${pf%.path}; read -r f < \"$pf\"; [ -n \"$f\" ] || continue; "
            "if [ -f \"$t\" ]; then cp -p \"$t\" \"$f\"; else rm -f \"$f\"; fi; "
            f"done; {end}fi; {tail}")


# --- core comparison (task 10.2) --------------------------------------------------------
#
# The core of one game is swapped through the launcher's own per-game option (lume-core
# options.rs: ROMS/system/lume/games/<system>.toml, keyed by the game's path in the index),
# written ON THE CONSOLE: the remote command resolves "game N of system S" to its path from
# the launcher index, the same records the grid shows, and prints only `applied` or an
# error. The path never crosses the cable. The launcher resolves a stored emulator only when
# the system offers it (options::resolve_layers), so a core that is not yet an `alt_cores` of
# the catalog is offered by our own card file systems.d/zz-lume-tuning.toml, written at the
# start of the sequence: the launcher reads the catalog when it starts again after A1.

INSTALLED, MISSING = "installed", "missing"


def core_installed_command(core: str) -> str:
    """`installed` when the core's library is on the console, `missing` otherwise."""
    _ident(core, "core", CORE_RE)
    return (f"if [ -f {CORES_DIR}/{core}_libretro.so ]; then echo {INSTALLED}; "
            f"else echo {MISSING}; fi")


def card_cores_command(system: str, cores) -> str:
    """Our systems.d file: the cores offered to `system` during the comparison."""
    _ident(system, "system", CORE_RE)
    cores = [_ident(c, "core", CORE_RE) for c in cores]
    body = ("# written by tests/device/tuning_ab.py for a core comparison; removed at the end\n"
            "[[system]]\n"
            f'id = "{system}"\n'
            "emulators = [" + ", ".join(f'{{ runner = "retroarch", core = "{c}" }}'
                                        for c in cores) + "]\n")
    return (f"mkdir -p {TUNING_SYSTEMS.rsplit('/', 1)[0]}; "
            f"printf '%s' {shlex.quote(body)} > {TUNING_SYSTEMS}.tmp; "
            f"mv -f {TUNING_SYSTEMS}.tmp {TUNING_SYSTEMS}; echo applied")


def default_core_command(system: str) -> str:
    """The A runs of a comparison: no per-game option in the system (the saved file comes
    back at the end), so the game opens in the default core."""
    _ident(system, "system", CORE_RE)
    return f"rm -f {GAMES_DIR}/{system}.toml; echo applied"


def game_core_command(system: str, position: int, core: str) -> str:
    """The B run: the per-game options file of `system` holds only game `position` (1-based,
    grid order) with `core`. The index record gives the path offset and length in the string
    table (lume-index index.rs); the path is escaped for a TOML basic string ON THE CONSOLE
    and never printed."""
    _ident(system, "system", CORE_RE)
    _ident(core, "core", CORE_RE)
    if isinstance(position, bool) or not isinstance(position, int) or position < 1:
        raise TuningError("position must be an integer >= 1")
    idx, games = f"{INDEX_DIR}/{system}.bin", f"{GAMES_DIR}/{system}.toml"
    entry = '["%s"]\\nemulator = { runner = "retroarch", core = "%s" }\\n'
    return (f"f={idx}; n=$(od -An -tu4 -j8 -N4 \"$f\" 2>/dev/null | tr -d ' '); "
            f"if ! [ \"${{n:-0}}\" -ge {position} ] 2>/dev/null; then "
            f"echo 'error game {position} of {system} is not in the launcher index'; exit 0; fi; "
            f"set -- $(od -An -tu4 -j{32 + (position - 1) * 32 + 8} -N8 \"$f\"); "
            "p=$(dd if=\"$f\" bs=1 skip=$((32 + n * 32 + $1)) count=$2 2>/dev/null "
            "| sed 's/[\\\\\"]/\\\\&/g'); "
            "case \"$p\" in ''|*[[:cntrl:]]*) echo 'error unusable game path'; exit 0;; esac; "
            f"mkdir -p {GAMES_DIR}; "
            f"printf '{entry}' \"$p\" {core} > {games}.tmp; "
            f"mv -f {games}.tmp {games}; echo applied")


def expect_applied(out: str, what: str) -> None:
    """A remote command answers `applied` or `error <reason>` (never a path)."""
    for line in out.splitlines():
        if line.startswith("error "):
            raise TuningError(f"{what}: {line[6:]}")
    if "applied" not in out.split():
        raise TuningError(f"{what}: unexpected answer from the console")


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
    if variant.env:
        parts.append(_runner_env(variant.env))
    return "".join(parts) + "echo applied"


def _runner_env(env) -> str:
    # the card's love runner: the image's file with a [runner.env] (the card wins)
    body = "\n[runner.env]\n" + "".join(f'{k} = "{v}"\n' for k, v in env)
    card = f"{CARD_RUNNERS}/love.toml"
    return (f"mkdir -p {CARD_RUNNERS}; cp {IMAGE_RUNNERS}/love.toml {card}.tmp; "
            f"printf '%s' {shlex.quote(body)} >> {card}.tmp; mv -f {card}.tmp {card}; ")


def runner_next_command(env) -> str:
    """The card's LÖVE runner file for the NEXT run, written while the current game still
    runs: the launcher reads the runners once, when it starts again right after a game closes
    (lume-core catalog::load_all), and the running game's environment was fixed at its spawn.
    `env` empty: the file as it was at the save (an A run comes next)."""
    if env:
        return _runner_env(env) + "echo applied"
    card = f"{CARD_RUNNERS}/love.toml"
    return (f"if [ -f {SAVE_DIR}/runner ]; then cp -p {SAVE_DIR}/runner {card}; "
            f"else rm -f {card}; fi; echo applied")


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
            if kind == "core":
                _ident(kv, "change core", CORE_RE)
                continue
            k, eq, v = kv.partition("=")
            if kind not in ("ra", "opt", "env") or not eq:
                raise TuningError(f"change {tok!r} is not ra:key=value, opt:key=value or "
                                  f"env:NAME=value")
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
    main, cores = _split_cores_section(text)
    main = main.rstrip("\n") + "\n" + line + "\n"
    path.write_text(main + ("\n" + cores if cores else ""), encoding="utf-8")


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


# --- core comparison: results, families and the aggregated report (task 10.2) ----------
#
# One sequence (A1, B, A2) gives one CoreResult: the game (system and position, never a name
# or a path), the default core of the A runs, the core of B and whether B opened. The results
# go to a private file out of git (out/tuning/<console>-cores.jsonl): the choice per game is
# the user's, on his card. The report (docs/tuning/<console>.md) gets only the aggregate per
# core and hardware family, rewritten from that file after every sequence.

OPENED, NOT_OPEN, NOT_INSTALLED = "opened", "not-open", "not-installed"
STATUSES = (OPENED, NOT_OPEN, NOT_INSTALLED)
# why B did not open (or the class of its end): lume-run start-failed, no start event, another
# core started, the game ended before or during the measurement (`exit=<code> end=<how>`)
REASON_RE = re.compile(r"^[A-Za-z0-9_.=-]{1,24}( [A-Za-z0-9_.=-]{1,24})?$")
NO_FAMILY = "todas"                 # no families file: one group per core
UNKNOWN_FAMILY = "sem-familia"      # a families file without this position
CORES_BEGIN = "<!-- cores:begin -->"
CORES_END = "<!-- cores:end -->"


def exit_class(line: str) -> str:
    """The class of a game end from a cut lume-run end line (`... exit=<code> end=<how>
    secs=<n>`): only the exit code and the way it ended, nothing else of the line."""
    parts = []
    for key in ("exit", "end"):
        m = re.search(rf"\b{key}=(\S+)", line)
        if m:
            parts.append(f"{key}={re.sub(r'[^A-Za-z0-9_.-]', '_', m.group(1))[:16]}")
    return " ".join(parts) or "ended"


@dataclass
class CoreResult:
    date: str
    build: str
    system: str
    position: int
    default: str                    # the core of the A runs
    core: str                       # the core of B
    status: str                     # OPENED, NOT_OPEN, NOT_INSTALLED
    reason: str = ""                # why B did not open
    a: tuple = ()                   # RunMetrics of the A runs
    b: RunMetrics | None = None

    def check(self) -> None:
        _ident(self.system, "system", CORE_RE)
        _ident(self.default, "core", CORE_RE)
        _ident(self.core, "core", CORE_RE)
        if isinstance(self.position, bool) or not isinstance(self.position, int) \
                or self.position < 1:
            raise TuningError("position must be an integer >= 1")
        if self.status not in STATUSES:
            raise TuningError(f"unknown status {self.status!r}")
        if self.reason and not REASON_RE.match(self.reason):
            raise TuningError(f"reason {self.reason!r} is not allowed")

    def to_json(self) -> str:
        self.check()
        d = asdict(self)
        return json.dumps(d, ensure_ascii=True, sort_keys=True)

    @staticmethod
    def from_json(text: str) -> "CoreResult":
        d = json.loads(text)

        def metrics(m):
            return None if m is None else RunMetrics(**{**m, "cpu_pct": tuple(m["cpu_pct"])})
        r = CoreResult(d["date"], d["build"], d["system"], int(d["position"]), d["default"],
                       d["core"], d["status"], d.get("reason", ""),
                       tuple(metrics(m) for m in d.get("a", [])), metrics(d.get("b")))
        r.check()
        return r


def save_result(path: Path, result: CoreResult) -> None:
    line = result.to_json()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_results(path: Path) -> list[CoreResult]:
    """The results file; a broken line (an interrupted write) is skipped."""
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(CoreResult.from_json(line))
        except (ValueError, KeyError, TypeError, TuningError):
            continue
    return out


def latest_results(results: list[CoreResult]) -> list[CoreResult]:
    """The last result of each game and core (a measurement made again replaces the old)."""
    last: dict[tuple, CoreResult] = {}
    for r in results:
        last.pop((r.system, r.position, r.core), None)
        last[(r.system, r.position, r.core)] = r
    return list(last.values())


def load_families(path: Path | None) -> dict[str, dict[int, str]]:
    """The private families file (kept by the user out of git, e.g.
    var/roms_test/families.toml): one table per system, `<position> = "<family>"`. A missing
    file is no families (the report groups by core only)."""
    if path is None or not path.exists():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise TuningError(f"{path.name}: bad TOML: {e}") from None
    out: dict[str, dict[int, str]] = {}
    for system, table in data.items():
        _ident(system, "families system", CORE_RE)
        if not isinstance(table, dict):
            raise TuningError(f"families: [{system}] must be a table of position = \"family\"")
        for pos, fam in table.items():
            if not pos.isdigit() or int(pos) < 1:
                raise TuningError(f"families: [{system}] key {pos!r} is not a position >= 1")
            out.setdefault(system, {})[int(pos)] = _ident(fam, "family", NAME_RE)
    return out


def family_of(families: dict, system: str, position: int) -> str:
    if not families:
        return NO_FAMILY
    return families.get(system, {}).get(position, UNKNOWN_FAMILY)


@dataclass
class Candidate:
    core: str
    drawn_fps: float | None
    speed: float | None
    clock_mhz: float | None
    temp_c: float | None
    audio_failures: float | None


def _candidate(core: str, runs) -> Candidate:
    runs = [m for m in runs if m is not None]

    def avg(metric):
        return _mean(m.value(metric) for m in runs)
    audio = [m.audio_failures for m in runs]
    return Candidate(core, avg("drawn_fps"), avg("speed"), avg("clock_mhz"), avg("temp_c"),
                     None if not audio or None in audio else sum(audio) / len(audio))


def game_candidates(results: list[CoreResult]) -> dict[tuple, list[Candidate]]:
    """Per game (system, position): the default core (mean of every A run of the game) and
    every core that opened (its B run)."""
    by_game: dict[tuple, list[CoreResult]] = {}
    for r in latest_results(results):
        by_game.setdefault((r.system, r.position), []).append(r)
    out = {}
    for key, rs in by_game.items():
        a_runs = [m for r in rs for m in r.a]
        cands = [_candidate(rs[0].default, a_runs)] if a_runs else []
        cands += [_candidate(r.core, [r.b]) for r in rs if r.status == OPENED and r.b]
        out[key] = cands
    return out


def pick(cands: list[Candidate]) -> str | None:
    """The fastest core that runs the game at full speed: full core speed and no more audio
    failures than the default core, then the lowest mean clock (the least work for the same
    game), then more drawn frames. Without any at full speed, the highest core speed."""
    if not cands:
        return None
    ref_audio = cands[0].audio_failures
    full = [c for c in cands if c.speed is not None and c.speed >= SPEED_FULL
            and (c.audio_failures is None or ref_audio is None
                 or c.audio_failures <= ref_audio)]
    if full:
        inf = float("inf")
        return min(full, key=lambda c: (c.clock_mhz if c.clock_mhz is not None else inf,
                                        -(c.drawn_fps or 0.0))).core
    return max(cands, key=lambda c: c.speed if c.speed is not None else -1.0).core


def picks(results: list[CoreResult]) -> dict[tuple, str]:
    """(system, position) -> the chosen core. Private: printed on the PC, never in the report
    (the choice per game stays on the user's card)."""
    out = {}
    for key, cands in sorted(game_candidates(results).items()):
        chosen = pick(cands)
        if chosen:
            out[key] = chosen
    return out


CORE_COLUMNS = ("data", "imagem", "core", "família", "jogos", "abrem", "velocidade cheia",
                "quadros/s", "velocidade", "falhas de áudio", "clock MHz", "temp °C",
                "contra o padrão", "escolhido em")

CORES_HEAD = """## Cores alternativos por família de hardware (tarefa 10.2)

Comparação de cores pela opção por jogo do launcher: cada jogo do sistema roda no core padrão
(A) e em cada core alternativo (B), na ordem `A, B, A`. Uma linha por core e família de
hardware, sem jogo: **jogos** medidos, quantos **abrem** no core, quantos rodam com a
**velocidade cheia** (≥ 99% do nominal), as médias dos que abrem (quadros/s, velocidade, clock,
temperatura), a soma das falhas de áudio, a diferença média **contra o padrão** nos mesmos
jogos e em quantos jogos o core é o **escolhido** (o de menor clock entre os de velocidade cheia
e som igual ao do padrão). A família vem do arquivo privado de famílias do conjunto de teste;
sem ele, `todas`. A escolha de cada jogo fica só no cartão do usuário.

"""


def _core_rows(results: list[CoreResult], families: dict) -> list[dict]:
    latest = latest_results(results)
    chosen = picks(latest)
    groups: dict[tuple, dict] = {}

    def group(core, fam, default):
        return groups.setdefault((fam, 0 if default else 1, core), {
            "core": core, "family": fam, "games": set(), "opened": [], "missing": 0,
            "deltas": [], "dates": [], "default": default})

    by_game: dict[tuple, list[CoreResult]] = {}
    for r in latest:
        by_game.setdefault((r.system, r.position), []).append(r)
    for (system, pos), rs in by_game.items():
        fam = family_of(families, system, pos)
        a_runs = [m for r in rs for m in r.a]
        ref = _candidate(rs[0].default, a_runs) if a_runs else None
        if ref is not None:
            g = group(rs[0].default, fam, True)
            g["games"].add((system, pos))
            g["opened"].append(ref)
            g["dates"] += [(r.date, r.build) for r in rs if r.a]
        for r in rs:
            g = group(r.core, fam, False)
            g["dates"].append((r.date, r.build))
            if r.status == NOT_INSTALLED:
                g["missing"] += 1
                continue
            g["games"].add((system, pos))
            if r.status == OPENED and r.b is not None:
                c = _candidate(r.core, [r.b])
                g["opened"].append(c)
                if ref is not None:
                    g["deltas"].append(c)
                    g.setdefault("refs", []).append(ref)
    rows = []
    for key in sorted(groups):
        g = groups[key]
        n, op = len(g["games"]), g["opened"]
        full = sum(1 for c in op if c.speed is not None and c.speed >= SPEED_FULL)
        audio = [c.audio_failures for c in op]
        date, build = max(g["dates"]) if g["dates"] else ("-", "-")
        if g["default"]:
            versus = "padrão"
        elif g["deltas"]:
            pairs = list(zip(g["deltas"], g["refs"]))
            dclock = _mean(c.clock_mhz - r.clock_mhz for c, r in pairs
                           if c.clock_mhz is not None and r.clock_mhz is not None)
            dfps = _mean(c.drawn_fps - r.drawn_fps for c, r in pairs
                         if c.drawn_fps is not None and r.drawn_fps is not None)
            versus = "; ".join(p for p in (
                None if dclock is None else f"clock {dclock:+.0f}",
                None if dfps is None else f"quadros {dfps:+.1f}") if p) or "-"
        else:
            versus = "-"
        picked = sum(1 for k, c in chosen.items() if c == g["core"]
                     and family_of(families, *k) == g["family"])
        if n == 0 and g["missing"]:
            cells = ["0", "não instalado"] + ["-"] * 6
        else:
            cells = [str(n), f"{len(op)} de {n}", f"{full} de {n}",
                     _f(_mean(c.drawn_fps for c in op)),
                     _pct(_mean(c.speed for c in op)),
                     "-" if not audio or None in audio else _f(sum(audio), 0),
                     _f(_mean(c.clock_mhz for c in op), 0),
                     _f(_mean(c.temp_c for c in op))]
        rows.append(dict(zip(CORE_COLUMNS, [date, build, g["core"], g["family"], *cells,
                                            versus, str(picked)])))
    return rows


def check_core_row_privacy(row: dict) -> None:
    _ident(row["core"], "core", CORE_RE)
    _ident(row["família"], "family", NAME_RE)
    if row["data"] != "-" and not re.match(r"^\d{4}-\d{2}-\d{2}$", row["data"]):
        raise TuningError(f"date {row['data']!r} is not YYYY-MM-DD")
    if not re.match(r"^[A-Za-z0-9_.:+-]{1,40}$", row["imagem"]):
        raise TuningError(f"build {row['imagem']!r} is not allowed")
    for col in CORE_COLUMNS[4:]:
        text = row[col]
        if FORBIDDEN_TEXT.search(text) or "\n" in text:
            raise TuningError(f"cell {text!r} has a forbidden character")
        for word in re.split(r"[\s,;()]+", text):
            if word.lower().endswith(scripts.ROM_EXTENSIONS):
                raise TuningError(f"cell {text!r} looks like it names a ROM file")


def cores_section(results: list[CoreResult], families: dict) -> str:
    lines = [CORES_BEGIN, CORES_HEAD.rstrip("\n"), "",
             "| " + " | ".join(CORE_COLUMNS) + " |",
             "|" + "|".join("---" for _ in CORE_COLUMNS) + "|"]
    for row in _core_rows(results, families):
        check_core_row_privacy(row)
        lines.append("| " + " | ".join(row[c] for c in CORE_COLUMNS) + " |")
    lines.append(CORES_END)
    return "\n".join(lines) + "\n"


def _split_cores_section(text: str) -> tuple[str, str]:
    """(the report without the cores section, the section) of a report file."""
    i = text.find(CORES_BEGIN)
    if i < 0:
        return text, ""
    return text[:i].rstrip("\n") + "\n", text[i:]


def write_cores_section(path: Path, console: str, results: list[CoreResult],
                        families: dict) -> None:
    """Rewrite the cores section of docs/tuning/<console>.md from every result (the A/B rows
    of the file stay as they are, above it)."""
    section = cores_section(results, families)
    text = path.read_text(encoding="utf-8") if path.exists() else report_header(console)
    main, _ = _split_cores_section(text)
    path.write_text(main.rstrip("\n") + "\n\n" + section, encoding="utf-8")


def parse_cores_section(text: str) -> list[dict]:
    """The rows of the cores section, as dicts by column name."""
    _, section = _split_cores_section(text)
    out = []
    for line in section.splitlines():
        if not line.startswith("| ") or line.startswith("| data |"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        if len(cells) == len(CORE_COLUMNS):
            out.append(dict(zip(CORE_COLUMNS, cells)))
    return out
