# Design

## Context

Motivação em `proposal.md`; requisitos em `specs/game-actions`, `specs/performance-hud` e nos
deltas de `game-runners` e `frontend-session`.

Estado atual que o desenho reaproveita:

- **`lume-input`** (`aports/lume-input/input.c`) captura os controles (EVIOCGRAB), publica o
  controle virtual por uinput e trata o Fn como acorde (`key_event`, linhas 743-792): o Fn
  sozinho vira um toque (o `input_menu_toggle_btn = "10"` dos autoconfigs abre o menu do
  RetroArch); Fn+Start manda `quit` aos clientes de `/run/lume/input.sock`; o Fn com outra
  tecla sai junto com ela. Os perfis (`ga36.conf`, `r36s.conf`, `vm.conf`) têm `fn` e `quit`
  em códigos de saída (depois do mapa). Ele já fala com o RetroArch: `LUME_LEVEL` por UDP em
  `127.0.0.1:55355` (patch 0011), que desenha a linha de volume com um widget.
- **`lume-run`** (`lume/lume-run/src/main.rs`) é o supervisor: abre o jogo no cgroup
  `game-<n>`, escuta o socket do `lume-input` no laço do jogo (hoje só `quit`) e executa o
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
  "pausar" sem alternar, mas `GET_STATUS` responde `GET_STATUS PAUSED ...`, `GET_STATUS
  PLAYING ...` ou `GET_STATUS CONTENTLESS` (`command.c:1048-1067`), o que permite pausar e
  despausar sabendo o estado. `screenshot_directory` já aponta para `/storage/screenshots`.
- **Swap**: ZRAM de tamanho fixo (50% da RAM, `lume-power`).
- **Kernel 6.18**: o `lima` informa o tempo ocupado da GPU por cliente no `fdinfo` (desde o
  6.8); o `panfrost` também, mas só com o `profiling` dele ligado no sysfs.

## Goals / Non-Goals

**Goals:**
- Um único caminho para os atalhos do jogo: o `lume-input` só reconhece acordes e dá nome à
  ação; quem sabe o que a ação significa para o programa aberto é o `lume-run`, pelo runner.
- A barra sem processo novo; a barra e o menu do Lume sem custo quando escondidos.
- O menu do Lume como camada do sistema: aparece sobre qualquer aplicação, mesmo travada, e
  permite fechá-la (D14, se a prova da J1 passar).
- O RetroArch só desenha: os números, os itens e o estado do menu vêm do sistema, para um
  frontend futuro trocar só o desenho.

**Non-Goals:**
- Barra dentro do launcher, troca de slot por atalho, níveis de detalhe da barra.
- Barra e dica sobre runners que não sejam o RetroArch (aparecem com o jogo rodando, então
  precisariam de compositor ou de um widget em cada programa).
- Governor, perfis de energia e o custo do `logd` (próxima change).

## Decisions

### D1. Acordes no `lume-input`, ações com nome no socket

O perfil do console ganha uma tabela de acordes, em códigos de saída:

```
fn_hold_ms 500                 # toque abaixo disso, segurar a partir disso (D13)
chord BTN_B      app_menu      # BTN_B do controle virtual (o mapa do R36S já converte)
chord BTN_TR     save_state
chord BTN_TL     load_state
chord BTN_Y      screenshot
chord BTN_X      hud
chord BTN_START  quit          # substitui a linha "quit BTN_START"
```

Regras novas do `key_event`:
- o Fn nunca sai (some o toque no soltar e o `emit_key(out, p->fn, 1)` do acorde); o Fn
  sozinho vira os gestos `fn_tap`, `fn_hold` e `fn_release` aos clientes (D13);
- Fn + tecla da tabela: manda o nome da ação aos clientes e engole a tecla (pressão, repetição
  e soltura), como o `quit` faz hoje;
- Fn + tecla fora da tabela: engole a tecla e não manda nada (acordes reservados);
- Fn + volume continua sendo o brilho.

