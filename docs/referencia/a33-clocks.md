# Allwinner A33: clocks, tensões e limites (referência)

Base para o P-11 (frequências acima do mainline), o P-20 (clock por jogo) e qualquer
mudança de clock, tensão ou temperatura no GA36. Escrito em 2026-11-10.

Cada valor tem a origem ao lado. As fontes, da mais forte para a mais fraca:

1. **GA36 medido**: o que o nosso kernel mostrou no aparelho (`ROMS/logs/hw/boot-10.txt`,
   seção `== clocks`, imagem `20261110-222606`).
2. **Fábrica GA36**: o que o firmware de fábrica deste aparelho declara ou mediu
   (`docs/referencia/ga36-emuelec/`, em especial `README.md` e `gpu.md`).
3. **Mainline**: `arch/arm/boot/dts/allwinner/sun8i-a33.dtsi` e `sun8i-a23-a33.dtsi` do
   Linux 6.18.62 e o driver `drivers/clk/sunxi-ng/ccu-sun8i-a23.c` (o A33 usa o CCU do A23).
4. **Manual**: *Allwinner A33 User Manual*, release 1.1 (2014-09-22), páginas indicadas.

Para o GA36, os valores de fábrica valem mais que o manual: o manual diz o que o chip
aceita, a fábrica diz o que foi validado nesta placa.

## 1. O que os documentos não trazem

- **Limites elétricos** (tabelas *Absolute Maximum Ratings* e *Recommended Operating
  Conditions*: faixas de VDD-CPU, VDD-SYS, VCC-DRAM, VCC-IO, temperatura de junção) ficam
  no **datasheet**, não no manual. Em 2026-11-10 o datasheet não pôde ser lido: o
  linux-sunxi respondeu HTTP 522 nas duas URLs (ver "Fontes"). **Nenhum limite elétrico
  deste arquivo vem do datasheet.** Ler o datasheet e completar esta seção antes de
  qualquer mudança de tensão.
- **Frequências máximas por bloco**: o manual não dá o máximo da CPU nem da GPU (a seção
  2.2.1, p. 12, só diz que o Cortex-A7 suporta DVFS com domínio de energia próprio; a 2.2.2,
  p. 13, só cita a Mali400 MP2). O que limita a CPU e a GPU na prática são as tabelas de
  OPP (seção 4) e a tensão disponível.
- **Tabela de DVFS** (frequência × tensão): não está no manual. Vem dos FEX das placas e
  do kernel do fabricante (seção 4).

## 2. CCU (Clock Control Unit)

Base `0x01C20000` (manual, p. 34). Entrada de referência: cristal de 24 MHz (p. 32).
O CCU tem 11 PLLs, com um PLL independente para a CPU (p. 32).

### 2.1 PLLs

| PLL | Offset | Saída | Faixa válida (manual) | Padrão de reset | GA36 medido | Página |
|---|---|---|---|---|---|---|
| PLL_CPUX | 0x000 | 24 MHz·N·K / (M·P); N 1–32, K 1–4, M 1–4, P 1/2/4 | 200 MHz–2,6 GHz | 408 MHz | 1008 MHz | 37–38 |
| PLL_AUDIO | 0x008 | 24 MHz·N / (M·P); N 1–128, M 1–32, P 1–16; 8X = 24 MHz·N·2/M | 20–200 MHz | 24,571 MHz | 24,576 MHz tocando (98,29 MHz em repouso) | 38 |
| PLL_VIDEO | 0x010 | inteiro: 24 MHz·N/M (N 1–128, M 1–16); fracionário: 270 ou 297 MHz | 30–600 MHz | 297 MHz | 297 MHz | 39–40 |
| PLL_VE | 0x018 | igual ao VIDEO | 30–600 MHz | 297 MHz | 320 MHz (sem uso) | 40–41 |
| PLL_DDR0 | 0x020 | 24 MHz·N·K / M; N 1–32, K 1–4, M 1–4; exige `CFG_UPDATE` (bit 20) | 200 MHz–2,6 GHz | 408 MHz | 408 MHz (desligado) | 41–42 |
| PLL_PERIPH | 0x028 | 24 MHz·N·K / 2; 2X = 24 MHz·N·K | 200 MHz–1,8 GHz | 600 MHz | 600 MHz (2X 1200 MHz) | 42–43 |
| PLL_GPU | 0x038 | inteiro: 24 MHz·N/M (N 1–128, M 1–16); fracionário: 270 ou 297 MHz | 30–600 MHz | 297 MHz | 144 MHz (ocioso) | 43–44 |
| PLL_MIPI | 0x040 | (PLL_VIDEO·N·K)/M no modo MIPI; N 1–16, K 1–4, M 1–16 | não informado | (0x00000502) | 356,4 MHz | 44–46 |
| PLL_HSIC | 0x044 | 24 MHz·N/M | 30–600 MHz | 480 MHz | 480 MHz (sem uso) | 46–47 |
| PLL_DE | 0x048 | 24 MHz·N/M | 30–600 MHz | 297 MHz | 297 MHz (sem uso) | 47–48 |
| PLL_DDR1 | 0x04C | 24 MHz·N; N ≥ 12 "na aplicação"; exige `SDRPLL_UPD` (bit 30) | não informado | 576 MHz | 1080 MHz | 48–49 |

