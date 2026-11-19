# R36S "V5": gravar, subir e conferir

Guia da primeira subida e da conferência do R36S V5 (Rockchip RK3326, aarch64) com a
imagem `console`, o cartão único do GA36 e do R36S (change `r36s-single-card`).

> **Estado (2026-11-13):** a imagem inicia no aparelho: tela, controle e som funcionam.
> Abertos: volume baixo e zumbido do alto-falante (P-45), fone (P-42) e a verificação nos
> dois consoles (tarefas 9.1 a 9.5 da change). As seções marcadas com *a medir* esperam
> essas verificações.

## 1. Gerar e gravar

```sh
uv run lume build console                          # 1ª vez: LUME_GA36_FACTORY e LUME_R36S_FACTORY (README)
uv run lume flash console /dev/sdX --full --eject  # cartão novo: imagem + ROMS no resto do cartão
uv run lume flash console /dev/sdX --update --eject   # cartão já gravado com a console: a ROMS fica
# cartão do GA36 gravado antes (BOOT de 1 GiB): o --update recusa; copiar a ROMS e usar --full
```

O mesmo cartão serve aos dois consoles: basta trocar de aparelho.

## 2. A cadeia de boot de fábrica

O R36S sobe pela cadeia do próprio aparelho, a mesma do cartão que veio com ele (um ArkOS
para o "R36S V5"). Ela é binário fechado, fica fora do git e o build a lê da cópia do
cartão original (`LUME_R36S_FACTORY`), conferida por SHA256 (`src/lume_tool/r36s_vendor.py`).

| Etapa | Onde está no cartão | O que faz |
|---|---|---|
| BROM do RK3326 | (no SoC) | lê o `idbloader` **só no setor 64** (provado: no 1088 não inicia) |
| `idbloader` | setores 64 a 405 | inicializa a DDR e carrega o U-Boot |
| `uboot.img` (`LOADER`) | setor 16384, cópias a cada 2048 até 22528 | U-Boot da linha Hardkernel (`odroidgoa-uboot-config`) |
| `trust.img` (`BL3X`) | setores 24576 e 28672 | BL31 (ARM Trusted Firmware): PSCI para ligar os núcleos e desligar |
| `boot.ini` | raiz da `BOOT` | script lido pelo U-Boot: carrega o kernel e o DTB e chama `booti` |

O `boot.ini` de fábrica carrega `Image`, `uInitrd` e `rk3326-r35s-linux.dtb` de
`mmc 1:1`. O nosso (`board/r36s/boot.ini`) carrega `r36s/Image` (kernel com o initramfs
embutido) e o DTB padrão `dtbs/rk3326/rk3326-r36s-v5.dtb`, sem `uInitrd`; a linha de comando fica no kernel
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
| 262144 | `BOOT` (FAT32, 2 GiB): ver a tabela abaixo | build |
| depois | `ROMS` (exFAT): jogos, saves, configuração e logs dos dois | `flash` ou 1º boot |

O build monta a área a partir das duas cadeias e confere que nenhuma região do R36S cai
sobre dados do GA36 (`src/lume_tool/bootarea.py`). O initramfs de cada console monta o próprio
sistema: `BOOT/r36s/SYSTEM` no R36S, `BOOT/ga36/SYSTEM` no GA36.

**A partição `BOOT`** (a mesma nos dois consoles; `docs/BRINGUP-GA36.md` tem a mesma tabela):

| Caminho | O que é |
|---|---|
| `VERSION` | build gravado no cartão |
| `boot.ini` | lido pelo U-Boot do R36S: carrega `r36s/Image` e `dtbs/rk3326/rk3326-r36s-v5.dtb` |
| `rg351mp-kernel.dtb`, `rg351p-kernel.dtb` | de fábrica: o U-Boot do R36S os exige para iniciar (seção 2) |
| `logo.bmp` | logo do boot (o de fábrica do R36S), BMP 640x480 de 24 bits |
| `dtbs/a33/` | DTBs do GA36: `sun8i-a33-ga36-mb-v1.2-panel1.dtb` (`ga36-panel1`, o padrão) e `sun8i-a33-ga36-mb-v1.2-panel2.dtb` (`ga36-panel2`) |
| `dtbs/rk3326/` | DTB do R36S: `rk3326-r36s-v5.dtb` (`r36s-v5`, o padrão) |
| `dtbs/rk3326/vendor/` | DTBs de clones do R36S convertidos no PC (`<lume,id>.dtb`, cerca de 170), lidos só quando nomeados (seção 3.1) |
| `dtbs/force` | opcional, criado pelo usuário: o nome do DTB a usar (seção 3.1) |
| `ga36/` | `SYSTEM`, `zImage` (o kernel com que a imagem de boot do setor 172032 é regravada na troca de DTB) e `modules` (os módulos do kernel, montados em `/lib/modules`) |
| `r36s/` | `SYSTEM`, `Image` e `modules` |

