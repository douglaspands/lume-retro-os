# Design

## Context

Motivação em `proposal.md`. Requisitos:

- `specs/card-maintenance`, `specs/system-sleep`, `specs/audio-output` e
  `specs/display-brightness` (capabilities novas);
- deltas de `boot-runtime`, `device-support` e `game-launcher`;
- e, na tarefa 1.4, os deltas só de nome das specs que citam `r36os`.

Os caminhos abaixo já usam os nomes novos do D7; a tabela do D7 traz os antigos.

Estado atual (2026-11-18):

- **Boot**: `setup_storage` (`initramfs/lib/storage.sh:136`) decide o que fazer com a partição
  2 pelo setor de boot (`fs_type_at`) e, sendo exFAT, roda `check_roms` (`fsck.exfat -p`) em
  todo boot. Depois o `init` monta a `ROMS` (`initramfs/init:87`, `noatime`) e a move para
  `/newroot/storage`. Medido no GA36 (boot 55): 0,87 s de verificação com o cartão quase vazio.
- **Desligamento**: o `session` faz `sync` (linhas 44 e 142) e chama `poweroff`. Não há
  desmontagem explícita da `ROMS`, e não se sabe se o kernel limpa o bit *VolumeDirty* nesse
  caminho.
- **Botão de energia**: nada o trata hoje (só o `lume-bootsel` conhece o `KEY_POWER`). As
  fontes são o `axp20x-pek` no GA36 e o `rk805-pwrkey` no R36S. Segurar por vários segundos
  desliga à força pelo PMIC.
- **Volume**: o `r36os-input` muda um controle do mixer por tecla, e nos dois consoles esse
  controle é digital: `mixer GA36MB DAC 3 160` (`ga36.conf:46`) e `mixer rk817int Master 5`
  (`r36s.conf:45`). O `Headphone` analógico do GA36 fica fixo pelo `mixer` (43 de 63). O patch
  0005 do RetroArch limita o volume do menu a 0 dB.
- **Fone**: o `jack` do R36S já lê o estado com `iface=CARD` (falha (a) do P-42 corrigida). O
  serviço ainda cai em laço depois de "watching", e o GA36 nunca foi testado.
- **Brilho**: o teto fixo `backlight_max 7` está em `aports/r36os-input/ga36.conf:52`. A
  linha da borda esquerda (Fn+Volume) é desenhada pelo `r36os-input` com as cores do tema.
- **Kernel**: `SUSPEND`, `PM_SLEEP` e `ARM_PSCI_FW` ligados nos dois. O `RTC_DRV_SUN6I` e o
  `RTC_DRV_RK808` estão no kernel, com `RTC_HCTOSYS`. O console sobe em 1970, e o RTC não
  tem bateria própria.
- **Configurações** (`lume/lume-ui/src/app.rs`, `SetRow`): Idioma, Tema, Tela, Volume,
  Brilho, Sistema, Games, RetroArch, Desligar, mais Wi-Fi e Bluetooth quando há adaptador. O
  `lume-ui` roda como `game`; tarefas de root seguem o molde do `ssh-wifi`.
- **Navegação**: as confirmações aceitam esquerda e direita para trocar o foco
  (`lume-ui/src/app.rs:1138`, `lume-run/src/menu.rs:159`).
- **Nós de entrada**: `crw-rw---- root input`, e o usuário `game` está no grupo `input`.
- **Imagem**: o sistema é um squashfs em slots, trocado inteiro pelo `push`. O que fica de
  um build para o outro está no cartão (`ROMS/system`, os logs e a configuração).
- **Outras changes no mesmo branch** (`feature/virtual-gamepad`): `game-governor`,
  `lume-hud-actions` e `virtual-gamepad` têm tarefas abertas que citam nomes `r36os`, e o
  ciclo do R36S delas está pausado à espera desta change.

## Goals / Non-Goals

**Goals:**
- Os nomes do projeto passam a ser `lume` antes de qualquer outra correção.
- Boot limpo sem leitura além de um setor da `ROMS`.
- O som segue o volume no ganho analógico, e o amplificador fica desligado sem som.
- Suspender e acordar pelo botão de energia, sem perder o jogo nem corromper o cartão.
- Entender a falha do brilho no GA36 e trocar a trava fixa pelo limite aprendido.
- Nenhum serviço novo no caminho do boot (P-58).

**Non-Goals:**
- Verificação periódica automática do cartão.
- Bateria fraca (`game-governor`) e aprendizado da bateria (P-98).
- `discard` contínuo na montagem do exFAT.
- Hora certa garantida, relógio na tela e acerto manual da hora.
- Shaders (P-89, `lume-shaders` 2.2).
- Trocar `r36os` em cabeçalhos de DTS de clones, patches do kernel e changes arquivadas.

## Decisions

### D1. O bit do exFAT decide a verificação

O setor de boot do exFAT tem `VolumeFlags` no deslocamento 106 (2 bytes, little-endian): o
bit 1 é o `VolumeDirty` e o bit 2 é o `MediaFailure`. O `storage.sh` ganha `volume_flags`
(mesmo molde do `fs_type_at`, `dd` de 2 bytes), e o caso `check` vira:

```
 decide_p2 = check
      |
      +-- pedido de verificação na ROMS? (D3) --sim--> fsck.exfat -p, apaga o pedido
      |
      +-- VolumeDirty ou MediaFailure? -------sim--> fsck.exfat -p
      |
      +-- senão: "roms OK clean: check skipped", nenhuma verificação
```

