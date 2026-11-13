# R36S "V5": gravar, subir e conferir

Guia da primeira subida e da conferência do R36S V5 (Rockchip RK3326, aarch64) com a
imagem `console`, o cartão único do GA36 e do R36S (change `r36s-single-card`).

> **Estado (2026-11-13):** a imagem inicia no aparelho: tela, controle e som funcionam.
> Abertos: volume baixo e zumbido do alto-falante (P-45), fone (P-42) e a verificação nos
> dois consoles (tarefas 9.1 a 9.5 da change). As seções marcadas com *a medir* esperam
> essas verificações.

## 1. Gerar e gravar

```sh
uv run r36os build console                          # 1ª vez: R36OS_GA36_FACTORY e R36OS_R36S_FACTORY (README)
uv run r36os flash console /dev/sdX --full --eject  # cartão novo: imagem + ROMS no resto do cartão
uv run r36os flash console /dev/sdX --update --eject   # cartão já gravado com a console: a ROMS fica
# cartão do GA36 gravado antes (BOOT de 1 GiB): o --update recusa; copiar a ROMS e usar --full
```

O mesmo cartão serve aos dois consoles: basta trocar de aparelho.

## 2. A cadeia de boot de fábrica

O R36S sobe pela cadeia do próprio aparelho, a mesma do cartão que veio com ele (um ArkOS
para o "R36S V5"). Ela é binário fechado, fica fora do git e o build a lê da cópia do
cartão original (`R36OS_R36S_FACTORY`), conferida por SHA256 (`src/r36os/r36s_vendor.py`).

| Etapa | Onde está no cartão | O que faz |
|---|---|---|
| BROM do RK3326 | (no SoC) | lê o `idbloader` **só no setor 64** (provado: no 1088 não inicia) |
| `idbloader` | setores 64 a 405 | inicializa a DDR e carrega o U-Boot |
| `uboot.img` (`LOADER`) | setor 16384, cópias a cada 2048 até 22528 | U-Boot da linha Hardkernel (`odroidgoa-uboot-config`) |
| `trust.img` (`BL3X`) | setores 24576 e 28672 | BL31 (ARM Trusted Firmware): PSCI para ligar os núcleos e desligar |
| `boot.ini` | raiz da `BOOT` | script lido pelo U-Boot: carrega o kernel e o DTB e chama `booti` |

O `boot.ini` de fábrica carrega `Image`, `uInitrd` e `rk3326-r35s-linux.dtb` de
`mmc 1:1`. O nosso (`board/r36s/boot.ini`) carrega `r36s/Image` (kernel com o initramfs
embutido) e `r36s/rk3326-r36s-v5.dtb`, sem `uInitrd`; a linha de comando fica no kernel
(`CONFIG_CMDLINE_FORCE`: `root=PARTUUID=4c554d32-01`, `ttyS2` a 1500000 e `tty1`).

**Tarefa 1.1, o U-Boot lê o nosso `boot.ini`?** **Sim (medido em 2026-11-12)**, mas com
uma condição. O U-Boot de fábrica mede a revisão da placa pelo ADC, escolhe um DTB do
RG351 (`rg351mp-kernel.dtb`, `rg351p-kernel.dtb` ou `rg351v-kernel.dtb`) e o carrega da
raiz da `BOOT` antes de ler o `boot.ini`. Sem esse arquivo ele grava `dtb load fail` em
`BOOT/error.log` e para: tela do logo e nada mais. Com o arquivo, ele lê o nosso
`boot.ini`, que carrega o nosso kernel e o nosso DTB (o log mostra
`Machine model: R36S V5`). Por isso a raiz da `BOOT` leva os dois DTBs do RG351 do cartão
de fábrica (binário de fábrica, conferido por SHA256; tarefa 4.5). **Diagnóstico:** se o
R36S para no logo, procure `BOOT/error.log` pelo PC.

## 3. O cartão único

| Setores | Conteúdo | Origem |
|---|---|---|
| 0 | MBR (assinatura `4c554d32`, só a `BOOT`) | build |
| 1 a 15 | área de fábrica do GA36 | GA36 |
| 16 a 63 | boot0 do GA36 encolhido para 24 KiB (soma eGON recalculada) | GA36 |
| 64 a 405 | `idbloader` | R36S |
| 16384 a 32767 | `uboot.img` (x4) e `trust.img` (x2) | R36S |
| 38192 em diante | U-Boot 2017, tabela `softw411`, FAT "bootloader", env | GA36 |
| 172032 | imagem de boot Android do painel 1 do GA36 | build |
| 262144 | `BOOT` (FAT32, 2 GiB): `VERSION`, `boot.ini`, `rg351mp-kernel.dtb` e `rg351p-kernel.dtb` (de fábrica), `ga36/`, `r36s/` | build |
| depois | `ROMS` (exFAT): jogos, saves, configuração e logs dos dois | `flash` ou 1º boot |