A linha antiga `quit <código>` continua aceita (vira `chord <código> quit`), para perfis do
cartão de versões anteriores. O `vm.conf` usa as teclas do teclado da VM (`fn KEY_F1`, com
`chord KEY_ENTER quit` e as outras ações em teclas livres).

*Alternativa descartada:* o `lume-input` conhecer os runners e mandar comandos direto ao
RetroArch. Juntaria entrada e política do jogo num daemon em C que roda como root; o
`lume-run` já tem o runner, o pid e o fim do jogo.

### D2. Protocolo do socket nos dois sentidos

Hoje o socket só vai do daemon aos clientes (`quit`, `volume`, `brightness`). Fica assim,
uma mensagem por linha:

| Sentido | Mensagem | Quem usa |
|---|---|---|
| daemon → cliente | `quit`, `app_menu`, `save_state`, `load_state`, `screenshot`, `hud` | `lume-run` (o `lume-ui` ignora) |
| daemon → cliente | `volume`, `brightness` | `lume-ui` (sem mudança) |
| daemon → cliente | `fn_tap`, `fn_hold <tabela>`, `fn_release` (D13) | `lume-run` no jogo; o `lume-ui` no launcher, na change de ajustes do launcher (P-74) |
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
pause      = "retroarch-pause"   # GET_STATUS + PAUSE_TOGGLE (D10)
app_menu   = "retroarch-cmd:MENU_TOGGLE"
reset      = "retroarch-cmd:RESET"
save_state = "retroarch-cmd:SAVE_STATE"
load_state = "retroarch-cmd:LOAD_STATE"
screenshot = "retroarch-cmd:SCREENSHOT"
```

Formas aceitas: `retroarch-cmd:<COMANDO>` (UDP em `127.0.0.1:55355`), `key:<KEY_*>` (o
`lume-run` pede `tap` ao `lume-input`) e `signal:<NOME>` (ao grupo do jogo). A ação `pause`
aceita também `retroarch-pause` (pausa pelo próprio RetroArch, D10); sem `pause` declarada, o
sistema pausa congelando o grupo do jogo (`SIGSTOP`/`SIGCONT`). `quit` continua
no campo `quit` (política de encerramento com prazo, que já é spec). `overlay` aceita só
`retroarch` nesta versão; sem ele, `fn_hold` e `hud` são ignorados com uma linha no log (o menu
do Lume é do sistema, D14, e não depende do `overlay`). Um
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
(ligada ou não) fica em `/run/lume/hud`, lido no início de cada jogo; o boot começa sem o
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
  medidas do protótipo (D10). **Só existe se a prova do D14 falhar**; se ela passar, o menu é
  desenhado pelo sistema e este comando não entra no patch. O widget não pausa nada: a pausa é
  do `lume-run` (D10). Sem atualização em 3 s, some.

- `LUME_HINT [linha1|linha2|...]` (vazio esconde): a dica dos acordes (D13), um painel com
  uma linha por acorde (`Fn+R1  Salvar estado`), sem pausar o jogo. Sem atualização em 3 s,
  some sozinha.

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
 fechado --toque Fn--> lista --A em Reiniciar/Encerrar--> confirmação (foco em Não)
    ^                    |  |                                 |      |
    |<--B ou toque Fn----+  +--A em Voltar ao jogo-----> fechado    |
    |<--A em Menu do RetroArch: fecha e manda app_menu              |
    |<--Sim: reset (volta ao jogo) ou quit educado; Não/B: lista <--+
```

**Pausa e retomada** (pedido do usuário, 2026-11-17: pausar pelo recurso do próprio
RetroArch, que vale para qualquer core, e despausar ao voltar):

```
 toque no Fn --> pause do runner
                  retroarch-pause: GET_STATUS (espera ate 1 s)
                    PLAYING --> PAUSE_TOGGLE, guarda "eu pausei"
                    PAUSED  --> nada, guarda "ja estava"
                    sem resposta --> app sem resposta: SIGSTOP no grupo, menu com
                                     "Forcar fechamento" (D14)
                  sem pause declarada: SIGSTOP no grupo, guarda "eu pausei"

 Voltar ao jogo (A, B ou toque) --> "eu pausei": PAUSE_TOGGLE (ou SIGCONT)
                                    "ja estava": nada
 Encerrar / Reiniciar          --> despausa antes de mandar QUIT/RESET, para o
                                    RetroArch processar o comando
```