Eventos novos na categoria `roms`: `clean: check skipped`, `dirty: checked ...` e
`requested: checked ...`.

*Alternativa descartada:* verificar a cada N boots. Sem relógio, N boots podem ser um dia ou
um mês.

### D2. Desligamento que deixa o volume limpo (condicionado à prova)

O kernel (`fs/exfat/super.c`, 6.18.62) liga o *VolumeDirty* ao montar e só o limpa no
`exfat_put_super` (desmontar) e no `exfat_reconfigure` (qualquer remontagem, depois de um
`sync_filesystem`); o `sync` sozinho não limpa. O `mount-ro` do runlevel `shutdown` remonta
a `/storage` só leitura, então o desligamento pelo menu deve deixar o bit limpo, a menos que
a remontagem falhe (arquivo aberto para escrita depois do `killprocs`). Medido no GA36 com a
`/storage` montada: `VolumeFlags` = `0x0002` (sujo, como esperado).

**Decisão (usuário, 2026-11-18):** o build atual não tem como ler o bit antes do `fsck` do
boot seguinte (o initramfs fica dentro do kernel e não registra o bit), e ler o cartão no PC
arrisca a corrupção do leitor USB. Por isso a 5.2 entra sempre, junto da 5.1: o fim da
sessão remonta a `/storage` como somente leitura depois do `sync` e antes do `poweroff` (se
falhar, desmonta, e registra a falha sem impedir o desligamento). A tabela da 2.1 sai dos
eventos da 5.1 na J2 e na J3. A suspensão (D11) usa o mesmo `sync`, mas não remonta, porque
o console volta ao mesmo ponto.

**Como ficou (5.1 e 5.2, 2026-11-18):**
- **Ordem no `session` (`release_storage`):** evento, `persist flush`, `sync`, **parar o
  `lume-logd`**, `sync`, remontar só leitura (ou desmontar), `poweroff`. Parar o `lume-logd`
  antes é necessário: ele grava os eventos finais e a marca `.clean` ao parar; com a `ROMS` já
  só leitura, todo desligamento pelo menu viraria `previous abrupt`. O reinício (9.12) chama a
  mesma função, e **a hora do desligamento (9.1) tem de ser gravada antes dela**.
- **kexec no R36S e reinício do GA36 (rc 11):** o segundo kernel sempre vê o volume limpo e o
  `dmesg` do primeiro se perde. O initramfs grava as linhas do primeiro em
  `ROMS/system/card/.restart-log` antes do kexec ou do reinício, e o início seguinte as registra
  com o sufixo `(before kexec)` ou `(before reboot)`. No R36S, a linha que vale para a 2.1 é a
  com sufixo.
- **Botão segurado:** o `lume-sleep` manda `SIGUSR1` ao `session`, que termina o frontend,
  espera ele acabar e chama a mesma `power_off` (com o `release_storage`); só sem sessão viva,
  ou depois de 30 s sem desligar, o `lume-sleep` chama `poweroff` e depende do `mount-ro` do
  OpenRC (8.3). A J2 confere o bit nesse caminho também.

### D3. Pedido de verificação dentro da ROMS

O pedido é o arquivo `ROMS/system/card/check-next-boot`. Se ele existir depois de o
initramfs montar a `ROMS`, o initramfs desmonta a partição, roda o `fsck`, apaga o pedido e
monta de novo. O custo extra só existe quando há pedido.

*Alternativa descartada:* o pedido na `BOOT`, que exigiria remontá-la gravável.

### D4. Serviço `lume-card` sem laço

Serviço OpenRC no pacote `lume-saves`. Ele espera pedidos com o `inotifyd` em `/run/lume/card/`
(pasta do grupo `game`). Cada pedido é um arquivo com o nome do verbo:

| Pedido | O que faz | Resultado |
|---|---|---|
| `trim` | `fstrim -v /storage`; um segundo pedido com um em andamento é apagado sem rodar | `/run/lume/card/status` com `running`, depois `ok <bytes>` ou `fail <motivo>`; `ROMS/system/card/last-trim` com o número do boot |
| `check-next-boot` | cria `ROMS/system/card/check-next-boot` | `status` `ok`; o boot que consome o pedido grava `ROMS/system/card/last-check` |

Um pedido com outro nome é apagado e registrado como recusado. O serviço sobe depois do
`frontend`.

### D5. Item "Cartão" no launcher

Linha nova `SetRow::Card` entre Sistema e Games. O painel mostra o espaço livre (`statvfs`),
o `last-trim` e o `last-check`, e A executa as duas ações. O painel lê o `status` a cada
segundo só enquanto está aberto e o TRIM está em andamento. Textos em en, pt e es. Primeiro
no protótipo; depois o `lume-ui` segue a régua (`card_matches_the_prototype_ruler`).

### D6. Read-ahead pela medição

Regra do udev no `lume-power`: `ACTION=="add|change", KERNEL=="mmcblk[0-9]",
ATTR{queue/read_ahead_kb}="<valor>"`. O valor sai da medição 2.2: o tempo de abrir uma ROM
grande com 128, 256, 512 e 1024 KiB, com o cache limpo entre as medidas, nos dois consoles.
Ganha o menor valor depois do qual o tempo para de cair. Sem ganho claro, não há regra.