A `BOOT` tem só o que os consoles leem; as imagens de boot dos painéis do GA36 ficam na pasta
do build no PC (`docs/BRINGUP-GA36.md`, seção 3).

**Trocar o logo:** pelo PC, substituir `BOOT/logo.bmp` por outro BMP de 640x480 e 24 bits.
No R36S vale no boot seguinte. O GA36 continua com o logo da área de fábrica dele, que é o
mesmo arquivo do `logo.bmp` de fábrica do R36S: o U-Boot do GA36 não desenha um BMP da `BOOT`
(prova 1.4 de `boot-dtb-select`; trocar nos dois fica para o bootloader próprio, P-43).

### 3.1 Escolher o device tree (DTB)

O U-Boot sempre inicia o kernel com o DTB padrão. No initramfs, o `lume-bootsel` olha
`BOOT/dtbs/rk3326/` e decide, nesta ordem: o arquivo `BOOT/dtbs/force`; a lista na tela
(tecla segurada ao ligar); a volta ao último DTB que funcionou; a escolha salva da lista; o
aprendido para o ID do painel; as regras de cada DTB (ID do painel, leituras de ADC, GPIO e
I2C); o padrão. Se o escolhido não é o que está rodando, o kernel reinicia uma vez com ele
(kexec, alguns segundos a mais). O `r36s-v5` tem a regra `lume,panel-id = [fe 52 02]`, o ID
que o ST7703 deste aparelho responde, então o R36S V5 segue com ele sem troca (`reason:
rule`, ou `learned` quando o aprendido já existe). Com a tela muda (o painel não responde
ao driver), a busca sozinha testa os outros DTBs da pasta, um por boot.

- **Pelo PC:** escrever o nome (por exemplo `r36s-v5`) em `BOOT/dtbs/force`. Apagar o
  arquivo volta ao automático. Um nome que não existe é ignorado (motivo no log).
- **Pela tecla:** segurar **Vol-** ao ligar abre a lista; direcional ou volume navegam e
  **A** confirma. A escolha fica salva em `ROMS/system/etc/dtb-rk3326-<serial>.conf` (um
  por aparelho; `dtb-rk3326.conf` sem número de série) e "Automatic" apaga a escolha. O
  U-Boot de fábrica não faz nada com Vol-, Vol+, Start, Select ou A segurados ao ligar
  (prova 1.2 de `boot-dtb-select`, boots 116 a 119): o Vol- é livre para a lista.
- **DTB novo:** copiar o `.dtb` (com o nó `lume-select`) para `BOOT/dtbs/rk3326/` basta
  para ele entrar na lista.
- **Log:** `boot/boot-<n>.log` tem `lume-bootsel: selected <id> (reason: …)`, e o
  `hw/boot-<n>.txt` tem `dt in use` (formato em `docs/LOGS.md`).
- **DTBs convertidos** (`BOOT/dtbs/rk3326/vendor/`, change `boot-dtb-select` D17): só são
  lidos quando o `force`, a lista, o aprendido ou o estado os nomeiam; a busca sozinha não
  os testa. Na lista eles aparecem com
  "(converted)"; esquerda/L1 e direita/R1 pulam uma página.

**DTB de fábrica convertido, provado (2026-11-16, build `20261115-232617`, boots 92 a 95):**
`factory-r35s` (o `rk3326-r35s-linux.dtb` do cartão de fábrica, por `lume dtb-import`) em
`BOOT/dtbs/force`. Boot 92: tela preta. O painel respondeu o ID (`fe5202`) ao driver
`panel-generic-dsi`, mas o DTB convertido não levava a taxa da DSI, e a estimativa do
mainline não dá imagem neste painel. Depois que o conversor passou a gravar a taxa do kernel
do fabricante (180 Mbps, a mesma do nativo) e os tempos da PHY do nativo, o boot 94 mostrou
imagem. A pergunta foi confirmada com A, e tela, botões, analógicos, som e brilho
funcionaram como no nativo. O launcher abriu em 30,8 s, contra cerca de 24 s no nativo; a
diferença é o kexec. O boot 93, sem ninguém na frente, mostrou a volta sozinha
(`not confirmed within 15 s`, `reverted`). Ao tirar o `force` e o aprendido, o boot 95
voltou ao `r36s-v5` (`auto`).