Depois do `PAUSE_TOGGLE`, o `lume-run` confere com outro `GET_STATUS` que o estado mudou; se
não mudou, registra no log e segue (o menu abre mesmo assim). "Forçar fechamento" manda
`SIGKILL` ao grupo do jogo, sem esperar o prazo do runner, e só aparece com o app sem
resposta; com o app respondendo, o menu tem o "Encerrar jogo" educado de sempre.

A cada mudança o `lume-run` atualiza o desenho do menu (D14, ou `LUME_MENU` no caminho de
reserva), e durante a captura renova a cada 1 s (o mesmo prazo do `poll` da barra). Os textos ficam no `lume-core`, em en, pt
e es, com o idioma lido como o `lume-ui` lê; o item "Menu do <aplicação>" usa o nome do runner.
Os gestos do Fn continuam valendo com o menu aberto: Fn+Start encerra direto, o toque fecha
o menu de qualquer estado (lista ou confirmação). Segurar o Fn com o menu aberto não mostra a
dica (o menu já está na tela).

O visual é uma tela nova do Lume: entra primeiro no protótipo
(`docs/lume-launcher/prototipo/`), na família do menu do jogo do launcher, aprovada pelo
usuário, e as medidas a 640x480 viram as constantes do widget (regra da régua). A prova
compara uma captura do aparelho com o protótipo.

*Alternativa descartada:* voltar ao `lume-ui` para mostrar o menu. Encerraria ou congelaria o
jogo, e o `lume-ui` não pode abrir a tela enquanto o RetroArch é o dono do DRM (o D14 resolve
isso pegando a tela emprestada, sem fechar o jogo).

### D11. Captura do controle

`capture on` faz o `lume-input` soltar no controle virtual toda tecla que esteja apertada
(para nada ficar preso no jogo), parar de encaminhar os eventos ao uinput e mandar `nav ...`
ao cliente que pediu. `capture off`, ou o fim da conexão desse cliente, ou 2 s sem nenhuma
mensagem dele, encerra a captura e volta a encaminhar. O `lume-run` manda `capture on` de novo
a cada 1 s enquanto o menu está aberto. O acorde do Fn continua sendo tratado antes da
captura, então Fn+Start e o toque no Fn funcionam com o menu aberto.

### D12. Foto do jogo

`screenshot` é uma ação do runner como as outras; no RetroArch, `SCREENSHOT` com as chaves do
D9. A pasta é `ROMS/screenshots/`, legível no PC. Isso atende o P-57 para o RetroArch; uma
captura do sistema para qualquer programa (ler o framebuffer do DRM) continua no P-57.

### D13. Gestos do Fn, à moda do botão Steam

Pedido do usuário (2026-11-17): o Fn se comporta como o botão Steam do SteamOS (e o Xbox/PS
nos controles): toque abre o menu, segurar mostra os atalhos, segurar + botão é atalho. O
`lume-input` decide o gesto; os clientes só reagem.

```
  Fn down --+-- outra tecla antes de soltar ----> acorde (ação da tabela ou reservado);
            |                                      se a dica estava na tela: fn_release antes
            |
            +-- solto antes de fn_hold_ms -------> fn_tap
            |
            +-- fn_hold_ms sem outra tecla -------> fn_hold <tabela>
                     +-- solto sem outra tecla ---> fn_release (sem fn_tap)
```

- Um Fn que já foi parte de um acorde nunca gera `fn_tap` nem `fn_hold` até ser solto.
- `fn_hold` leva a tabela de acordes do perfil, `fn_hold B=app_menu R1=save_state ...`
  (nomes curtos dos botões, os do glifo da tela), para a dica não ter uma segunda cópia da
  tabela. O Fn+Vol (brilho) entra na tabela como `Vol=brightness`.
- O temporizador do segurar entra no `poll` do daemon (prazo só enquanto o Fn está apertado);
  sem o Fn apertado, o daemon continua sem prazo.
