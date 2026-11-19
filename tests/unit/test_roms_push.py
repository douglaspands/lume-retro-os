"""Unit tests of `lume dev roms push` with a fake console: a local folder stands for
/storage and the remote scripts run in the local shell (no device, no ssh). Every name is
synthetic."""
import hashlib
import shutil
import subprocess

import pytest

from lume_tool import cli, roms_push as rp


class FakeLink:
    """The card as a local folder; the console's scripts run in `sh`."""

    def __init__(self, root, corrupt=None):
        self.root = str(root)
        self.corrupt = dict(corrupt or {})   # rel -> number of copies that arrive damaged
        self.copies = []                     # (method, rels)
        self.refreshed = 0

    def run(self, script, data=b""):
        r = subprocess.run(["sh", "-c", script], input=data, capture_output=True)
        return r.returncode, r.stdout

    def _damage(self, rels):
        for rel in rels:
            if self.corrupt.get(rel, 0) > 0:
                self.corrupt[rel] -= 1
                p = f"{self.root}/{rel}"
                with open(p, "r+b") as f:
                    f.write(b"USBC")

    def copy_tar(self, src_root, rels):
        self.copies.append(("tar", list(rels)))
        rc = rp.stream_tar(["sh", "-c", rp.tar_extract_script(self.root)], src_root, rels)
        self._damage(rels)
        return rc

    def copy_rsync(self, src_root, rels):
        self.copies.append(("rsync", list(rels)))
        for rel in rels:
            dst = rp.Path(self.root) / rel
            if dst.exists():                     # --ignore-existing
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_root / rel, dst)
        self._damage(rels)
        return 0

    def refresh_index(self):
        self.refreshed += 1


def gamelist(*games):
    body = "".join(f"\t<game>\n\t\t<path>./{p}</path>\n\t\t<name>{n}</name>\n"
                   f"\t\t<image>./images/{p}.png</image>\n\t</game>\n" for p, n in games)
    return f'<?xml version="1.0"?>\n<gameList>\n{body}</gameList>\n'


def make_set(tmp_path):
    src = tmp_path / "set"
    for sysid, games in (("sysa", ("alpha-rom.bin", "beta-rom.bin")),
                         ("sysb", ("gamma-rom.zip",))):
        d = src / "roms" / sysid
        (d / "images").mkdir(parents=True)
        for g in games:
            (d / g).write_bytes(hashlib.sha256(g.encode()).digest() * 100)
            (d / "images" / f"{g}.png").write_bytes(b"PNG-" + g.encode())
        (d / "gamelist.xml").write_text(
            gamelist(*[(g, f"Title {g}") for g in games]))
    (src / "bios").mkdir()
    (src / "bios" / "firmware-x.bin").write_bytes(b"bios" * 50)
    return src


def card(tmp_path):
    c = tmp_path / "card"
    (c / "roms" / "sysa").mkdir(parents=True)
    (c / "bios").mkdir()
    return c


SOURCE_NAMES = ("alpha-rom", "beta-rom", "gamma-rom", "firmware-x", "Title ", ".png")


def test_empty_card_gets_everything(tmp_path, capsys):
    src, c = make_set(tmp_path), card(tmp_path)
    link = FakeLink(c)
    assert rp.push_roms(src, link, method="tar") == 0
    for f in src.rglob("*"):
        if f.is_file():
            assert (c / f.relative_to(src)).read_bytes() == f.read_bytes()
    assert link.refreshed == 1
    out = capsys.readouterr().out
    assert "transfer: tar over ssh" in out
    sysa = next(ln for ln in out.splitlines() if ln.startswith("sysa"))
    # files (2 games + 2 images), copied, verified, recopied, kept, differ, gamelist
    assert sysa.split() == ["sysa", "4", "4", "4", "0", "0", "0", "+2"]


def test_rsync_method_is_used_when_asked(tmp_path, capsys):
    src, c = make_set(tmp_path), card(tmp_path)
    link = FakeLink(c)
    assert rp.push_roms(src, link, method="rsync") == 0
    assert [m for m, _ in link.copies] == ["rsync"]
    assert "transfer: rsync over ssh" in capsys.readouterr().out


