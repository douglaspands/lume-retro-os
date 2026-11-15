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
| Fn sozinho | — | — | abre o menu do RetroArch, dentro de um jogo do RetroArch |
| Volume + / − | volume do sistema, em qualquer tela e em qualquer jogo | | |

A busca ignora maiúsculas e acentos e exige todas as palavras: "super bros" acha "Súper Bros".

**Fn+Start** funciona com qualquer programa aberto pelo launcher: RetroArch, LÖVE, um script de
Ports ou um emulador travado. Primeiro o programa recebe um pedido para sair (o RetroArch grava o
save interno nessa hora); se não sair em alguns segundos, ele e tudo o que abriu são encerrados.

## Dock

Favoritos (primeiro), os consoles que têm jogos, Recentes e Configurações (último). Um console
sem jogos não aparece. Cada console é um tile com a sigla dele; logos próprios vão no cartão,
em `ROMS/system/lume/themes/<tema>/icons/<id>.png` (a imagem não traz logo de fabricante; ver o
[formato de tema](lume-launcher/formato-de-tema.md)).

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
Tema (Lume, o padrão, e Material escuro e claro), Volume, Brilho, Sistema (modelo, CPU,
memória, cartão, bateria e a memória do próprio launcher, lidos só enquanto o item está
selecionado), **Atualizar listas**, RetroArch (o menu completo, sem jogo; ao sair, volta às
Configurações) e Desligar (pede confirmação; Cancelar é o padrão). Wi-Fi e Bluetooth aparecem
só com um adaptador USB conectado.

## Listas de jogos (`gamelist.xml`)

Cada console tem `ROMS/roms/<id>/gamelist.xml`, no formato do EmulationStation. As listas são
atualizadas no boot (em segundo plano: a primeira tela usa o índice anterior), quando o cabo USB
do PC é desligado e pelo item "Atualizar listas" das Configurações.

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
`emulators = [{ runner = "retroarch", core = "snes9x" }]` (o arquivo
`/usr/lib/libretro/snes9x_libretro.so` precisa existir).

Depois de "Atualizar listas", o emulador aparece nas Configurações de cada jogo do console.

## Arquivos do launcher no cartão

| Arquivo | Conteúdo |
|---|---|
| `ROMS/system/lume/settings.toml` | idioma, tema, volume e brilho |
| `ROMS/system/lume/themes/` | seus temas (`<id>/theme.toml`) e logos dos consoles (`<id>/icons/<sistema>.png`); o `LEIA-ME.txt` da pasta explica o formato |
| `ROMS/system/lume/systems/<id>.toml` | opções do console |
| `ROMS/system/lume/games/<id>.toml` | opções de cada jogo (só o que difere) |
| `ROMS/system/lume/states/<id>.toml` | core que gravou cada slot de save state |
| `ROMS/system/lume/cache/` | índice e miniaturas (apagar é seguro: o próximo scan refaz) |

Apagar `ROMS/system/lume/` volta o launcher ao padrão de fábrica; jogos, saves e states
continuam.
