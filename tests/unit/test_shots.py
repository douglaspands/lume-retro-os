import pytest

from r36os import dev, shots


def solid(w, h, rgb):
    return shots.Image(w, h, bytes(rgb) * (w * h))


def with_pixel(img, x, y, rgb):
    data = bytearray(img.rgb)
    i = (y * img.width + x) * 3
    data[i:i + 3] = bytes(rgb)
    return shots.Image(img.width, img.height, bytes(data))


def test_png_round_trip():
    img = with_pixel(solid(8, 6, (10, 20, 30)), 3, 2, (200, 100, 50))
    assert shots.decode_png(shots.encode_png(img)) == img


def test_equal_images_pass_without_diff_file(tmp_path):
    img = solid(16, 16, (1, 2, 3))
    ref = tmp_path / "ref.png"
    ref.write_bytes(shots.encode_png(img))
    diff = tmp_path / "diff.png"
    result = shots.compare_screen(ref, shots.encode_png(img), diff)
    assert result.ok and result.differing == 0
    assert not diff.exists()


def test_different_images_fail_and_write_diff(tmp_path):
    ref_img = solid(32, 32, (0, 0, 0))
    cur = shots.Image(32, 32, b"\xff\xff\xff" * 100 + ref_img.rgb[300:])
    ref = tmp_path / "ref.png"
    ref.write_bytes(shots.encode_png(ref_img))
    diff = tmp_path / "out" / "diff.png"
    result = shots.compare_screen(ref, shots.encode_png(cur), diff)
    assert not result.ok and result.differing == 100
    written = shots.decode_png(diff.read_bytes())
    assert written.rgb[:3] == b"\xff\x00\x00"
    assert written.rgb[-3:] == b"\x00\x00\x00"


def test_small_difference_under_the_tolerance_passes():
    ref = solid(16, 16, (100, 100, 100))
    cur = with_pixel(ref, 0, 0, (100 + shots.CHANNEL_TOLERANCE, 100, 100))
    assert shots.compare_images(ref, cur).ok


def test_size_mismatch_fails():
    assert not shots.compare_images(solid(4, 4, (0, 0, 0)), solid(8, 4, (0, 0, 0))).ok


def test_missing_reference_is_an_error(tmp_path):
    with pytest.raises(shots.ShotError):
        shots.compare_screen(tmp_path / "none.png", b"", tmp_path / "d.png")


def test_board_from_machine():
    assert shots.board_from_machine("armv7l\n") == "ga36"
    assert shots.board_from_machine("aarch64") == "r36s"
    with pytest.raises(shots.ShotError):
        shots.board_from_machine("x86_64")


def test_repo_screens_file_lists_home():
    assert "home" in shots.load_screens(dev.SHOTS_DIR)