**Medido (2.2, J1, 2026-11-18).** Leitura inteira do arquivo a frio (`drop_caches`), média
de três:

| Console | Arquivo | 128 KiB | 256 | 512 | 1024 |
|---|---|---|---|---|---|
| GA36 | PS1, 133 MB | 6,36 s | 6,19 s | 6,14 s | 6,07 s |
| GA36 | Neo Geo, 38 MB | 1,89 s | 1,83 s | 1,81 s | 1,79 s |
| R36S | PS1, 133 MB | 6,48 s | 6,18 s | 5,99 s | 5,90 s |
| R36S | Neo Geo, 38 MB | 1,90 s | 1,81 s | 1,76 s | 1,76 s |

O cartão lê ~21 MB/s no GA36 e o read-ahead maior ganha no máximo ~5% (0,3 s numa ROM grande):
nenhum ganho claro no GA36. No R36S (J1, 2026-11-19, mesmo cartão, `/proc/uptime` com
resolução de 10 ms) o ganho é um pouco maior: 512 KiB tira ~7,5% nos dois arquivos (0,5 s no de
PS1) e o Neo Geo para de cair ali; 1024 só tira mais 1,5% no PS1.

### D7. Nomes `lume` (nós TREE)

Tudo o que o projeto criou passa a se chamar `lume`. A tabela completa, arquivo por
arquivo, sai da tarefa 1.1 (`docs/NOMES.md`). As regras são estas:

| Antes | Depois |
|---|---|
| APKs `r36os-input`, `r36os-powerctl`, `r36os-devmem`, `r36os-initramfs-static` | `lume-input`, `lume-powerctl`, `lume-devmem`, `lume-initramfs-static` |
| Serviços `/etc/init.d/r36os-*` | `/etc/init.d/lume-*` |
| Ferramentas `/usr/bin/r36os-*` (`r36os-power`, `r36os-playlists`, `r36os-evrec`, `r36os-shot`, ...) | `/usr/bin/lume-*` |
| `/usr/libexec/r36os`, `/etc/r36os`, `/run/r36os` | `/usr/libexec/lume`, `/etc/lume`, `/run/lume` |
| `/usr/share/r36os` | `/usr/share/lume` (já existe: a 1.1 confere colisões arquivo por arquivo) |
| Variáveis `R36OS_*` | `LUME_*` |
| Regras do udev `61-r36os-input.rules` | `61-lume-input.rules` |
| Ferramenta do PC `r36os` (`src/r36os`, entrada no `pyproject.toml`) | `lume` (pacote `src/lume_tool`, comando `lume`; o módulo `lume.py` de hoje ganha outro nome, para não confundir) |

**Fica como está:**
- os comentários dos DTS de clones convertidos (`board/r36s/dts-vendor/`, gerados pela
  ferramenta: a próxima conversão já sai com o nome novo);
- os patches do kernel (fixados, regra dos patches);
- as changes arquivadas e `docs/referencia/`;
- o nome do repositório;
- a área de fábrica `R36OS_GA36_FACTORY` (nome de um arquivo fora do git, renomeado só se a
  1.1 achar uso em código; aí o código aceita os dois nomes).

**Ordem** (regras do grafo, recurso `TREE`): o código do console vem primeiro (1.2), depois
a ferramenta do PC (1.3), e por último a documentação, as specs e as tarefas abertas das
outras changes (1.4). Cada um fica sozinho na sua onda, e o teste-guarda
`tests/unit/test_lume_names.py` fecha na 1.4: ele falha se achar `r36os` num nome de
arquivo, pacote, serviço, caminho ou comando do console e da ferramenta (os comentários dos
itens que ficam como estão não contam).

**Cartão e atualização:** como o `push` troca o sistema inteiro, os serviços antigos somem
sozinhos. O risco está no que o `persist` guarda em `ROMS/system`. A 1.2 lista cada caminho
persistido que contém `r36os` (runlevels, `conf.d`, `power.conf`, `logs.conf`). Para cada
um, ou o caminho no cartão não muda, ou há uma migração única no boot, feita depois do
frontend e registrada como `persist OK migrated <antigo> -> <novo>`. A J0 (1.5) prova isso
com um `lume push` sobre o GA36 com os nomes antigos.

### D8. Menus verticais: só cima e baixo movem o foco

Numa lista vertical ou numa confirmação com as opções uma embaixo da outra, só cima e baixo
mudam o item em foco; esquerda e direita nunca trocam de item. Elas mantêm só dois usos:
mudar o valor de uma linha com seletor (Tema, core, aspecto), que é o único jeito de mudá-lo,
e passar para a coluna ao lado quando o layout tem uma (▶ na lista das Configurações leva ao
painel, como hoje). Numa confirmação, esquerda e direita não fazem nada. Isso vale para o `lume-ui` (confirmação de Desligar e de Suspender, listas) e para
o `lume-run` (confirmação do menu do jogo). A regra "Sim em cima ou à esquerda" vira "Sim em
cima" numa confirmação vertical. A regra do menu do jogo é da capability `game-actions`
(change `lume-hud-actions`): o código entra aqui, e o delta da spec entra depois que aquela
change for arquivada.

### D9. Volume analógico e amplificador desligado sem som

O volume do usuário (0 a 100%) passa a mexer no **ganho analógico da saída ativa**, e o DAC
fica em 0 dB.

