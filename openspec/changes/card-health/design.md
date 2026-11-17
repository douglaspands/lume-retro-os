# Design

## Context

Motivação em `proposal.md`; requisitos em `specs/card-maintenance` e nos deltas de
`boot-runtime` e `game-launcher`.

Estado atual:

- **Boot**: `setup_storage` (`initramfs/lib/storage.sh:136`) decide o que fazer com a partição
  2 pelo setor de boot (`fs_type_at`) e, sendo exFAT, roda `check_roms` (`fsck.exfat -p`) em
  todo boot; depois o `init` monta a `ROMS` (`initramfs/init:87`, `noatime`) e a move para
  `/newroot/storage`. Medido no GA36 (boot 55): 0,87 s de verificação com o cartão quase vazio.
- **Desligamento**: o `session` faz `sync` (linhas 44 e 142) e chama `poweroff`; não há
  desmontagem explícita da `ROMS`. Não se sabe se o kernel limpa o bit *VolumeDirty* nesse
  caminho: se não limpar, o bit fica ligado em todo boot e a verificação continuaria sempre.
- **Configurações** (`lume/lume-ui/src/app.rs`, `SetRow`, linha 98 e `set_rows`, linha 1067):
  Idioma, Tema, Tela, Volume, Brilho, Sistema, Games, RetroArch, Desligar, mais Wi-Fi e
  Bluetooth com adaptador. O `lume-ui` roda como `game`; tarefas de root seguem o molde do
  `ssh-wifi` (o launcher escreve um arquivo, um serviço root o aplica).
- **Serviços que reagem a arquivos**: o `lib.sh` já tem o laço de `inotifyd` com debounce, usado
  pelo `persist` e pelo `savesync`.
- **Contador de boots**: `ROMS/logs/.boot` (o mesmo `<n>` de todos os logs).
- **Cartão**: aceita discard (`discard_max_bytes` 1,9 GB no GA36); o exFAT do kernel 6.18 aceita
  `FITRIM`; `read_ahead_kb` padrão 128.

## Goals / Non-Goals

**Goals:**
- Boot limpo sem nenhuma leitura além de um setor da `ROMS`.
- Manutenção só quando o usuário pede, com o serviço parado no resto do tempo.

**Non-Goals:**
- Verificação periódica automática (sem relógio, e um contador de boots como gatilho voltaria a
  pesar no boot sem aviso).
- Bateria fraca (change do governor).
- Mudar opções de montagem do exFAT (`discard` contínuo fica de fora: um TRIM por escrita pesa
  num cartão SD).

## Decisions

### D1. O bit do exFAT decide a verificação

O setor de boot do exFAT tem `VolumeFlags` no deslocamento 106 (2 bytes, little-endian): bit 1
`VolumeDirty`, bit 2 `MediaFailure`. O `storage.sh` ganha `volume_flags` (mesmo molde do
`fs_type_at`, `dd` de 2 bytes) e o caso `check` vira:

```
 decide_p2 = check
      |
      +-- pedido de verificação na ROMS? (D3) --sim--> fsck.exfat -p, apaga o pedido
      |
      +-- VolumeDirty ou MediaFailure? -------sim--> fsck.exfat -p
      |
      +-- senão: "roms OK clean: check skipped", nenhuma verificação
```

Eventos novos no log do boot e no `events.log` (categoria `roms`, já existente): `clean: check
skipped`, `dirty: checked ...` e `requested: checked ...`, com o resultado do `fsck` como hoje.

*Alternativa descartada:* verificar a cada N boots. Sem relógio, N boots podem ser um dia ou um
mês, e o custo voltaria sem o usuário saber por quê.

### D2. Desligamento que deixa o volume limpo (condicionado à prova)

A primeira prova (J1) lê o bit depois de um desligamento pelo menu, pelo botão e depois de um
corte de energia. Se o desligamento normal deixar o bit ligado, o fim da sessão passa a
remontar a `/storage` como somente leitura (`mount -o remount,ro`) depois do `sync` e antes do
`poweroff`, o que faz o kernel gravar o volume como limpo; se nem isso bastar, desmonta. Os
serviços que gravam no cartão (`logd`, `persist`, `savesync`) já descarregam antes, pela ordem
atual do desligamento. Se a prova mostrar o bit limpo, nada muda aqui e a tarefa registra o
resultado.