**Regra do ID do painel, provada (2026-11-16, build `20261116-101936`, `lume-bootsel` r13,
boots 98 e 99):** com o aprendido do boot anterior, o boot 98 saiu `learned` (o aprendido vem
antes das regras), mas já com `rules of r36s-v5: match`. Com o `dtb-rk3326-learned.conf`
apagado e o estado vazio, o boot 99 registrou `selected r36s-v5 (reason: rule)` e `keeping
the running device tree, no kexec`; a regra não grava nada no aprendido.

**Alimentação de outra placa, `darkosre-r36s-r35s-v11-2022-08-18` (D18, 2026-11-16, mesmo
build, boots 100 a 104):** com o `force`, o kexec subiu o V11 com imagem e a pergunta na tela,
mas o **A** deste aparelho não responde: o V11 lê os botões em `gpio1`/`gpio2` (A em
`gpio1 PA2`) e o R36S V5 os tem em `gpio3`. Os boots 100 e 101 voltaram sozinhos ao
`r36s-v5` em 15 s (`reverted`). Com `good=` do V11 gravado à mão no estado, o boot 103 ficou
no V11 (frontend em 23,4 s desde o kernel) e o `regulator_summary` bateu com a origem em todos
os reguladores do RK817: `vcc_lcd` (LDO8) a 2,8 V contra 1,8 V no nativo, `vccio_sd` (LDO5)
a 1,8 V contra 3,3 V, `vcc_sd` (LDO6) a 3,0 V (faixa 1,8–3,0 V), `vcc3v3_pmu` a 3,3 V contra
3,0 V, `vdd_logic` até 1,15 V, LDO7 `vcc_backlight` ligado e `boost` a 5,0 V. Tela no menu e
cartão montado com o I/O a 1,8 V. Sem som: o V11 não declara GPIO de amplificador, então o
`gpio3 PC4` deste aparelho fica desligado (o `Playback Mux` estava em `SPK`); a detecção do
fone também vem invertida (`ACTIVE_LOW`). São diferenças da placa, não da alimentação. O
`force` e o `good=` saíram e o boot 104 voltou ao `r36s-v5` (`rule`).

**Lista pela tecla (2026-11-16, boots 105 a 107):** a lista só abre ligando com o Vol-
segurado **até ela aparecer**: o driver das teclas sobe em ~2,7 s e o `lume-bootsel` lê a
tecla em ~3,5 s. Pelo `reboot` do SSH, sem a tecla, ela não abre (boot 105); no boot 107 o
Vol- foi solto 90 ms antes da leitura, enquanto a tela enchia de linhas `evlog` da repetição da
tecla (patch 0021, corrigido no build `20261116-122213`: só o aperto e a soltura). Boot 106:
`list shown (1 candidate(s), 169 converted)`, `list: r36s-v5 chosen and saved`, `reason:
manual`; boot 107 seguiu com `reason: manual` sem lista. A lista abre com o cursor na escolha
salva, ou em *Automatic* (a última linha); para cima a partir de *Automatic* é o último
convertido (`factory-r35s`), e Vol- também desce.

**Regra com prioridade (2026-11-16, build `20261116-122213`, boots 109 e 110):** uma cópia do
`r36s-v5` com `lume,id` `r36s-v5-rule`, prioridade 10 e a mesma regra, posta na `BOOT` com o
`good=` dela no estado: as duas regras batem e o boot 109 escolheu `r36s-v5-rule (reason:
rule)` por kexec, sem pergunta. Sem a cópia, o boot 110 voltou ao `r36s-v5` (`rule`).

**Número de série:** não há `/sys/devices/soc0` no RK3326, então o estado é por SoC
(`dtb-rk3326.conf`). O U-Boot de fábrica grava `/serial-number` no DTB (`c3d9b8674f4b94f6`
neste aparelho, igual nos boots 108 e 110). Desde o `lume-bootsel` r14 (build
`20261116-135455`) ele nomeia o estado (`dtb-rk3326-c3d9b8674f4b94f6.conf`) e passa ao DTB
do kexec, então os dois inícios acham o mesmo arquivo (`device: bootloader serial number
...`, boots 112 a 114).