- **GA36:** o perfil passa a `mixer GA36MB Headphone <passo>`, na escala de 0 a 63, com a
  curva perceptiva de hoje mapeada para as posições. O `mixer` do boot deixa o `DAC` em 0 dB.
- **R36S:** o mainline expõe só o `Master` digital do RK817. A prova 2.5 (J1) procura, pelo
  I2C com um tom tocando, o registrador de ganho do classe D e o do fone que mudam o volume
  sem mudar o ruído de fundo. Achado, um patch do kernel (7.1) expõe esse ganho como um
  controle ALSA. Se nenhum servir, o R36S fica com o digital e com o desligamento no silêncio
  do item seguinte, registrado no P-45.
- **Volume 0** é mudo de verdade: o interruptor da saída desligado, com o DAPM desligando o
  amplificador.
- **Silêncio:** com o jogo pausado, no menu ou no launcher, o amplificador fica desligado.
  O caminho sai da medição da 2.5: o DAPM com o fluxo fechado, o `spk-ctl`/`simple-audio-amplifier`
  baixo, ou o RetroArch fechando o fluxo de áudio na pausa. Ganha o que desligar o
  amplificador com a menor espera para o som voltar.
- O nível de cada saída fica em `ROMS/system/audio/level-<saída>` (formato congelado na 3.4)
  e é reaplicado no boot pelo `mixer`. A linha da borda direita e o percentual das
  Configurações mostram esse nível.
- O ganho de energia está no amplificador desligado. O ganho analógico em si muda pouco o
  consumo; ele resolve o chiado (P-29) e talvez o zumbido do R36S (P-45).

**Medido no GA36 (2.5, J1, 2026-11-18).**
- O `Headphone` (0 a 63) controla as duas saídas: o roteamento do DTS liga a saída do fone à
  entrada do amplificador do alto-falante (`Speaker Amp INL/INR` ← `HP`).
- Silêncio digital com o DAC em 0 dB, `Headphone` em 16, 32, 48 e 63: nenhum chiado ouvido pelo
  usuário no alto-falante. O chiado do P-29 não vem do ganho analógico em silêncio; fica para
  a J2 julgar num jogo.
- Tom de 440 Hz com o DAC em 0 dB: limpo em 32, 40, 48, 56 e 63. **Máximo limpo: 63.**
- O amplificador (`audio-amplifier`, GPIO `enable`) já é desligado pelo DAPM quando nenhum fluxo
  está aberto, e ligado em ~0,1 s quando o fluxo abre. Com o fluxo aberto em silêncio ele
  gasta **~12 mA** (336 contra 324 mA da bateria, launcher parado no brilho 7). O caminho do
  silêncio no GA36 é, então, fechar o fluxo (pausa ou menu); o ganho de energia é pequeno.

**Caminho escolhido (7.3, 2026-11-18): o RetroArch fecha o fluxo na pausa e no menu (patch
0014).** O que o código mostra:
- No kernel (6.18), o ASoC só desliga o caminho de reprodução, com o amplificador, quando os
  parâmetros do fluxo são liberados: `soc_pcm_hw_clean` → `snd_soc_dapm_stream_stop`, no
  `hw_free` ou no `close` (`sound/soc/soc-pcm.c`). Pausa (`snd_pcm_pause`), `snd_pcm_drop` e
  *underrun* não passam por aí: o fluxo pausado ou parado deixa o amplificador ligado. Só fechar
  (ou `hw_free`) serve.
- O desligamento depois do fechamento espera o `pmdown_time` (5 s por padrão, `soc-core.c`)
  só se um componente do link pedir (`use_pmdown_time`). No GA36 nenhum pede (`sun8i-codec`,
  `sun8i-codec-analog`, `sun4i-i2s`, `simple-amplifier`): desliga na hora, como a 2.5 mediu.
  No R36S o `rk817_codec` pede: o amplificador desliga 5 s depois da pausa, e voltar ao jogo
  antes disso não religa nada. **R36S não medido** (a J1 dele está pendente); o mecanismo é o
  mesmo, e a J3 confere a corrente.
- No RetroArch 1.22.2, o menu (com `menu_pause_libretro`) para o driver de áudio
  (`menu_driver_toggle` → `CMD_EVENT_AUDIO_STOP` → `audio_driver_stop`), mas o `alsa_stop` só
  faz `snd_pcm_pause(1)`; a pausa simples (`PAUSE_TOGGLE` do `lume-run`, o menu Lume) nem para
  o driver (`runloop_pause_checks`), e o fluxo fica em *underrun*. Nenhuma opção existente
  (`audio_enable_menu`, `audio_mute_enable`, `menu_pause_libretro`) fecha o fluxo.
- O patch 0014: o `alsa_stop` fecha o fluxo; o `alsa_start` não abre nada (o menu fechado
  sobre um jogo pausado não religa o amplificador); a primeira escrita reabre o fluxo com o
  mesmo dispositivo, taxa e latência; a pausa do jogo para o driver como o menu.
- **Espera para o som voltar:** a reabertura acontece antes da primeira amostra; o kernel liga
  o caminho no `prepare` (~0,1 s medido no GA36), e só então as amostras entram, então o começo
  do som não é cortado. O custo é o primeiro quadro depois da pausa esperar essa abertura uma
  vez. No R36S, voltar em menos de 5 s nem espera.
