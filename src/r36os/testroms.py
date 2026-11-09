"""ROMs de teste geradas pelo próprio build (6.4): programas mínimos, sem conteúdo
de terceiros. Cada uma só fica num laço infinito, com o cabeçalho que o core exige.
Vão só para o disco de teste da VM, nunca para as imagens dos consoles.
"""

from __future__ import annotations

import struct
from pathlib import Path


def nes() -> bytes:
    """iNES, mapper 0: 16 KiB PRG ($C000), 8 KiB CHR vazia.

    Laço INC $00 / JMP $C000: o byte $0000 da RAM muda enquanto o jogo roda e para
    quando o RetroArch pausa o core (o self-test lê com READ_CORE_RAM).
    """
    header = b"NES\x1a" + bytes([1, 1, 0, 0]) + bytes(8)
    prg = bytearray(16 * 1024)
    prg[0:5] = b"\xe6\x00\x4c\x00\xc0"  # INC $00; JMP $C000
    prg[0x3FFA:0x4000] = struct.pack("<HHH", 0xC000, 0xC000, 0xC000)  # NMI, RESET, IRQ
    return header + bytes(prg) + bytes(8 * 1024)


def snes() -> bytes:
    """LoROM 128 KiB (o menor tamanho que o Snes9x 1.52 aceita): cabeçalho em $7FC0,
    reset em $8000 com BRA $8000."""
    rom = bytearray(128 * 1024)
    rom[0:2] = b"\x80\xfe"  # BRA -2
    rom[0x7FC0:0x7FD5] = b"LUME RETRO OS TESTE  "
    rom[0x7FD5] = 0x20  # LoROM, slow
    rom[0x7FD6] = 0x00  # só ROM
    rom[0x7FD7] = 0x07  # 128 KiB (2^7 KiB)
    rom[0x7FD9] = 0x01
    rom[0x7FFC:0x7FFE] = struct.pack("<H", 0x8000)  # reset (modo emulação)
    rom[0x7FEA:0x7FEC] = struct.pack("<H", 0x8000)  # NMI nativo
    rom[0x7FFA:0x7FFC] = struct.pack("<H", 0x8000)  # NMI emulação
    rom[0x7FDC:0x7FE0] = b"\xff\xff\x00\x00"  # complemento + checksum somam 0x1FE
    s = sum(rom) & 0xFFFF
    rom[0x7FDC:0x7FE0] = struct.pack("<HH", s ^ 0xFFFF, s)
    return bytes(rom)


def sms() -> bytes:
    """Master System 32 KiB: DI; JR $ em $0000 e cabeçalho TMR SEGA em $7FF0."""
    rom = bytearray(32 * 1024)
    rom[0:3] = b"\xf3\x18\xfe"  # DI; JR -2
    rom[0x7FF0:0x7FF8] = b"TMR SEGA"
    rom[0x7FFA:0x7FFC] = struct.pack("<H", sum(rom[:0x7FF0]) & 0xFFFF)
    rom[0x7FFF] = 0x4C  # região export, 32 KiB
    return bytes(rom)


def megadrive() -> bytes:
    """Mega Drive 128 KiB: vetores, cabeçalho SEGA e BRA.S * em $200."""
    rom = bytearray(128 * 1024)
    rom[0:8] = struct.pack(">II", 0x00FFFE00, 0x00000200)  # SP inicial, PC inicial
    for v in range(2, 64):
        rom[v * 4:v * 4 + 4] = struct.pack(">I", 0x200)
    rom[0x100:0x110] = b"SEGA MEGA DRIVE "
    rom[0x110:0x120] = b"(C)LUME 2026.NOV"
    title = b"LUME RETRO OS TESTE".ljust(48)
    rom[0x120:0x150] = title
    rom[0x150:0x180] = title
    rom[0x180:0x18E] = b"GM 00000000-00"
    rom[0x1A0:0x1A8] = struct.pack(">II", 0, len(rom) - 1)
    rom[0x1A8:0x1B0] = struct.pack(">II", 0xFF0000, 0xFFFFFF)
    rom[0x1F0:0x1F3] = b"JUE"
    rom[0x200:0x202] = b"\x60\xfe"  # BRA.S *
    words = struct.unpack(f">{(len(rom) - 0x200) // 2}H", rom[0x200:])
    rom[0x18E:0x190] = struct.pack(">H", sum(words) & 0xFFFF)
    return bytes(rom)


def _gb(cgb: bool) -> bytes:
    rom = bytearray(32 * 1024)
    rom[0x100:0x104] = b"\x00\xc3\x50\x01"  # NOP; JP $0150
    rom[0x134:0x143] = b"LUMETESTE".ljust(15, b"\x00")
    rom[0x143] = 0xC0 if cgb else 0x00
    rom[0x147] = 0x00  # só ROM
    rom[0x148] = 0x00  # 32 KiB
    rom[0x150:0x153] = b"\xf3\x18\xfe"  # DI; JR -2
    chk = 0
    for b in rom[0x134:0x14D]:
        chk = (chk - b - 1) & 0xFF
    rom[0x14D] = chk
    g = sum(rom) - rom[0x14E] - rom[0x14F]
    rom[0x14E:0x150] = struct.pack(">H", g & 0xFFFF)
    return bytes(rom)


def gb() -> bytes:
    return _gb(cgb=False)


def gbc() -> bytes:
    return _gb(cgb=True)


def gba() -> bytes:
    """GBA: B para $C0, cabeçalho com checksum, laço B . em $C0."""
    rom = bytearray(64 * 1024)
    rom[0:4] = struct.pack("<I", 0xEA00002E)  # B $C0
    rom[0xA0:0xAC] = b"LUMETESTE\x00\x00\x00"
    rom[0xAC:0xB0] = b"LUME"
    rom[0xB0:0xB2] = b"00"
    rom[0xB2] = 0x96
    chk = 0
    for b in rom[0xA0:0xBD]:
        chk = (chk - b) & 0xFF
    rom[0xBD] = (chk - 0x19) & 0xFF
    rom[0xC0:0xC4] = struct.pack("<I", 0xEAFFFFFE)  # B .
    return bytes(rom)


def psx_exe() -> bytes:
    """PS-X EXE: carrega em $80010000 e fica em j . / nop."""
    code = struct.pack("<II", 0x08004000, 0x00000000)  # j 0x80010000; nop
    text = code.ljust(2048, b"\x00")
    header = bytearray(2048)
    header[0:8] = b"PS-X EXE"
    struct.pack_into("<IIIIIIII", header, 0x10,
                     0x80010000, 0, 0x80010000, len(text), 0, 0, 0, 0)
    struct.pack_into("<I", header, 0x30, 0x801FFFF0)  # SP
    header[0x4C:0x4C + 20] = b"Sony Computer Entertainment Inc. for North America area"[:20]
    return bytes(header) + text


# sistema -> (nome do arquivo, gerador). Arcade fica de fora: precisa de romsets reais.
ROMS = {
    "nes": ("Teste NES.nes", nes),
    "snes": ("Teste SNES.sfc", snes),
    "mastersystem": ("Teste Master System.sms", sms),
    "megadrive": ("Teste Mega Drive.md", megadrive),
    "gb": ("Teste Game Boy.gb", gb),
    "gbc": ("Teste Game Boy Color.gbc", gbc),
    "gba": ("Teste GBA.gba", gba),
    "psx": ("Teste PlayStation.exe", psx_exe),
}


def write_all(dest: Path) -> list[Path]:
    out = []
    for system, (name, gen) in ROMS.items():
        p = dest / "roms" / system / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(gen())
        out.append(p)
    return out
