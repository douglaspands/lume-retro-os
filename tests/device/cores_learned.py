"""Write what the core comparisons learned, per game, to the user's card (private data, asked by
the user on 2026-11-20 for a future feature such as P-116). Never into the repository.

Run from the repository root with the console on the cable:
    .venv/bin/python tests/device/cores_learned.py ga36|r36s
It reads out/tuning/<console>-cores.jsonl (tests/device/tuning_ab.py), the launcher index on the
card (the file of each grid position), the test set's gamelist.xml and families.toml (var/), and
writes ROMS/system/lume/cores-learned.toml atomically. Format: docs/tuning/aprendizado-cores.md."""
import json
import pathlib
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET

from lume_tool import tuning

CONSOLE = sys.argv[1] if len(sys.argv) > 1 else "ga36"
SSH = ["ssh", "-o", "UserKnownHostsFile=/dev/null", "-o", "StrictHostKeyChecking=no",
       "-o", "LogLevel=ERROR", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "root@10.55.0.1"]
DEST = "/storage/system/lume/cores-learned.toml"
RESULTS = pathlib.Path(f"out/tuning/{CONSOLE}-cores.jsonl")
FAMILIES = tomllib.loads(pathlib.Path("var/roms_test/families.toml").read_text())


def card_path(system: str, position: int) -> str:
    """Game `position` of `system` in the launcher grid, from the launcher index on the card."""
    f = f"/storage/system/lume/cache/index/{system}.bin"
    cmd = (f"f={f}; n=$(od -An -tu4 -j8 -N4 $f | tr -d ' '); "
           f"set -- $(od -An -tu4 -j{32 + (position - 1) * 32 + 8} -N8 $f); "
           "dd if=$f bs=1 skip=$((32 + n * 32 + $1)) count=$2 2>/dev/null")
    return subprocess.run([*SSH, cmd], capture_output=True, text=True, check=True).stdout


def names(system: str) -> dict[str, str]:
    gl = pathlib.Path(f"var/roms_test/roms/{system}/gamelist.xml")
    if not gl.exists():
        return {}
    out = {}
    for g in ET.parse(gl).getroot().findall("game"):
        p = (g.findtext("path") or "").strip().removeprefix("./")
        out[p] = (g.findtext("name") or "").strip()
    return out


def avg(runs, key):
    vals = [r[key] for r in runs if r.get(key) is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def metrics(m):
    if not m:
        return {}
    return {"speed": round(m["speed"], 3) if m.get("speed") is not None else None,
            "fps": round(m["drawn_fps"], 1) if m.get("drawn_fps") is not None else None,
            "clock_mhz": round(m["clock_mhz"]) if m.get("clock_mhz") is not None else None,
            "audio_failures": m.get("audio_failures"),
            "temp_c": round(m["temp_c"], 1) if m.get("temp_c") is not None else None}


rows = [json.loads(line) for line in RESULTS.read_text().splitlines() if line.strip()]
last = {}
for r in rows:                                    # the last measurement of each game and core
    last[(r["system"], r["position"], r["core"])] = r
picks = tuning.picks(tuning.load_results(RESULTS))

games = {}
for (system, pos, core), r in sorted(last.items()):
    g = games.setdefault((system, pos), {"default": r["default"], "date": r["date"], "results": {}})
    g["date"] = max(g["date"], r["date"])
    if r["status"] == "opened":
        g["results"][core] = {"opens": True, **metrics(r["b"])}
        if r.get("a"):
            a = r["a"]
            g["results"].setdefault(r["default"], {"opens": True, **metrics(
                {k: avg(a, k) for k in ("speed", "drawn_fps", "clock_mhz", "audio_failures",
                                        "temp_c")})})
    elif r["status"] == "not-open":
        g["results"][core] = {"opens": False, "reason": r["reason"]}

def q(s):
    return json.dumps(s, ensure_ascii=False)

out = ["# Lume Retro OS: what the measurements learned about the cores of each game on this card.",
       "# Private data of this card (game names and files); written by the PC tool",
       "# (game-experience-tuning, tests/device/tuning_ab.py) and read by future features (P-116).",
       "# `best` is the core with the lowest clock among those at full speed (speed >= 0.99), or",
       "# the fastest when none reaches it. speed 1.0 = full speed; clock_mhz = mean CPU clock the",
       "# governor chose (lower = less battery); audio_failures = seconds with an underrun.",
       "schema = 1", ""]
for (system, pos), g in sorted(games.items()):
    path = card_path(system, pos)
    name = names(system).get(path, pathlib.PurePosixPath(path).stem)
    board = FAMILIES.get(system, {}).get(str(pos), system)
    out += ["[[game]]", f"system = {q(system)}", f"file = {q(path)}", f"name = {q(name)}",
            f"board = {q(board)}", f"console = {q(CONSOLE)}", f"date = {q(g['date'])}",
            f"default_core = {q(g['default'])}", f"best = {q(picks.get((system, pos), g['default']))}", ""]
    for core, res in sorted(g["results"].items()):
        out.append("[[game.result]]")
        out.append(f"core = {q(core)}")
        for k, v in res.items():
            if v is None:
                continue
            out.append(f"{k} = {q(v) if isinstance(v, str) else str(v).lower() if isinstance(v, bool) else v}")
        out.append("")
text = "\n".join(out)
tomllib.loads(text)                                # valid TOML before it reaches the card
subprocess.run([*SSH, f"cat > {DEST}.tmp && sync && mv -f {DEST}.tmp {DEST} && sync"],
               input=text, text=True, check=True)
print(f"{len(games)} games written to {DEST} ({len(text)} bytes)")
