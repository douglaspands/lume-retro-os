# Proposal

## Why

O usuário vai começar a usar os consoles no dia a dia para melhorar a experiência (desempenho e
usabilidade), e hoje cada core roda com as opções padrão do upstream e as mesmas chaves do
RetroArch para todos, menos o `video_threaded=false` do PS1. Antes da otimização por compilação
(P-10), os cores precisam estar no melhor ponto que a configuração alcança, medido no aparelho,
para que a P-10 compare contra essa base e mostre só o ganho das flags e do PGO. No mesmo uso
apareceram lacunas pequenas de experiência: o analógico não move nada nos jogos, o TurboGrafx
não tem core, copiar jogos pelo cabo exige truques (o `dropbear` não tem `scp` nem `sftp`) e os
jogos de LÖVE não sabem o idioma do sistema.

## What Changes

- **Analógico como direcional:** o analógico esquerdo replica o direcional nas portas 1 a 4,
  como padrão de fábrica que o usuário pode mudar no menu; o PS1 no modo DualShock mantém o
  analógico separado. Um cartão que já existe recebe o padrão novo sem perder o que o usuário
  mudou.
- **Ajuste por core e por console, só por configuração:** linha de base dos cores padrão medida
  primeiro; depois testes A/B das chaves do RetroArch e das opções de cada core, no GA36 e no
  R36S, com as métricas do `lume-logd` (quadros mostrados por segundo, velocidade do core,
  falhas de áudio, clock escolhido pelo governor, temperatura). O resultado vira:
  - chaves de desempenho por core e por console no `retroarch-core.keys`, que ganha a dimensão
    do console (`ga36:<core>`, `r36s:<core>`);
  - opções de core de fábrica (`.opt`), que o usuário pode mudar no Quick Menu.
  Os jogos de LÖVE entram nos testes (variáveis do SDL e do Mesa no runner). Nenhuma flag de
  compilação muda (P-10 continua adiada).
- **TurboGrafx-16 e TurboGrafx-CD:** core novo `mednafen_pce_fast` (aport local, commit fixo,
  build padrão do upstream), dois sistemas novos no catálogo (`pcengine` e `pcenginecd`), com a
  BIOS do CD (`syscard3.pce`) no catálogo e no `LEIA-ME.txt`.
- **CPS-3:** sistema novo `cps3` no catálogo, no `fbneo` (que já está na imagem), com o romset
  do FBNeo no `LEIA-ME.txt`. Os backups do usuário não têm romsets de CPS-3: a prova no aparelho
  espera os romsets.
- **Conjunto de jogos de teste padrão:** os jogos escolhidos para os testes (comerciais, com
  `gamelist.xml` e capas, priorizando arcade, CPS-1, CPS-2 e Neo Geo, os sistemas preferidos do
  usuário) ficam no PC em `var/roms_test/` (fora do git), e um comando do `lume` os põe num
  cartão pelo cabo, sem apagar o que já está lá, para validar depois de limpar o cartão.
- **Cópia de arquivos pelo cabo:** `openssh-sftp-server` e `rsync` na imagem, para `scp`, `sftp`
  (inclusive o gerenciador de arquivos do PC) e `rsync` pela rede USB; nenhum dos dois roda no
  boot.
- **Idioma e fuso no ambiente dos jogos:** cada jogo aberto pelo launcher recebe `LANG` e
  `LANGUAGE` do idioma do launcher (en, pt, es) e `TZ` do fuso do sistema, em qualquer runner.
- **Listas de jogos corrompidas:** investigar os seis `gamelist.xml` encontrados com lixo binário
  no cartão do GA36 em 2026-11-19 (contra o requisito de gravação atômica) e corrigir a causa se
  ela for do sistema.

## Capabilities

### New Capabilities
- `core-tuning`: como a distro afina cada core e o RetroArch por configuração, por console: a
  linha de base medida, as chaves fixas por core e por console, as opções de core de fábrica, o
  analógico como direcional e a semeadura de padrões novos em cartões existentes.

### Modified Capabilities
- `game-library`: pastas e sistemas novos (`pcengine`, `pcenginecd`, `cps3`) e o core
  `mednafen_pce_fast` na lista de sistemas e cores incluídos.
- `device-testing`: conjunto de jogos de teste padrão no PC e o comando que o leva ao cartão.
- `game-runners`: o ambiente de todo jogo aberto pelo launcher traz o idioma (`LANG`,
  `LANGUAGE`) e o fuso (`TZ`) do sistema.
- `usb-otg`: além do SSH, a rede USB aceita cópia por `scp`, `sftp` e `rsync`.

## Impact

- `aports/lume-retroarch-cfg/` (`factory/retroarch/retroarch.cfg`, `retroarch-core.keys`, `.opt`
  de fábrica novos) e `aports/lume-core/files/usr/libexec/lume/frontends/retroarch` (leitura da
  dimensão do console e semeadura dos padrões novos); `tests/unit/test_retroarch_cfg.py`.
- Aport novo `aports/libretro-mednafen-pce-fast/`; `rootfs/packages.txt`;
  `aports/lume-games/files/usr/share/lume/systems.json`, `LEIA-ME.txt`, `docs/CATALOG.md`; testes
  do catálogo e da paridade de manifesto; `tests/cores/run_roms.sh`.
- `lume/lume-run` (ambiente do jogo) e `aports/lume-games/.../runners.d/love.toml`.
- `rootfs/packages.txt` (`openssh-sftp-server`, `rsync`); tamanho do `SYSTEM` cresce pouco.
- `src/lume_tool/` (comando que leva `var/roms_test/` ao cartão) e `docs/` do teste no aparelho.
- Roteiros e scripts de medição em `tests/device/`; relatório agregado por core em `docs/`
  (sem nome de jogo nem resultado por jogo).
- Aparelhos: GA36 (no cabo agora) e R36S, nas janelas de aparelho; builds de pacotes para
  armv7, aarch64 e x86_64.