O build monta a área a partir das duas cadeias e confere que nenhuma região do R36S cai
sobre dados do GA36 (`src/r36os/bootarea.py`). O initramfs de cada console monta o próprio
sistema: `BOOT/r36s/SYSTEM` no R36S, `BOOT/ga36/SYSTEM` no GA36.

## 4. Primeiro boot

- **Sinais de vida, em ordem:** o logo do fabricante (U-Boot de fábrica), depois as
  mensagens do kernel no painel, o **LED azul** aceso (o kernel chegou ao `init`) e o menu
  do RetroArch. *Tempo até o menu: a medir.*
- **Tela preta depois do logo:** o kernel não subiu ou o painel não acendeu. Se o LED
  azul acende, o kernel está rodando e o problema é o painel: os logs vão para a `ROMS`
  mesmo assim (`ROMS/logs/boot/`, pelo PC).
- **Serial (opcional):** `ttyS2` (UART2, pinos m1), **1500000 baud**, a velocidade do
  bootloader de fábrica do início ao fim. Um adaptador USB-serial de 3,3 V encurta muito
  o diagnóstico.

**Tarefa 4.4, primeira subida (risco do BL31 de fábrica com o kernel mainline):**
**medido em 2026-11-12:** o BL31 de fábrica funciona com o kernel mainline (PSCI v1.0, os
4 núcleos sobem: `smp: Brought up 1 node, 4 CPUs`); U-Boot, kernel, initramfs, `SYSTEM` e
RetroArch em ~19,4 s até o frontend (`frontend (s from kernel)` no `hw/boot-<n>.txt`); RTC
do RK817, bateria, Panfrost, "R36S Gamepad" e jack aparecem no log. A imagem no painel
apareceu a partir do boot 14 (seção 5). *Falta:* conferir se o desligamento corta a energia.

## 5. Painel: diagnóstico

O painel é de 3,5", 640x480, ligado por DSI de 4 lanes, com um controlador da família
ST7703 que responde `F1 12 87` ao `SETEXTC` e ID `FE 52 02`. A sequência de
inicialização e o modo de vídeo vêm do DTB de fábrica (`panel-init-sequence`), no driver
`panel-sitronix-st7703` (patch 0010). O DSI tem dois caminhos:

- **baixa velocidade (LP):** comandos e leituras do painel;
- **alta velocidade (HS):** o vídeo; depende da temporização do D-PHY
  (`phy-rockchip-inno-dsidphy`).

**O log conta o que o painel respondeu** (`ROMS/logs/boot/boot-<n>.log`,
`grep -nE "panel|dsi|dphy"`):

| Linha | O que diz |
|---|---|
| `panel state before-init 0a: 08` e `... power: booster off, sleep in, display off` | o reset funcionou: o painel está dormindo antes da sequência |
| `panel init sequence: 0 (sent in command mode)` | a sequência foi enviada sem erro, antes do vídeo, como o kernel de fábrica faz |
| `panel state after-init 0a: 9c` e `... power: booster on, sleep out, display on` | os comandos chegaram: o painel acordou e ligou o display |
| `panel state ... 04: fe 52 02` | ID do controlador |
| `panel state ... 0c: 70` / `0f: c0` | formato de 24 bits / autodiagnóstico OK |
| `panel state ... <reg>: error -110` | leitura sem resposta (timeout) |
| `dropped N stale read payload words` | uma leitura anterior deu timeout e a resposta chegou atrasada (descartada) |
| `SoC revision: PX30/RK3326` ou `PX30S/RK3326S` | revisão do chip; no PX30S o D-PHY usa a tabela de 2,5 GHz |
| `lane rate … Hz (prediv …, fbdiv …), timing row up to … Hz of the … table` | a taxa do link de vídeo e a temporização usada |
| `lane rate … Mbps (PHY … Hz)` (`dw-mipi-dsi-rockchip`) | a taxa que o host usa nos tempos de linha; precisa ser igual à do PLL (patch 0014) |
| `status sample <n>: int_st0 … int_st1 … phy_status …` | erros do host DSI com o vídeo rodando, 1 s entre amostras: `int_st1` bit 7 (`0x80`) = estouro da FIFO de pixels; `int_st0` = contenção no D-PHY ou erro de confirmação; `phy_status` bit 0 = PLL travado |

