# Design

## Context

Motivação em `proposal.md`; requisitos em `specs/game-actions`, `specs/performance-hud` e nos
deltas de `game-runners` e `frontend-session`.

Estado atual que o desenho reaproveita:

- **`r36os-input`** (`aports/r36os-input/input.c`) captura os controles (EVIOCGRAB), publica o
  controle virtual por uinput e trata o Fn como acorde (`key_event`, linhas 743-792): o Fn
  sozinho vira um toque (o `input_menu_toggle_btn = "10"` dos autoconfigs abre o menu do
  RetroArch); Fn+Start manda `quit` aos clientes de `/run/r36os/input.sock`; o Fn com outra
  tecla sai junto com ela. Os perfis (`ga36.conf`, `r36s.conf`, `vm.conf`) têm `fn` e `quit`
  em códigos de saída (depois do mapa). Ele já fala com o RetroArch: `LUME_LEVEL` por UDP em
  `127.0.0.1:55355` (patch 0011), que desenha a linha de volume com um widget.
- **`lume-run`** (`lume/lume-run/src/main.rs`) é o supervisor: abre o jogo no cgroup
  `game-<n>`, escuta o socket do `r36os-input` no laço do jogo (hoje só `quit`) e executa o
  `quit` pela política do runner (`polite_quit`: `QUIT` por UDP ou SIGTERM). A política vem do
  arquivo de lançamento (`launch.rs`), que a interface escreve a partir do runner
  (`lume-core/src/runner.rs`, `runners.d/*.toml`).
- **Spec `game-runners`**: durante o jogo só podem existir o jogo, o supervisor (menos de 2 MB
  de RSS) e o daemon de entrada. Um processo novo para a barra ou para o menu violaria esse
  requisito.
- **Tela**: com o jogo aberto, o dono do KMS/DRM é o programa do jogo. Sem compositor, o Lume
  só aparece sobre o jogo se o próprio programa desenhar por ele: no RetroArch, um widget.
- **Foto do save state**: o `lume-ui` já mostra `<estado>.png` no menu do jogo; a captura está
  ligada só na configuração de fábrica (`factory/retroarch/retroarch.cfg:47`), que só vai para
  cartões novos (P-04).
- **RetroArch 1.22.2**: comandos de rede `MENU_TOGGLE`, `RESET`, `SAVE_STATE`, `LOAD_STATE`,
  `LOAD_STATE_SLOT <n>`, `SCREENSHOT`, `PAUSE_TOGGLE` e `QUIT`; não há "salvar num slot" nem
  "pausar" sem alternar. `screenshot_directory` já aponta para `/storage/screenshots`.
- **Swap**: ZRAM de tamanho fixo (50% da RAM, `lume-power`).
- **Kernel 6.18**: o `lima` informa o tempo ocupado da GPU por cliente no `fdinfo` (desde o
  6.8); o `panfrost` também, mas só com o `profiling` dele ligado no sysfs.

## Goals / Non-Goals

**Goals:**
- Um único caminho para os atalhos do jogo: o `r36os-input` só reconhece acordes e dá nome à
  ação; quem sabe o que a ação significa para o programa aberto é o `lume-run`, pelo runner.
- A barra e o menu do Lume sem processo novo e sem custo quando escondidos.
- O RetroArch só desenha: os números, os itens e o estado do menu vêm do sistema, para um
  frontend futuro trocar só o desenho.

**Non-Goals:**
- Barra dentro do launcher, troca de slot por atalho, níveis de detalhe da barra.
- Menu do Lume sobre runners que não sejam o RetroArch (precisa de compositor ou frontend
  próprio).
- Governor, perfis de energia e o custo do `logd` (próxima change).

## Decisions

### D1. Acordes no `r36os-input`, ações com nome no socket

O perfil do console ganha uma tabela de acordes, em códigos de saída:

```
chord BTN_SELECT lume_menu
chord BTN_B      app_menu      # BTN_B do controle virtual (o mapa do R36S já converte)
chord BTN_TR     save_state
chord BTN_TL     load_state
chord BTN_Y      screenshot
chord BTN_X      hud
chord BTN_START  quit          # substitui a linha "quit BTN_START"
```

Regras novas do `key_event`:
- o Fn nunca sai (some o toque no soltar e o `emit_key(out, p->fn, 1)` do acorde); o Fn
  sozinho vira só a mensagem `fn` aos clientes, que nesta change ninguém usa (o `lume-run` a
  ignora) e que deixa pronto o menu do sistema no launcher do P-74;
- Fn + tecla da tabela: manda o nome da ação aos clientes e engole a tecla (pressão, repetição
  e soltura), como o `quit` faz hoje;
