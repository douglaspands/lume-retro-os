# A33 (GA36): clock e tensão da CPU

Referência para explorar no futuro (pedido do usuário, 2026-11-20, durante a P-115). Nada aqui
mudou a imagem: são dados reunidos para uma decisão posterior.

## O que o kernel do Lume usa hoje

A tabela de pontos de operação (OPP) da CPU do `sun8i-a33.dtsi` do Linux mainline, que o DTS do
GA36 não altera (`board/ga36/dts/sun8i-a33-ga36-mb-v1.2.dtsi`, "the CPU OPPs ... stay as in the
mainline"):

| Clock | Tensão (vdd-cpu) |
|---|---|
| 120, 240, 312, 408, 480, 504, 600, 648 MHz | 1,04 V |
| 720, 816 MHz | 1,10 V |
| 912, 1008 MHz | 1,20 V |

- Regulador da CPU: DCDC3 do PMIC AXP223 (`reg_dcdc3`, `vdd-cpu`), limitado no DTS do GA36 a
  **1,04 V a 1,32 V** (`regulator-min/max-microvolt`).
- 912 e 1008 MHz usam a **mesma** tensão.

## O que o upstream diz dos pontos acima de 1008 MHz

Do patch que montou essa tabela ("ARM: sun8i: a33: add all operating points", Quentin Schulz,
2017-03-21, aplicado):

- Os valores vêm dos arquivos fex de fábrica das placas A33 (repositório `linux-sunxi/sunxi-boards`,
  `sys_config/a33`) e do driver do kernel do fabricante; os fex só dão faixas de frequência por
  tensão.
- "There are two missing frequencies though: 1104MHz and 1200MHz which require the CPU to have
  1.32V supplied, which is higher than the default voltage."
- "Without all A33 boards defining the CPU regulator, we cannot have these two frequencies as it
  would cause the CPU to try to run a higher frequency without 'overvolting' which is very likely
  to crash the CPU. Therefore, these two frequencies must be enabled on a per-board basis."

Fontes: [patch v3 02/11](https://lists.infradead.org/pipermail/linux-arm-kernel/2017-March/495504.html),
[resposta de Chen-Yu Tsai](https://lkml.iu.edu/hypermail/linux/kernel/1703.2/04429.html) (Acked-by),
[resposta de Maxime Ripard](https://lkml.iu.edu/hypermail/linux/kernel/1703.2/04463.html) (aplicado).

## O firmware de fábrica do GA36 (EmuELEC)

Dados em [`ga36-emuelec/`](ga36-emuelec/): CPU de 120 a 1344 MHz (`cpuinfo_max_freq`), uso normal
até **1200 MHz**, queda para 1104 MHz acima de ~56 °C; DCDC3 em 1,20 V no boot (a tabela de tensão
por clock do kernel de fábrica não foi registrada). O regulador aceita de 0,6 a 1,86 V (limite do
PMIC, não da CPU).

## O datasheet

A33 Datasheet (Allwinner, 2014), capítulo 5 "Electrical Characteristics", lido em 2026-11-20 na
cópia que o usuário baixou (o PDF não vai para o repositório; cópia pública em
[linux-sunxi](https://wiki.linux-sunxi.org/A33/A33_Datasheet_release1.0.pdf)):

| Item (página) | Mínimo | Típico | Máximo |
|---|---|---|---|
| VDD-CPU, "Recommended Operating Conditions" (5.2, p. 30) | 0,9 V | 1,1 V | **1,4 V** |
| VDD-CPU, "Absolute Maximum Ratings" (5.1, p. 29) | −0,3 V | — | **1,5 V** |
| VDD-SYS (domínio do sistema e da GPU), recomendado (p. 30) | 0,9 V | 1,1 V | 1,4 V |
| VDD-SYS, máximo absoluto (p. 29) | −0,3 V | — | 1,5 V |
| Temperatura ambiente de operação, comercial (p. 29) | −20 °C | — | 75 °C |

Leitura: os 1,20 V de 912/1008 MHz e os 1,32 V que o upstream pede para 1104/1200 MHz ficam dentro
da faixa recomendada (até 1,4 V); o DTS do GA36 limita o regulador a 1,32 V, abaixo dela. O
"Absolute Maximum" de 1,5 V é limite de dano, não de uso. A página 29 avisa que operar fora das
condições recomendadas por tempo longo pode afetar a confiabilidade.

## O que se sabe pela P-115 (2026-11-20)

O GA36 travou por inteiro com o FBNeo num jogo pesado de arcade, ~6,5 min depois de abrir, a
1008 MHz (três vezes) e também com o teto em **912 MHz** (uma vez), a ~50 °C. Os dois clocks usam
1,20 V. Ainda não se sabe se é tensão: o próximo teste que separa as causas é o mesmo jogo com o
teto em **816 MHz (1,10 V)**; se travar também, a tensão sai da lista e sobram o vídeo e o core.
Ver a P-115 em `docs/PENDENCIAS.md`.

## Caminhos para explorar

- Medir a tensão real do DCDC3 durante o jogo (registro do AXP223 pelo I2C, `i2c-tools` já está na
  imagem do GA36) para confirmar que o kernel pede 1,20 V e o PMIC entrega.
- Subir a tensão de 912/1008 MHz para 1,25–1,30 V (dentro do limite de 1,32 V do DTS), por patch
  do DTS do GA36, e repetir o teste.
- Habilitar 1104/1200 MHz a 1,32 V só no GA36 (como o upstream recomenda, por placa) — mais
  desempenho, mais calor e bateria; só depois de a estabilidade estar resolvida.
