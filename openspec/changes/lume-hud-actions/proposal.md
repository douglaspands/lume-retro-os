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

- **O Fn como o botão Steam do SteamOS** (pedido do usuário, 2026-11-17): o `r36os-input`
  separa três gestos do Fn e manda cada um com nome ao supervisor do jogo:
  - **toque** (aperta e solta sozinho) → `fn_tap`: abre e fecha o menu do Lume sobre o jogo;
  - **segurar** sozinho (500 ms, ajustável no perfil) → `fn_hold`: mostra sobre o jogo a dica
    com os acordes que valem naquele jogo; soltar fecha a dica sem abrir o menu;
  - **acorde** (Fn seguro + outra tecla) → a ação da tabela; um acorde nunca vira toque.
- **Ações do Lume durante o jogo**: cada acorde vira uma ação com nome:
  - Fn+B → `app_menu` (menu da aplicação: o do RetroArch);
  - Fn+R1 → `save_state` e Fn+L1 → `load_state`, no slot rápido;
  - Fn+Y → `screenshot` (foto do jogo em `ROMS/screenshots/`);
  - Fn+X → `hud` (mostra e esconde a barra de status);
  - Fn+Start → `quit` (sem mudança: encerra direto, é a saída de emergência);
  - os demais acordes com Fn (Fn+Select incluído) ficam reservados para atalhos futuros e
    não chegam ao jogo.
- **Menu do Lume sobre o jogo** (toque no Fn): Voltar ao jogo, Encerrar jogo, Reiniciar e Menu do RetroArch, nessa ordem (pedido do usuário, 2026-11-17),
  com confirmação em Reiniciar e Encerrar. O controle navega o menu sem chegar
  ao jogo. O desenho segue o protótipo do launcher, e os textos seguem o idioma do usuário.
- **Pausa pela própria aplicação** (pedido do usuário, 2026-11-17): ao abrir o menu, o jogo é
  pausado pela ação `pause` do runner; no RetroArch, `GET_STATUS` + `PAUSE_TOGGLE`, a pausa
  dele, que vale para qualquer core. Ao voltar, despausa só se foi o menu que pausou. Runner
  sem pausa: o sistema congela o programa.
- **O menu é do sistema, não da aplicação** (pedido do usuário, 2026-11-17): aparece sobre
  qualquer runner, mesmo travado. O sistema pega a tela emprestada só com o menu aberto
  (congela a aplicação, duplica o descritor do DRM dela com `pidfd_getfd` e desenha sobre o
  último quadro). Se a aplicação não responde, o menu oferece "Forçar fechamento". Depende de
  uma prova técnica na primeira janela de aparelho; se falhar, o menu fica como widget do
  RetroArch, e o app travado continua fechando pelo Fn+Start.
- **O runner declara como executa cada ação** (`runners.d/*.toml`) e se sabe desenhar o menu do
  Lume; o `lume-run` executa a ação do jogo em curso. O RetroArch usa comandos de rede que já
  existem (`MENU_TOGGLE`, `RESET`, `SAVE_STATE`, `LOAD_STATE`, `SCREENSHOT`, `QUIT`); um
  emulador standalone pode declarar uma tecla, enviada pelo controle virtual, ou um sinal. Um
  runner sem a ação ignora o acorde, com uma linha no log. Fora do RetroArch, a barra e a dica
  não aparecem nesta versão (aparecem com o jogo rodando, o que exigiria um compositor).
- **BREAKING (atalhos):** o toque no Fn deixa de abrir o menu do RetroArch e passa a abrir o
  menu do Lume (o do RetroArch fica no Fn+B e num item do menu do Lume); Start + Select deixa
  de abrir o menu do RetroArch e volta a ser do jogo.
- **No launcher**, o toque e o segurar do Fn chegam ao `lume-ui` pelos mesmos eventos, mas o
  uso deles (menu do sistema com Desligar, Reiniciar e Configurações, e a dica no launcher) é
  da change de ajustes do launcher (P-74, P-72), que vem depois desta.
- **Barra de status no topo da tela**, à moda do Steam Deck, só enquanto ligada pelo Fn+X: CPU
  (% e clock), GPU (%), memória no formato `usada/total/swap` (o swap é o ZRAM em uso),
  bateria (%, potência atual e tempo restante estimado, ou o tempo até encher quando
  carregando). O supervisor do jogo coleta os números só com a barra visível.
- **O RetroArch só desenha**: a barra e a dica dos acordes (e o menu, só no caminho de
  reserva) são widgets de um patch novo,
  alimentados por comandos de rede, no mesmo caminho da linha de volume (patch 0011).
- **Foto em todo save state**: a captura da imagem do estado passa a ser fixada pela
  configuração do Lume, e não só pela configuração de fábrica (que só vai para cartões novos).

Fora do escopo: a barra dentro do launcher, a barra e a dica em runners que não sejam o
RetroArch, troca de slot por atalho, o governor e os perfis por cenário (próxima change), o
indicador de carga no launcher (P-78) e o custo do `logd` (P-60), que vão para a change do
governor.

## Capabilities

### New Capabilities
- `game-actions`: atalhos do sistema durante o jogo (o Fn como botão do sistema: toque,
  segurar com a dica dos acordes, e acordes), as ações
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
- `lume/lume-menu` (novo, se a prova passar: desenha o menu do Lume pegando a tela da
  aplicação), `lume/lume-run` (ações do runner, pausa, menu do Lume, barra), `lume/lume-core` (protocolo,
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
