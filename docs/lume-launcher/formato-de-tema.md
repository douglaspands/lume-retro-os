# Formato de tema

Objetivo: **versátil para criar** e **barato de interpretar**. Declarativo, em TOML, sem
scripts. Implementado em `lume/lume-ui/src/theme.rs` (change `lume-launcher`, D11, tarefa 7.2).

## Onde ficam

| Lugar | Quem traz |
|---|---|
| `/usr/share/lume/themes/base.toml` | a imagem: o tema padrão e o valor-base de cada token |
| `/usr/share/lume/themes/<id>/theme.toml` | a imagem: `lume` (o padrão), `material-dark` e `material-light` |
| `ROMS/system/lume/themes/<id>/theme.toml` | o usuário, no cartão (vence o da imagem com o mesmo `id`). A pasta `themes/` é criada no boot (serviço `lume-index`) com um `LEIA-ME.txt` que explica o formato, em cartão novo ou antigo, e nunca mais é tocada |

Uma pasta cujo nome começa com `_` não é tema: o launcher não a lista nem a carrega. É lá que
fica o modelo `ROMS/system/lume/themes/_lume-original/theme.toml`, o tema original (Lume) com
todos os tokens e os valores dele, comentados, para o usuário copiar com outro nome. O
`lume-index` o mantém igual ao da imagem (grava só quando difere); um teste garante que uma
cópia dele dá exatamente o tema `lume`.

O `lume-ui` não conhece nenhum tema nem valor de token: tudo vem desses arquivos. Criar um
tema é criar uma pasta com um `theme.toml`; ele aparece em Configurações → Tema sem mudar
código nem tradução. Trocar o tema padrão da imagem é mudar o `default` do `base.toml`.

## Base (`base.toml`)

```toml
default = "lume"               # tema de quem não escolheu nenhum, e do tema inválido

[tokens]                       # valor de cada token que o tema não define
bg = "#14161a"
icon = 5.8
```

A lista de `[tokens]` é também a lista dos tokens que existem e dos seus tipos (texto é cor,
número é tamanho ou contagem): um tema com outro token, ou com o tipo errado, é recusado. Só
a imagem traz a base; um tema do cartão não a muda. Sem a base (imagem quebrada), o erro vai
para o log e as cores aparecem em magenta.

Um tema do cartão pode trazer `icons/<sistema>.png` para o Dock. A distro não traz nenhum
ícone nem logotipo de fabricante: sem ícone, cada console é um tile com a sigla (`abbr` do
catálogo).

- A pasta `ROMS/system/lume/themes/<id>/icons/` vale para o tema `<id>` e para os temas que
  herdam dele, mesmo sem `theme.toml` ao lado. Exemplo: logos em
  `ROMS/system/lume/themes/lume/icons/snes.png` aparecem com o tema padrão.
- O PNG é lido como máscara: vale a transparência (ou o brilho, num PNG sem transparência,
  como um logo branco sobre preto). O logo é pintado numa cor só, a do texto do ícone
  (`icon_fg`, ou `icon_sel_fg` no foco), e cabe em 78% x 56% do tile. Um logo branco ou preto
  com fundo transparente funciona em qualquer tema.

## Arquivo

```toml
[theme]
id = "material-light"          # igual ao nome da pasta
name = { en = "Light", pt = "Claro", es = "Claro" }   # opcional: nome nas Configurações
extends = "material-dark"      # opcional: herda tudo e muda só o que vier abaixo

[tokens]
bg = "#FEF7FF"
accent = "#6750A4"
```

- **Cores**: `#rrggbb` ou `#rrggbbaa` (com transparência).
- **Tamanhos**: em `em`, 1/40 da largura da tela (16 px a 640x480). O layout acompanha a
  resolução (640x480, 854x480, 720x720).
- **Nome**: um por idioma (`en`, `pt`, `es`); falta o idioma, vale o `en`; falta o `name`,
  aparece o `id`.
- **Herança**: a cadeia vai até o `base.toml`; um tema declara só o que muda. Herança
  circular é recusada.
- **Validação**: token desconhecido, cor inválida, tipo errado ou `cols`/`rows` fora de 1 a 8
  recusam o tema. O launcher registra o erro no log e usa o `default` do `base.toml` (`lume`).

O `lume` usa os tons azuis do Lume TV launcher (`themes/lume/theme.css` do projeto
`douglaspands/lume-tv-launcher`, do mesmo autor) e herda do `material-dark` as formas, os
tamanhos e as posições: é o exemplo de um tema que muda só as cores.

## Tokens

| Token | Tipo | Uso |
|---|---|---|
| `bg`, `fg`, `muted` | cor | fundo, texto, texto secundário |
| `accent`, `accent_fg` | cor | destaque (botões das dicas, foco da grade) e o texto sobre ele |
| `overlay` | cor | escurece a tela por trás dos menus |
| `icon_bg`, `icon_fg`, `icon_sel_bg`, `icon_sel_fg` | cor | tiles do Dock, normal e em foco |
| `tile_bg`, `tile_bg_sel`, `tile_bg_opaque` | cor | quadrados da grade; `_opaque`: teclas da busca, fundo da imagem do save state, trilhas das barras |
| `panel_bg`, `panel_bg_opaque` | cor | painéis (menu do jogo, Configurações); `_opaque`: campo da busca |
| `sel_bg`, `sel_fg` | cor | linha em foco das listas |
| `toast_bg`, `toast_fg` | cor | avisos curtos |
| `radius_icon`, `radius_tile`, `radius_panel`, `radius_item` | em | cantos arredondados |
| `icon` | em | tamanho do ícone do Dock em repouso (a base da ampliação) |
| `dock_gap` | em | espaço entre ícones do Dock (0,5 = 8 px a 640x480, como no protótipo) |
| `mag_peak`, `mag_base`, `mag_spread` | número | ampliação do Dock: o ícone em foco cresce `mag_peak` vezes, os distantes ficam em `mag_base`, numa curva gaussiana de largura `mag_spread` |
| `dock_top`, `dock_origin` | número | a linha por onde passam os ícones (fração da altura da tela) e o ponto de cada ícone que fica nela (fração da altura do ícone): um ícone maior sobe |
| `dock_name_px`, `dock_sub_px` | em | nome do item em foco e a linha embaixo dele (jogos, ou o que o item faz) |
| `list_title_px`, `list_name_px`, `status_px`, `hint_px` | em | lista de jogos: título do cabeçalho (negrito), nome do jogo em foco, contador e bateria, e o texto dos botões do rodapé em todas as telas |
| `nav_bg`, `nav_fg` | cor | chip das setas (◀▶, ▲▼) no rodapé |
| `cols`, `rows` | inteiro | colunas e linhas mínimas da grade (uma tela mais alta ganha linhas) |
| `label_px`, `title_px` | em | tamanho dos textos das outras telas |
| `anim_ms` | inteiro | duração das animações; 0 desliga |
| `cache_bytes` | inteiro | teto do cache de capas na RAM (padrão 4 MiB) |

## Sem Modo lite

O Modo lite saiu em 2026-11-14, a pedido do usuário: não há mais a opção nas Configurações
nem a seção `[features]` (um tema com ela é recusado). Animação e transparência são tokens
como os outros: `anim_ms = 0` desliga a animação, e um tema opaco não usa cores com alfa.

## Por que TOML

É o formato que o usuário edita com mais facilidade num PC, e o mesmo dos runners e das
configurações do launcher.

Voltar: [Visão geral](visao-geral.md)
