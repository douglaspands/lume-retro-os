# Catálogo de sistemas (`systems.json`)

`/usr/share/r36os/systems.json` é a fonte única dos sistemas do Lume Retro OS. Dele
saem as pastas da partição `ROMS`, as listas de jogos do RetroArch e o `LEIA-ME.txt`.
Qualquer frontend futuro deve ler este arquivo em vez de manter uma lista própria.

Fonte no repositório: `rootfs/overlay/usr/share/r36os/systems.json`.
Validação: `r36os.catalog.validate()` (teste `tests/unit/test_catalog.py`).

## Esquema (versão 1)

```json
{
  "schema": 1,
  "systems": [ <sistema>, ... ],
  "cores":   { "<core>": { "package": "<pacote apk>", "file": "<core>_libretro.so" } }
}
```

Cada `<sistema>` tem exatamente estes campos:

| Campo | Tipo | Significado |
|---|---|---|
| `id` | texto `[a-z0-9]+` | pasta em `ROMS/roms/<id>/` e chave estável do sistema |
| `name` | texto, sem `/` | nome no menu; também o nome da lista `<name>.lpl` e do ícone do tema |
| `extensions` | lista de textos | extensões aceitas, minúsculas e sem ponto; o resto é ignorado |
| `core` | nome de core | core padrão |
| `core_by_arch` | objeto `{arch: core}` | core padrão numa arquitetura (`x86_64`, `aarch64`, `armv7`) |
| `alt_cores` | lista de cores | cores alternativos instalados |
| `bios` | lista de `{files, required, note}` | BIOS aceitas em `ROMS/bios/`; `files` são nomes alternativos |

Regras:

- Todo core citado em `core`, `core_by_arch` ou `alt_cores` tem entrada em `cores`, e
  o pacote dela está em `rootfs/packages.txt`, ou seja, instalado nos três alvos.
- O core padrão de um sistema na arquitetura `A` é `core_by_arch[A]`, se existir, ou
  `core`.
- `ids` e `names` são únicos.

## Contrato de pastas da partição `ROMS`

```
roms/<id>/      jogos de cada sistema
bios/           BIOS (nomes em systems.json)
saves/<id>/     saves internos dos jogos (o RetroArch cria por sistema)
states/<id>/    save states
screenshots/
system/         configuração persistente (apagar = restaurar a fábrica)
LEIA-ME.txt
```

As pastas são recriadas a cada boot se faltarem, sem apagar nada.
