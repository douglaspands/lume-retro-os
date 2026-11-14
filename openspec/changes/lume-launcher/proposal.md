# Proposal

## Why

Hoje o frontend do Lume Retro OS é o próprio RetroArch, com o menu Ozone. Ele é pesado para
navegar uma coleção grande, não mostra capas e só abre cores libretro. Também não há como sair de um jogo e voltar para a
lista sem passar pelo menu dele. O usuário quer um launcher próprio com o comportamento do
EmulationStation do dArkOS: um Dock de consoles, a grade de jogos com capas e o menu do jogo, e o
jogo aberto por linha de comando. Ele tem de ser escrito em Rust, gastar o mínimo de CPU e de RAM
no GA36 (o aparelho mais fraco) e quase nada enquanto um jogo roda. O planejamento (notas, metas e
protótipo candidato `20261114-033157`) está em `docs/lume-launcher/`. Este change faz a
reconciliação com o Lume, que é Alpine, sem EmulationStation e com o contrato de sessão de
`docs/FRONTEND.md`. É a pendência P-44.

## What Changes

- **lume-launcher como frontend padrão**: entra pelo contrato de sessão
  (`/usr/libexec/r36os/frontends/lume` e `FRONTEND="lume"`). O RetroArch passa a ser só o
  provedor dos cores: é aberto com o jogo e fecha quando o jogo termina. **BREAKING** para quem
  espera o menu do RetroArch no boot. O menu completo continua acessível por um item das
  Configurações e, dentro do jogo, por Start+Select.
- **Interface** (Rust + SDL2), conforme o protótipo candidato:
  - Dock infinito com Favoritos, Recentes e Configurações;
  - grade de capas e busca por nome;
  - menu do jogo: Iniciar, Iniciar de um save state e Favoritar;
  - emulador ou core em 3 camadas (jogo, console, padrão), com aspecto e shader nos cores do
    RetroArch;
  - Configurações: Wi-Fi e Bluetooth (só com dongle), Idioma, Tema (Material escuro e claro),
    Modo lite, Volume, Brilho, Sistema, "Atualizar listas de jogos" e Desligar.
  - O desenho só acontece quando há input e o cache de capas tem teto em bytes.
- **O launcher sai durante o jogo**: um supervisor pequeno (`lume-run`) roda o jogo e, quando
  ele termina, reabre a interface no mesmo console e no mesmo jogo. Durante o jogo só ficam na
  memória o `lume-run` e o daemon de entrada.
- **Fn+Start universal**: encerra qualquer coisa aberta pelo launcher (RetroArch, LÖVE,
  emulador standalone, script de Ports) e volta à lista. A combinação é detectada abaixo dos
  programas, por um daemon de entrada que fica com o controle físico. O encerramento é
  garantido: primeiro um pedido educado (comando `QUIT` do RetroArch, ou SIGTERM), depois a
  morte do grupo inteiro do jogo (cgroup). **BREAKING** para a regra atual de que nenhuma
  combinação encerra o RetroArch.
- **Emuladores por configuração**: cada emulador é um *runner* descrito num arquivo TOML em
  `runners.d/`, que diz o comando e como encerrar. O usuário pode trazer os dele no cartão. O
  `systems.json` passa ao esquema 3, com a lista de emuladores de cada sistema (runner e core).
- **Listas de jogos no formato do EmulationStation**: um scan lê `roms/<id>/` e faz o diff com
  `roms/<id>/gamelist.xml`.
  - Jogo novo entra no XML.
  - Jogo que sumiu sai da lista exibida, mas os metadados e as imagens ficam no XML, sem regras
    de proteção.
  - O scan roda no boot (em segundo plano), quando o cabo USB é desligado e pelo item das
    Configurações.
  - A interface lê um índice binário, não o XML.
- **Ícones próprios no Dock**: tiles com a sigla do console, desenhados pelo tema. A distro não
  traz logotipo de fabricante. Um tema do usuário no cartão pode trazer os dele.

Fora do escopo:
- portas do PortMaster, que precisam de um ambiente glibc (P-56, registrada por este change);
- scraping de capas;
- navegador de Arquivos e tela de Capturas do protótipo;
- estatísticas de tempo de jogo;
- temas além dos 2 Material.

## Capabilities

### New Capabilities

- `game-launcher`: a interface do launcher. Cobre telas, navegação só por gamepad, listas,
  favoritos, recentes, busca, menu do jogo, opções em 3 camadas, configurações, temas e idiomas,
  e as metas de consumo e de tempo.
- `game-runners`: como um jogo é aberto e encerrado. Cobre runners declarativos, o supervisor
  que libera a tela e volta à interface, o Fn+Start universal com encerramento garantido, e
  volume no sistema.

### Modified Capabilities

- `frontend-session`: o frontend padrão passa a ser o lume-launcher. "Sair desliga" passa a ser
  o item Desligar do launcher. A regra "nenhuma combinação encerra o RetroArch" vira "Fn+Start
  encerra o jogo e volta ao launcher". O requisito de menu sem miniaturas passa a valer só para o
  menu do RetroArch. A proibição de logotipos passa a cobrir também o launcher.
- `game-library`: o catálogo ganha a lista de emuladores por sistema (esquema 3). As listas de
  jogos passam a ser os `gamelist.xml` do EmulationStation, com diff incremental, e o frontend
  pode pedir o scan.

## Impact

- **Código novo**:
  - workspace Rust `lume/` com os crates `lume-ui`, `lume-index`, `lume-run` e um crate comum;
  - aport `aports/lume-launcher` (cargo, crates vendorizados e fixados pelo `Cargo.lock`);
  - runners e temas em `/usr/share/lume/`.
- **Entrada**: o `aports/r36os-padmerge` vira o daemon de entrada dos dois consoles (hoje só o
  R36S). Ele passa a cuidar do Fn+Start, do volume e da combinação com o Fn, e o GA36 também
  passa a ter controle virtual. A autoconfiguração do RetroArch mantém os nomes dos controles.
- **Sessão e sistema**:
  - `rootfs/overlay/etc/conf.d/frontend`, `usr/libexec/r36os/frontends/lume`, `session`
    (cgroup delegado ao usuário `game`);
  - `logd`: o RetroArch ausente passa a ser "no launcher", não falha;
  - `usb-gadget`: avisa o scan quando o cabo é desligado;
  - `systems.json` no esquema 3, com `src/r36os/catalog.py` e os testes de catálogo.
- **RetroArch**: chaves fixas de saída e de volume mudam (`retroarch-lume.cfg` e
  `test_retroarch_cfg.py`). O jogo é aberto com aspecto e shader por `--appendconfig` e com o
  save state por slot.
- **Kernel**: conferir cgroup v2 (`cgroup.kill`) nos dois `.config` finais.
- **Medição**: RSS, CPU parado, tempo até a primeira tela e tempo de volta do jogo, no GA36 e no
  R36S, com as métricas do `logd`.
- **Documentação**:
  - `docs/FRONTEND.md`, `docs/CATALOG.md`, `docs/lume-launcher/` e os guias de bring-up;
  - `docs/PENDENCIAS.md`: o P-44 vira este change e o P-56 entra como nova pendência
    (PortMaster).
- **Branch**: `feature/lume-launcher`; a base (`main` ou `feature/boot-dtb-select`) será
  confirmada com o usuário.