- Fn + tecla fora da tabela: engole a tecla e não manda nada (acordes reservados);
- Fn + volume continua sendo o brilho.

A linha antiga `quit <código>` continua aceita (vira `chord <código> quit`), para perfis do
cartão de versões anteriores. O `vm.conf` usa as teclas do teclado da VM (`fn KEY_F1`, com
`chord KEY_ENTER quit` e as outras ações em teclas livres).

*Alternativa descartada:* o `r36os-input` conhecer os runners e mandar comandos direto ao
RetroArch. Juntaria entrada e política do jogo num daemon em C que roda como root; o
`lume-run` já tem o runner, o pid e o fim do jogo.

### D2. Protocolo do socket nos dois sentidos

Hoje o socket só vai do daemon aos clientes (`quit`, `volume`, `brightness`). Fica assim,
uma mensagem por linha:

| Sentido | Mensagem | Quem usa |
|---|---|---|
| daemon → cliente | `quit`, `lume_menu`, `app_menu`, `save_state`, `load_state`, `screenshot`, `hud` | `lume-run` (o `lume-ui` ignora) |
| daemon → cliente | `volume`, `brightness` | `lume-ui` (sem mudança) |
| daemon → cliente | `fn` (Fn sozinho) | ninguém nesta change; o `lume-ui` no P-74 |
| daemon → cliente | `nav up\|down\|left\|right\|a\|b` | `lume-run`, só com a captura ligada (D11) |
| cliente → daemon | `tap <KEY_*>` | `lume-run`, para a ação por tecla (D3) |
| cliente → daemon | `capture on`, `capture off` | `lume-run`, menu do Lume (D11) |

O `tap` aceita só códigos de tecla do teclado (`KEY_*`), que o controle virtual passa a
declarar; o daemon emite pressão e soltura com 50 ms entre elas. O protocolo é congelado por
um nó próprio com testes de leitura e escrita dos dois lados (C e Rust) antes dos
consumidores.

### D3. Ações declaradas no runner

`runners.d/*.toml` ganha uma tabela opcional e um campo:

```toml
[runner]
overlay = "retroarch"            # sabe desenhar a barra e o menu do Lume

[runner.actions]
app_menu   = "retroarch-cmd:MENU_TOGGLE"
reset      = "retroarch-cmd:RESET"
save_state = "retroarch-cmd:SAVE_STATE"
load_state = "retroarch-cmd:LOAD_STATE"
screenshot = "retroarch-cmd:SCREENSHOT"
```

Formas aceitas: `retroarch-cmd:<COMANDO>` (UDP em `127.0.0.1:55355`), `key:<KEY_*>` (o
`lume-run` pede `tap` ao `r36os-input`) e `signal:<NOME>` (ao grupo do jogo). `quit` continua
no campo `quit` (política de encerramento com prazo, que já é spec). `overlay` aceita só
`retroarch` nesta versão; sem ele, `lume_menu` e `hud` são ignorados com uma linha no log. Um
valor inválido recusa o runner com a mensagem do erro.

O arquivo de lançamento leva as ações resolvidas, uma por linha (`action=save_state
retroarch-cmd:SAVE_STATE`) e `overlay=retroarch`. Chaves desconhecidas já são ignoradas pelo
`launch.rs`, então um `lume-run` antigo com uma interface nova não quebra.

O `retroarch.toml` declara tudo. O `love.toml` e o `sh.toml` não declaram nada.

### D4. Slot rápido

O `SAVE_STATE` grava no slot atual da sessão do RetroArch. O launcher já abre um slot com `-e
N`, que torna N o slot atual. Aberto pela grade, o launcher passa `--lume-set state_slot=0`
(vale só para essa execução), para o slot rápido ser 0 mesmo que o usuário tenha mudado o slot
no menu antes. Aberto pelo estado automático, o slot rápido também é 0.

*Alternativa descartada:* um patch com `SAVE_STATE_SLOT <n>` para gravar sempre no 0. Seria
um patch a mais, e o jogo aberto pelo slot 3 gravaria no 0, longe do estado que o usuário
escolheu continuar.

### D5. Foto do save state fixada pelo Lume

`savestate_thumbnail_enable = "true"` entra no `retroarch-lume.cfg` (as chaves fixas que o
script do frontend aplica antes de cada execução), além da configuração de fábrica.

### D6. A barra mora no `lume-run`

O `lume-run` recebe `hud` no laço do jogo (o mesmo `poll`). Com a barra ligada, o `poll` ganha
prazo de 1 s; a cada volta ele lê os números, monta o texto e manda `LUME_HUD <texto>` ao
RetroArch. Desligada, manda `LUME_HUD` vazio e o `poll` volta a esperar sem prazo. O estado
(ligada ou não) fica em `/run/r36os/hud`, lido no início de cada jogo; o boot começa sem o
arquivo, ou seja, escondida.

