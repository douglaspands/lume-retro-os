# lume-launcher: guia do usuário

O lume-launcher é a interface do Lume Retro OS: um Dock de consoles, a grade de jogos com
capas e o menu de cada jogo. Ele abre o jogo no emulador certo e, quando o jogo termina, volta
ao mesmo lugar. Durante o jogo, a interface sai da memória. Planejamento e decisões:
[`docs/lume-launcher/`](lume-launcher/README.md) e a change `lume-launcher`.

## Controles

| Botão | Dock | Grade de jogos | Menus |
|---|---|---|---|
| Direcional | gira o Dock (sem fim) | move o foco | sobe e desce; ‹ › muda o valor |
| A | entra no item | abre o menu do jogo | escolhe |
| B | — | limpa a busca; sem busca, volta ao Dock | fecha |
| X | — | busca por nome (teclado na tela) | — |
| Y | — | opções do console | — |
| L1 / R1 | — | salta uma parte da lista (mais longe se repetir rápido) | — |
| **Fn+Start** | nada | nada | **encerra o jogo aberto e volta ao launcher** |
| Volume + / − | volume do sistema, em qualquer tela e em qualquer jogo | | |
| Fn + Volume + / − | brilho da tela, em passos de 5%, em qualquer tela e em qualquer jogo | | |
| Energia (toque) | suspende o console; outro toque acorda (ver [Suspender](#suspender-e-desligar-pelo-botão-de-energia)) | | |
| Energia (segurar 2 s) | desliga, como o item Desligar | | |

### Atalhos dentro do jogo (o Fn é o botão do sistema)

O Fn funciona como o botão Steam do SteamOS: **tocar** abre o menu do Lume, **segurar** mostra
os atalhos e **segurar + outro botão** faz o atalho. Um atalho nunca vira toque.

| Gesto | O que faz |
|---|---|
| Tocar no Fn | abre e fecha o **menu do Lume** sobre o jogo, com o jogo pausado: Voltar ao jogo, Encerrar jogo, Reiniciar, Menu do RetroArch (Reiniciar e Encerrar pedem confirmação: Sim em cima, Não embaixo e em foco). Com o menu aberto, os botões não chegam ao jogo |
| Segurar o Fn (meio segundo) | mostra a lista dos atalhos que valem neste jogo; soltar a esconde |
| Fn+B | menu do RetroArch (abre e fecha) |
| Fn+R1 / Fn+L1 | salva / carrega o estado no slot rápido (o slot com que o jogo abriu; pela grade, o 0) |
| Fn+Y | foto do jogo em `ROMS/screenshots/`, com data e hora no nome, sem a barra nem os menus |
| Fn+X | mostra e esconde a barra de status no topo (continua ligada no jogo seguinte) |
| Fn+Start | encerra o jogo na hora, também com o menu aberto (saída de emergência) |

Os outros Fn + botão (Fn+A, Fn+Select...) ficam reservados e não fazem nada. Start + Select
voltou a ser do jogo. Se o programa do jogo travar, o toque no Fn mostra "Forçar fechamento".
A barra, a lista de atalhos e o menu aparecem nos jogos do RetroArch; num Port ou num jogo LÖVE,
só Fn+Start vale nesta versão (os outros atalhos só deixam uma linha no log).

A barra, a dica dos acordes e a foto do Fn+Y são do sistema, não do emulador (decisão do
usuário, 2026-11-17): o `lume-menu` desenha a barra (`--hud`) e a dica (`--hint`) num plano de
sobreposição da tela por cima de qualquer jogo, sem pausá-lo, e grava a foto (`--shot`, PNG da
imagem do jogo, sem a barra) em `ROMS/screenshots/`. Cada um só roda enquanto pedido: a barra
enquanto ligada, a dica enquanto o Fn está segurado, a foto uma vez por aperto.

A barra serve para avaliar o desempenho do jogo e achar o gargalo. Ela mostra
`FPS 59.7 │ CPU 47% 1008 │ GPU 62% 38M │ MEM 124/492 sw 20 │ BAT 74% 1.9W 2:40`, espalhada
pela largura da tela numa faixa preta a 92%, com os rótulos na cor de destaque e uma divisória
entre os grupos: quadros por segundo do jogo (as trocas de quadro que o kernel conta para os
arquivos DRM do jogo, `drm-page-flips` no `fdinfo`, patch 0036, a cada segundo), uso (média dos
núcleos) e clock da CPU em MHz, uso
da GPU e a memória que o jogo ocupa nela, em MiB (pelo `fdinfo` do arquivo DRM do jogo; a GPU
não tem memória própria, são buffers na RAM do sistema; no GA36 isso vem do patch 0035 do
kernel, e sem ele aparece o clock da GPU em MHz), memória usada/total e o swap só quando em uso,
em MiB, e bateria (nível, potência e tempo restante;
carregando, `BAT 74% + 0:50`, o tempo até encher). `--` é um valor que o aparelho não informa e
`--:--` aparece nos primeiros 30 s, até haver uma estimativa.

Fora das Configurações, o volume aparece como uma linha na borda direita da tela e o brilho
como uma linha branca na borda esquerda; as duas somem logo depois do último aperto.

A busca ignora maiúsculas e acentos e exige todas as palavras: "super bros" acha "Súper Bros".

**Fn+Start** funciona com qualquer programa aberto pelo launcher: RetroArch, LÖVE, um script de
Ports ou um emulador travado. Primeiro o programa recebe um pedido para sair (o RetroArch grava o
save interno nessa hora); se não sair em alguns segundos, ele e tudo o que abriu são encerrados.

## Suspender e desligar pelo botão de energia

- **Tocar** no botão de energia (soltar antes de 1 s) suspende o console, com o launcher ou
  com um jogo na tela: o jogo pausa, a tela, a luz e o som se apagam. Outro toque acorda o
  console no mesmo ponto, com o mesmo brilho e volume, e **o jogo continua sozinho**. Os
  outros botões não acordam o console, e o que for apertado com ele suspenso é descartado.
- **Segurar** o botão por 2 s desliga, pelo mesmo caminho do item Desligar (grava o pendente
  antes). Segurar por vários segundos continua desligando à força pelo hardware, como reserva.
- O item **Suspender** das Configurações (acima de Desligar) faz o mesmo que o toque, sem
  confirmação.
- Antes de suspender, o que estava pendente de gravação vai para o cartão (`sync`): acabar a
  bateria com o console suspenso não perde o save.
- Se a suspensão falhar, o console volta ao estado de antes com a tela acesa, e o
  `events.log` registra o motivo (`sleep FAIL ...`, ver [`docs/LOGS.md`](LOGS.md#eventslog)).

### Protocolo do sono (para quem programa)

Congelado na change `device-fixes` (D11, tarefa 3.2). Código de referência:
`lume/lume-core/src/sleep.rs` (tipos, leitura e escrita, prazo da resposta, admissão do
pedido) e `lume/lume-core/src/input.rs` (o socket); `aports/lume-input/input.c` e o serviço
`lume-sleep` (pacote `lume-power`, em shell) seguem o mesmo protocolo e mudam junto.

```
 toque no botão (solto antes de 1 s)  lume-input -> pedido   /run/lume/sleep/suspend
                                      lume-input -> clientes power_tap
 botão segurado 2 s                   lume-input -> pedido   /run/lume/sleep/poweroff
                                      lume-input -> clientes power_hold
 item Suspender                       lume-ui    -> pedido   /run/lume/sleep/suspend

 lume-sleep (inotifyd)                grava phase    "suspend <seq>"
 lume-input repassa                   socket         "suspend <seq>"
 cada cliente, já pausado             socket         "suspend_ok <seq>"
 lume-input (todos ou 2 s)            grava clients  "suspend <seq> ok|timeout <a>/<n>"
 lume-sleep: som, hora, sync, luz, Wi-Fi, governor, gadget USB solto, /sys/power/state
 ... o botão de energia acorda ...
 lume-sleep: os mesmos passos na ordem inversa, por último phase "resume <seq>"
 lume-input descarta a entrada acumulada e repassa "resume <seq>"
```

**Socket do `lume-input`** (`/run/lume/input.sock`, `SOCK_SEQPACKET`, uma mensagem por
pacote, sem quebra de linha):

| Mensagem | Sentido | Significado |
|---|---|---|
| `power_tap` | daemon → clientes | o botão foi tocado. Só aviso: o `lume-input` já fez o pedido `suspend`, e o cliente **não** faz outro |
| `power_hold` | daemon → clientes | o botão ficou segurado 2 s (o pedido `poweroff` já foi feito). Só aviso |
| `suspend <seq>` | daemon → clientes | pausar o jogo (`lume-run`, pelo caminho de pausa da `lume-hud-actions`) ou parar de desenhar (`lume-ui`) e então responder |
| `suspend_ok <seq>` | cliente → daemon | pronto para suspender, com o mesmo `<seq>` |
| `resume <seq>` | daemon → clientes | o console voltou: continuar (o jogo continua sozinho; o `lume-ui` redesenha). Sem resposta |

`<seq>` é um inteiro decimal positivo, crescente a cada suspensão desde que o `lume-sleep`
subiu; os lados só comparam igualdade. Uma mensagem com `<seq>` ausente, zero ou com outro
texto não é do protocolo e é ignorada.

**Prazos:**

| Prazo | Valor | Quem espera | Ao estourar |
|---|---|---|---|
| resposta dos clientes | 2 s | `lume-input`, pelo `suspend_ok <seq>` de cada cliente ligado quando o aviso saiu | grava `clients` com `timeout <respondidos>/<total>` e a suspensão segue |
| resposta do `lume-input` | 3 s | `lume-sleep`, pelo `clients` do seu `<seq>` | segue sem ele (`sleep FAIL clients: lume-input did not answer within 3s`) |
| guarda do despertar | 1 s | `lume-sleep` | um `suspend` até 1 s depois de voltar a `awake` é o toque que acordou o console: apagado sem rodar |
| religar o gadget USB | ~1 s | `lume-sleep`, em segundo plano | — (não atrasa a tela) |
| toque / segurar | solto antes de 1 s / 2 s | `lume-input` | — |

Um cliente que se desliga durante a espera deixa de ser esperado. Uma resposta de outro
`<seq>`, uma segunda resposta do mesmo cliente ou de um cliente que não foi avisado não conta.
Sem nenhum cliente ligado, o `clients` sai na hora com `ok 0/0`.

**Pasta `/run/lume/sleep/`** (criada pelo `lume-sleep` ao subir, `root:game`, modo `1770`;
sem ela não há serviço, e o toque só deixa uma linha no log do `lume-input`):

| Arquivo | Quem grava | Conteúdo |
|---|---|---|
| `suspend` | `lume-input` (toque), `lume-ui` (item Suspender) | vazio: o pedido. Criado com `O_EXCL`: se já existe, o pedido está pendente e nada novo é feito |
| `poweroff` | `lume-input` (segurado 2 s) | vazio: o pedido |
| `phase` | `lume-sleep` (root, por `rename`) | `suspend <seq>` ou `resume <seq>`: o aviso ao `lume-input`, que observa a pasta |
| `clients` | `lume-input` (root, por `rename`) | `suspend <seq> ok <n>/<n>` ou `suspend <seq> timeout <a>/<n>` |
| `status` | `lume-sleep` (root, por `rename`) | `awake`, `suspending <seq>`, `suspended <seq> <modo>`, `resuming <seq>` ou `poweroff` |

O `lume-sleep` e o `lume-input` só confiam em `phase`, `clients` e `status` do dono root (o
grupo `game` pode criar arquivos na pasta). Nomes começados por `.` (temporários, trava) não
são pedidos. Qualquer outro nome é apagado e registrado (`sleep FAIL refused request: <nome>`).

**Admissão do pedido** (o arquivo é apagado em todo caso): `suspend` roda com o `status` em
`awake`; durante uma sequência (`suspending`, `suspended`, `resuming`) o pedido em dobro é
apagado sem rodar, só com uma linha no log do kernel; dentro da guarda de 1 s depois de
acordar também. `poweroff` roda em qualquer estado, menos depois de outro `poweroff`. O
`poweroff` leva ao desligamento da sessão, pelo mesmo caminho do item Desligar.

**Modo de cada console:** `/usr/share/lume/sleep/<placa>.conf` (pacote `lume-power`), linha
`mode freeze` ou `mode mem` (`#` comenta); sem arquivo ou com valor inválido, `freeze`.
`freeze` grava `freeze` em `/sys/power/state`; `mem` grava `deep` em `/sys/power/mem_sleep` e
depois `mem` em `/sys/power/state`, e só vale num console que acordou 10 vezes em 10.

| Console | Modo | Origem |
|---|---|---|
| GA36 | `freeze` | medido (2.3, J1, 2026-11-18): `mem_sleep` só oferece `[s2idle]`; 10 de 10 despertares pelo botão |
| R36S | `freeze` | padrão, ainda não medido: a J1 do R36S (2.3) confere o `mem_sleep` e preenche o arquivo |
| VM | `freeze` | padrão (sem arquivo) |

**Dois achados da J1 no GA36 que o `lume-sleep` (8.3) e o `lume-input` (8.2) cumprem:**

1. **Gadget USB:** depois de um `freeze` o `musb` fica em `b_peripheral` com o UDC
   `not_attached`, e o PC não enumera nem com o cabo recolocado. Antes de gravar em
   `/sys/power/state`, o `lume-sleep` guarda o conteúdo de
   `/sys/kernel/config/usb_gadget/lume/UDC` e grava vazio nele (solta o gadget); ~1 s depois
   de acordar, em segundo plano, grava de volta o nome guardado (só se estava ligado). Falha:
   `sleep FAIL usb: <motivo>`, sem impedir a suspensão.
2. **Entrada acumulada:** ao acordar, a interface "andava" sozinha com os eventos do controle
   da suspensão. Entre o `phase suspend` e o `phase resume` o `lume-input` não repassa nada
   (nem toque, nem acorde, nem pedido); no `resume`, antes de avisar os clientes, ele lê e
   descarta tudo o que está na fila das origens, solta as teclas seguradas no controle virtual
   e ignora o botão de energia até vê-lo solto (o toque que acordou não vira outro pedido).

## Dock

Favoritos (primeiro), os consoles que têm jogos, Recentes e Configurações (último). Um console
sem jogos não aparece. Cada console é um tile com a sigla dele; os logos fazem parte do tema,
na pasta `icons/` dele no cartão (`ROMS/system/lume/themes/<tema>/icons/<id>.png`). Um tema sem
`icons/` usa os do tema de quem herda e, por último, os do tema padrão, então um tema copiado
do modelo continua com os logos até trazer os próprios (a imagem não traz logo de fabricante;
ver o [formato de tema](lume-launcher/formato-de-tema.md)).

## Menu do jogo

- **Iniciar jogo**.
- **Save states**: os slots do core que vai abrir o jogo, com a imagem do slot em foco ao lado
  (o RetroArch grava `<estado>.png` com "Save State Thumbnails", ligado de fábrica). Slots
  feitos com outro core aparecem como "N em outro core" e não abrem (um save state só funciona
  no core que o gravou).
- **Configurações**: **Emulador**, **Aspecto** e **Shader**, só para esse jogo. "Padrão" apaga
  a escolha do jogo, e ele volta a seguir o console. Aspecto e Shader aparecem só nos cores do
  RetroArch. Um jogo com opção própria ganha um ponto no canto da capa. B volta ao menu do jogo.
- **Incluir em favoritos** / **Remover dos favoritos**.

As listas dos menus e das Configurações dão a volta: para baixo no último item vai ao primeiro.

As **opções do console** (Y na grade) definem o padrão de todos os jogos daquele console, e
"Limpar opções dos jogos" apaga as escolhas de cada jogo. A ordem é sempre: jogo, console,
catálogo.

## Configurações

A lista fica à esquerda; à direita, o painel do item em foco mostra o valor, a barra do nível
ou o que o item faz. Idioma (vale também para o RetroArch e para as mensagens do sistema),
Tema (Lume, o padrão, e Material escuro e claro), Tela (mostrar ou não o percentual ao lado
da bateria), Volume, Brilho, Sistema (modelo, CPU,
memória, cartão, bateria e a memória do próprio launcher, lidos só enquanto o item está
selecionado), Games (com **Atualizar listas**: A atualiza), RetroArch (o menu completo, sem jogo; ao sair, volta às
Configurações) e Desligar (pede confirmação: Desligar em cima, Cancelar embaixo e em foco). Wi-Fi e Bluetooth aparecem
só com um adaptador USB conectado.

Na lista, ▲▼ escolhem o item e A ou ▶ entram no painel dele; no painel, ▲▼ trocam a linha, ◀▶
mudam o valor, A executa e B volta à lista. Sistema só mostra valores; RetroArch e Desligar
executam direto com A.

### SSH pela rede Wi-Fi

No painel do Wi-Fi, **SSH pela rede** (desligado de fábrica) deixa entrar no console como root
pela rede Wi-Fi, sem preparar nada no PC:

1. Ligue **SSH pela rede** no painel do Wi-Fi (◀▶ ou A).
2. O painel mostra o comando e o **código**, por exemplo `ssh console@192.168.1.20` e
   `7K4M-9Q2X`.
3. No PC (o `ssh` já vem no Windows, no macOS e no Linux), digite o comando e, quando pedir a
   senha, o código.

O código fica o mesmo, também depois de reiniciar, até você escolher **Gerar novo código** no
painel; aí o antigo deixa de valer. Ele fica no cartão (`ROMS/system/ssh/wifi-code`), então
quem tem o cartão na mão também pode lê-lo. O console só escuta no endereço da rede Wi-Fi
(nunca numa ligação Wi-Fi Direct) e para quando o Wi-Fi cai ou a opção é desligada; o root sem
senha continua valendo só pelo cabo USB. A chave do console
(`ROMS/system/ssh/dropbear_ed25519_host_key`) é criada na primeira vez e não muda a cada boot.

Avançado: quem tem uma chave SSH pode pô-la em `ROMS/system/ssh/authorized_keys` (uma por
linha) e entrar como `root` sem o código.

## Listas de jogos (`gamelist.xml`)

Cada console tem `ROMS/roms/<id>/gamelist.xml`, no formato do EmulationStation. As listas são
atualizadas no boot (em segundo plano: a primeira tela usa o índice anterior), quando o cabo USB
do PC é desligado e por "Atualizar listas", no item Games das Configurações.

- Um jogo novo entra com o nome do arquivo, sem a extensão.
- Um jogo que já está no XML nunca é reescrito: nome, capa, descrição e os campos de um scraper
  ficam como estão.
- Um jogo cuja ROM sumiu sai da lista, mas a entrada e as imagens ficam. Se a ROM voltar, ele
  volta com a mesma capa.
- Um XML sem mudança não é regravado. Um XML com erro não é tocado (o log diz qual).

Campos lidos pelo launcher:

```xml
<game>
	<path>./Jogo (USA).sfc</path>         <!-- relativo à pasta do console -->
	<name>Jogo</name>
	<image>./images/Jogo (USA).png</image> <!-- PNG, JPEG ou WebP; outro arquivo vira a caixa com o nome -->
	<favorite>true</favorite>
	<playcount>3</playcount>
	<lastplayed>20261114T183000</lastplayed>
</game>
```

`favorite`, `playcount` e `lastplayed` são gravados pelo launcher no próprio XML, para um
scraper ou outro EmulationStation verem os mesmos dados. As pastas `images`, `img`, `media`,
`videos` e `manuals` de cada console nunca são lidas como jogos.

## Adicionar um emulador pelo cartão (runner)

Um **runner** diz como abrir um jogo. Um arquivo por runner em `ROMS/system/lume/runners.d/`:

<!-- runner-example -->
```toml
[runner]
id = "meu-emulador"
kind = "native"                     # native, ou libretro (mostra Aspecto e Shader)
exec = ["/storage/bios/meu-emulador/run", "--fullscreen", "{rom}"]
quit = "sigterm"                    # sigterm, ou retroarch-cmd (só o RetroArch)
timeout = 3                         # segundos até o encerramento forçado
```

- `exec` é a lista de argumentos, sem shell. Cada marcador vale um argumento inteiro: `{rom}`,
  `{core}`, `{core_path}`, `{system}`, `{bios_dir}`, `{saves_dir}`, `{states_dir}`. Uma ROM com
  espaço no nome chega como um argumento só.
- O primeiro item é o caminho absoluto de um executável. Um arquivo com erro, ou que cite um
  executável que não existe, é ignorado e o log diz qual foi; os outros runners continuam.
- Com o mesmo `id` de um runner da imagem (`retroarch`, `love`, `sh`), o do cartão vence.
- Os atalhos do Fn chegam ao emulador pela tabela opcional `[runner.actions]`: `pause`,
  `app_menu`, `reset`, `save_state`, `load_state` e `screenshot`, cada uma como
  `retroarch-cmd:<COMANDO>` (comando de rede do RetroArch), `key:<KEY_*>` (uma tecla apertada e
  solta no controle virtual, por exemplo `key:KEY_F2`) ou `signal:<NOME>` (sinal ao programa,
  por exemplo `signal:SIGUSR1`); `pause` aceita também `retroarch-pause`. Sem `pause`, o menu do
  Lume congela o programa enquanto está aberto. Uma ação que o runner não declara só deixa uma
  linha no log. `overlay = "retroarch"` diz que o runner desenha a barra e a lista de atalhos.

```toml
[runner.actions]
save_state = "key:KEY_F2"
load_state = "key:KEY_F4"
screenshot = "signal:SIGUSR1"
```

Depois, cite o runner num console, em `ROMS/system/lume/systems.d/*.toml`:

```toml
[[system]]                 # acrescenta um emulador a um console existente
id = "snes"
emulators = [{ runner = "meu-emulador" }]

[[system]]                 # ou cria um console novo (a pasta roms/pico8/ é criada no scan)
id = "pico8"
name = "PICO-8"
abbr = "P8"
extensions = ["p8"]
emulators = [{ runner = "meu-emulador" }]
```

Um core do RetroArch que não está no catálogo também entra assim:
`emulators = [{ runner = "retroarch", core = "snes9x2005_plus" }]` (o arquivo
`/usr/lib/libretro/snes9x2005_plus_libretro.so` precisa existir).

Depois de "Atualizar listas", o emulador aparece nas Configurações de cada jogo do console.

## Arquivos do launcher no cartão

| Arquivo | Conteúdo |
|---|---|
| `ROMS/system/lume/settings.toml` | idioma, tema, volume, brilho e as opções de Tela |
| `ROMS/system/lume/themes/` | seus temas (`<id>/theme.toml`) e logos dos consoles (`<id>/icons/<sistema>.png`); o `LEIA-ME.txt` da pasta explica o formato |
| `ROMS/system/lume/systems/<id>.toml` | opções do console |
| `ROMS/system/lume/games/<id>.toml` | opções de cada jogo (só o que difere) |
| `ROMS/system/lume/states/<id>.toml` | core que gravou cada slot de save state |
| `ROMS/system/lume/cache/` | índice e miniaturas (apagar é seguro: o próximo scan refaz) |

Apagar `ROMS/system/lume/` volta o launcher ao padrão de fábrica; jogos, saves e states
continuam.