def test_card_with_games_keeps_its_own_and_gets_the_missing(tmp_path, capsys):
    src, c = make_set(tmp_path), card(tmp_path)
    own = gamelist(("own-game.bin", "Own"), ("alpha-rom.bin", "Card title"))
    (c / "roms/sysa/gamelist.xml").write_text(own)
    (c / "roms/sysa/own-game.bin").write_bytes(b"own")
    (c / "roms/sysa/alpha-rom.bin").write_bytes(b"different content")   # a conflict
    link = FakeLink(c)
    assert rp.push_roms(src, link, method="tar") == 0
    assert (c / "roms/sysa/own-game.bin").read_bytes() == b"own"
    assert (c / "roms/sysa/alpha-rom.bin").read_bytes() == b"different content"
    assert (c / "roms/sysa/beta-rom.bin").read_bytes() == \
        (src / "roms/sysa/beta-rom.bin").read_bytes()
    merged = (c / "roms/sysa/gamelist.xml").read_text()
    assert merged.startswith(own[:own.index("</gameList>")])     # card's bytes untouched
    assert merged.count("<game>") == 3
    assert merged.count("alpha-rom.bin</path>") == 1               # card's entry kept
    assert "Title beta-rom.bin" in merged and "<image>./images/beta-rom.bin.png" in merged
    assert merged.rstrip().endswith("</gameList>")
    rp.parse_gamelist(merged.encode(), "/x")                       # still valid XML
    out = capsys.readouterr().out
    sysa = next(ln for ln in out.splitlines() if ln.startswith("sysa"))
    assert sysa.split() == ["sysa", "4", "3", "3", "0", "1", "1", "+1"]
    # nothing copied over an existing file
    assert all("roms/sysa/alpha-rom.bin" not in rels for _, rels in link.copies)


def test_second_push_changes_nothing(tmp_path, capsys):
    src, c = make_set(tmp_path), card(tmp_path)
    assert rp.push_roms(src, FakeLink(c), method="tar") == 0
    before = {p: p.read_bytes() for p in c.rglob("*") if p.is_file()}
    link = FakeLink(c)
    assert rp.push_roms(src, link, method="tar") == 0
    assert link.copies == [] and link.refreshed == 0
    assert {p: p.read_bytes() for p in c.rglob("*") if p.is_file()} == before
    assert "transfer: nothing to copy" in capsys.readouterr().out


def test_hash_difference_is_copied_again(tmp_path, capsys):
    src, c = make_set(tmp_path), card(tmp_path)
    link = FakeLink(c, corrupt={"roms/sysb/gamma-rom.zip": 1})
    assert rp.push_roms(src, link, method="tar") == 0
    assert (c / "roms/sysb/gamma-rom.zip").read_bytes() == \
        (src / "roms/sysb/gamma-rom.zip").read_bytes()
    assert link.copies[-1] == ("tar", ["roms/sysb/gamma-rom.zip"])
    sysb = next(ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("sysb"))
    assert sysb.split()[1:5] == ["2", "2", "2", "1"]


def test_hash_difference_twice_fails(tmp_path, capsys):
    src, c = make_set(tmp_path), card(tmp_path)
    link = FakeLink(c, corrupt={"roms/sysb/gamma-rom.zip": 2})
    assert rp.push_roms(src, link, method="tar") == 1
    assert len(link.copies) == 2                       # one copy and one recopy only
    io = capsys.readouterr()
    assert "still differ" in io.err
    sysb = next(ln for ln in io.out.splitlines() if ln.startswith("sysb"))
    assert sysb.split()[-1] == "skipped"               # no list for a failed system
    assert not (c / "roms/sysb/gamelist.xml").exists()


def test_unreadable_card_list_is_left_alone(tmp_path, capsys):
    src, c = make_set(tmp_path), card(tmp_path)
    junk = b"\x8f\x01 random bytes, not XML"
    (c / "roms/sysa/gamelist.xml").write_bytes(junk)
    assert rp.push_roms(src, FakeLink(c), method="tar") == 1
    assert (c / "roms/sysa/gamelist.xml").read_bytes() == junk
    assert "game list not merged" in capsys.readouterr().err