**Lista, aprendizado e *Automatic* (mesmo build, boots 113 e 114):** o `init` desliga o eco do
`tty1`, e o Vol- segurado não enche mais a tela. Boot 113: lista → `factory-r35s`, kexec,
pergunta confirmada com A, `learned: factory-r35s for panel:fe5202`. Boot 114: lista →
*Automatic*, `saved choice cleared` e `selected factory-r35s (reason: learned)`, por kexec e
sem pergunta. O aprendido e o estado foram apagados depois, e o aparelho voltou ao `r36s-v5`
(`rule`).

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

1. `uv run lume build console` (com `podman ps` vazio antes).
2. Com o cartão no PC, copiar `out/r36s/kernel/Image` para `BOOT/r36s/Image` e
   `out/r36s/kernel/modules` para `BOOT/r36s/modules` (os dois juntos: com módulos de outra
   versão o console sobe sem módulos e o log de boot tem uma linha `ERROR`) e, se o DTS
   mudou, `out/r36s/kernel/dtbs/rk3326-r36s-v5.dtb` para `BOOT/dtbs/rk3326/`. Pelo cabo,
   `uv run lume push` faz isso sozinho.
3. O leitor USB `14cd:125d` corrompe gravações pequenas: depois de copiar, `sync -f`,
   desmontar (`udisksctl unmount -b /dev/sdX1`), montar só leitura
   (`udisksctl mount -b /dev/sdX1 -o ro`), conferir o SHA256 dos arquivos copiados e dos
   dois DTBs do RG351 contra o build, e ejetar com `uv run lume eject /dev/sdX`.
4. Mudanças no `SYSTEM` (userland, como o `mixer`) exigem `lume flash console` (gravação
   completa ou `--update`).

## 7. Controle

Os botões (`gpio-keys`) e os dois analógicos (`adc-joystick`, SARADC canal 1 atrás de um
multiplexador) são unidos pelo daemon de entrada `lume-input` (perfil
`/usr/share/lume/input/r36s.conf`, change `lume-launcher`, D8) num único **"R36S Gamepad"**,
com os mesmos códigos de botão do GA36, então a autoconfiguração do RetroArch tem os mesmos
índices (`/usr/share/libretro/autoconfig/udev/R36S Gamepad.cfg`). Os botões de volume são
um dispositivo à parte (`volume-keys`), também capturado pelo daemon.

O daemon captura as origens com exclusividade (`EVIOCGRAB`) e cuida de três coisas além da
junção:

- **Fn (F5, `BTN_MODE`) sozinho**: sai como apertar e soltar o Fn, quando ele é solto (o menu
  do RetroArch abre nessa hora).
- **Fn+Start**: manda `quit` ao launcher pelo socket `/run/lume/input.sock`, e nenhuma das
  duas teclas sai; o jogo aberto pelo launcher é encerrado. Fora de um jogo, nada acontece.
- **Volume**: os botões mudam o controle `Master` do `rk817int` em passos de 5%, em qualquer
  programa, e não chegam aos programas.

`lume-input --list` mostra os dispositivos de entrada com o barramento (o virtual é
`bus=0x6`).

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

## Pelo cabo USB

Ligue o PC na porta **OTG** do R36S, não na de carga (DC), e sem adaptador. O console
aparece no PC como **"Lume R36S"** (fabricante "Lume Retro OS"), com duas funções:

- **MTP:** a `ROMS` como armazenamento "ROMS" no gerenciador de arquivos;
- **rede USB:** o PC recebe `10.55.0.2` e o console fica em `10.55.0.1`:
  `ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null root@10.55.0.1` (root sem
  senha, só por esse cabo) e `uv run lume push` (atualização sem tirar o cartão; ver o
  `README.md`).

**Testes pelo cabo (`lume dev`):** o cartão vai de um console ao outro e só um deles fica no
PC; os dois respondem em `10.55.0.1`. Use `.venv/bin/lume dev wait`, `dev sh <comando>`,
`dev shot <arquivo.png>`, `dev keys '<sequência>'`, `dev log` e
`dev check --console r36s` (recusa o GA36 com "the console on the cable is the GA36, not the
R36S"), além de `dev shot --compare <tela>` para as capturas de referência (ver
[BUILD.md](BUILD.md)). O `lume push` espera o console voltar e confere o boot novo
(`ok: boot N completed with build X (...)`); `--no-wait` só reinicia. Para mudar só um
fragmento `lume-*`/`lume-*` sem reboot (só na RAM): `lume push --hot <fragmento>` ou
`lume dev watch <fragmento>` (ver "Testar no console pelo cabo" em [BUILD.md](BUILD.md)).