- **Launcher:** o `lume-ui` não abre o PCM (o SDL sobe só o vídeo; o volume é pelo `amixer`,
  que mexe só nos controles); com o launcher na tela o amplificador fica desligado.
- **Suspensão (8.3):** nada a fazer para o som. Antes do `freeze`, o `lume-run` pausa o jogo
  (8.4), e a pausa já fecha o fluxo. Mesmo com um fluxo aberto, o `snd_soc_suspend` do kernel
  desliga o DAPM na suspensão.

### D10. Fone nos dois consoles

O `jack` passa a valer nos dois consoles. Encaixar e tirar o fone troca a saída, e cada
saída guarda o próprio volume (D9). No R36S, a causa do laço do serviço (o `od` lendo o
evdev) é corrigida com o mesmo leitor de eventos do `lume-input`. No GA36, a detecção do fone
sai da prova 2.5 (pino e evento). Sem detecção no hardware, o fone do GA36 fica documentado
como "saída ligada aos dois, sem troca".

**Medido no GA36 (2.5, J1, 2026-11-18):** o DTS não tem pino de detecção, e encaixar o fone
não muda nenhum GPIO configurado nem interrupção. Mas a entrada do fone tem chave mecânica:
com o fone encaixado, o som sai só no fone e o alto-falante fica mudo. No GA36 a troca de
saída é do hardware; sem evento, o volume por saída (D9) vale só no R36S, e o GA36 fica com
um nível só.

### D11. Suspensão pelo botão de energia

```
 toque curto (solto antes de 1 s)  --> lume-input manda "power_tap" --> lume-sleep suspende
 segurado por 2 s                  --> lume-input manda "power_hold" --> sessão desliga (o mesmo
                                                                        caminho do menu)
 segurado por vários segundos      --> o PMIC desliga à força (reserva, como hoje)
```

O serviço root `lume-sleep` (pacote `lume-power`, sobe depois do `frontend`, sem laço) faz,
em ordem e com prazo:

1. avisa os clientes (`suspend`): o `lume-run` pausa o jogo pelo caminho de pausa da
   `lume-hud-actions` (3.1 de lá), e o `lume-ui` para de desenhar;
2. muda o som (D9) e grava a hora (D15);
3. faz `sync`, apaga a luz e desliga o Wi-Fi, se houver;
4. avisa o governor (cenário `suspend` no `lume-power`);
5. grava em `/sys/power/state` a profundidade do console.

Ao acordar, devolve tudo na ordem inversa e **o jogo continua sozinho** (padrão proposto).

- A profundidade (`mem` ou `freeze`) de cada console sai da prova 2.3: ler o
  `/sys/power/mem_sleep`, suspender, acordar e medir a corrente da bateria em cada modo. O
  `mem` só vale se acordar 10 vezes em 10 sem falha.
- Só o botão de energia acorda o console: `wakeup-source` no nó do `axp20x-pek` e do
  `rk805-pwrkey` no DTS (8.1), e o resto não acorda. **Como ficou (8.1):** nenhuma das duas
  teclas tem nó no DTS (são células MFD). No GA36 o driver `axp20x-pek` se faz fonte de
  despertar sozinho (a J1 acordou 10 de 10 sem overlay); no R36S o `wakeup-source` que já
  estava no nó do RK817 é o que arma a interrupção do PMIC como despertar (núcleo I2C). O
  resto sai em tempo de execução: linhas `nowake` no `/usr/share/lume/sleep/<placa>.conf`,
  que o `lume-sleep` desliga no `power/wakeup` antes de suspender e religa depois (carregador,
  bateria, RTC); os drivers dessas fontes as ligam sem ler o DTS. Restam duas que o sysfs não
  desliga: o `musb` do GA36 (arma a interrupção no probe) e o plugue do carregador no R36S
  (divide a linha do PMIC com o botão), a conferir na J2 e na J1/J3 do R36S. Tabela em
  `docs/LAUNCHER.md`. Sem opção nova de kernel nos dois.
- Eventos `sleep OK suspend <modo>`, `sleep OK resume after <s>` e `sleep FAIL ...`.
- Uma falha na suspensão volta ao estado de antes e registra o motivo, sem deixar a tela
  apagada.

**Medido no GA36 (2.3, J1, 2026-11-18):**

| Console | `mem_sleep` | Modo | Despertar pelo botão | Corrente suspenso |
|---|---|---|---|---|
| GA36 | `[s2idle]` só (`mem` vira s2idle) | `freeze` | 10 de 10 no primeiro toque (de 3 a 181 s dormindo), mais 2 avulsos e 35 min seguidos | não medida com precisão: com a bateria cheia a carga fica em 100% e a tensão caiu 22 mV em 35 min; repetir com a bateria pela metade |
| R36S | (pendente, J1 do R36S) | | | |

- O `axp221-pek` já é fonte de despertar no GA36 sem overlay; o `rtc0` não tem `wakealarm` no
  sysfs e o busybox não tem `rtcwake`.
- **O gadget USB não volta depois do `freeze`:** o `musb` fica em `b_peripheral` com o UDC
  `not_attached` e o PC não enumera nem com o cabo recolocado. Soltar o gadget do UDC antes
  e religá-lo ~1 s depois de acordar resolve (UDC `configured`, o PC enumera). O `lume-sleep`
  faz isso (8.3).