**Tela cinza com uma mancha clara e fixa no centro, que não muda com o menu:** o painel
está ligado e acordado, mas não recebe vídeo. Se as linhas acima mostram o painel
acordado (`9c`), o problema está no caminho de alta velocidade (D-PHY, taxa do link), não
nos comandos. **Resolvido no boot 14 (2026-11-12):** o RetroArch apareceu no painel depois
das mudanças dos patches 0018 (espera de 250 ms depois do *exit sleep*), 0019 (taxa de
180 Mbps por lane e tempos `hstt` 64 64 16 20 do D-PHY externo) e 0020 (lane de clock em
LP para comandos LP). Ainda não se sabe qual delas basta sozinha; isso, a conferência de
nitidez e cores e o histórico completo estão na tarefa 4.6 da change `r36s-single-card`.

## 6. Testar só um kernel novo

Para testar uma mudança de kernel ou de DTB sem regravar o cartão inteiro:

1. `uv run r36os build console` (com `podman ps` vazio antes).
2. Com o cartão no PC, copiar `out/r36s/kernel/Image` para `BOOT/r36s/Image` e, se o DTS
   mudou, `out/r36s/kernel/dtbs/rk3326-r36s-v5.dtb` para `BOOT/r36s/`.
3. O leitor USB `14cd:125d` corrompe gravações pequenas: depois de copiar, `sync -f`,
   desmontar (`udisksctl unmount -b /dev/sdX1`), montar só leitura
   (`udisksctl mount -b /dev/sdX1 -o ro`), conferir o SHA256 dos arquivos copiados e dos
   dois DTBs do RG351 contra o build, e ejetar com `uv run r36os eject /dev/sdX`.
4. Mudanças no `SYSTEM` (userland, como o `mixer`) exigem `r36os flash console` (gravação
   completa ou `--update`).

## 7. Controle

Os botões (`gpio-keys`) e os dois analógicos (`adc-joystick`, SARADC canal 1 atrás de um
multiplexador) são unidos pelo serviço `r36os-padmerge` num único **"R36S Gamepad"**, com
os mesmos códigos de botão do GA36, então a autoconfiguração do RetroArch tem os mesmos
índices (`/usr/share/libretro/autoconfig/udev/R36S Gamepad.cfg`). Os botões de volume são
um dispositivo à parte (`volume-keys`), como no GA36.

| Tecla no DTS | Função provisória | Confirmar |
|---|---|---|
| F1 | Select | *a medir* |
| F2 | Start | *a medir* |
| F3 | L3 | *a medir* |
| F4 | R3 | *a medir* |
| F5 | menu (como o Fn do GA36) | *a medir* |

**Analógicos (medido em 2026-11-12 e 2026-11-13):** o `adc-joystick` mainline tinha um bug
(`adc_joystick_invert()` usava o índice do canal onde o `input_abs_get_min/max` espera o
código `ABS_*`, então o eixo invertido saía com a faixa errada): corrigido pelo patch 0022.
Os dois sticks são montados girados 90° e a ordem dos canais saiu de um teste roteirizado
(oito movimentos segurados, lido no log com o patch 0021, que registra cada evento de
entrada como `evlog: …`). No DTS: canal 1 = `ABS_X` e canal 3 = `ABS_Y`, os dois
invertidos; canal 2 = `ABS_RX` e canal 0 = `ABS_RY`, sem inverter. O usuário confirmou em
2026-11-13 que o gamepad funciona corretamente. O repouso de cada eixo fica fora do centro
da faixa fixa e o DTS centra a faixa no repouso medido **deste** aparelho; outro R36S pode
precisar de calibração (tarefa 6.8).

## 8. Áudio

O alto-falante é o amplificador classe D interno do RK817 (sem amplificador externo no DTB
de fábrica); o `PC4` (`spk-ctl` de fábrica) liga o estágio de potência e no nosso DTS é um
`simple-audio-amplifier` depois do `SPKO`. O mesmo pino do codec serve ao alto-falante e ao
canal esquerdo do fone, escolhido pelo `Playback Mux` (`SPK` ou `HP`; o `mixer` deixa em
`SPK`). A detecção do fone é `gpio2 PC6`, **ativa em alto** como na fábrica (invertida, o
sistema achava que havia fone e ficava mudo).