def test_output_has_no_source_names(tmp_path, capsys):
    src, c = make_set(tmp_path), card(tmp_path)
    (c / "roms/sysa/alpha-rom.bin").write_bytes(b"x")
    rp.push_roms(src, FakeLink(c, corrupt={"roms/sysa/beta-rom.bin": 2}), method="tar")
    io = capsys.readouterr()
    text = io.out + io.err
    for name in SOURCE_NAMES:
        assert name not in text


def test_crash_does_not_leak_names(tmp_path, capsys):
    src = make_set(tmp_path)

    class Broken:
        root = "/nonexistent"

        def run(self, script, data=b""):
            raise OSError(2, "No such file or directory", str(src / "roms/sysa/alpha-rom.bin"))

    assert rp.cmd_roms_push("h", src, "tar", link_factory=lambda h: Broken()) == 1
    err = capsys.readouterr().err
    assert "alpha-rom" not in err and "withheld" in err

    class Weird(Broken):
        def run(self, script, data=b""):
            raise ValueError("bad thing in alpha-rom.bin")

    assert rp.cmd_roms_push("h", src, "tar", link_factory=lambda h: Weird()) == 1
    assert "alpha-rom" not in capsys.readouterr().err


def test_missing_folder_is_an_error(tmp_path, capsys):
    assert rp.cmd_roms_push("h", tmp_path / "none", link_factory=lambda h: None) == 1
    assert "does not exist" in capsys.readouterr().err


@pytest.mark.parametrize("path,expected", [
    ("./a.sfc", "a.sfc"),
    ("/storage/roms/snes/sub/a.sfc", "sub/a.sfc"),
    ("./sub/../a.sfc", "a.sfc"),
    ("/other/a.sfc", "/other/a.sfc"),
    ("  ./a.sfc \n", "a.sfc"),
])
def test_normalize_matches_lume_index(path, expected):
    assert rp.normalize(path, "/storage/roms/snes") == expected


def test_merge_into_empty_root_and_absent_list():
    pc = rp.parse_gamelist(gamelist(("a.bin", "A"), ("b.bin", "B")).encode(), "/pc")
    text, n = rp.merge_lists(None, pc)
    assert n == 2 and text == pc.data
    empty = rp.parse_gamelist(b'<?xml version="1.0"?>\n<gameList/>\n', "/card")
    text, n = rp.merge_lists(empty, pc)
    assert n == 2
    merged = rp.parse_gamelist(text, "/card")
    assert [k for k, _ in merged.games] == ["a.bin", "b.bin"]


def test_empty_game_elements_do_not_confuse_the_spans():
    data = b"<gameList><game/><game><path>./a.bin</path></game></gameList>"
    gl = rp.parse_gamelist(data, "/c")
    assert gl.games == [("", b"<game/>"), ("a.bin", b"<game><path>./a.bin</path></game>")]
    assert data[gl.close:] == b"</gameList>"


def test_merge_matches_absolute_card_paths():
    card_list = rp.parse_gamelist(
        b"<gameList><game><path>/storage/roms/s/a.bin</path></game></gameList>",
        "/storage/roms/s")
    pc = rp.parse_gamelist(gamelist(("a.bin", "A"), ("b.bin", "B")).encode(), "/pc/roms/s")
    text, n = rp.merge_lists(card_list, pc)
    assert n == 1
    assert text.startswith(b"<gameList><game><path>/storage/roms/s/a.bin</path></game>\n")


def test_cli_parses_roms_push():
    args = cli._parser().parse_args(
        ["dev", "roms", "push", "some/dir", "--method", "tar", "--console", "ga36"])
    assert (args.dev_command, args.roms_command, str(args.dir), args.method,
            args.console) == ("roms", "push", "some/dir", "tar", "ga36")
    args = cli._parser().parse_args(["dev", "roms", "push"])
    assert args.dir is None and args.method == "auto"
