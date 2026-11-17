# Proposal

## Why

Durante o jogo, o único atalho do sistema que o Lume controla é o Fn+Start (sair). O menu
abre pelo Fn sozinho ou pelo Start + Select, que é do RetroArch e atrapalha os jogos que usam
essa combinação. Salvar, carregar, reiniciar e tirar foto só pelo menu do RetroArch, e não há
como ver, no meio do jogo, quanto a CPU, a GPU, a memória e a bateria estão sendo usadas. A
próxima change do roadmap (o governor e os cenários de bateria, tema 6 das pendências) precisa
justamente desses números na tela para comparar os perfis. Por isso esta change vem antes
dela.

## What Changes

- **Ações do Lume durante o jogo**: o `r36os-input` passa a tratar o Fn como modificador do
  sistema e transforma cada acorde numa ação com nome, enviada ao supervisor do jogo:
  - Fn+Select → `lume_menu` (menu do Lume sobre o jogo);
  - Fn+B → `app_menu` (menu da aplicação: o do RetroArch);
  - Fn+R1 → `save_state` e Fn+L1 → `load_state`, no slot rápido;
  - Fn+Y → `screenshot` (foto do jogo em `ROMS/screenshots/`);
  - Fn+X → `hud` (mostra e esconde a barra de status);
  - Fn+Start → `quit` (sem mudança: encerra direto, é a saída de emergência);
  - os demais acordes com Fn ficam reservados para atalhos futuros e não chegam ao jogo.
- **Menu do Lume sobre o jogo** (Fn+Select): Voltar ao jogo, Reiniciar, Menu do RetroArch e
  Encerrar jogo, com confirmação em Reiniciar e Encerrar. O jogo fica pausado e o controle
  navega o menu sem chegar ao jogo. O desenho segue o protótipo do launcher, e os textos seguem
  o idioma do usuário.
- **O runner declara como executa cada ação** (`runners.d/*.toml`) e se sabe desenhar o menu do
  Lume; o `lume-run` executa a ação do jogo em curso. O RetroArch usa comandos de rede que já
  existem (`MENU_TOGGLE`, `RESET`, `SAVE_STATE`, `LOAD_STATE`, `SCREENSHOT`, `QUIT`); um
  emulador standalone pode declarar uma tecla, enviada pelo controle virtual, ou um sinal. Um
  runner sem a ação ignora o acorde, com uma linha no log. Fora do RetroArch, o menu do Lume
  não abre nesta versão (o Lume não tem como desenhar sobre outro programa sem um compositor).
- **BREAKING (atalhos):** o Fn sozinho deixa de abrir o menu e não faz nada; Start + Select
  deixa de abrir o menu do RetroArch e volta a ser do jogo.
- **Barra de status no topo da tela**, à moda do Steam Deck, só enquanto ligada pelo Fn+X: CPU
  (% e clock), GPU (%), memória no formato `usada/total/swap` (o swap é o ZRAM em uso),
  bateria (%, potência atual e tempo restante estimado, ou o tempo até encher quando
  carregando). O supervisor do jogo coleta os números só com a barra visível.
- **O RetroArch só desenha**: a barra e o menu do Lume são widgets de um patch novo,
  alimentados por comandos de rede, no mesmo caminho da linha de volume (patch 0011).
- **Foto em todo save state**: a captura da imagem do estado passa a ser fixada pela
  configuração do Lume, e não só pela configuração de fábrica (que só vai para cartões novos).

Fora do escopo: a barra dentro do launcher, o menu do Lume em runners que não sejam o
RetroArch, troca de slot por atalho, o governor e os perfis por cenário (próxima change), o
indicador de carga no launcher (P-78) e o custo do `logd` (P-60), que vão para a change do
governor.

## Capabilities

### New Capabilities
- `game-actions`: atalhos do sistema durante o jogo (o Fn como modificador do Lume), as ações
  com nome, o menu do Lume sobre o jogo e como cada runner executa as ações, incluindo a foto
  do jogo e a do save state.
- `performance-hud`: a barra de status sobre o jogo, o que ela mostra, quando a coleta roda e
  o custo dela.

### Modified Capabilities
- `game-runners`: o runner declara as ações que suporta e se desenha o menu do Lume; o
  requisito "Fn sozinho continua abrindo o menu" sai.
- `frontend-session`: os atalhos padronizados passam a ser Fn+B (ou o menu do Lume) para o
  menu do RetroArch, e o Start + Select deixa de abrir o menu.

## Impact

- `aports/r36os-input/input.c` e os perfis `ga36.conf`, `r36s.conf` e `vm.conf` (tabela de
  acordes, captura do controle); testes do `r36os-input`.
- `lume/lume-run` (ações do runner, menu do Lume, barra), `lume/lume-core` (protocolo,
  runner, textos do menu nos três idiomas), `lume/lume-ui` (o arquivo de lançamento leva as
  ações) e `aports/lume-games/.../runners.d/*.toml`.
- `aports/retroarch`: um patch novo com os widgets da barra e do menu do Lume.
- `aports/lume-retroarch-cfg`: `input_menu_toggle_gamepad_combo`, `input_menu_toggle_btn` dos
  autoconfigs, `savestate_thumbnail_enable` e as chaves da foto do jogo no
  `retroarch-lume.cfg`.
- Protótipo do launcher (`docs/lume-launcher/prototipo/`): a tela do menu do Lume sobre o
  jogo, que serve de régua para o widget.
- Regra do udev para o `profiling` do `panfrost` no R36S.
- Documentação: `docs/LAUNCHER.md`, `docs/FRONTEND.md`, guias de bring-up; pendências P-62
  (atalhos com Fn no jogo) atendida e P-57 (captura de tela) atendida no RetroArch.
- Provas no GA36 e no R36S (o mesmo cartão, um console de cada vez).
