# Referência: medições no GA36-MB V1.2 (projeto EmuELEC)

Cópia, feita em 2026-11-09, dos dados medidos no próprio aparelho (Allwinner A33,
Cortex-A7) pelo projeto anterior do dono deste repositório. Aquele projeto modificava a
imagem EmuELEC 4.7 de fábrica, com kernel sunxi legado. Os arquivos estão aqui para que
este repositório não dependa de nenhuma pasta externa. São **referência**: nada daqui
entra na imagem nem no build.

A change `alpine-retroarch-distro` usa os padrões do Alpine de propósito, para avaliá-los
primeiro no GA36. As otimizações abaixo ficam para uma change futura. Os valores de
sysfs vêm do kernel sunxi legado e mudam de nome no kernel mainline.

## Resumo do que foi medido

### Compilação para o A33

Flags vencedoras (`cores/*/receita.toml`, avaliação em `cores/snes9x2005_plus/RESULTADOS.md`):

```
-O2 -marm -mcpu=cortex-a7 -mfpu=neon-vfpv4 -mfloat-abi=hard -DNDEBUG
-flto=auto -fuse-linker-plugin -ffunction-sections -fdata-sections
ligação: -Wl,--gc-sections -Wl,-O1 -s
```

- `-O2` gastou 10,2% menos CPU que o core original no Yoshi's Island (Super FX 2), a 1200 MHz.
- `-O3` foi cerca de 10% **pior** que o original. A explicação provável é o código maior
  (663 KB contra 556 KB) no cache de instruções de 32 KB do Cortex-A7.
- PGO (treinado no aparelho) ficou 5,1% acima do `-O2`, e foi descartado.
- Também foram descartados: `-Ofast`/`-ffast-math` (core inteiro, risco no áudio),
  `-funroll-loops`, `-falign-*`, graphite e `-fno-plt`. `-mthumb` não foi testado.
- **SNES:** o `snes9x2010` satura um núcleo (100%) no Yoshi em todas as variantes. O
  `snes9x2005_plus` fica abaixo de 60% num núcleo, e por isso é o core do SNES para o A33.
  O defeito de som num trecho do Yoshi aparece nos dois e é da emulação.
- `cores/toolchain/`: o cross-GCC armhf (Debian bookworm, glibc) e o wrapper `a33-cc`,
  que põe as flags da variante depois das do Makefile do core.

### CPU, temperatura e DRAM (`medicoes/r36-sysinfo.txt`)

- CPU de 120 MHz a 1344 MHz (`cpuinfo_max_freq`); o uso normal vai até 1200 MHz.
- Acima de cerca de 56 °C o clock cai de 1200 para 1104 MHz, mesmo em `performance`.
- Trip points do kernel de fábrica: 75 °C e 90 °C ativos, 110 °C crítico.
- DRAM a 552 MHz (mínimo de 168 MHz no devfreq `dsm`), o que confere com o Apêndice B do design.
- Governor ajustado (`sistema/cpu-ondemand-tune`): ondemand com `up_threshold` 30,
  `sampling_down_factor` 10 e mínimo de 600 MHz. Com isso o aparelho responde rápido
  sem fixar o máximo.

### Reguladores da AXP223 no boot de fábrica

| Regulador | Tensão | | Regulador | Tensão |
|---|---|---|---|---|
| dcdc1 | 3000 mV | | aldo1 | 3000 mV |
| dcdc2 | 1100 mV | | aldo2 | 2500 mV |
| dcdc3 | 1200 mV | | aldo3 | 3000 mV |
| dcdc4 | 1100 mV | | dldo3 | 3000 mV |
| dcdc5 | 1500 mV (DDR3) | | dc5ldo | 1100 mV |

dc1sw, dc5ldo, dldo3, aldo1-3 e dcdc2/3/5 ficam ligados (o kernel avisa "incomplete constraints, leaving on").

### Áudio (`sistema/audio-*`)

- O ganho de saída é um só, analógico: `speaker volume control` vai de 0 a 63, e o DAC
  toca em 0 dB. A escala de fábrica é `ganho = (volume * 43 + 50) / 100 + 20`. O volume 0
  de fábrica não silencia; o certo é ganho 0.
- Contra pipocos no RetroArch: `audio_latency = 96` (de 64) e `audio_resampler_quality = 1` (de 2).
- O `Speaker Function` (`spk` ou `headset`) segue o estado do fone (`h2w/state` no kernel legado).

### Bateria (`sistema/bateria-*`, `ferramentas/*bateria*.py`)

- A curva de tensão para porcentagem foi medida num ciclo completo de descarga (15 boots,
  264 min, 2640 mAh integrados). Ela compensa a resistência interna (150 mΩ) e filtra as
  amostras. O erro médio é 0,7 ponto e o máximo 5,5.
- `ferramentas/ajusta_curva_bateria.py` refaz a curva a partir de um `r36-thermal.csv`.
- O registro bruto, com uma amostra a cada 5 s, está em `medicoes/r36-thermal*.csv`
  (temperatura, clock, ocupação por núcleo, bateria, core e ROM), gravado por `sistema/thermal-log`.

### Memória

`sistema/zram-swap`: swap em zram com metade da RAM e prioridade máxima, no lugar de
swapfile no cartão.

### Gravação do cartão (`ferramentas/flash.*`)

O layout é o da imagem EmuELEC, não o deste repositório, mas as proteções servem de
modelo para gravar o cartão do GA36:

- só aceita um disco inteiro removível ou um `mmcblk`, nunca uma partição nem um disco do sistema;
- exige que o usuário digite o nome do dispositivo;
- confere o sha256 antes de gravar e relê depois;
- faz `sync`, `blockdev --flushbufs` e `udisksctl power-off` ao terminar;
- tem `--dry-run` e grava em arquivo (`--target-file`) para testar sem cartão.

## Arquivos

| Caminho | Origem no projeto EmuELEC |
|---|---|
| `cores/snes9x2005_plus/`, `cores/snes9x2010/` | `cores/<core>/` (receita, resultados, registro dos builds) |
| `cores/toolchain/` | `cores/toolchain/` |
| `sistema/cpu-ondemand-tune` | `features/44-cpu-ondemand` |
| `sistema/zram-swap` | `features/40-zram-swap` |
| `sistema/audio-prepara`, `audio-ganho` | `features/46-audio` |
| `sistema/bateria-percentual`, `bateria-curva.conf` | `features/48-bateria-percentual` |
| `sistema/thermal-log` | `features/43-registro-termico` |
| `medicoes/` | `var/r36-sysinfo.txt`, `var/r36-thermal.csv`, `var/r36-thermal.1.csv` |
| `ferramentas/` | `tools/ajusta_curva_bateria.py`, `tools/analisa_bateria.py`, `tools/r36img/flash.py`, `flash.sh` |

Não foram copiados a imagem de fábrica (só baixando do post original), os binários dos
cores, o perfil de PGO (`.gcda`) e os temas do EmulationStation.