- **No jogo** (`lume-run`): `fn_tap` abre ou fecha o menu do Lume (D10); `fn_hold` monta a
  dica só com as ações que o runner declara, mais Fn+Start, com os nomes no idioma do usuário,
  e manda `LUME_HINT` (renovado a cada 1 s enquanto o Fn estiver seguro); `fn_release`, ou
  qualquer ação de acorde, manda `LUME_HINT` vazio. Com o menu do Lume aberto, `fn_hold` é
  ignorado. Runner sem `overlay`: `fn_tap` e `fn_hold` só registram no log.
- **No launcher** (`lume-ui`): os mesmos eventos chegam, e esta change não os usa (o
  `lume-ui` os ignora). O menu do sistema e a dica do launcher são da change de ajustes do
  launcher (P-74, P-72).

*Alternativas descartadas (D13):* manter o Fn sozinho sem função e o menu no Fn+Select (decisão
anterior, trocada pelo usuário pelo modelo do SteamOS); segurar o Fn para o menu de energia,
como o Xbox (Desligar fica dentro do menu do sistema, como no SteamOS); decidir o gesto no
`lume-run` (o daemon é o único que vê o tempo real das teclas, e o launcher precisa do mesmo
gesto).

### D14. Menu do Lume desenhado pelo sistema (condicionado à prova da J1)

Pedido do usuário (2026-11-17): como sistema operacional, o menu do Lume tem que aparecer
sobre o RetroArch mesmo com ele travado, com a opção de fechar a aplicação. Um widget do
RetroArch não cumpre isso (quem desenha é quem travou) e não existe nos outros runners.

Sem compositor, a aplicação é a dona do DRM (master) enquanto roda. O sistema pega a tela
emprestada só com o menu aberto:

```
 abrir:  pausa (D10) --> SIGSTOP no grupo do jogo (o RetroArch pausado ainda apresenta
         quadros e cobriria o menu) --> pidfd_getfd do fd do DRM da aplicação (o mesmo
         arquivo aberto, portanto master) --> GETFB2 do plano primário (o último quadro,
         fundo do menu, técnica do lume-shot) --> buffer próprio com o quadro + o menu
         desenhado em software --> commit atômico no plano primário
 fechar: commit devolvendo o framebuffer e o estado originais do plano --> fecha o fd
         duplicado --> SIGCONT --> despausa (D10)
```

- Custo zero com o menu fechado: nada roda nem fica aberto.
- Vale para qualquer runner (RetroArch, LÖVE, Ports, standalone), travado ou não; o
  `overlay` do runner deixa de decidir se o menu existe e passa a valer só para a barra e a
  dica (que aparecem com o jogo rodando e continuam como widgets do RetroArch).
- Quem desenha: um binário pequeno (`lume-menu`, Rust, sem SDL, texto com a fonte do tema
  rasterizada em software), aberto pelo `lume-run` só enquanto o menu está na tela, para o
  `lume-run` continuar abaixo de 2 MB. O requisito "só três processos durante o jogo" passa a
  admitir esse processo com o jogo pausado.
- Permissão: `pidfd_getfd` exige `PTRACE_MODE_ATTACH` sobre a aplicação; o `lume-run` é o pai
  e roda com o mesmo usuário. Conferir o Yama (`ptrace_scope`) do kernel; se precisar, o
  helper ganha só `CAP_SYS_PTRACE` por `setcap`.
- Commit recusado (`EBUSY` de um page flip pendente da aplicação): tenta de novo por até
  200 ms antes de desistir.

**Prova na J1 (tarefa 4.6), antes do código:** no GA36 (`sun4i-drm`/`lima`) e no R36S
(`rockchip`/`panfrost`), com um jogo do RetroArch e um Port abertos: pausa, `SIGSTOP`,
`pidfd_getfd`, um retângulo com o último quadro de fundo, volta ao jogo sem tela preta nem
quadro trocado; e com o RetroArch travado de propósito (`SIGSTOP` sem pausa). **Se passar**,
o D14 vale e o `LUME_MENU` sai do patch (D8). **Se falhar**, fica o caminho de reserva: o
menu pelo widget `LUME_MENU`, só no RetroArch respondendo, e o app travado só se fecha pelo
Fn+Start (que já força o fim no prazo do runner); os specs são revistos com o resultado.

