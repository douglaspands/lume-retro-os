# Formato de tema

Objetivo: **versátil para criar** e **barato de interpretar**. Declarativo, em TOML, sem
scripts. Implementado em `lume/lume-ui/src/theme.rs` (change `lume-launcher`, D11, tarefa 7.2).

## Onde ficam

| Lugar | Quem traz |
|---|---|
| `/usr/share/lume/themes/<id>/theme.toml` | a imagem: `material-dark` e `material-light` |
| `ROMS/system/lume/themes/<id>/theme.toml` | o usuário, no cartão (vence o da imagem com o mesmo `id`) |

Um tema do cartão pode trazer `icons/<sistema>.png` para o Dock. A distro não traz nenhum
ícone nem logotipo de fabricante: o tema padrão desenha cada console como um tile com a sigla
(`abbr` do catálogo).

## Arquivo

```toml
[theme]
id = "material-light"          # igual ao nome da pasta
extends = "material-dark"      # opcional: herda tudo e muda só o que vier abaixo

[tokens]
bg = "#FEF7FF"
accent = "#6750A4"

[features]
lite = false                   # true força o Modo lite
```

- **Cores**: `#rrggbb` ou `#rrggbbaa` (com transparência).
- **Tamanhos**: em `em`, 1/40 da largura da tela (16 px a 640x480). O layout acompanha a
  resolução (640x480, 854x480, 720x720).
- **Herança**: a cadeia vai até os padrões do motor; um tema declara só o que muda. Herança
  circular é recusada.
- **Validação**: token desconhecido, cor inválida, tipo errado ou `cols`/`rows` fora de 1 a 8
  recusam o tema. O launcher registra o erro no log e usa o `material-dark`.

## Tokens

| Token | Tipo | Uso |
|---|---|---|
| `bg`, `fg`, `muted` | cor | fundo, texto, texto secundário |
| `accent`, `accent_fg` | cor | destaque (botões das dicas, foco da grade) e o texto sobre ele |
| `overlay` | cor | escurece a tela por trás dos menus |
| `icon_bg`, `icon_fg`, `icon_sel_bg`, `icon_sel_fg` | cor | tiles do Dock, normal e em foco |
| `tile_bg`, `tile_bg_sel`, `tile_bg_opaque` | cor | quadrados da grade; `_opaque` vale no Modo lite |
| `panel_bg`, `panel_bg_opaque` | cor | painéis (menu do jogo, Configurações) |
| `sel_bg`, `sel_fg` | cor | linha em foco das listas |
| `toast_bg`, `toast_fg` | cor | avisos curtos |
| `radius_icon`, `radius_tile`, `radius_panel`, `radius_item` | em | cantos arredondados |
| `icon` | em | tamanho do ícone do Dock em repouso |
| `dock_gap` | número | espaço entre ícones, em ícones |
| `mag_peak`, `mag_base`, `mag_spread` | número | ampliação do Dock: o ícone em foco cresce `mag_peak` vezes, os distantes ficam em `mag_base`, numa curva gaussiana de largura `mag_spread` |
| `dock_top` | número | altura do Dock, em fração da tela |
| `cols`, `rows` | inteiro | colunas e linhas mínimas da grade (uma tela mais alta ganha linhas) |
| `label_px`, `title_px` | em | tamanho dos textos |
| `anim_ms` | inteiro | duração das animações; 0 desliga |
| `cache_bytes` | inteiro | teto do cache de capas na RAM (padrão 4 MiB) |

## Modo lite

Ligado nas Configurações (ou por `features.lite`): `anim_ms` vira 0 e toda cor com
transparência vira a variante `_opaque` do token, ou a mesma cor sem transparência. Nos dois
temas Material, que já são opacos, o efeito visível é a falta de animação.

## Por que TOML

É o formato que o usuário edita com mais facilidade num PC, e o mesmo dos runners e das
configurações do launcher.

Voltar: [Visão geral](visao-geral.md)