### D3. Pedido de verificação dentro da ROMS

O pedido é o arquivo `ROMS/system/card/check-next-boot`. Para lê-lo, o initramfs monta a
`ROMS` como já faz e, se o arquivo existir, desmonta, roda o `fsck`, apaga o pedido e monta de
novo. O custo extra só existe quando há pedido. O pedido fica no cartão, então sobrevive a
qualquer desligamento.

*Alternativa descartada:* o pedido na `BOOT`. Exigiria remontar a partição de boot como
gravável para um pedido do usuário, e um corte nessa hora a arrisca.

### D4. Serviço `r36os-card` sem laço

Serviço OpenRC (pacote `lume-saves`, ao lado do `persist`) que espera pedidos com o `inotifyd`
em `/run/r36os/card/` (pasta do grupo `game`, gravável pelo `lume-ui`). Pedidos são arquivos
com o nome do verbo:

| Pedido | O que faz | Resultado |
|---|---|---|
| `trim` | `fstrim -v /storage`; um segundo pedido com um em andamento é apagado sem rodar | `/run/r36os/card/status` com `running`, depois `ok <bytes>` ou `fail <motivo>`; `ROMS/system/card/last-trim` com o número do boot |
| `check-next-boot` | cria `ROMS/system/card/check-next-boot` | `status` `ok`; o boot que consome o pedido grava `ROMS/system/card/last-check` |

Outro nome de arquivo é apagado e registrado como recusado. O serviço sobe depois do
`frontend` (não pesa no boot, P-58) e o `inotifyd` dorme sem pedido.

### D5. Item "Cartão" no launcher

Linha nova `SetRow::Card` entre Sistema e Games. O painel lê o espaço livre (`statvfs` de
`/storage`), `last-trim` e `last-check`, e oferece as duas ações com A. Durante o TRIM, o painel
lê o `status` a cada segundo só enquanto estiver aberto e com o pedido em andamento. Textos em
en, pt e es no `i18n`. O visual entra antes no protótipo, no molde do painel Sistema, e o
`lume-ui` segue a régua (teste `card_matches_the_prototype_ruler`).

### D6. Read-ahead pela medição

Regra do udev no `lume-power`:
`ACTION=="add|change", KERNEL=="mmcblk[0-9]", ATTR{queue/read_ahead_kb}="<valor>"`. O valor sai
da medição: tempo de abrir uma ROM grande (PS1 e arcade) com 128, 256, 512 e 1024 KiB, com o
cache do kernel limpo entre as medidas, nos dois consoles. Ganha o menor valor depois do qual
o tempo para de cair. Se nenhum valor ganhar de forma clara, a regra não entra e a tarefa
registra o resultado.

## Risks / Trade-offs

- [O kernel não limpa o bit e a verificação roda sempre] → D2, decidido pela prova J1 antes
  do código do D1 ser ligado.
- [Um volume corrompido sem o bit ligado não é verificado] → É o comportamento de qualquer
  sistema com exFAT; o usuário tem "Verificar no próximo boot", e o `errors=remount-ro` da
  montagem continua protegendo de gravar num volume com erro.
- [O TRIM demora em cartões grandes e trava o painel] → Roda no serviço, não no `lume-ui`; o
  painel só lê o `status`.
- [O leitor ou o cartão recusa o TRIM] → `fail <motivo>` na tela e no log; nada mais muda.
- [Read-ahead maior gasta memória de cache] → Medir `mem_avail_mb` num jogo pesado com o valor
  escolhido.
- [Remontar como somente leitura no desligamento falha com um arquivo aberto] → O `session`
  registra a falha e segue para o `poweroff`, como hoje; o boot seguinte verifica pelo bit.

## Migration Plan

Cartões existentes não mudam: sem pedido e com o volume limpo, o boot só pula a verificação. A
pasta `ROMS/system/card/` é criada quando a primeira ação roda. Voltar à versão anterior pelo
`push` traz de volta a verificação em todo boot.

## Open Questions

- O valor do read-ahead: sai da medição (D6) e não muda o desenho.