*Alternativas descartadas:* um compositor do Lume com o jogo como cliente (custo em todo
quadro, pesado para o Mali-400 do GA36); `DROP_MASTER`/`SET_MASTER` (só quem é master pode
largar, e uma aplicação travada não larga); lease do DRM (exige a aplicação colaborar).

## Risks / Trade-offs

- [O menu do RetroArch fica sem botão próprio: se o `lume-run` ou o socket falhar, ele não
  abre no jogo] → O Fn+Start depende do mesmo caminho e já é o padrão; o `lume-run` registra
  no log quando o daemon de entrada some, e o self-test do aparelho confere o socket.
- [Captura presa deixa o console sem controle] → Liberação pelo fim da conexão e pelo prazo
  de 2 s sem mensagem (D11); teste de unidade dos três casos; prova na J2 matando o `lume-run`
  com o menu aberto.
- [Pegar a tela da aplicação falha num dos consoles (permissão, `EBUSY`, plano com formato ou
  rotação diferentes)] → Prova da J1 (4.6) antes de qualquer código do D14; caminho de
  reserva pelo widget (D8).
- [A GPU pendura dentro do kernel e nem o `SIGSTOP` nem o commit andam] → O menu não aparece;
  o Fn+Start continua forçando o fim pelo `SIGKILL` no prazo do runner, e o `lume-run`
  registra no log.
- [`PAUSE_TOGGLE` desencontrado deixa o jogo pausado ao voltar] → O `lume-run` guarda se foi
  ele quem pausou e confere com `GET_STATUS` depois de cada alternância; teste de unidade com
  o RetroArch falso nos casos PLAYING, PAUSED e sem resposta.
- [`panfrost` sem `fdinfo` útil sem o `profiling`] → O `lume-run` liga o `profiling` ao
  mostrar a barra e desliga ao esconder, se o sysfs existir; sem leitura, `GPU --`. A prova da
  J1 vem antes do código da GPU.
- [O `lume-run` não roda como root e não grava no sysfs do `panfrost`] → Regra do udev para o
  grupo `video`, como a da luz da tela (`90-lume-backlight.rules`); senão, `GPU --` no R36S.
- [Fn+L1 sem querer carrega por cima do progresso] → O RetroArch guarda o "desfazer
  carregamento" no menu rápido; documentar no guia.
- [Usuários acostumados ao Fn sozinho para o menu do RetroArch] → O toque continua abrindo
  um menu (o do Lume, que tem o item "Menu do RetroArch"); mudança documentada no guia, e o
  spec removido explica a migração.
- [Toque e segurar confundidos: 500 ms curto ou longo demais] → `fn_hold_ms` no perfil,
  ajustado na J2 com o usuário; o toque é decidido no soltar, então segurar mais nunca abre o
  menu por engano.
- [Acorde desistido vira toque] → Um Fn que tocou outra tecla nunca gera `fn_tap` (teste de
  unidade do daemon).
- [O RSS do `lume-run` passa de 2 MB com a barra e o menu] → Leituras em buffers fixos, textos
  estáticos; medir o RSS com os dois ligados.
- [O texto da barra não cabe em 640 px] → Medir no aparelho; se preciso, cortar o clock da CPU
  primeiro.
- [Foto do jogo sem o shader] → `video_gpu_screenshot = "false"` grava a imagem do core, sem
  shader, para não levar a barra e o menu; aceitável nesta versão.
- [Runners fora do RetroArch sem menu do Lume, se a prova do D14 falhar] → Limite declarado
  no spec revisto; Fn+Start continua encerrando qualquer programa.

## Migration Plan

1. Os perfis do console aceitam `quit` e `chord`; os da imagem passam a `chord`.
2. Um cartão com runners antigos continua funcionando (sem ações: os acordes não fazem nada
   neles, menos o Fn+Start).
