# Catálogo de sistemas (`systems.json`)

`/usr/share/lume/systems.json` é a fonte única dos sistemas do Lume Retro OS. Dele
saem as pastas da partição `ROMS`, as listas de jogos do RetroArch, os sistemas e emuladores
do lume-launcher e o `LEIA-ME.txt`. Qualquer frontend deve ler este arquivo em vez de manter
uma lista própria.

Fonte no repositório: `rootfs/overlay/usr/share/lume/systems.json`.
Validação: `lume_tool.catalog.validate()`, chamada no início do build do rootfs (um erro para o
build), com os testes em `tests/unit/test_catalog.py`.

## Esquema (versão 3)

```json
{
  "schema": 3,
  "systems": [ <sistema>, ... ],
  "cores":   { "<core>": { "package": "<pacote apk>", "file": "<core>_libretro.so" } }
}
```

Cada `<sistema>` tem exatamente estes campos:

| Campo | Tipo | Significado |
|---|---|---|
| `id` | texto `[a-z0-9]+` | pasta em `ROMS/roms/<id>/` e chave estável do sistema |
| `name` | texto, sem `/` | nome no menu; também o nome da lista `<name>.lpl` |
| `abbr` | texto de 1 a 5 caracteres | sigla do tile do sistema no Dock do launcher (ex.: `SNES`, `PS1`) |
| `extensions` | lista de textos | extensões aceitas, minúsculas e sem ponto; o resto é ignorado |
| `core` | nome de core ou `null` | core padrão; `null` num sistema sem core do RetroArch (`love`, `ports`) |
| `core_by_arch` | objeto `{arch: core}` | core padrão numa arquitetura (`x86_64`, `aarch64`, `armv7`) |
| `alt_cores` | lista de cores | cores alternativos instalados |
| `emulators` | lista de `{runner, core?}` | emuladores que não são cores do RetroArch, depois dos cores (ver abaixo) |
| `bios` | lista de `{files, required, note}` | BIOS aceitas em `ROMS/bios/` (a do Neo Geo, `neogeo.zip`, vai em `roms/neogeo/`, como diz a `note`); `files` são nomes alternativos |
| `romset` | texto ou `null` | `null` nos sistemas comuns; nos de arcade, o romset que o core padrão aceita (o `LEIA-ME.txt` o imprime) |

Regras:

- Todo core citado em `core`, `core_by_arch` ou `alt_cores` tem entrada em `cores`, e
  o pacote dela está em `rootfs/packages.txt`, ou seja, instalado nos três alvos.
- O core padrão de um sistema na arquitetura `A` é `core_by_arch[A]`, se existir, ou
  `core`.
- `ids` e `names` são únicos.
- Sistema de arcade (com `romset`) não pode ter `core_by_arch`: o cartão único leva a mesma
  pasta de romsets aos dois consoles, e um romset só funciona no core da versão dele. O
  validador recusa o catálogo que quebrar a regra.
- **Por enquanto, os mesmos cores nos dois consoles** (decisão do usuário, 2026-11-19): todo
  `core_by_arch` está vazio, e o GA36 (armv7) e o R36S (aarch64) abrem cada sistema no mesmo
  core. Com a evolução, cada console pode seguir o próprio caminho pelo `core_by_arch`, medido
  no aparelho (P-24). O teste `test_same_cores_on_both_consoles_for_now` guarda a regra até
  essa decisão mudar. Master System, Mega Drive e Sega CD usavam o `picodrive` no armv7 por
  desempenho no A33; agora usam o `genesis_plus_gx` nos dois, com o `picodrive` como
  alternativo (a velocidade no GA36 fica para a J2 dele).

## Emuladores do launcher

A lista de emuladores de um sistema numa arquitetura (`lume_tool.catalog.emulators()`, e a mesma
regra no `lume-core`) tem o primeiro item como padrão:

1. os cores do RetroArch, pelo runner `retroarch`: o core padrão da arquitetura, depois `core`
   e os `alt_cores`, sem repetir;
2. os itens de `emulators`, na ordem.

Assim os cores ficam num lugar só, e o `lume-playlists` continua lendo `core`. O validador
recusa:

- runner citado que não está em `/usr/share/lume/runners.d/` (o build para);
- o runner `retroarch` dentro de `emulators` (os cores vão em `core` e `alt_cores`);
- `core` num emulador que não é libretro;
- sistema sem `core` e sem `emulators`.

O formato dos runners e a extensão pelo cartão (`ROMS/system/lume/runners.d/` e
`ROMS/system/lume/systems.d/`) estão em `docs/LAUNCHER.md`.

## Contrato de pastas da partição `ROMS`

```
roms/<id>/      jogos de cada sistema (inclui love/ e ports/, sem core do RetroArch)
bios/           BIOS (nomes em systems.json)
saves/<id>/     saves internos dos jogos (o RetroArch cria por sistema)
states/<id>/    save states
screenshots/
system/         configuração persistente (apagar = restaurar a fábrica)
LEIA-ME.txt
```

As pastas são recriadas a cada boot se faltarem, sem apagar nada.