- **Entrada acumulada:** ao acordar, a interface "andou" sozinha com os eventos do controle
  da suspensão; o `lume-sleep`/`lume-input` descartam a entrada acumulada ao acordar (8.2, 8.3).
- Acordado, o launcher parado gasta ~324 mA da bateria no brilho 7.

**Protocolo congelado (3.2):** `docs/LAUNCHER.md` ("Protocolo do sono") e
`lume/lume-core/src/sleep.rs`. O `lume-input` faz o pedido (`/run/lume/sleep/suspend` no
toque, `poweroff` no segurado) e manda `power_tap`/`power_hold` aos clientes só como aviso; o
`lume-sleep` avisa pelo arquivo `phase` (`suspend|resume <seq>`), o `lume-input` repassa aos
clientes pelo socket, espera `suspend_ok <seq>` até 2 s e responde no arquivo `clients`; o
`lume-sleep` espera essa resposta até 3 s. Modo por console em
`/usr/share/lume/sleep/<placa>.conf` (GA36 `freeze` medido, R36S `freeze` até a J1 dele).

### D12. Brilho: o limite aprendido no lugar da trava

> **Saiu desta change (usuário, 2026-11-18):** a J2a, a revisão do D12 e as tarefas de brilho
> (3.3, 6.1, 6.2, 6.5) vão para uma change própria e isolada do P-95. Ficam nesta change só os
> kernels de experimento da 6.3, já mesclados, e os resultados do E2 e do E3 abaixo. O GA36
> continua com o `backlight_max 7`. O texto abaixo fica como registro para a change do P-95.

- O `backlight_max` sai dos perfis. O brilho vai até o máximo do hardware.
- **Limite seguro** por aparelho, guardado em `ROMS/system/display/limit-<serial>` (formato
  congelado na 3.3). O padrão é 7 no GA36 e nenhum no R36S.
- ~~Pontinho vermelho no nível do limite~~: **removido pelo usuário (2026-11-18)**; o limite
  não aparece na tela, fica só no registro (D19).
- **Relato pelo usuário:** Fn+Select ("a tela falhou agora", acorde livre desde a
  `lume-hud-actions`) grava no `events.log` o nível, a tensão e a corrente da bateria, a
  temperatura, o carregador ligado e o tempo de tela acesa, e baixa o limite para um nível
  abaixo do atual. A resposta na tela é uma linha curta.
- **Aprendizado:** uma hora acumulada acima do limite, sem relato, sobe o limite em um nível.
  Cada mudança vira o evento `display OK limit <de> -> <para> (<motivo>)`.
- **Recomeçar o aprendizado** (pedido do usuário, 2026-11-18): linha no painel Brilho das
  Configurações, com confirmação. Apaga o limite deste aparelho e grava "sem limite"
  (`none` no arquivo do 3.3, diferente de arquivo ausente, que usa o padrão do console): o
  brilho vai até 10, sem pontinho, até o primeiro relato, que recria o limite um nível abaixo.
  Evento `display OK limit <de> -> none (reset)`. O `lume-ui` grava o pedido e o
  `lume-input` aplica (mesmo dono do arquivo que o relato).
- **Causa (P-95):** os experimentos E1 a E5 do P-95 viram as tarefas 2.7 (sem build: E2
  corrente e E3 calor) e 6.3 (com kernel de experimento: E1 DCDC1 a 3,3 V e E4 DSI). A E5
  (foto da placa) fica com o usuário, quando puder. O resultado vai para o P-95 e o
  `docs/BRINGUP-GA36.md`.
- **E2 parcial (2.7, J1, 2026-11-18):** com o console frio (~43 °C no SoC) e a bateria em 100%,
  a imagem ficou estável do nível 6 ao 10 no carregador e do 6 ao 8 só na bateria (no 9 e
  no 10 o AXP leu um VBUS falso, então essa parte valeu como carregador). Corrente da bateria
  por nível: 6 = 240 mA, 7 = 316 mA, 8 = 339 mA. Faltam a bateria baixa e o calor (E3).
- **E3 (2.7, J1, 2026-11-18):** com um jogo de PS1 o SoC só chegou a 49 °C, e nada falhou no
  nível 8 por 10 min. Com a CPU forçada (1008 MHz nos 4 núcleos), **a falha apareceu no nível 8
  com o SoC a ~66 °C** (bateria a 3,97 V e 670 mA), **continuou depois de o brilho voltar ao 6**
  e sumiu ao esfriar (nada a ~51 °C). O aspecto (foto do usuário) é uma cópia fantasma da
  imagem, deslocada para baixo e listrada, numa piscada rápida: o painel pega linhas da
  posição errada. O gatilho é o **calor**, e a falha é de **sinal/temporização** (DSI e
  JD9366), não da luz de fundo. Consequências: o E4 e o modo de ~60 Hz da 6.3 passam a ser
  testados **no quente** (com a mesma carga forçada), e o limite aprendido registra a
  temperatura no relato (Fn+Select), para a regra do limite poder passar a usar a temperatura
  junto com o nível se os relatos mostrarem isso.
