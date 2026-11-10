"""docs/LOGS.md describes what r36os-logd writes (task 5.8), and the logs are in English."""

import re

from r36os.paths import REPO_ROOT

LIBEXEC = REPO_ROOT / "rootfs/overlay/usr/libexec/r36os"
LOGD = (LIBEXEC / "logd").read_text()
LOGS_SH = (LIBEXEC / "logs.sh").read_text()
DOC = (REPO_ROOT / "docs/LOGS.md").read_text()
# Scripts that record events
EVENT_SOURCES = LOGD + LOGS_SH + (LIBEXEC / "bootlog").read_text() + (LIBEXEC / "session").read_text()


def _section(title: str) -> str:
    return DOC.split(f"## `{title}", 1)[1].split("\n## ", 1)[0]


def _header_columns() -> list[str]:
    """Columns of the header built in discover() (variables as patterns)."""
    body = re.search(r"discover\(\) \{(.*?)\n\}", LOGD, re.S).group(1)
    cols: list[str] = []
    for fmt in re.findall(r"printf '([^']*)'", body):
        for col in fmt.replace("\\n", "").split(","):
            col = col.replace("%s", "<x>")
            if col:
                cols.append(col)
    return cols


def test_header_matches_doc():
    cols = _header_columns()
    assert cols[:2] == ["time", "uptime_s"]
    doc_cols = re.findall(r"^\| `([^`]+)` \|", _section("metrics/"), re.M)
    # the doc (in Portuguese) names the placeholders
    patterns = {"temp_<x>_c": "temp_<zona>_c", "freq_<x>_mhz": "freq_<política>_mhz",
                "cpu<x>_pct": "cpu<N>_pct"}
    expected = [patterns.get(c, c) for c in cols]
    assert expected == doc_cols


def test_event_categories_documented():
    used = set(re.findall(r"\bevent ([a-z]+) [A-Z]+\b", EVENT_SOURCES))
    doc = set(re.findall(r"^\| `([a-z]+)` \|", _section("events.log"), re.M))
    assert used, "no events found"
    assert used <= doc, f"undocumented categories: {used - doc}"


def test_event_results_are_ok_or_fail():
    results = set(re.findall(r"\bevent [a-z]+ ([A-Z]+)\b", EVENT_SOURCES))
    assert results == {"OK", "FAIL"}


def test_frontend_states_documented():
    states = set(re.findall(r"FE_STATE=([a-z_]+)", LOGD))
    row = re.search(r"^\| `frontend` \|(.*)$", _section("metrics/"), re.M).group(1)
    assert states and states <= set(re.findall(r"`([a-z_]+)`", row)), states


def test_log_text_is_english():
    """No accents in event messages, in the CSV header or in the default logs.conf."""
    lines = [line for line in EVENT_SOURCES.splitlines() if re.search(r"\bevent [a-z]+ [A-Z]+ ", line)]
    lines += re.findall(r"printf '([^']*)'", LOGD)
    lines += re.search(r"LOGS_CONF_DEFAULT='(.*?)'", LOGS_SH, re.S).group(1).splitlines()
    accented = [line for line in lines if re.search(r"[À-ÿ]", line.replace("°C", ""))]
    assert not accented, accented


def test_conf_defaults_documented():
    # lines of LOGS_CONF_DEFAULT (the last one closes the string with ')
    defaults = dict(re.findall(r"^([a-z_]+)=([0-9]+)'?$", LOGS_SH, re.M))
    assert defaults == {"enable": "1", "interval": "5", "flush": "60",
                        "keep_boots": "30", "max_mb": "64"}
    for k, v in defaults.items():
        assert f"| `{k}` | `{v}` |" in DOC, k
