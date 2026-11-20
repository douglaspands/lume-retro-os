"""Device test scripts (TOML) of `lume dev run`: schema and validation (virtual-gamepad, D4).

    description = "optional text"
    consoles = ["ga36", "r36s"]            # non-empty subset of ga36, r36s, vm

    [[step]]
    name = "open the menu"                 # the step label: never a game
    type = "keys"                          # keys|play|wait_event|wait_process|shot|sh|
                                           # open_game|close_game|home|push_love
    timeout = 30                           # seconds, > 0; default depends on the type
    sequence = "fn+start,wait:500"         # type fields below

Type fields (all required unless marked optional):
    keys          sequence (the `dev keys` syntax)
    play          recording (a path under cache/, a `.evrec`)
    wait_event    pattern (regex), category (optional)
    wait_process  process, state = "present" | "absent"
    shot          screen (a name in tests/device/shots/screens.toml)
    sh            command
    open_game     system, position (integer >= 1)
    close_game    (none)
    home          (none): back to the Dock, focus on Favorites (the launcher home)
    push_love     source (a game directory under tests/device/, packed into a reproducible
                  .love), dest (absolute console path ending in .love)

Privacy: game names and ROM paths never go in a script. The keys `game`, `rom`, `path`,
`content` and `title` are refused anywhere, and a step `name` must not look like a ROM file
(a ROM-like extension such as .gba or .zip). Unknown types and unknown fields are errors.
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

CONSOLES = ("ga36", "r36s", "vm")
FORBIDDEN_KEYS = ("game", "rom", "path", "content", "title")
# extensions that mark a ROM or an archive of one; a step name ending in one is refused
ROM_EXTENSIONS = (
    ".zip", ".7z", ".gba", ".gb", ".gbc", ".nes", ".sfc", ".smc", ".md", ".gen", ".sms",
    ".gg", ".pce", ".n64", ".z64", ".v64", ".nds", ".iso", ".bin", ".cue", ".chd", ".cso",
    ".pbp", ".a26", ".a78", ".lnx", ".ws", ".wsc", ".ngp", ".ngc", ".col", ".sg", ".fds",
)

# type -> (default timeout in seconds, required fields, optional fields)
TYPES: dict[str, tuple[int, tuple[str, ...], tuple[str, ...]]] = {
    "keys": (60, ("sequence",), ()),
    "play": (120, ("recording",), ()),
    "wait_event": (30, ("pattern",), ("category",)),
    "wait_process": (30, ("process", "state"), ()),
    "shot": (30, ("screen",), ()),
    "sh": (30, ("command",), ()),
    "open_game": (60, ("system", "position"), ()),
    "close_game": (30, (), ()),
    "home": (30, (), ()),
    "push_love": (60, ("source", "dest"), ()),
}
DEST_RE = re.compile(r"/[A-Za-z0-9_./-]+")
COMMON = ("name", "type", "timeout")
TOP = ("description", "consoles", "step")
STATES = ("present", "absent")


class ScriptError(ValueError):
    """An invalid script; the message names the step when there is one."""


@dataclass
class Step:
    name: str
    type: str
    timeout: float
    fields: dict = field(default_factory=dict)


@dataclass
class Script:
    consoles: list[str]
    steps: list[Step]
    description: str = ""


def _walk_forbidden(node, where: str) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k in FORBIDDEN_KEYS:
                raise ScriptError(f"{where}: field `{k}` is forbidden (no game names or "
                                  f"ROM paths in scripts)")
            _walk_forbidden(v, where)
    elif isinstance(node, list):
        for v in node:
            _walk_forbidden(v, where)


def _str(step: dict, key: str, where: str) -> str:
    v = step[key]
    if not isinstance(v, str) or not v.strip():
        raise ScriptError(f"{where}: `{key}` must be a non-empty string")
    return v


def _check_recording(rel: str, where: str) -> None:
    p = PurePosixPath(rel)
    if p.is_absolute() or ".." in p.parts or p.parts[:1] != ("cache",) or len(p.parts) < 2:
        raise ScriptError(f"{where}: `recording` must be a path under cache/")
    if p.suffix != ".evrec":
        raise ScriptError(f"{where}: `recording` must end in .evrec")


def _validate_step(i: int, step: object) -> Step:
    where = f"step {i}"
    if not isinstance(step, dict):
        raise ScriptError(f"{where}: must be a table")
    label = step.get("name")
    if label is not None:
        where = f"step {i} `{label}`" if isinstance(label, str) else where
    for key in ("name", "type"):
        if key not in step:
            raise ScriptError(f"{where}: missing `{key}`")
    name = _str(step, "name", where)
    if name.lower().endswith(ROM_EXTENSIONS):
        raise ScriptError(f"{where}: the step name looks like a ROM file")
    stype = _str(step, "type", where)
    if stype not in TYPES:
        raise ScriptError(f"{where}: unknown type `{stype}` (known: {' '.join(TYPES)})")
    default_timeout, required, optional = TYPES[stype]
    unknown = set(step) - set(COMMON) - set(required) - set(optional)
    if unknown:
        raise ScriptError(f"{where}: unknown field(s) for {stype}: "
                          f"{', '.join(sorted(unknown))}")
    for key in required:
        if key not in step:
            raise ScriptError(f"{where}: {stype} needs `{key}`")
    timeout = step.get("timeout", default_timeout)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ScriptError(f"{where}: `timeout` must be a number of seconds > 0")
    fields = {k: step[k] for k in (*required, *optional) if k in step}
    for key, v in fields.items():
        if key == "position":
            if isinstance(v, bool) or not isinstance(v, int) or v < 1:
                raise ScriptError(f"{where}: `position` must be an integer >= 1")
        else:
            _str(fields, key, where)
    if stype == "keys":
        from lume_tool.dev import DevError, parse_sequence   # the `keys` step reuses it
        try:
            parse_sequence(fields["sequence"])
        except DevError as e:
            raise ScriptError(f"{where}: {e}") from None
    elif stype == "wait_event":
        try:
            re.compile(fields["pattern"])
        except re.error as e:
            raise ScriptError(f"{where}: bad `pattern`: {e}") from None
    elif stype == "wait_process" and fields["state"] not in STATES:
        raise ScriptError(f"{where}: `state` must be one of {', '.join(STATES)}")
    elif stype == "play":
        _check_recording(fields["recording"], where)
    elif stype == "push_love":
        src = PurePosixPath(fields["source"])
        if src.is_absolute() or ".." in src.parts or src.parts[:2] != ("tests", "device") \
                or len(src.parts) < 3:
            raise ScriptError(f"{where}: `source` must be a directory under tests/device/")
        dest = fields["dest"]
        if not DEST_RE.fullmatch(dest) or ".." in dest.split("/") or not dest.endswith(".love"):
            raise ScriptError(f"{where}: `dest` must be an absolute console path ending in .love")
    return Step(name, stype, float(timeout), fields)


def validate(data: dict) -> Script:
    """Validate a parsed TOML document and return the script."""
    _walk_forbidden(data, "script")
    unknown = set(data) - set(TOP)
    if unknown:
        raise ScriptError(f"unknown top-level field(s): {', '.join(sorted(unknown))}")
    consoles = data.get("consoles")
    if (not isinstance(consoles, list) or not consoles
            or any(c not in CONSOLES for c in consoles) or len(set(consoles)) != len(consoles)):
        raise ScriptError(f"`consoles` must be a non-empty list from: {', '.join(CONSOLES)}")
    desc = data.get("description", "")
    if not isinstance(desc, str):
        raise ScriptError("`description` must be a string")
    steps = data.get("step")
    if not isinstance(steps, list) or not steps:
        raise ScriptError("a script needs at least one [[step]]")
    return Script(list(consoles), [_validate_step(i, s) for i, s in enumerate(steps, 1)], desc)


def loads(text: str) -> Script:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ScriptError(f"bad TOML: {e}") from None
    return validate(data)


def load(path: str | Path) -> Script:
    try:
        return loads(Path(path).read_text(encoding="utf-8"))
    except ScriptError as e:
        raise ScriptError(f"{path}: {e}") from None


def check_console(script: Script, console: str) -> None:
    """Refuse to run a script on a console it does not list."""
    if console not in script.consoles:
        raise ScriptError(f"script is for {', '.join(script.consoles)}, not {console}")