- **Revisão do D12 condicionada ao E4 (usuário, 2026-11-18).** Como a falha continua no
  brilho 6 com o console quente, limitar o brilho pode não ser a mitigação. Depois da J2
  (6.3, no quente), o D12 é revisto conforme o resultado:
  - **o E4 ou o modo de ~60 Hz fazem a falha sumir no quente:** a correção de temporização
    entra na imagem padrão; o pontinho vermelho e o limite de brilho saem (6.1, 6.2, 3.3 e
    a spec `display-brightness` ajustadas), e fica só o relato Fn+Select como registro;
  - **nenhum resolve:** o aprendizado passa a aprender uma **temperatura limite** por aparelho
    (no lugar, ou além, do nível), e o sistema reage a ela antes da falha (aviso na tela e o
    governor segurando o clock), com a proposta levada ao usuário antes do código.
  As tarefas 3.3, 6.1 e 6.2 só começam depois dessa revisão (6.3 e a J2 vêm antes delas no
  grafo).

### D13. Painel do GA36 a ~60 Hz

> **Saiu desta change (usuário, 2026-11-18):** a prova do ~60 Hz vai com a J2a para a change
> do P-95; as variantes `60hz` e `60hz-porch` já estão prontas (6.3).

Modo novo do JD9366 no patch 0005: pixel clock próximo de 32,3 MHz ou porches menores,
dentro do PLL do vídeo do A33 e da taxa do DSI. É testado só com o build do kernel, junto
com o kernel do experimento E4 (D12), e o `SLOTS.old` desfaz uma tela preta. Aprovado, o
`video_refresh_rate` do `retroarch-ga36.cfg` acompanha (o teste
`test_ga36_refresh_rate_matches_panel_mode` acusa a diferença). Se nenhum modo der imagem
estável nos dois painéis, a tarefa registra o limite e o P-25 fica aberto.

### D14. Mega Drive no GA36

A prova 2.6 confere se o `picodrive` entrega quadros com o formato de pixel que o lima
mostra (o contador anda e a tela fica preta). Os caminhos possíveis: o formato de pixel do
core (RGB565 contra XRGB8888) no driver de vídeo, ou trocar o core do armv7 para o
`genesis_plus_gx` se ele rodar em velocidade cheia. O arcade (P-26) só é conferido na mesma
janela.

### D15. Hora que só anda para a frente

O Wi-Fi é opcional e o RTC não tem bateria própria, então nenhuma fonte é garantida:

- **gravar:** no desligamento e na suspensão, a hora atual vai para
  `ROMS/system/clock` (texto, segundos);
- **restaurar:** depois do `frontend`, sem nada no caminho do boot, a hora passa a ser a maior
  entre a gravada, a data do build e o RTC (se ele trouxer uma hora válida);
- **corrigir:** quando houver uma fonte real (NTP com o dongle de Wi-Fi, ou o PC pelo cabo no
  `lume push`/`lume dev`), a hora é corrigida e o RTC também, sem nada depender disso;
- os logs continuam pelo número do boot, e a hora é só informação aproximada;
- nada aparece na tela.

A prova 2.4 lê o RTC depois de um desligamento, só para registrar se a hora sobrevive com a
bateria principal.

**Medido no GA36 (2.4, J1, 2026-11-18):** RTC acertado pelo cabo (`hwclock -w`), desligado
pelo menu por ~6 min com o cabo ligado: voltou com 2 a 3 s de diferença do PC, e o boot já
pegou a hora (o `events.log` saiu com a data certa). O RTC também anda entre reinícios
(antes do acerto ele marcava 1970-01-10, contando desde a última perda de energia). **Sem o
cabo** (2026-11-18, boot 193 a 194): desligado pelo menu às 21:45:11 e ligado às 22:01:58
(~17 min só na bateria), o RTC voltou **exatamente** com a hora do PC (0 s de diferença). No
GA36 a hora sobrevive ao desligamento pela bateria principal; falta o R36S.

### D16. Nós de entrada só leitura para os jogos (P-87)

Uma regra do udev deixa o controle do aparelho, o controle virtual do `lume-input` e os
botões de energia e volume em `0640 root input`. Só o `lume-input` (root) escreve neles.
Controles USB ficam com `0660`, porque a vibração e os LEDs precisam de escrita, e a 9.3
confere o SDL do RetroArch com eles.

### D17. Analógicos calibrados no início (P-47, 6.8)

O `lume-input` lê o repouso de cada eixo nas primeiras amostras ao abrir o controle (como a
fábrica) e passa a reportar `valor - repouso + centro`, com a zona morta do perfil. Se o
repouso lido estiver fora da faixa plausível (um analógico segurado no boot), ele usa o
centro do DTS e registra o aviso.

### D18. `flashed` aponta para o build gravado (P-50)

O `mark_flashed()` (`src/r36os/flash.py:285`, `src/lume_tool/flash.py` depois do D7)
resolve o caminho (`build_dir.resolve().name`) antes de criar o link. O `flash` com `sudo`
na frente passa a avisar.

### D19. Menu do sistema pelo Fn no launcher (trazido da `launcher-adjustments`)

Decisão do usuário (2026-11-18): o menu do sistema, a dica do Fn e o reiniciar saem da
`launcher-adjustments` (D1 a D4 de lá) e entram aqui, junto com o Suspender. A
`launcher-adjustments` fica só com as cores e os logos dos consoles.

- **Camada própria no `lume-ui`:** um campo `system: Option<SystemMenu>`, separado do
  `overlay`, desenhado por cima de qualquer tela ou folha e com a entrada antes do resto; ao
  fechar, a tela de baixo continua como estava.