Notas do manual:

- O PLL_PERIPH "deve ficar fixo em 600 MHz; não é recomendado variar" (p. 42).
- Tempo de travamento: `PLL_STABLE_TIME_REG0` (0x200) para todos os PLLs menos o da CPU e
  `PLL_STABLE_TIME_REG1` (0x204) para o PLL_CPU, em µs, padrão 0xFF (p. 72).
- `PLL_CPUX_BIAS_REG` (0x220) bit 28 `EXG_MODE`: a CPU passa a usar o PLL_PERIPH no lugar
  do PLL_CPU (p. 72). É o caminho para trocar o PLL_CPU sem parar a CPU.

### 2.2 Barramentos e blocos

| Registrador | Offset | O que define | GA36 medido | Página |
|---|---|---|---|---|
| CPU_AXI_CFG | 0x050 | fonte da CPU (LOSC, OSC24M, PLL_CPU; ao trocar, espera até 8 ciclos), AXI = CPU / 1–4, APB da CPU = CPU / 1, 2 ou 4 | CPU 1008 MHz, AXI 336 MHz (/3) | 49 |
| AHB1_APB1_CFG | 0x054 | AHB1 de LOSC, OSC24M, AXI ou PLL_PERIPH/pré-divisor 1–4, dividido por 1, 2, 4 ou 8; APB1 = AHB1 / 2, 4 ou 8 | AHB1 200 MHz, APB1 100 MHz | 49–50 |
| APB2_CFG | 0x058 | APB2 (UART, TWI) de LOSC, OSC24M ou PLL_PERIPH, /(n·m) | 24 MHz | 50–51 |
| MBUS_CLK | 0x15C | fonte OSC24M, PLL_PERIPH(2X), PLL_DDR0 ou PLL_DDR1, /1–8; "mudar o divisor devagar e esperar 16 ciclos" | 400 MHz (PERIPH 2X / 3) | 69 |
| MIPI_DSI_CLK | 0x168 | relógio do DSI e do D-PHY a partir do PLL_VIDEO (1X ou 2X) ou do PLL_PERIPH | dsi-sclk 297 MHz | 69–70 |
| GPU_CLK | 0x1A0 | GPU = PLL_GPU / 1–8 | 144 MHz | 71 |
| ATS_CLK | 0x1B0 | máximo de 200 MHz (único bloco com máximo explícito nesta parte) | — | 71–72 |
| ADDA_DIG_CLK | 0x140 | relógio digital do codec (1X e 4X) a partir do PLL_AUDIO | ac-dig = PLL_AUDIO | 68 |

### 2.3 Sensor térmico (THS, `0x01C25000`)

- Temperatura = (Dig − 1665) / 6,18 °C, com `Dig` lido do registrador de valor térmico
  (manual, seção 3.18.3, p. 239).
- O ADC do sensor tem relógio de OSC24M ou do PLL de áudio, com máximo de 24 MHz e até
  1 MSPS (p. 238).
- No nosso kernel o driver é o `sun4i-gpadc-iio` (`CONFIG_SUN4I_GPADC`), não o
  `sun8i_thermal` (commit `cfd9076`).

## 3. Tensões (reguladores da AXP223)

| Trilho | Alimenta | Fábrica GA36 | Nosso DTS | Origem |
|---|---|---|---|---|
| dcdc2 (`vdd-sys`) | domínio do sistema (GPU, barramentos, controladores) | 1,10 V | 1,10 V fixo, sem faixa: o kernel não muda a tensão | fábrica `README.md`; tarefa 9.10 |
| dcdc3 (`vdd-cpu`) | CPU | 1,20 V no momento da medição | faixa de 1,04 a 1,32 V, controlada pelo cpufreq | fábrica `README.md`; DTS |
| dcdc5 (`vcc-dram`) | DRAM DDR3 | 1,50 V | sempre ligado | fábrica `README.md` |
| dc5ldo (`vdd-cpus`) | domínio de baixo consumo (CPUS/RTC) | 1,10 V | sempre ligado | fábrica `README.md` |
| dcdc1 (`vcc-io`) | I/O, cartão | 3,00 V | sempre ligado | fábrica `README.md` |

**Limites máximos de cada trilho: pendente** (estão no datasheet, seção 1).

## 4. Pontos de operação (OPP)

### 4.1 CPU