3. As chaves do RetroArch são reaplicadas a cada início pelo script do frontend; voltar à
   versão anterior pelo `push` restaura o comportamento antigo.

## Notas da implementação (2026-11-17)

- **Estado da barra:** `$XDG_RUNTIME_DIR/lume/hud` no lugar de `/run/lume/hud`. O
  `/run/lume` é do root e o `lume-run` roda como `game`; a pasta de runtime também é apagada no
  boot, então o efeito do D6 é o mesmo (começa escondida, vale entre jogos).
- **Ordem da 4.5:** o widget `LUME_MENU` (caminho de reserva) entrou já no patch 0012, antes da
  prova da 4.6, para o menu poder ser visto e avaliado na vm. Se a 4.6 passar, o `lume-menu`
  (3.4) desenha o menu e o `LUME_MENU` sai do patch, como o D8 pede. Até lá, o toque no Fn num
  runner sem `overlay` só registra no log.
- **Esconder um widget:** o `lume-run` manda `LUME_HUD -` (e `LUME_HINT -`, `LUME_MENU -`). Um
  comando sem argumento faz o RetroArch 1.22.2 apontar o argumento para depois do fim da string
  (`command_get_arg`), então o "vazio" do D8 virou `-`.
- **Teclas do `tap`:** o controle virtual declara as teclas `KEY_*` da tabela do daemon, menos
  `KEY_UP`..`KEY_DOWN`: o driver udev de joypad do RetroArch numera essa faixa antes de
  `BTN_MISC`, e declarar as setas deslocaria todos os índices dos autoconfigs.
- **Frontend de reserva:** sem `lume-run` (`FRONTEND="retroarch"`), nada abriria o menu do
  RetroArch dentro de um jogo depois do D9; o script do frontend devolve `input_menu_toggle_gamepad_combo = "4"`
  quando `LUME_LAUNCHER` não está definido.
- **Pausa:** o RetroArch alterna a pausa no quadro seguinte; a conferência depois do
  `PAUSE_TOGGLE` tenta 5 vezes, com 40 ms entre elas, antes de registrar o aviso.
- **Cores do widget:** os tokens do tema padrão da imagem (`themes/base.toml`): `panel_bg`,
  `accent`/`sel_bg`, `accent_fg`/`sel_fg`, `fg`, `muted`, `overlay`. As fontes são as dos
  widgets do RetroArch (menores que as do protótipo a 640x480: título ~16 px contra 22,4 px,
  itens ~16 px contra 20 px), a decidir na aprovação da 1.3.
- **Barra para achar o gargalo (usuário, 2026-11-17; além do escopo do D6, aceito por ele):**
  `FPS 59.7 │ CPU 47% 1008 │ GPU 62% 38M │ MEM 124/492 │ BAT ...`. O FPS vem do contador de
  quadros do `GET_STATUS` (patch 0004) a cada segundo; o uso e a memória da GPU vêm do `fdinfo`
  do arquivo DRM do jogo, que no GA36 exigiu o patch 0035 do kernel (`lima`: `drm-engine-gp/pp`
  e `drm-*-memory`). Letra da barra 15% menor (`LUME_HUD_SCALE`) para caber numa linha a
  640x480, medido no GA36 com o pior caso. O uso desses sinais pelo governor (subir só a CPU ou
  só a GPU) ficou no P-20.

## Resultados da J1 no GA36 (2026-11-17; o R36S ainda falta)

- **D14 (4.6):** passou no GA36 nos três casos (RetroArch, RetroArch travado, LÖVE), como
  `game`, sem `CAP_SYS_PTRACE` (não há Yama); 79 ms a 1,1 s até o menu. Se o R36S também
  passar, o `lume-menu` (3.4) desenha o menu e o `LUME_MENU` sai do patch 0012. Regra para o
  `lume-menu`: liberar no fd da aplicação tudo o que criar (`RMFB`, `DESTROY_DUMB`,
  `GEM_CLOSE` do handle do `GETFB2`), ou a CMA acaba (visto na terceira rodada).