- **Itens, nessa ordem:** Configurações, Suspender, Reiniciar, Desligar; foco inicial em
  Configurações.
  - Configurações abre as Configurações lembrando a tela de origem; B volta a ela.
  - Suspender pede a suspensão sem confirmação (o mesmo pedido do botão, D11 e 3.2).
  - Reiniciar e Desligar abrem a confirmação vertical (o item em cima, Cancelar embaixo com o
    foco, só cima e baixo mudam a escolha, D8).
- **Eventos:** `Ev::FnTap` abre e fecha; `Ev::FnHold(tabela)` mostra a dica dos atalhos (só
  `Vol=brightness` no launcher, mais "Fn (toque): Menu do sistema"); `Ev::FnRelease` a
  esconde. Os três vêm da thread do socket (`lume/lume-ui/src/input.rs`) pelo parser do
  `lume-core`.
- **Reiniciar pelo contrato de sessão:** o `lume-ui` sai com **66**; o `lume-run` repassa o 66
  como repassa o 0; o `session` ganha o ramo `rc 66` (`closed by user: rebooting`,
  `persist flush`, `sync`, `reboot`). Código documentado no `docs/FRONTEND.md`; um frontend que
  nunca sai com 66 continua igual.
- **Configurações:** sem Desligar, sem Suspender e **sem RetroArch** (o acesso ao menu completo
  do RetroArch fora do jogo volta pela P-101). A lista fica Idioma, Tema, Tela, Volume,
  Brilho, Sistema, Cartão, Games (mais Wi-Fi e Bluetooth com adaptador).
- **Rodapé do Dock:** a dica do Fn (glifo + "Menu") ao lado das de A e do direcional.
- **Brilho sem pontinho:** o usuário dispensou o pontinho vermelho (2026-11-18); o limite do
  D12 fica só no registro até a revisão pós-E4.
- Protótipo primeiro (4.1), régua a 640x480, três idiomas.

## Risks / Trade-offs

- [Um nome errado num serviço do boot deixa o console sem subir] → Nós `TREE` com `opus`; a
  1.2 roda a `test_boot_order` e as suítes de shell; a J0 sobe o GA36 antes de qualquer outro
  código; o `SLOTS.old` volta ao build anterior.
- [Um caminho persistido com o nome antigo se perde no cartão] → A lista e a migração da 1.2
  e a prova da J0 sobre um console com os nomes antigos.
- [O kernel não limpa o bit e a verificação roda sempre] → D2, decidido pela 2.1 antes do D1
  ser mesclado.
- [Um volume corrompido sem o bit não é verificado] → "Verificar no próximo boot" e o
  `errors=remount-ro`.
- [O R36S não tem ganho analógico acessível] → O D9 fica com o digital mais o desligamento
  no silêncio, registrado.
- [Desligar o amplificador no silêncio corta o começo do som] → A medição da 2.5 escolhe o
  caminho com a menor espera, conferida de ouvido na J2/J3.
- [A suspensão `mem` não acorda] → Só entra com 10 de 10 na prova; senão `freeze`. Segurar o
  botão continua desligando à força pelo PMIC.
- [A bateria acaba durante a suspensão] → No `freeze`, o `lume-power` continua lendo a
  bateria e desliga pelo crítico. No `mem` nada roda, e o PMIC corta a energia; o volume fica
  limpo pelo `sync` do D11, e o boot seguinte verifica pelo bit, se precisar.
- [O DCDC1 a 3,3 V passa do limite de algum componente do GA36] → Só no kernel de
  experimento, dentro da faixa do A33 e do JD9366, com o usuário olhando e o `SLOTS.old`.
- [Fn+Select engolido num jogo que o usa] → O Fn já não sai para os jogos desde a
  `lume-hud-actions`, então o acorde não chega ao jogo.
- [A troca de nomes reescreve tarefas de outras changes enquanto elas estão pausadas] → É
  a regra do grafo para changes no mesmo branch: a 1.4 atualiza as tarefas abertas no mesmo
  merge, sem mudar o que elas pedem.

## Migration Plan

- **Nomes:** o primeiro `lume push` depois da onda `TREE` troca o sistema inteiro. A
  migração única do D7 move os caminhos persistidos, e a J0 a prova.
- **Cartão:** sem pedido e com o volume limpo, o boot só pula a verificação.
- **Brilho:** o limite começa no padrão (7 no GA36), igual ao teto de hoje, só que sem
  trava.
- **Volume:** o nível digital de hoje é convertido uma vez para a posição analógica mais
  próxima.
- **Hora:** sem `ROMS/system/clock`, vale a data do build.
- **Voltar ao build anterior** pelo `SLOTS.old` devolve os nomes antigos. Os caminhos já
  migrados no cartão continuam lá, e o build antigo não os lê, o que perde só as escolhas
  feitas depois da migração.

## Open Questions

- **Prova dos nós `TREE` (padrão proposto, a confirmar pelo usuário):** as suítes de unidade
  e de shell mais um boot no GA36 na J0, sem a `vm`, que segue fora do ciclo (P-81). Se o
  usuário pedir a `vm`, reativá-la vira um nó antes da 1.2.
- **Ao acordar, o jogo continua sozinho (padrão proposto, a confirmar):** a outra opção é
  ficar pausado até um botão.
- O valor do read-ahead (D6), a profundidade da suspensão (D11), o caminho do silêncio e o
  ganho do R36S (D9) saem das medições da J1 e não mudam o desenho.
