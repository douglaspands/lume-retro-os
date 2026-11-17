"""Delivery status of an OpenSpec change: progress, waves, ready nodes, what runs, what is left.

Usage: .venv/bin/python .claude/skills/change-status/status.py [<change>] [--json]

Reads openspec/changes/<change>/tasks.md (checkboxes, the "Grafo de execução" table and the
device windows table) and the live state of the repository: worktrees of the change and
whether their branches are merged, running podman containers, and r36os build/pkg/push/flash
processes (also the ones started through cache/tmp/timed.py), with their age. Output is plain text (English
labels); the skill turns it into a short summary for the user.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CHECK = re.compile(r"^- \[([ x])\] (\d+\.\d+) (.*)")
GROUP = re.compile(r"^## (\d+)\. (.*)")
ID = re.compile(r"\d+\.\d+")


def run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT,
                              timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def active_change() -> str:
    data = json.loads(run(["openspec", "list", "--json"]) or "{}")
    names = [c.get("name") for c in data.get("changes", []) if c.get("status") != "complete"]
    if len(names) != 1:
        sys.exit(f"give the change name (active changes: {', '.join(names) or 'none'})")
    return names[0]


def parse_tasks(text: str) -> tuple[dict, dict, list]:
    tasks: dict[str, dict] = {}
    groups: dict[str, str] = {}
    graph_rows: list[list[str]] = []
    windows: list[list[str]] = []
    group = None
    for line in text.splitlines():
        if m := GROUP.match(line):
            group = m.group(1)
            groups[group] = m.group(2).strip()
        elif m := CHECK.match(line):
            title = re.split(r"\.\s|:\s|;\s|\s\(", m.group(3), maxsplit=1)[0].strip()
            tasks[m.group(2)] = {"done": m.group(1) == "x", "group": group,
                                 "title": title[:70]}
        elif line.startswith("|") and not line.startswith("|---"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells and ID.fullmatch(cells[0]) and len(cells) >= 7:
                graph_rows.append(cells)
            elif cells and re.fullmatch(r"J\d+", cells[0]):
                windows.append(cells)
    for c in graph_rows:
        node, deps, res, executor, model, wave, window = c[:7]
        if node in tasks:
            tasks[node].update(deps_text=deps, resources=res, executor=executor, model=model,
                               wave=int(wave) if wave.isdigit() else None, window=window)
    return tasks, groups, windows


def expand_deps(text: str, ids: list[str]) -> list[str]:
    if "todos" in text:
        return ids
    out: list[str] = []
    for a, b in re.findall(r"(\d+\.\d+)\s*[–-]\s*(\d+\.\d+)", text):
        ga, na = map(int, a.split("."))
        gb, nb = map(int, b.split("."))
        out += [i for i in ids if ga == gb == int(i.split(".")[0])
                and na <= int(i.split(".")[1]) <= nb]
        text = text.replace(f"{a}", "").replace(f"{b}", "")
    out += [i for i in ID.findall(text) if i in ids]
    return out


def live_state(change: str) -> dict:
    merged = set(run(["git", "branch", "--merged", f"feature/{change}",
                      "--format=%(refname:short)"]).split())
    worktrees = []
    for block in run(["git", "worktree", "list", "--porcelain"]).split("\n\n"):
        path = re.search(r"^worktree (.*)$", block, re.M)
        branch = re.search(r"^branch refs/heads/(.*)$", block, re.M)
        if path and branch and branch.group(1).startswith(f"{change}/"):
            b = branch.group(1)
            ahead = run(["git", "rev-list", "--count", f"feature/{change}..{b}"]).strip()
            worktrees.append({"node": b.split("/", 1)[1], "branch": b,
                              "merged": b in merged, "ahead": int(ahead or 0)})
    containers = [l for l in run(["podman", "ps", "--format",
                                  "{{.Names}} {{.Image}} {{.RunningFor}}"]).splitlines() if l]
    # r36os commands running now (timed by cache/tmp/timed.py or not), with their age
    builds = []
    for line in run(["ps", "-eo", "etimes=,args="]).splitlines():
        secs, _, args = line.strip().partition(" ")
        m = re.match(r"\S*python\S*\s+\S*timed\.py (\S+) (.*)$", args)
        if m:
            builds.append({"label": m.group(1), "command": m.group(2),
                           "minutes": int(secs) // 60})
        elif re.match(r"\S*(python\S*\s+\S*)?bin/r36os (build|pkg|push|flash)\b", args) and not any(
                b["command"] in args for b in builds):
            builds.append({"label": "r36os", "command": args.split("r36os", 1)[1].strip(),
                           "minutes": int(secs) // 60})
    return {"worktrees": worktrees, "containers": containers, "builds": builds}


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    change = args[0] if args else active_change()
    path = ROOT / "openspec/changes" / change / "tasks.md"
    tasks, groups, windows = parse_tasks(path.read_text())
    ids = list(tasks)
    for i, t in tasks.items():
        t["deps"] = [d for d in expand_deps(t.get("deps_text", ""), ids) if d != i]
    done = [i for i in ids if tasks[i]["done"]]
    pending = [i for i in ids if not tasks[i]["done"]]
    ready = [i for i in pending if all(tasks[d]["done"] for d in tasks[i]["deps"])]
    waves = sorted({t["wave"] for t in tasks.values() if t.get("wave") is not None})
    current = next((w for w in waves if any(tasks[i].get("wave") == w for i in pending)), None)
    live = live_state(change)
    report = {
        "change": change,
        "done": len(done), "total": len(ids),
        "percent": round(100 * len(done) / len(ids), 1) if ids else 0.0,
        "groups": [{"group": g, "name": n,
                    "done": sum(tasks[i]["done"] for i in ids if tasks[i]["group"] == g),
                    "total": sum(tasks[i]["group"] == g for i in ids)}
                   for g, n in groups.items() if any(tasks[i]["group"] == g for i in ids)],
        "waves": [{"wave": w,
                   "done": [i for i in ids if tasks[i].get("wave") == w and tasks[i]["done"]],
                   "pending": [i for i in pending if tasks[i].get("wave") == w]}
                  for w in waves],
        "current_wave": current,
        "ready": [{"node": i, "title": tasks[i]["title"], "model": tasks[i].get("model"),
                   "executor": tasks[i].get("executor"), "wave": tasks[i].get("wave")}
                  for i in ready],
        "windows": [{"window": w[0], "nodes": w[1], "pending": [
            i for i in ID.findall(w[1]) if i in tasks and not tasks[i]["done"]],
            "user": w[3] if len(w) > 3 else ""} for w in windows],
        "live": live,
    }
    if "--json" in sys.argv:
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return
    bar = "#" * round(report["percent"] / 5) + "." * (20 - round(report["percent"] / 5))
    print(f"change {change}: {len(done)}/{len(ids)} tasks [{bar}] {report['percent']}%")
    print(f"current wave: {current}")
    print("groups:")
    for g in report["groups"]:
        print(f"  {g['group']:>2}. {g['name'][:55]:<55} {g['done']}/{g['total']}")
    print("waves:")
    for w in report["waves"]:
        print(f"  wave {w['wave']}: done {' '.join(w['done']) or '-'} | "
              f"pending {' '.join(w['pending']) or '-'}")
    print("ready now (all dependencies done):")
    for r in report["ready"]:
        print(f"  {r['node']:<5} wave {r['wave']} {r['executor']:<6} {r['model'] or '-':<7}"
              f" {r['title']}")
    print("device windows:")
    for w in report["windows"]:
        print(f"  {w['window']}: pending {' '.join(w['pending']) or 'none'}")
    print("running:")
    for b in live["builds"]:
        print(f"  {b['label']}: r36os {b['command']} ({b['minutes']} min)")
    for c in live["containers"]:
        print(f"  container {c}")
    for wt in live["worktrees"]:
        state = "merged" if wt["merged"] else f"not merged, {wt['ahead']} commit(s) ahead"
        print(f"  worktree {wt['node']}: {state}")
    if not (live["builds"] or live["containers"] or live["worktrees"]):
        print("  nothing")


if __name__ == "__main__":
    main()