Fontes, só leitura de arquivos pequenos:

| Campo | Fonte |
|---|---|
| CPU % | diferença do `/proc/stat` (linha `cpu`) entre duas leituras |
| clock | `scaling_cur_freq` da policy0 (um cluster nos dois SoCs) |
| GPU % | diferença dos tempos `drm-engine-*` no `/proc/<pid>/fdinfo/<fd>` do jogo, pelo tempo decorrido; o fd do DRM é achado uma vez por jogo |
| MEM | `MemTotal - MemAvailable`, `MemTotal`, `SwapTotal - SwapFree` do `/proc/meminfo` |
| bateria | `capacity`, `status`, `voltage_now`, `current_now` e, se houver, `charge_full`/`charge_now` da fonte de tipo `Battery` em `/sys/class/power_supply` |

Texto, neutro de idioma: `CPU 47% 1008MHz  GPU 62%  MEM 124/1006/200  BAT 74% 1.9W 2:40`, com
`--` no valor ausente e `--:--` sem estimativa; carregando, `BAT 74% +` e o tempo até encher.

*Alternativas descartadas:* um daemon `lume-hud` (viola o requisito de processos durante o
jogo e soma memória); o `logd` (amostra de 5 s, e já custa ~30% de um núcleo no GA36, P-60);
o próprio RetroArch coletar (prende a barra ao RetroArch).

### D7. Estimativa da bateria

A potência é `|V × I|`. O tempo restante usa a corrente média móvel (cerca de 60 s): `carga
restante / corrente média`, com a carga restante de `charge_now`, ou de `capacity × charge_full`
quando só houver a porcentagem. Sem `charge_full`, usa a queda da `capacity` nos últimos
minutos. Até haver 30 s de amostras, mostra `--:--`. O sinal da `current_now` muda entre
drivers (AXP223 e RK817); o `status` decide se está carregando. A média vive só enquanto o
`lume-run` roda, então recomeça a cada jogo.

A média da corrente mede o consumo sem esperar a porcentagem mudar de 1 em 1, o que levaria
minutos e não cumpriria os 30 s do spec.

### D8. Widgets no RetroArch (um patch novo)

Patch numerado no `aports/retroarch`, no molde do 0011, com dois comandos de rede:

- `LUME_HUD [texto]`: faixa no topo com fundo semitransparente e o texto, sem mudar o
  viewport do jogo; some sozinha se não receber texto em 3 s, para a barra não congelar na
  tela se o `lume-run` morrer.
- `LUME_MENU [título|item1|item2|...|foco]` (vazio esconde): o menu do Lume, desenhado com as
  medidas do protótipo (D10). Enquanto visível, o widget **pausa** o jogo e o som pelo mesmo
  caminho da pausa do RetroArch, lembrando se o jogo já estava pausado, e ao esconder volta ao
  estado anterior. Sem atualização em 3 s, também some e devolve o jogo.

O RetroArch não interpreta os itens: só desenha o que recebe. Só funciona com os widgets
gráficos ligados, como a linha de volume.

### D9. Configuração do RetroArch

- `input_menu_toggle_gamepad_combo = "0"`: Start + Select volta a ser do jogo.
- `input_menu_toggle_btn` sai dos autoconfigs `GA36-MB Gamepad.cfg` e `R36S Gamepad.cfg`; o
  menu só abre pelo `MENU_TOGGLE` (Fn+B ou o item do menu do Lume). O "RetroArch" das
  Configurações do launcher (sem jogo) já abre direto no menu e sai por ele.
- Foto do jogo: `video_gpu_screenshot = "false"` (a imagem do core, sem widgets, barra nem
  menu do Lume), `auto_screenshot_filename = "true"` (nome com data e hora, sem sobrescrever)
  e o `screenshot_directory` que já existe.

### D10. Menu do Lume: dono, estados e visual

O `lume-run` é o dono do menu. Estados:

```
 fechado --Fn+Select--> lista --A em Reiniciar/Encerrar--> confirmação (foco em Não)
    ^                    |  |                                 |      |
    |<--B ou Fn+Select---+  +--A em Voltar ao jogo-----> fechado    |
    |<--A em Menu do RetroArch: fecha e manda app_menu              |
    |<--Sim: reset (volta ao jogo) ou quit educado; Não/B: lista <--+
```