- **Patch 0024:** o alto-falante só tocou depois de levar o caminho do codec aos valores do
  driver de fábrica (DAC L/R ligados, `ACLASSD_CFG1` 0xa5, `ACLASSD_CFG2` 0xc4, `DDAC_MUTE_MIXCTL`
  0x10). O dump dos registradores que levou a isso foi feito com um patch provisório, já
  removido; a conferência hoje é pelo regmap do debugfs e pelo `board/r36s/diag/codecdump.sh`
  (roda no ArkOS pelo menu Ports e salva os registradores durante um tom).
- **Patch 0025:** o som saía 4 a 6% devagar (o tom de 440 Hz lia 205 Hz no afinador na
  oitava de baixo) porque o divisor fracionário do I2S recebia 1200 MHz; o kernel de fábrica
  limita essa entrada a 600 MHz. Com o limite, o tom de 440 Hz mede 440 Hz.
- **Abertos:** o som é muito mais baixo que no ArkOS de fábrica e há zumbido em silêncio
  (P-45); a troca de saída com o fone não acontece (P-42).

## 9. Checklist de conferência

## 8. Checklist de conferência

| Item | Como conferir | Onde ver |
|---|---|---|
| Boot | LED azul e menu do RetroArch | aparelho; `boot/boot-<n>.log` com `== console: r36s` |
| Núcleos e desligamento | 4 núcleos; desligar pelo menu corta a energia | `hw/boot-<n>.txt`; aparelho |
| Painel e brilho | imagem desde as mensagens do kernel, 640x480 | tela |
| GPU | renderer `Panfrost` (não `llvmpipe`) | `frontend/boot-<n>.log` |
| Controle | todos os botões, F1-F5 e os dois analógicos no menu e num jogo | tela |
| Áudio | som no alto-falante (volume e zumbido: P-45); com fone, a troca é o P-42 | ouvido; `events.log` sem `audio FAIL` |
| Taxa do painel | ~59,02 Hz (`video_refresh_rate` do `retroarch-r36s.cfg`) | métricas (`fps`) |
| Bateria | porcentagem e corrente | `metrics/boot-<n>.csv` (`bat_*`) |
| Temperatura | dentro das zonas do `rk3326.dtsi` | `metrics/boot-<n>.csv` |
| Cartão único | o mesmo cartão no GA36 e de volta no R36S; um save passa entre os dois | tarefas 9.1 a 9.4 |

## 10. Medido no aparelho

| Data | Item | Resultado |
|---|---|---|
| 2026-11-12 | Tarefa 1.1 (`boot.ini`) | lido, desde que a raiz da `BOOT` tenha o DTB do RG351 que o U-Boot escolhe (seção 2) |
| 2026-11-12 | Tarefa 4.4 (primeira subida) | inicia até o RetroArch em ~19,4 s; 4 núcleos pelo BL31 de fábrica; RTC, bateria, Panfrost, gamepad e jack no log |
| 2026-11-12 | Mixer do RK817 | controles reais: `Master`, `Mic Capture Gain`, `Playback Mux`, `Internal Speakers` (sem `Headphones`) |
| 2026-11-12 | Painel | acende, acorda e liga o display pelos comandos, mas fica cinza sem vídeo (seção 5) |
| 2026-11-12 | Painel (boot 14) | o RetroArch aparece no painel depois dos patches 0018 a 0020; nitidez e cores ainda a conferir (tarefa 4.6) |
| 2026-11-12 | Analógicos (boots 15 a 20) | bug do `adc-joystick` corrigido (0022); canais e inversões do DTS ajustados por teste roteirizado (seção 7) |
| 2026-11-12 | Áudio (boots 16 a 24) | alto-falante toca com o patch 0024 e na velocidade certa com o 0025; mudo sem eles (seção 8) |
| 2026-11-13 | Gamepad | funciona corretamente (usuário); botões e os quatro eixos no menu e em jogo |
| 2026-11-13 | Volume e zumbido | volume muito abaixo da fábrica e zumbido em silêncio continuam: P-45 |

*A preencher com as tarefas 9.1 a 9.4 da change (boot integrado). As medições (cores, taxa do
painel, F1-F5) ficam para a próxima change: P-46.*