- **D6/D7, GPU no GA36:** o `lima` do kernel 6.18 não publica `drm-engine-*` no `fdinfo`; o
  campo de uso da GPU não tem fonte por cliente. O devfreq dá o clock atual (144/240/384 MHz)
  e o tempo em cada clock; o `load` vem vazio. **A decidir com o usuário:** `GPU 240MHz` (só o
  clock) ou `GPU --` no GA36.
- **D7, bateria do GA36 (AXP223):** `current_now` negativo descarregando e positivo carregando
  (o `status` decide, como previsto); sem `charge_now` nem `charge_full`, com
  `charge_full_design` (3000 mAh). Ramo: a estimativa pela queda da `capacity` (o que o
  `hud.rs` faz sem `charge_full`); usar o `charge_full_design` daria tempo desde os primeiros
  30 s, com o erro do desgaste da bateria. Detalhes no `docs/BRINGUP-GA36.md`.

## Open Questions

- Largura real do texto da barra na fonte dos widgets a 640x480: decide só a ordem de corte.
- `current_now` e `charge_full` no AXP223 e no RK817: decide qual ramo do D7 cada console usa.
- Toque no Fn com o menu do RetroArch aberto (pelo Fn+B): abrir o menu do Lume por cima ou
  fechar o do RetroArch. Decidir na J2.
- Resultado da prova do D14 (J1, tarefa 4.6): decide se o menu é desenhado pelo sistema ou
  pelo widget de reserva.

## Revisão do D14 pela device-fixes 9.14 (2026-11-18)

O log do GA36 (boot 193, um jogo LÖVE) mostrou três falhas do desenho pelo sistema; a 9.14
muda a forma do `lume-menu`, não a decisão do D14:

- **`our buffer: Out of memory`:** o `lume-menu` criava os buffers a cada abertura, no arquivo
  DRM do jogo, numa CMA de 16 MiB (o padrão do Kconfig; o motor de vídeo do A33 não tem
  IOMMU) já cheia pelo jogo. Agora a CMA do GA36 tem 64 MiB (`CONFIG_CMA_SIZE_MBYTES` no
  fragmento do kernel) e o `lume-menu --serve PGID` nasce com o jogo, cria **uma vez** os
  buffers (dois de tela cheia para o menu, também usados pela dica; duas faixas para a
  barra) num arquivo DRM **próprio**, não mestre, e reaproveita. Depois disso fica parado na
  leitura do stdin: nada roda com o menu, a barra e a dica fechados. O R36S não precisa: o
  VOP tem IOMMU e o defconfig do arm64 já reserva 32 MiB.
- **`bar not shown: Permission denied`:** o `--hud` guardava a cópia (`pidfd_getfd`) de um
  arquivo do jogo que deixou de ser o mestre (hipótese, não medida: o SDL larga o mestre e
  reabre o card quando o LÖVE recria a janela); todo `SETPLANE` dava `EACCES`, que no
  `drm_ioctl` só vem da falta de mestre. Agora cada operação pega o arquivo mestre atual do
  jogo (conferido com `AUTH_MAGIC`, que só o mestre pode chamar) e o fecha logo depois. Nenhum
  privilégio novo: o `game` já está no grupo `video` e o `pidfd_getfd` do mesmo usuário passa
  sem Yama (J1).
- **`plane 45: Invalid argument`:** o `sun4i_backend_atomic_check` aceita no máximo dois
  planos com alfa no A33; o SDL do LÖVE já põe ARGB8888 no plano primário, então a barra e a
  dica juntas passavam do limite. A escolha do plano tenta primeiro todos os planos livres em
  ARGB8888 e depois os mesmos em XRGB8888 (opaco, sem alfa); o motivo de cada recusa vai para
  o log.
- **Toque:** o grupo para na hora (`SIGSTOP`, ou a pausa do RetroArch e depois o `SIGSTOP`), o
  `lume-run` manda `menu ...` ao processo que já está pronto e espera o `menu ok`, que sai
  depois do primeiro quadro (o fade continua depois). O `--hud`, o `--hint` e o `lume-menu
  PGID` de uma vez saíram; o `--shot` continua um processo curto.