| Origem | Frequências e tensões |
|---|---|
| Mainline (`sun8i-a33.dtsi`) | 120 a 648 MHz a 1,04 V; 720 e 816 MHz a 1,10 V; 912 e 1008 MHz a 1,20 V. Latência de troca de 244 µs (8 períodos de 32 kHz) |
| Discussão do mainline (2016–2017) | 1104 e 1200 MHz pedem **1,32 V**. Ficaram fora da tabela comum e só entram em placas cujo regulador da CPU chega a essa tensão (a SinA33 recebeu os dois) |
| Fábrica GA36 | de 120 a 1344 MHz (`cpuinfo_max_freq`); uso normal até 1200 MHz; acima de ~56 °C cai de 1200 para 1104 MHz; níveis 1104, 1200, 1344 e 1536 MHz no FEX (P-11) |
| Nosso GA36 hoje | até 1008 MHz (tabela mainline), `schedutil` |

Para passar de 1008 MHz (P-11): o `dcdc3` do GA36 já vai até 1,32 V no DTS. Faltaria
acrescentar as OPPs de 1104 e 1200 MHz a 1,32 V, como na SinA33. **Não usar uma
frequência sem a tensão correspondente**: os mantenedores alertam que isso pode travar a
CPU.

### 4.2 GPU

| Origem | Valor |
|---|---|
| Mainline | 144, 240 e 384 MHz; boot em 384 MHz (`assigned-clock-rates`) |
| Fábrica GA36 (`[mali_para]` do FEX) | máximo de 408 MHz a 1,10 V |
| Nosso GA36 hoje | 144, 240 e 384 MHz a 1,10 V no `vdd-sys` (tarefa 9.10), devfreq `simple_ondemand`, resfriamento pela zona `cpu-thermal` a 85 °C e 95 °C |
| Manual | PLL_GPU de 30 a 600 MHz (p. 43–44); GPU = PLL_GPU / 1–8 (p. 71). Sem máximo de clock da GPU |

### 4.3 DRAM

| Origem | Valor |
|---|---|
| Manual | DDR3/DDR3L, 16 bits, até 2 GB, duas *ranks*, escala dinâmica de frequência (seção 2.2.3, p. 14) |
| Fábrica GA36 | 552 MHz, mínimo de 168 MHz pelo devfreq `dsm` |
| Nosso GA36 hoje | `pll-ddr1` 1080 MHz, `dram` 270 MHz, `mbus` 400 MHz. A DRAM é configurada pelo boot0 de fábrica e o Linux não a altera |
| Fex Guide | `dram_clk` em MHz, múltiplo de 24 |

**Pergunta em aberto:** o `dram` de 270 MHz do nosso kernel contra os 552 MHz da fábrica.
Pode ser só convenção (relógio do controlador contra relógio da memória, ou 1080 / 2 = 540
de taxa efetiva), ou a memória pode estar mais lenta que na fábrica, o que pesaria no
desempenho (P-10). Conferir no registrador `DRAM_CFG_REG` (0x0F4) e no `PLL_DDR1` antes de
concluir.

## 5. Temperaturas

| Gatilho | Valor | Origem |
|---|---|---|
| CPU, passivo (reduz clock) | 75 °C | mainline; igual à fábrica |
| GPU, passivo | 85 °C | mainline |
| CPU, *hot* | 90 °C | mainline; igual à fábrica |
| GPU, *hot* | 95 °C | mainline |
| Crítico (desliga) | 110 °C | mainline; igual à fábrica |
| Temperatura máxima de junção | **pendente** (datasheet) | — |

## Fontes

- Manual: <https://dl.linux-sunxi.org/A33/A33%20user%20manual%20release%201.1.pdf>
  (cópia lida: <https://www.olimex.com/Products/OLinuXino/A33/A33-OLinuXino/resources/A33-user-manual-release-1.1.pdf>).
  Documento confidencial da Allwinner, com copyright: só os valores ficam aqui, não o PDF.
- Datasheet, **não lido** (HTTP 522 em 2026-11-10):
  <https://wiki.linux-sunxi.org/A33/A33_Datasheet_release1.0.pdf> e
  <https://dl.linux-sunxi.org/A33/A33%20Datasheet%20release%201.1.pdf>.
- OPPs da CPU no mainline:
  <https://lists.infradead.org/pipermail/linux-arm-kernel/2016-December/474028.html>,
  <https://lkml.iu.edu/hypermail/linux/kernel/1612.2/01436.html> e
  <https://lkml.iu.edu/hypermail/linux/kernel/1703.2/04463.html> (1104 e 1200 MHz a 1,32 V).
- PLL da CPU do A33: <https://lore.kernel.org/lkml/20161213191459.mmoejcmf26qqtyze@lukather/T/>.
- Formato FEX (`dvfs_table`, `mali_para`, `dram_clk`): <https://linux-sunxi.org/Fex_Guide>.
- Dados deste aparelho: `docs/referencia/ga36-emuelec/` e `ROMS/logs/hw/boot-<n>.txt`.