A cada mudança o `lume-run` manda o `LUME_MENU` com os textos e o foco, e durante a captura
renova a cada 1 s (o mesmo prazo do `poll` da barra). Os textos ficam no `lume-core`, em en, pt
e es, com o idioma lido como o `lume-ui` lê; o item "Menu do <aplicação>" usa o nome do runner.
Os acordes do jogo continuam valendo com o menu aberto: Fn+Start encerra direto, Fn+Select
fecha.

O visual é uma tela nova do Lume: entra primeiro no protótipo
(`docs/lume-launcher/prototipo/`), na família do menu do jogo do launcher, aprovada pelo
usuário, e as medidas a 640x480 viram as constantes do widget (regra da régua). A prova
compara uma captura do aparelho com o protótipo.

*Alternativa descartada:* voltar ao `lume-ui` para mostrar o menu. Encerraria ou congelaria o
jogo, e o `lume-ui` não pode abrir a tela enquanto o RetroArch é o dono do DRM.

### D11. Captura do controle

`capture on` faz o `r36os-input` soltar no controle virtual toda tecla que esteja apertada
(para nada ficar preso no jogo), parar de encaminhar os eventos ao uinput e mandar `nav ...`
ao cliente que pediu. `capture off`, ou o fim da conexão desse cliente, ou 2 s sem nenhuma
mensagem dele, encerra a captura e volta a encaminhar. O `lume-run` manda `capture on` de novo
a cada 1 s enquanto o menu está aberto. O acorde do Fn continua sendo tratado antes da
captura, então Fn+Start e Fn+Select funcionam com o menu aberto.

### D12. Foto do jogo

`screenshot` é uma ação do runner como as outras; no RetroArch, `SCREENSHOT` com as chaves do
D9. A pasta é `ROMS/screenshots/`, legível no PC. Isso atende o P-57 para o RetroArch; uma
captura do sistema para qualquer programa (ler o framebuffer do DRM) continua no P-57.

## Risks / Trade-offs

- [O menu do RetroArch fica sem botão próprio: se o `lume-run` ou o socket falhar, ele não
  abre no jogo] → O Fn+Start depende do mesmo caminho e já é o padrão; o `lume-run` registra
  no log quando o daemon de entrada some, e o self-test do aparelho confere o socket.
- [Captura presa deixa o console sem controle] → Liberação pelo fim da conexão e pelo prazo
  de 2 s sem mensagem (D11); teste de unidade dos três casos; prova na J2 matando o `lume-run`
  com o menu aberto.
- [O RetroArch pausado pode não redesenhar os widgets] → O widget usa a mesma pausa do menu do
  RetroArch, que redesenha o último quadro; prova na J2. Se falhar, o patch desenha sobre o
  quadro guardado.
- [`panfrost` sem `fdinfo` útil sem o `profiling`] → O `lume-run` liga o `profiling` ao
  mostrar a barra e desliga ao esconder, se o sysfs existir; sem leitura, `GPU --`. A prova da
  J1 vem antes do código da GPU.
- [O `lume-run` não roda como root e não grava no sysfs do `panfrost`] → Regra do udev para o
  grupo `video`, como a da luz da tela (`90-lume-backlight.rules`); senão, `GPU --` no R36S.
- [Fn+L1 sem querer carrega por cima do progresso] → O RetroArch guarda o "desfazer
  carregamento" no menu rápido; documentar no guia.
- [Usuários acostumados ao Fn sozinho para o menu] → Mudança documentada no guia; o spec
  removido explica a migração.
- [O RSS do `lume-run` passa de 2 MB com a barra e o menu] → Leituras em buffers fixos, textos
  estáticos; medir o RSS com os dois ligados.
- [O texto da barra não cabe em 640 px] → Medir no aparelho; se preciso, cortar o clock da CPU
  primeiro.
- [Foto do jogo sem o shader] → `video_gpu_screenshot = "false"` grava a imagem do core, sem
  shader, para não levar a barra e o menu; aceitável nesta versão.
- [Runners fora do RetroArch sem menu do Lume] → Limite declarado no spec; Fn+Start continua
  encerrando qualquer programa.

## Migration Plan

1. Os perfis do console aceitam `quit` e `chord`; os da imagem passam a `chord`.
2. Um cartão com runners antigos continua funcionando (sem ações: os acordes não fazem nada
   neles, menos o Fn+Start).
3. As chaves do RetroArch são reaplicadas a cada início pelo script do frontend; voltar à
   versão anterior pelo `push` restaura o comportamento antigo.

## Open Questions

- Largura real do texto da barra na fonte dos widgets a 640x480: decide só a ordem de corte.
- `current_now` e `charge_full` no AXP223 e no RK817: decide qual ramo do D7 cada console usa.
