"""R36S V5 panel variant in panel-sitronix-st7703 (task 4.2 of r36s-single-card), checked
without building the kernel: the init sequence of patch 0010 is appendix C of the
alpine-retroarch-distro design and the mode is the 60 Hz timing of appendix A."""

import re

from r36os import kpatch
from r36os.kernel import OWN_DRIVER_FILES
from r36os.paths import REPO_ROOT

DESIGN = (REPO_ROOT / "openspec/changes/archive/2026-11-11-alpine-retroarch-distro/design.md").read_text()
DRIVER = "\n".join(kpatch.added_lines(kpatch.find("0010-"),
                                      "drivers/gpu/drm/panel/panel-sitronix-st7703.c"))
# #defines of panel-sitronix-st7703.c (mainline, not touched by the patch)
ST7703 = {"SETEXTC": 0xB9, "SETDISP": 0xB2, "SETRGBIF": 0xB3, "SETCYC": 0xB4,
          "SETBGP": 0xB5, "SETVCOM": 0xB6, "SETPOWER_EXT": 0xB8, "SETMIPI": 0xBA,
          "SETVDC": 0xBC, "UNKNOWN_BF": 0xBF, "SETSCR": 0xC0, "SETPOWER": 0xC1,
          "SETIO": 0xC7, "SETCABC": 0xC8, "SETPANEL": 0xCC, "SETGAMMA": 0xE0,
          "SETEQ": 0xE3, "SETGIP1": 0xE9, "SETGIP2": 0xEA, "UNKNOWN_EF": 0xEF}


def _appendix_c() -> list[tuple[int, ...]]:
    """The R36S V5 sequence of appendix C as DCS writes (command and parameters)."""
    appendix = DESIGN.split("## Apêndice C", 1)[1]  # the design is written in Portuguese
    block = appendix.split("**R36S V5:**", 1)[1].split("```", 2)[1]
    out = []
    for line in block.strip().splitlines():
        kind, delay, size, *data = (int(x, 16) for x in line.split())
        assert kind in (0x05, 0x15, 0x39) and size == len(data), line
        out.append(tuple(data))
    return out


def _driver_sequence() -> list[tuple[int, ...]]:
    body = re.search(r"static void r36s_v5_init_sequence\(.*?\n\{(.*?)\n\}", DRIVER, re.S).group(1)
    out = []
    for args in re.findall(r"mipi_dsi_dcs_write_seq_multi\(dsi_ctx, (.*?)\);", body, re.S):
        cmd, *params = [a.strip() for a in args.split(",")]
        cmd_value = ST7703[cmd.removeprefix("ST7703_CMD_")] if cmd.startswith("ST7703_CMD_") \
            else int(cmd, 16)
        out.append((cmd_value, *(int(p, 16) for p in params)))
    return out


def test_init_sequence_is_appendix_c():
    expected = _appendix_c()
    # the factory sequence ends with sleep out (11) and display on (29), which
    # st7703_enable() sends after the init sequence
    assert expected[-2:] == [(0x11,), (0x29,)]
    assert _driver_sequence() == expected[:-2]
    assert expected[0] == (0xB9, 0xF1, 0x12, 0x87)  # the ST7703 family signature


def test_panel_waits_after_reset_and_keeps_the_factory_order():
    # first boot on the R36S (2026-11-12): with only the 15-20 ms of st7703_prepare(),
    # the third command failed with "failed to write command FIFO" (-110), so the
    # sequence starts with the 100 ms reset-delay-ms of the factory device tree.
    # Leaving sleep before the sequence (Gameforce Chi) left a stain on this panel:
    # sleep out stays after the sequence, in st7703_enable(), as in the factory order.
    body = re.search(r"static void r36s_v5_init_sequence\(.*?\n\{(.*?)\n\}", DRIVER, re.S).group(1)
    calls = re.findall(r"(mipi_dsi_\w+)\(dsi_ctx(?:, (\w+))?", body)
    assert calls[:2] == [("mipi_dsi_msleep", "100"),
                         ("mipi_dsi_dcs_write_seq_multi", "ST7703_CMD_SETEXTC")]
    assert "exit_sleep" not in body