**Espaço da `BOOT` no `push` (change `push-boot-swap`):** o `push` renomeia o
`r36s/SYSTEM` e o `r36s/modules` em uso para `.old` (apagados no `push` seguinte), para não
perder clusters na FAT. Os `push` anteriores a essa change perdiam ~290 MB a cada troca do
`SYSTEM`; se o cartão do R36S tiver esse resto, o `push` avisa com
`warning: BOOT has <N> MiB in lost clusters` e segue. Para recuperar, com o cartão no leitor
do PC: `sudo fsck.vfat -a /dev/sdX1` e apagar os `FSCK*.REC` da raiz da `BOOT`, ou
`lume flash --update`. Se a energia cair entre os dois `mv` da troca, o boot usa o `.old`
com uma linha `ERROR ... using r36s/SYSTEM.old from the previous build` no log.
*Primeiro `push` no R36S com a change: pendente (tarefa 6.1 da change `r36s-usb-proof`).*

**Como funciona no R36S:** o `u2phy` vê o pino ID, mas não o VBUS da porta OTG (medição de
2026-11-13, change `usb-device-access`). O controlador (dwc2) usa um *role switch* que começa
como device e força a sessão por override. O serviço `lume-usb` lê o `USB-HOST` do `extcon`
e troca para host quando um adaptador OTG puxa o ID para baixo, para o pendrive no adaptador
continuar funcionando. Ele enumerou na medição, antes do role switch; com o role switch
ainda não foi provado.

**Diagnóstico:**
- a linha `usb:` do `ROMS/logs/trace/boot-<n>.log` mostra o PHY (`extcon`), o papel do role
  switch (`role=`) e o estado do gadget (`udc=…:configured` com o PC ligado);
- no `events.log`, `usb OK device: connected|disconnected`, `network: up|down` e
  `ssh: login accepted`;
- no `boot/boot-<n>.log`, as mensagens `lume-usb:` (inclusive `port role host|device`) e
  `umtprd:` (a saída do servidor MTP).

**Medido:** o modo device ainda não foi provado no R36S (a prova com o PC foi feita no GA36).

## 9. Checklist de conferência

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
| 2026-11-19 | Read-ahead (`device-fixes` 2.2) | PS1 133 MB: 6,48 / 6,18 / 5,99 / 5,90 s com 128 / 256 / 512 / 1024 KiB; Neo Geo 38 MB: 1,90 / 1,81 / 1,76 / 1,76 s (D6) |
| 2026-11-19 | GPU e bateria (`lume-hud-actions` 4.1) | `panfrost`: `drm-engine-fragment`/`vertex-tiler` só com `profiling=1`, arquivo `root 0644` (regra do udev nova, 4.4); RK817 sem `current_now`/`voltage_now`, só `current_avg` (positivo carregando, negativo descarregando) e `voltage_avg`; `charge_now`, `charge_full`, `status` presentes; sem Yama |
| 2026-11-19 | Suspensão, parte automática (`device-fixes` 2.3) | `mem_sleep` = `s2idle [deep]`; 10 de 10 em `freeze` e 10 de 10 em `mem` acordados pelo RTC, sem despertar antes da hora; botão e carregador pendentes |
| 2026-11-19 | V2 (`virtual-gamepad` 4.3) | `dev keys` ok (o primeiro botão com a tela escurecida só devolve a luz); gravação de 62 s tocada com atraso máx. 0,75 ms e tela final idêntica; `play` como `game` recusado (rc 3); `open-close-*` de NES, SNES, Mega Drive, GB, GBC, GBA e PS1 ok; `launcher-screens` com as referências novas (dica Fn, itens Cartão e Games) ok na tela inicial; replay de GBA igual em duas sessões do jogo (0 px aos 6 s e no fim) |
| 2026-11-19 | Achados da V2 | o `open_game` errava o Dock depois de movimentos à mão (o launcher só gravava o estado ao abrir um jogo): corrigido no `lume-ui`, falta o build; o RetroArch numera as gravações de replay sozinho (`.replay1`, `.replay2`) e uma segunda reprodução na mesma sessão do jogo não volta ao começo |

*A preencher com as tarefas 9.1 a 9.4 da change (boot integrado). As medições (cores, taxa do
painel, F1-F5) ficam para a próxima change: P-46.*