def test_mode_is_the_60hz_timing_of_appendix_a():
    # the factory kernel runs this same mode (register dump of the factory system,
    # task 4.6); the 50 MHz timing of ROCKNIX (boot 12) changed nothing
    body = re.search(r"r36s_v5_mode = \{(.*?)\};", DRIVER, re.S).group(1)
    m = {k: eval(v, {"__builtins__": {}})  # noqa: S307 (numbers and + only)
         for k, v in re.findall(r"\.(\w+)\s*= ([0-9 +]+),", body)}
    # 27.0 MHz; h 640 / fp 120 / sync 10 / bp 120; v 480 / fp 17 / sync 4 / bp 13
    assert m["clock"] == 27000 and m["hdisplay"] == 640 and m["vdisplay"] == 480
    assert m["hsync_start"] - m["hdisplay"] == 120 and m["hsync_end"] - m["hsync_start"] == 10
    assert m["htotal"] - m["hsync_end"] == 120
    assert m["vsync_start"] - m["vdisplay"] == 17 and m["vsync_end"] - m["vsync_start"] == 4
    assert m["vtotal"] - m["vsync_end"] == 13
    refresh = m["clock"] * 1000 / (m["htotal"] * m["vtotal"])
    assert round(refresh, 2) == 59.02  # the rate of D8 (video_refresh_rate, task 6.4)


def test_panel_state_is_read_back_and_logged():
    # third and fourth boots on the R36S (2026-11-12): no error and a grey screen; the
    # panel is read back over DSI before and after the init sequence (patch 0012) so
    # the boot log tells whether the commands reached the controller
    log = "\n".join(kpatch.added_lines(kpatch.find("0012-"),
                                       "drivers/gpu/drm/panel/panel-sitronix-st7703.c"))
    assert "bool log_state;" in log and ".log_state = true," in log
    # logged from st7703_init_panel(), so the reads run where the sequence is sent
    patch = kpatch.find("0012-").read_text()
    assert 'st7703_log_state(ctx, "before-init");' in log
    assert 'st7703_log_state(ctx, "after-init");' in patch.split("@@ static int st7703_init_panel(", 1)[1]
    assert '"panel state %s %02x: %*ph\\n"' in log and '"panel state %s %02x: error %d\\n"' in log
    regs = re.search(r"st7703_state_regs\[\] = \{(.*?)\n\};", log, re.S).group(1)
    for name in ("MIPI_DCS_GET_DISPLAY_ID", "MIPI_DCS_GET_POWER_MODE", "MIPI_DCS_GET_SIGNAL_MODE",
                 "MIPI_DCS_GET_DIAGNOSTIC_RESULT", "ST7703_CMD_SETEXTC", "ST7703_CMD_SETMIPI"):
        assert f"{{ {name}," in regs, name
    # every controller register read back fits the read buffer
    assert max(int(n) for n in re.findall(r", (\d+) \}", regs)) <= 32


def test_dsi_read_drops_stale_payload():
    # seventh boot on the R36S (2026-11-12): the first read timed out and every later
    # read returned the answer of the read before it
    host = "\n".join(kpatch.added_lines(kpatch.find("0012-"),
                                        "drivers/gpu/drm/bridge/synopsys/dw-mipi-dsi.c"))
    assert "static void dw_mipi_dsi_drain_read_fifo(" in host
    assert "if (msg->rx_buf && msg->rx_len)\n\t\tdw_mipi_dsi_drain_read_fifo(dsi);" in host
    assert "dw-mipi-dsi.c" in OWN_DRIVER_FILES
    assert "dw-mipi-dsi-rockchip.c" in OWN_DRIVER_FILES  # patch 0014


def test_init_sequence_is_sent_before_the_video_stream():
    # seventh boot: sent from enable, in video mode, the panel woke up (power mode
    # 0x9c) but kept the grey screen; the factory kernel sends it before the video
    desc = re.search(r"r36s_v5_desc = \{(.*?)\};", DRIVER, re.S).group(1)
    assert ".init_in_prepare = true," in desc
    assert "ctx->panel.prepare_prev_first = ctx->desc->init_in_prepare;" in DRIVER
    prepare = DRIVER.split("if (ctx->desc->init_in_prepare) {", 1)[1]
    assert "ret = st7703_init_panel(ctx);" in prepare.split("}", 1)[0]
    enable = re.search(r"static int st7703_enable\(.*?\n\}", DRIVER, re.S).group(0)
    assert "if (ctx->desc->init_in_prepare)\n\t\treturn 0;" in enable


def test_dsi_settings_match_the_factory_flags():
    desc = re.search(r"r36s_v5_desc = \{(.*?)\};", DRIVER, re.S).group(1)
    # dsi,flags = 0xa03 and 4 lanes in the factory DTB: video, burst, no EOT, LPM
    assert ".lanes = 4" in desc
    for flag in ("MIPI_DSI_MODE_VIDEO", "MIPI_DSI_MODE_VIDEO_BURST",
                 "MIPI_DSI_MODE_NO_EOT_PACKET", "MIPI_DSI_MODE_LPM"):
        assert flag in desc, flag
    assert '{ .compatible = "r36s,r36s-v5-panel", .data = &r36s_v5_desc }' in DRIVER
