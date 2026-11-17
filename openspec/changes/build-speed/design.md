# Design

## Context

Ver `proposal.md` (Why). O estado que molda o desenho:

- `src/r36os/kernel.py`: `source_tree()` extrai o tarball para `.cache/src/linux-<versão>-<hash
  de todos os patches>` e aplica a série com `git apply` (com `GIT_CEILING_DIRECTORIES`);
  `build_kernel()` usa `.cache/kbuild/<console>-<hash>` e `ccache`, no container `cross`. A data
  do kernel (`build_stamp`) é a do último commit em `kernel/patches/`, comum aos dois consoles. O
  kernel embute o initramfs.
- `src/r36os/build.py`: por console, os pacotes locais que faltam (por nome, sem olhar conteúdo),
  initramfs, kernel, DTBs com `dt-validate`, rootfs (`apk add --root`) e `SYSTEM` (`mksquashfs`
  zstd 19). Nada é pulado por conteúdo.
- `src/r36os/archive.py`: comprime a imagem inteira do cartão (zstd 10, uma thread) a cada build.
- `src/r36os/push.py`: compara a `boot-files.sha256` com o cartão (bom), mas para ler os arquivos
  descompacta a imagem inteira; o `VERSION` (com o `build_id` da hora) sempre difere; termina no
  `reboot` sem esperar.
- `initramfs/init`: monta `<console>/SYSTEM` (ou `.old`) como `lowerdir` único, overlay com
  tmpfs; `<console>/modules` à parte.
- `aports/`: 19 pacotes, todos compilados num container da arquitetura sob qemu (o
  `lume-launcher` armv7 leva 8 min; P-61); o `rootfs/overlay/` (scripts, serviços, configuração,
  temas, shaders) é copiado por fora do `apk`.
- O cartão tem `BOOT` (FAT32) e `ROMS`; não há partição Linux gravável, então tudo o que é
  trocado no cartão é arquivo da `BOOT`.
- O boot leva 24–34 s até o frontend (P-58): um reboot pesa no ciclo de teste.

## Goals / Non-Goals

**Goals:**
- Mudança num script ou tema: build em segundos, no console em segundos (`push --hot`).
- Patch num driver: menos de 1 minuto de compilação por arquitetura afetada.
- Mudança no `lume-launcher`: perto de 1 minuto de build por arquitetura.
- Build sem mudança: segundos. Push sem mudança: não envia nem reinicia.
- PC usável e mais frio durante qualquer build.
- Um comando dá o resultado de um teste no aparelho (passou/falhou), sem helper avulso.

**Non-Goals:**
- `apk add` dentro do console (P-14), boot mais rápido (P-58), userland armv7 único.
- Manter a imagem `vm` construída e testada nesta change (decisão do usuário; volta por
  pendência própria).

## Decisions

### D1. Fragmento = pacote `.apk`; slot = unidade no cartão

Dois níveis com granularidades diferentes:

```
 fragmento (.apk)  fino: compila, versiona e se instala sozinho     custo: segundos no PC
 slot (squashfs)   grosso: o que vai ao cartão e é montado          custo: um mount
```

Um slot é montado a partir dos arquivos instalados de um grupo de fragmentos. Assim o número de
fragmentos pode crescer sem aumentar o número de mounts no boot.

- Alternativa: um squashfs por fragmento. Rejeitada: dezenas de mounts no caminho do boot.
- Alternativa: só slots, sem pacote. Rejeitada: não dá versão por parte nem build pontual.

### D2. Fragmentos por arquitetura e noarch

- **Regra:** o que contém ELF é por arquitetura; o resto é `arch="noarch"`. O build falha se um
  fragmento noarch tiver ELF.
- **Nomes iguais nas duas arquiteturas**, sem nome de console (`lume-kernel`, não
  `lume-kernel-r36s`): o `apk` já separa por repositório e pelo campo `arch`. O kernel de uma
  arquitetura serve a todo console dela (rumo da `boot-dtb-select`); o fragmento do kernel passa a
  ser da arquitetura (`board/<board>/kernel.config` vira o fragmento da arquitetura enquanto houver
  um console por arquitetura).
- **Noarch montado no x86:** `abuild` no container `builder` x86_64, sem qemu; o mesmo arquivo
  `.apk` é copiado para `out/repo/armv7/` e `out/repo/aarch64/` (e `x86_64/`) e cada índice é
  refeito.
- **Campo de arquitetura (provado na tarefa 4.1, 2026-11-16):** o `abuild` 3.17 grava
  `arch = noarch` no `.PKGINFO` do pacote, e o índice é que leva a arquitetura do repositório: o
  próprio `abuild` refaz o `APKINDEX` com `apk index --rewrite-arch $CARCH`, e é por isso que o
  banco instalado dos consoles mostra `A:armv7`/`A:aarch64` para pacotes noarch do Alpine. O
  `apk` 3 busca o arquivo em `<repositório>/<arch do índice>/`; com um índice sem
  `--rewrite-arch` (`A:noarch`) o `apk add` do armv7 falha com "package mentioned in index not
  found". A assinatura do `.apk` (`.SIGN.RSA.r36os.rsa.pub`, sobre o segmento de controle) não
  depende da arquitetura, então o mesmo arquivo assinado serve a todas.
- **Método escolhido:** o `.apk` sai do `abuild` x86_64 numa área de preparo (`out/noarch/`),
  passa pela checagem de ELF e é copiado byte a byte (SHA256 conferido; nome igual com conteúdo
  diferente é recusado) para `out/repo/<arch>/` das três arquiteturas. Cada índice é refeito com
  `apk index --rewrite-arch <arch>` e assinado com `abuild-sign` e a chave local de sempre
  (`.cache/abuild/r36os.rsa`), no container x86_64, sem qemu. Assim `.PKGINFO` diz `noarch`, o
  `APKINDEX` diz `A:<arch>` e o `apk add --root` do armv7, do aarch64 e do x86_64 instala sem
  `--allow-untrusted` (`tests/integration/test_noarch_publish.py`). API em
  `src/r36os/packages.py`: `build_noarch(nomes)` → `.apk` conferidos, `publish_noarch(apks)`,
  `reindex(arches)` (usa o recurso `ARCH:<arch>`).
- **Checagem de ELF:** antes do build, `check_noarch_aport` exige `arch="noarch"` e nenhum
  arquivo ELF no diretório do aport; depois, `check_noarch_apk` lê o `.apk` e exige
  `arch = noarch` e nenhum arquivo de dados ELF. A falha nomeia o fragmento e os arquivos. O
  `archcheck` do `abuild` também recusa ELF em noarch, mas não diz qual arquivo e pode ser
  desligado com `options="!archcheck"`.
- **Corte inicial do `rootfs/overlay/`** (cada um vira `aports/<nome>/`, com os arquivos dentro):

| Fragmento | Conteúdo hoje |
|---|---|
| `lume-core` | `lib.sh`, `logs.sh`, `logd`, `rc-tee`, `session`, `bootlog`, `frontend`, `frontends/`, `os-release`, `issue`, `motd`, `hostname`, `conf.d/` |
| `lume-usb` | `usb-gadget`, `usb-storage`, `r36os-usb`, regras udev de USB |
| `lume-net` | `ssh-wifi`, `hostshare`, NetworkManager, dbus do Bluetooth |
| `lume-audio` | `mixer`, `jack`, `audiotest` |
| `lume-saves` | `savesync`, `persist` e os eventos |
| `lume-diag` | `selftest`, `hwinfo`, `hwsummary` |
| `lume-power` | `zram`, `sysctl.d`, regra do backlight |
| `lume-games` | `playlists`, `lume-index`, `systems.json`, `runners.d` |
| `lume-launcher-data` | `share/lume/` (i18n, temas, modelo de tema) e as fontes |
| `lume-retroarch-cfg` | `share/r36os/retroarch-*.cfg`, `factory`, `share/libretro/autoconfig` |
| `lume-shaders` | `share/libretro/shaders` |

  Regra de corte: o que sempre muda junto fica junto. Dependências pelo `depends` do `APKBUILD`
  (quase todos dependem de `lume-core`). O `rootfs/packages.txt` passa a listar os fragmentos.
- **Pacotes do kernel (tarefa 7.3, `src/r36os/kernel_packages.py`):** três pacotes por
  arquitetura, com o mesmo nome no armv7 (GA36) e no aarch64 (R36S): `lume-kernel`
  (`boot/zImage` ou `boot/Image`), `lume-modules` (`boot/modules.squashfs`, a imagem de módulos
  que é o slot `modules`) e `lume-dtbs` (`boot/dtbs/<soc>/*.dtb` e `boot/dtbs/<soc>/vendor/*.dtb`,
  com a pasta do SoC, não a do console). `pkgver` = versão do kernel fixada
  (`kernel.KERNEL_VERSION`), `pkgrel` calculado (mínimo 0).
  - **Onde ficam os arquivos:** em `/boot/...` dentro do pacote. Eles **nunca** são instalados
    no rootfs (não estão no `rootfs/packages.txt`): o console lê o kernel e os DTBs da BOOT e os
    módulos do slot. O pacote é a forma versionada, assinada e indexada desses arquivos.
  - **Sem compilar e sem qemu:** o kernel continua compilado fora do `abuild`
    (`kernel.build_kernel` → `out/<console>/kernel/`). A etapa `kernel packages` do
    `build_console_kernel` só embrulha esses arquivos: o `.apk` é escrito em Python (segmento de
    dados com dono `0:0`, modo 0644/0755, mtime = data fixa do kernel (D4) e o registro pax
    `APK-TOOLS.checksum.SHA1` de cada arquivo, como o `abuild-tar --hash`; `.PKGINFO` com
    `datahash`). Não há `APKBUILD`: nada a compilar, e assim o pacote não entra no
    `local_aports()` nem no `build_packages`. Conferido com o `apk` do builder: `apk index
    --rewrite-arch armv7` e `apk add --root` instalam o pacote e gravam os checksums.
  - **Versão pelo conteúdo (D3):** cada pacote tem o seu hash de entradas (nome, versão,
    arquitetura, o próprio `kernel_packages.py` e o SHA256 de cada arquivo). Entradas iguais às do
    `hashes.json` (arquivo presente) → nada é feito. Senão o `.apk` é feito em
    `out/pkg-staging/kernel-<arch>/` com o `pkgrel` seguinte e passa pelo mesmo `_settle` dos
    fragmentos: conteúdo igual ao publicado → descartado, a versão fica e o `hashes.json` só liga
    as entradas novas a ela; diferente → `.lume-content`, assinatura, `out/repo/<arch>/`,
    `hashes.json` e índice. Cada pacote decide sozinho: um DTB novo só muda o `lume-dtbs`. Como o
    kernel é reprodutível (D4, D5), um patch que só toca um driver do GA36 deixa os três pacotes
    do aarch64 com as mesmas entradas e a mesma versão.
  - **BOOT e slot vêm dos pacotes publicados:** depois de publicar, a etapa extrai os dados das
    três versões que o `hashes.json` aponta (conferidas pelo `.lume-content`) para
    `out/<console>/kernel-pkg/` (trocada inteira, com `PACKAGES` = `<nome> <versão>`). O
    `console_boot_files` tira dali `<console>/zImage|Image` e `dtbs/<soc>/...`, e o
    `write_slot_set` tira dali o slot `modules` (`kernel-pkg/boot/modules.squashfs`). Os bytes
    são os do `out/<console>/kernel/`, então a lista da BOOT e o slot de um console cujo kernel
    não mudou ficam idênticos e o `push` para ele não manda nada. As imagens Android de painel
    do GA36 (fora da BOOT) continuam feitas de `out/ga36/kernel/`.

### D3. Versão pelo conteúdo, compilação pelo hash de entradas

```
 hash de entradas (APKBUILD, arquivos, código do repositório que ele empacota,
                   script de build, versões das dependências de build)
     igual ao do pacote mais novo? --> nao compila
 hash do conteudo (lista de arquivos com modo e SHA256, metadados do pacote)
     igual ao do pacote mais novo? --> nao publica versao nova (descarta o build)
     diferente                     --> publica com o pkgrel seguinte
```

- Os dois hashes vão no `.PKGINFO` (campo `commit` com o de entradas; um arquivo
  `.lume-content` no controle com o de conteúdo) e num índice local `out/repo/<arch>/hashes.json`
  para consulta rápida.
- O `pkgrel` do `APKBUILD` vira o mínimo; ninguém o sobe à mão.
- O mesmo vale para kernel, módulos e DTBs: um patch que só toca um driver do GA36 recompila
  incrementalmente os dois kernels, mas o `lume-kernel` do aarch64 sai com o mesmo conteúdo e não
  muda de versão.
- **Formatos (tarefa 4.0, `src/r36os/manifests.py`):**
  - `.lume-content`, no controle do `.apk`: uma linha `lume-content 1 <sha256>` (com `\n`).
  - Hash de conteúdo: SHA256 da listagem, uma linha por item, ordenada:
    `f <modo> <uid>:<gid> <sha256 dos dados> <caminho>`, `l <modo> <uid>:<gid> <sha256 do
    alvo> <caminho>`, `d <modo> <uid>:<gid> - <caminho>` (modo em 4 dígitos octais) e
    `m <chave> <valor>` para cada campo do `.PKGINFO`, menos os que mudam a cada build
    (`builddate`, `commit`, `datahash`, `size`, `packager`) e com o `pkgver` sem o `-rN`.
    `content_entries(pkgdir)` lê a árvore do `pkgdir` (dono `0:0` por padrão).
  - Hash de entradas: SHA256 das linhas ordenadas `<rótulo> <sha256>` de cada entrada
    (`inputs_hash`); quais entradas entram é decisão do build do fragmento (6.1). No
    `.PKGINFO`, `commit = <40 primeiros dígitos>` (`commit_of_inputs`), no formato de um
    commit do git, que o `apk` espera nesse campo; o índice guarda os 64.
  - `out/repo/<arch>/hashes.json`: `{"format": 1, "arch": "<arch>", "packages": {"<nome>":
    {"version": "<pkgver>-rN", "inputs": "<sha256>", "content": "<sha256>", "file":
    "<nome>-<pkgver>-rN.apk"}}}`, pacotes por nome, gravado por rename. Ausente = índice
    vazio (primeiro build); JSON truncado, chave a mais ou a menos, hash que não tem 64
    dígitos hexadecimais ou `file` que não bate com nome e versão → erro.
- **Build incremental (tarefa 6.1, `src/r36os/fragments.py` + `src/r36os/packages.py`):**
  - **Entradas de um fragmento:** todo arquivo do diretório do aport (`APKBUILD` com o `pkgrel`
    commitado, arquivos ao lado, e o `stage/` que o `lume.stage()` monta, ou seja, o código de
    `lume/` e o `Cargo.lock`), menos as pastas de trabalho do `abuild` (`src/`, `pkg/`,
    `tmp/`) e, dentro de `stage/`, as pastas `target/` (cache do cargo) e `vendor/` (as crates,
    fixadas pelo `Cargo.lock` e pelo nome do tarball em `.cargo/vendor-tarball`, que entram);
    o texto do script de build do `packages.py` (sem o `commit` e sem o distcc, que não mudam o
    resultado); a receita da imagem `builder` (versão do Alpine + `builder.Containerfile`); e o
    hash de conteúdo de cada dependência de build local (`makedepends*`/`checkdepends` que
    estão no `hashes.json`, inclusive subpacotes como `mesa-dev`). Dependências de runtime
    (`depends`) não entram: não mudam o que é compilado. Atualizações do Alpine dentro da
    mesma versão não são detectadas (use `--force`). A ordem do build põe a dependência local
    antes de quem a usa, então um build sem mudanças nunca vê um hash de dependência diferente.
  - **`pkgrel` calculado sem editar o `APKBUILD`:** uma cópia gerada do `APKBUILD` com
    `pkgrel=` trocado fica em `out/pkg-staging/apkbuild/<arch>/<nome>/` e é montada **por
    cima** de `/aports/r36os/<nome>/APKBUILD` no container (bind mount de arquivo): o
    `startdir`, o `stage/` e o caminho do cache do cargo continuam os mesmos, sem copiar o
    aport. O `pkgrel` é o maior entre o do `APKBUILD` (mínimo), o seguinte ao de cada arquivo
    publicado com o mesmo `pkgver` e o seguinte à versão do `hashes.json`. Um `pkgrel`
    compilado mas descartado (conteúdo igual) é reaproveitado no build seguinte: ninguém o viu.
  - **`commit`:** o `abuild` 3.17 grava `commit = $ABUILD_LAST_COMMIT` no `.PKGINFO` e só
    consulta o git quando a variável está vazia; o script passa
    `ABUILD_LAST_COMMIT=<40 dígitos>` na linha do `abuild`. Conferido no pacote gerado.
  - **`.lume-content`:** o hash de conteúdo é lido do próprio `.apk` gerado (segmento de dados:
    arquivo, modo, dono e SHA256; link; diretório; link físico conta como arquivo), com o
    `.PKGINFO` sem os campos voláteis e com a versão do próprio build (`<pkgver>-rN`) trocada
    por `<pkgver>` em todo campo (o `abuild` grava `provides = cmd:x=<ver>` e o `install_if`
    do `-doc`, que mudariam a cada `pkgrel`). Para publicar, o Python refaz o segmento de
    controle com os membros do `abuild` na ordem (`.PKGINFO` primeiro) mais `.lume-content`,
    sem os blocos de fim (como `abuild-tar --cut`), e o `abuild-sign` do builder x86_64 assina
    de novo; o segmento de dados fica byte a byte (o `datahash` continua valendo). O `apk` 3.0.9
    instala o pacote com a chave local e ignora o arquivo extra
    (`tests/integration/test_fragment_versions.py`).
  - **Adoção sem build (primeiro build após o merge):** um aport sem entrada no `hashes.json`
    cujo pacote principal e todos os subpacotes (`subpackages=` com `$pkgname` expandido) já
    têm a versão mais nova publicada em `out/repo/<arch>/` (todas iguais, com o `pkgver` do
    `APKBUILD` e `pkgrel` não abaixo do dele) é **adotado sem compilar**: o hash de conteúdo
    sai do `.apk` publicado, o `hashes.json` grava as entradas atuais apontando para esse
    arquivo e o log diz `pkg <n>: adopted <arquivo> (no build)`. Assim o RetroArch e os cores
    não recompilam sob qemu (horas): eles ficam com os pacotes de hoje nesta change (P-80).
    Só compila o aport sem nada publicado, ou com subpacote/versão faltando; `--force` sempre
    compila. Vale também para os noarch (o arquivo precisa estar nas três arquiteturas).
  - **Decisão:** entradas iguais às do `hashes.json` (e arquivos presentes) → não compila.
    Senão compila numa área de preparo (`out/pkg-staging/<arch>/`, com `out/repo` como
    repositório para as dependências locais) e compara o conteúdo com o da versão publicada
    (do `hashes.json`; sem ele, o do `.apk` mais novo em `out/repo/<arch>/`). Conteúdo igual → não publica e
    o `hashes.json` passa a ligar as entradas novas ao arquivo já publicado (o `commit` do
    `.apk` continua o das entradas que o geraram). Diferente → publica todos os pacotes do
    aport (principal e subpacotes) com o `pkgrel` novo, grava o `hashes.json` e refaz o índice.
    `--force` (`r36os pkg --force`, e `rebuild_packages` do `build`) compila mesmo com entradas
    iguais; conteúdo igual continua sem publicar. O `build` passa todos os aports locais para o
    `build_packages`, que decide sozinho.
  - **Noarch:** `build_noarch` aplica a mesma regra contra o `hashes.json` das três
    arquiteturas e devolve só os `.apk` alterados, já assinados com `.lume-content`, com o hash
    de entradas completo em `<apk>.inputs` ao lado; `publish_noarch` copia, grava o
    `hashes.json` de cada arquitetura, limpa e refaz os índices.
  - **Limpeza:** depois de publicar (e no fim de todo `build_packages`), cada pacote de
    `out/repo/<arch>/` fica com a versão mais nova e a anterior; nunca sai uma versão citada no
    `manifest*.txt` do build `latest` ou `flashed` de cada imagem em `out/images/`, nem o
    arquivo que o `hashes.json` aponta. Uma linha diz quantos arquivos saíram e o espaço
    liberado; havendo remoção, o índice é refeito. No `out/repo` de 2026-11-17 isso tira 59
    arquivos (72,5 MiB) do armv7 e 40 (38,6 MiB) do aarch64; o `retroarch` fica com 4 versões
    porque o build `flashed` do console e o `latest` da VM citam r108 e r110.

### D4. Data fixa do kernel e `VERSION` fora da comparação

- `KBUILD_BUILD_TIMESTAMP` passa a ser fixo (data de lançamento da versão do kernel). Com a data do
  último commit, um patch do GA36 mudava a string de versão do kernel do R36S.
- O `VERSION` da `BOOT` não entra na comparação do `push` nem nos testes de "igual byte a byte";
  ele é enviado só quando outro arquivo é enviado.

### D5. Kernel incremental com git, sem regravar arquivos

- Árvore em `.cache/src/linux-<versão>/`, repositório git próprio: commit do tarball intocado
  (tag `upstream`).
- A série nova é montada **fora da árvore de trabalho**: índice temporário (`GIT_INDEX_FILE`) a
  partir de `upstream`, `git apply --cached` de cada patch, `write-tree` e `commit-tree`. Depois,
  `git read-tree -m -u <commit antigo> <commit novo>` troca só os arquivos de conteúdo diferente,
  e só eles ganham data nova. Um `git checkout upstream` antes da série nova regravaria todos os
  arquivos tocados por algum patch.
- Pasta de build fixa `.cache/kbuild/<arch>/`; o `make` incremental recompila o que depende dos
  arquivos novos. O `ccache` continua.
- `GIT_CEILING_DIRECTORIES` mantido.
- O primeiro uso importa a árvore (2 GB) no git uma vez.
- Medido (2026-11-17): um patch num driver só do GA36 recompila 6 objetos no armv7 e nenhum no
  aarch64. Se o patch só muda um comentário, o `zImage` sai idêntico byte a byte, o `lume-kernel`
  não é reempacotado e o `push` não manda kernel nenhum (build em 1 min 53 s). Com código de
  verdade, só o `lume-kernel` do armv7 sobe de `pkgrel` (build em 2 min 21 s, 7.3).

### D6. Etapas puladas e build pontual

- Cada etapa grava `<saída>.inputs` com o hash de entradas; igual e com saída presente → pulada,
  numa linha. `r36os build --clean` força tudo.
- Entradas dos DTBs: os `.dts`/`.dtsi` e só os patches que tocam
  `Documentation/devicetree/`, `include/dt-bindings/` ou `arch/*/boot/dts/` (lidos das linhas
  `diff --git` de cada patch). Um patch de driver não revalida os ~170 DTBs.
- Rootfs: a lista de fragmentos e pacotes, os `APKINDEX` (local e do espelho do Alpine), o
  idioma e o script.
- `r36os build <fragmento>... [--console ga36|r36s]` compila os fragmentos pedidos, remonta só os
  slots que os contêm e grava um conjunto novo no arquivo do build (D10), sem imagem `.img`.
  `r36os build console` faz tudo e gera a imagem.

### D7. Compilação sem emulação

- **`lume-launcher` (P-61):** primeiro passo, o `target/` do cargo num volume
  `.cache/cargo/<arch>` (recompila só as crates do lume, ainda sob qemu). Segundo passo, cross no
  x86: `cargo build --target armv7-unknown-linux-musleabihf` / `aarch64-unknown-linux-musl`, com
  a sysroot da arquitetura instalada por `apk --root --arch <arch> --no-scripts` (sem emulação) e o
  mesmo Rust do Alpine (1.96). O `abuild` só empacota o binário. Verificação: o binário roda no
  aparelho e os testes do `lume-ui` passam.
- **Segundo passo (9.2), como ficou** (`src/r36os/lume_cross.py`): o cargo roda no container
  x86_64 com o `rust` do Alpine 3.24 (1.96.1-r0). Provas curtas:
  1. O rustc x86_64 do Alpine já traz embutidos todos os alvos `*-alpine-linux-musl*`
     (`armv7-alpine-linux-musleabihf`, `aarch64-alpine-linux-musl`), com o mesmo target spec
     do rustc nativo (`--print target-spec-json` idêntico). A std do alvo sai do pacote
     `rust` da própria arquitetura, mesma versão e release, extraída só em
     `usr/lib/rustlib/<triple>`: o rustc x86 a carrega sem queixa. O plano B (std oficial de
     `*-unknown-linux-musl*`) não foi preciso. Se a versão do `rust` x86_64 e a do alvo
     divergirem (espelho no meio de uma atualização), o build para com a mensagem e
     `R36OS_LUME_CROSS=0` volta ao build nativo.
  2. Ligador: o `clang` do Alpine como driver (`--target`, `--sysroot`) com o GNU ld do
     `binutils-<arch>` do Alpine x86_64 (2.45.1-r1, o mesmo binutils do build nativo), e
     crt, libgcc, musl e SDL2 de uma sysroot instalada por `apk --root --arch <arch>
     --initdb --no-scripts` (`musl-dev gcc sdl2-dev`, chaves do Alpine da arquitetura mais
     a chave do repositório local), guardada em `.cache/lume-cross/<arch>/` e atualizada com
     `add -u` a cada build. O `lld` também liga, mas o GNU ld deu os mesmos tamanhos do
     pacote publicado; ficou o GNU ld. O link line do clang é o do gcc do Alpine (Scrt1,
     crtbeginS, `-z now -z relro --hash-style=gnu --build-id`, `--as-needed -lgcc_s`).
  3. O `sdl2-sys` (sem `use-pkgconfig`) só emite `-lSDL2`; mesmo assim o script exporta
     `PKG_CONFIG_SYSROOT_DIR`/`PKG_CONFIG_LIBDIR` da sysroot para um `-sys` futuro.
  4. Caminhos: o workspace é montado em `/aports/r36os/lume-launcher/stage/lume`, o mesmo do
     `abuild`; os binários só trazem `/rustc/<hash>/...` da std, como antes. As flags vêm do
     `default.conf` do `abuild` do alvo (o aarch64 liga com `pack-relative-relocs`, o armv7
     não). ELF igual ao publicado: interpretador, `NEEDED`, `BIND_NOW`/`PIE`, atributos ARM
     (v7, VFPv3-D16, hard-float) e tamanhos (aarch64: os 3 iguais; armv7: `lume-run` e
     `lume-index` iguais, `lume-ui` com uma página a mais). Os bytes não são iguais: o hash
     de metadados de cada crate no cargo inclui o host do rustc e o `--target`, então os
     nomes de símbolo e a ordem das funções mudam (o código é o mesmo onde se comparou). Dois
     builds cruzados seguidos dão o mesmo conteúdo. Lista de arquivos, modos e dependências
     (`so:libSDL2`, `so:libgcc_s`, `so:libc.musl-*`, sdl2, retroarch, love) do `.apk` iguais
     às do r27 publicado.
- **Como roda:** `_build_fragment` do `lume-launcher` em armv7/aarch64 chama
  `lume_cross.build()` (container x86_64; `target/` em `.cache/cargo/<arch>-cross`, separado
  do nativo porque os build scripts são x86) e monta os binários em `/lume-prebuilt` no
  container da arquitetura com `LUME_PREBUILT`; o APKBUILD então só confere e instala os
  binários. O empacotamento usa `abuild -d` com `apk add sdl2 font-roboto` (o `sdl2` é o
  que o `abuild` usa para achar o `so:libSDL2`): com `-r` ele instalava sob qemu os ~160
  pacotes das dependências de execução (retroarch, love, mesa) só para empacotar. O script
  cruzado entra no hash de entradas: trocar de modo recompila e o conteúdo novo ganha
  pkgrel novo. `R36OS_LUME_CROSS=0` volta ao build de antes (cargo sob qemu com o cache da
  9.1). O x86_64 continua nativo.
- **Tempos medidos** (`build_packages(..., force=True)` com `-j 4`, num `out/` e `.cache/`
  de rascunho): com uma linha mudada no `lume-core` (recompila core, index e ui), armv7
  60 s e aarch64 55 s, do início à publicação (cargo 31 s / 29 s, empacotamento 13 s / 5 s);
  sem mudança no código (`--force`), 38 s; primeira vez (sysroot, downloads e tudo
  compilado), aarch64 127 s. Linhas de base: 8m24s sob qemu, 3m55s com o cache da 9.1.
- **Cores e RetroArch: fora desta change** (decisão do usuário, 2026-11-16, durante a prova da
  9.3: "vamos deixar os cores para uma change só de cores"). Nesta change os cores continuam os
  pacotes de hoje, sem recompilar. O que segue fica como registro e ponto de partida da change de
  cores (P-36); o código mesclado fica desligado por padrão e nada dele foi provado (a compilação
  do gcc cruzado foi interrompida no começo).
- **Cores e RetroArch (P-36), plano original:** uma prova decide o caminho entre (a) `distcc` com compiladores
  x86 que geram código musl da arquitetura, com o mesmo gcc do Alpine 3.24, mantendo o `abuild` no
  container da arquitetura, e (b) cross completo do `abuild` (`CBUILD`/`CHOST`). Começa por (a),
  que muda menos o pipeline. Critério: o mesmo `manifest`, e os cores rodam iguais no aparelho.
  Com o D3, um core só recompila quando muda.
- **Prova do P-36 (9.3), caminho escolhido: (a) `distcc`.** Levantamento no Alpine 3.24: o gcc
  dos alvos é o `15.2.0-r5` (armv7 e aarch64, igual ao x86_64) e o binutils `2.45.1-r1`. O
  Alpine publica `binutils-armv7` e `binutils-aarch64` para x86_64 na mesma versão, mas não
  publica gcc cruzado para musl (só `gcc-arm-none-eabi` e afins, sem libc). O gcc cruzado sai do
  próprio APKBUILD `main/gcc` do aports 3.24-stable (commit `fd4fecac`, fixado em
  `src/r36os/distcc.py`), como o passo "Full cross GCC" do `scripts/bootstrap.sh`, mas com o
  `musl-dev` e o `libucontext-dev` do repositório binário do alvo na sysroot (sem `gcc-pass2`
  nem musl recompilado): `CTARGET=<arch> BOOTSTRAP=nobase LANG_D=false LANG_ADA=false abuild`.
  Mesmo fonte, mesmos patches e o mesmo `configure` do gcc nativo (inclusive
  `--with-arch/--with-fpu/--with-float/--with-mode` do armv7); a diferença é só não ter o
  bootstrap de 3 estágios, que não muda o código gerado. O script é
  `containers/cross-gcc.sh` e confere que o repositório do alvo ainda tem a mesma versão
  (gcc novo no Alpine = refixar o commit). As fases deps, fetch, unpack e prepare já passaram
  no x86_64.
- Funcionamento: o `abuild` continua no container emulado (pré-processamento, link e
  empacotamento sob qemu); o `ccache` entrega cada falha ao `distcc` (`CCACHE_PREFIX`) e o
  `distccd` roda nativo num container próprio (`localhost/r36os-distcc:<arch>`, sem gcc x86),
  onde `/usr/bin/cc`, `gcc`, `g++` e `c++` são o gcc cruzado, só em loopback, uma porta por
  arquitetura, com `nice`/`ionice` e o rótulo da proteção de calor. `DISTCC_FALLBACK=0`: uma
  falha remota quebra o build em vez de compilar escondido sob qemu. Opt-in por pacote:
  `R36OS_DISTCC=<nome>[,...]` ou `all`; sem a variável nada muda. O `ccache` do distcc é
  separado (`.cache/ccache/<arch>-distcc`) até a prova mostrar objetos iguais;
  `R36OS_CCACHE=0` desliga o cache para medir.
- Decisão pendente da prova (sessão principal): o mesmo `.so` do snes9x2005-plus pelo qemu e
  pelo distcc (sha256 igual, ou diferença explicada) e o core rodando um jogo no GA36. Se o
  objeto divergir sem explicação, ou o pré-processamento sob qemu dominar o tempo, o caminho
  (b) entra na fila.
- Alternativa: deixar tudo sob qemu. Rejeitada: o hash evita recompilar, mas quando o fragmento
  muda, a espera continua de minutos a horas.

### D8. Prioridade e número de tarefas

- O `podman` roda sob `nice -n 19 ionice -c 3`: a prioridade passa para conmon e o container,
  sem exigir `ionice` em cada imagem.
- `--jobs N` / `R36OS_JOBS` em `build`, `pkg` e `push`; padrão metade dos núcleos (mínimo 1).
  Vira `-j` do `make`, `JOBS` do `abuild`, `-processors` do `mksquashfs`, threads do zstd e as
  tarefas do `distcc`.
- O `nice` deixa a máquina responsiva; o calor só cai com menos tarefas. A medição separa os dois.
- Reserva: `systemd-run --user --scope -p CPUQuota=…` se o limite de tarefas não bastar.

### D9. Slots e manifesto no cartão

```
 BOOT/<console>/
   Image | zImage            (nome fixo: o U-Boot de fabrica le)
   SLOTS                      manifesto do conjunto: nome, arquivo, sha256, versoes dos fragmentos
   SLOTS.old                  o conjunto anterior
   slot/base-<sha12>         base do Alpine (bibliotecas, busybox, OpenRC)
   slot/runtime-<sha12>      RetroArch e os cores, mesa/drivers de video, SDL
   slot/lume-<sha12>         fragmentos do projeto + banco do apk + saidas de triggers
   slot/modules-<sha12>      modulos do kernel
 BOOT/dtbs/<soc>/...          (como hoje)
```

- **Nomes pelo conteúdo:** um slot novo nunca tem o nome de um slot em uso. O `push` copia os
  slots novos, confere, e troca o conjunto com um único rename (`SLOTS.new` → `SLOTS`, o antigo vira
  `SLOTS.old`). Corte de energia antes do rename: conjunto antigo inteiro; depois: conjunto novo
  inteiro. Os slots não citados por `SLOTS` nem por `SLOTS.old` são apagados no push seguinte.
- **Boot:** o initramfs lê `SLOTS` (ou `SLOTS.old` se o primeiro falta ou cita um arquivo
  ausente) e monta `lume`, `runtime` e `base` como `lowerdir` (de cima para baixo) e o `modules`
  como hoje. Sem `SLOTS`, monta o `<console>/SYSTEM` antigo (cartão antigo continua iniciando).
- **Separação:** o rootfs completo continua sendo montado por `apk add --root`, e cada arquivo vai
  para o slot do pacote dono (pelo banco do `apk`); arquivos sem dono ou de vários grupos
  (`/lib/apk/db`, `/etc/apk/world`, saídas de triggers como cache de fontes e mime) vão para o
  `lume`, o slot de cima, para que uma mudança num grupo não mude a base. Teste: todo arquivo do
  rootfs está em exatamente um slot. O mapa grupo → pacotes fica em `rootfs/slots.toml`.
- **Montagem no build (tarefa 4.4, `src/r36os/slots.py`):** o arquivo de um pacote que foi
  alterado depois da instalação (conteúdo diferente do `Z:` do banco do `apk`: `configure.sh`,
  overlay, idioma de fábrica) também vai para o `lume`, e assim a base não muda por causa
  deles. O diretório vai para o slot do dono e para todo slot que tem algo dentro dele, com o
  mesmo cabeçalho. O link físico cujo alvo ficou em outro slot vira arquivo. O pacote que
  nenhum grupo cita cai no `default` (`base`), e o teste lista os de `packages.txt` e
  `hw-packages.txt` que caíram assim. Etapa `slots` do build (pulada quando o conteúdo do
  `rootfs.tar`, sem os tempos, o `slots.toml` e as opções não mudam) grava
  `out/<console>/slot/{base,runtime,lume}-<sha12>` e `overlay.json`; a etapa `slot set`, em
  todo build, copia `kernel/modules` para `modules-<sha12>`, confere os 448 MiB e escreve o
  `SLOTS` com o build. Medido em 2026-11-17 (rootfs atuais): GA36 base 19,6 + runtime 259,0 +
  lume 2,3 + modules 1,3 = 282,2 MiB; R36S 21,5 + 262,2 + 2,3 + 15,0 = 301,0 MiB (o `SYSTEM`
  tinha 280,9 e 286,0 MiB). A união dos três slots é igual ao `SYSTEM` (nomes, tipos, modos,
  donos, tamanhos e conteúdo).
- **BOOT da imagem nova:** o `build console` grava só `<console>/SLOTS` e `<console>/slot/`
  (sem `SYSTEM` e sem `<console>/modules`, que o slot `modules` substitui). A conta dos 64 MiB
  livres soma cada slot duas vezes (o conjunto anterior que o push guarda, tomado do tamanho
  do novo); com os tamanhos acima (mais kernels, DTBs e arquivos de fábrica, ~65 MiB), a
  `BOOT` de 2 GiB fica com cerca de 790 MiB livres nessa conta (~1,37 GiB na imagem gravada).
- **Coerência:** cada slot grava o sha dos slots de baixo contra os quais foi montado; o
  manifesto só é gerado com um conjunto coerente, e o push nunca manda um slot sem o resto do
  conjunto que ele exige.
- **Cores:** nesta change ficam no slot `runtime`, com o RetroArch. Um slot `core-<nome>` por
  core, montado depois do frontend e trocado sem reinício, saiu para a change de cores (P-80); o
  formato do `SLOTS` já aceita as linhas `core-<nome>` (reservadas, nenhum build as gera aqui).
- **Formato do `SLOTS` (tarefa 4.0):** texto por linhas, campos separados por um espaço, sem
  JSON, para o `awk` do busybox. Leitores iguais em `src/r36os/manifests.py` (`read_slots`,
  `write_slots`) e `initramfs/lib/slots.sh`:

  ```
  lume-slots 1
  build 20261116-214233
  console ga36
  slot base slot/base-<sha12> <sha256> <bytes> -
  pkg base musl 1.2.5-r10
  slot runtime slot/runtime-<sha12> <sha256> <bytes> base=<sha256>
  slot lume slot/lume-<sha12> <sha256> <bytes> base=<sha256>,runtime=<sha256>
  pkg lume lume-core 1.0-r3
  slot modules slot/modules-<sha12> <sha256> <bytes> -
  slot core-snes9x slot/core-snes9x-<sha12> <sha256> <bytes> base=<sha256>,runtime=<sha256>
  end 5 2
  ```

  - Cabeçalho fixo: `lume-slots <formato>` (hoje 1), `build <id>`, `console <nome>` (o leitor
    recusa o manifesto de outro console).
  - `slot <nome> <arquivo> <sha256> <bytes> <de baixo>`: o arquivo é relativo a
    `<console>/` e é sempre `slot/<nome>-<12 primeiros dígitos do sha256>`; `<de baixo>` é `-`
    ou `<slot>=<sha256>,...`, os slots contra os quais este foi montado, que têm de estar
    acima dele no arquivo e com o mesmo sha256 (conjunto coerente).
  - Ordem fixa: `base`, `runtime`, `lume`, `modules` (os quatro obrigatórios) e os `core-<nome>`
    por nome. A ordem do overlay é a do arquivo: `base` embaixo, `lume` em cima.
  - `pkg <slot> <pacote> <versão>`: os pacotes (fragmentos e do Alpine) de cada slot, logo
    depois da linha dele; o log do boot mostra as versões por eles.
  - `end <linhas slot> <linhas pkg>` fecha o arquivo. Sem ele, com contagens diferentes, sem
    `\n` no fim, com linha desconhecida ou campo fora do formato, o manifesto é inválido.
  - No boot, o sha256 dos slots não é lido (custaria a leitura inteira; o `push` confere antes
    da troca), só a presença de cada arquivo citado. `slots_pick <boot> <console>` devolve
    `<console>/SLOTS` ou, com uma linha `lume: ERROR: <console>/SLOTS <motivo>; using
    <console>/SLOTS.old from the previous build`, o `SLOTS.old`; falha quando nenhum serve, e
    então o init monta o `<console>/SYSTEM` antigo (sem linha de log no cartão antigo, que não
    tem nenhum dos dois). `slots_list <boot> <manifesto> overlay|modules|cores|all` lista
    `<nome> <caminho na BOOT> <sha12>` na ordem de montagem; `slots_lowerdir` monta o
    `lowerdir` (de cima para baixo); `slots_packages` e `slots_build` dão o que vai ao log.
- Limites: a soma dos slots de um console no máximo 448 MiB; a `BOOT` com ao menos 64 MiB livres,
  contando o conjunto anterior (spec `system-image`).
- Alternativa: três camadas fixas e `.old` por arquivo (desenho anterior). Rejeitada: a troca
  por arquivo deixa conjuntos mistos depois de um corte de energia.

### D10. Arquivo do build por conteúdo; push sem descompactar

```
 out/images/objects/<sha256>              cada arquivo da BOOT, uma vez
 out/images/console/<build>/boot-files.sha256
 out/images/console/<build>/console-<build>.img.zst   so no build console
```

- Todo build (inteiro ou pontual) grava os objetos e a lista. O `push` lê os objetos de qualquer
  build arquivado, sem descompactar. O `flash` usa o `.img.zst` se houver, ou monta a imagem a
  partir dos objetos.
- A imagem é comprimida com várias threads (limite do D8). O `r36os clean` apaga objetos que
  nenhum build guardado cita.
- **Formatos (tarefa 4.0, `src/r36os/manifests.py`):** a `boot-files.sha256` continua com as
  linhas do `sha256sum` (`<sha256>  <caminho na BOOT>`, dois espaços, `\n` no fim), lida hoje
  por `image.read_boot_list` e pelo `push`: caminhos ordenados e o `VERSION` por último e
  obrigatório (sem ele no fim, a lista está truncada). Caminho absoluto, com `..`, repetido,
  ou linha no modo binário (` *`) → erro. Cada arquivo da lista é
  `out/images/objects/<sha256>` (nome = sha256 do conteúdo, 64 dígitos hexadecimais);
  `store_object` copia por um `.tmp` e rename e não regrava um objeto que já existe;
  `missing_objects` diz quais faltam.

### D11. Política de reinício

- **Padrão: reiniciar.** Slots do boot e kernel só trocam com o sistema parado; a troca do
  conjunto é atômica e cada atualização prova o boot.
- **Sem reinício:** só o `push --hot <fragmento>` (a troca de core sem reinício saiu com os
  cores para o P-80) —
  extrai os arquivos do `.apk` na camada gravável em RAM e reinicia os serviços do fragmento (os
  `init.d` que ele traz, ou os listados no `APKBUILD` em `_lume_restart`); some no reboot e deixa
  uma linha `push hot <fragmento> <versão>` no `events.log`. Kernel, módulos e `base` não aceitam
  `--hot`.
- Alternativa: slot do projeto fora do overlay (`/opt/lume` com links fixos) para trocar sem
  reboot. Rejeitada: acopla a base a cada caminho do projeto; o `--hot` cobre a iteração.

### D12. `r36os dev` e push que confere

- Ao fim do `push` (sem `--no-wait`): espera o console sumir e voltar pelo cabo, lê o log do boot
  novo e confere `boot OK completed`, os slots do `SLOTS` montados e as versões dos fragmentos
  enviados; imprime `ok` ou o que divergiu, com os tempos (envio, boot).
- `r36os dev wait | sh <cmd> | shot <arquivo> | keys <seq> | log | check`: os helpers do `dev.py`
  da change `lume-launcher` (opções de ssh sem chave conhecida, botões por `input_event` no pad
  virtual, combinações no pad do kernel, `r36os-shot`), com os números de evento lidos de
  `/proc/bus/input/devices` em cada console. `check` roda o `selftest` no modo do aparelho e devolve
  passou ou falhou.
- O `selftest` ganha um modo de aparelho (sem os casos só da VM), que o `dev check` aciona.

### D13. Validação no aparelho no lugar da VM

- O build e o teste da imagem `vm` saem do ciclo desta change; o código do alvo `vm` fica, sem
  slots (continua com um `SYSTEM`), e pode quebrar sem aviso: pendência nova para voltar a
  construí-la e testá-la.
- A liberação de um build de console passa a exigir `r36os dev check` verde no GA36 e no R36S
  (spec `vm-validation`, modificada).

### D14. Medição e limpeza

- Tempo por etapa no fim de todo build (inclusive `skipped` e em erro).
- Antes e depois: build completo (cache frio), sem mudança, patch num driver, mudança num
  script, mudança no `lume-launcher`; push e boot depois de cada um; temperatura máxima da CPU
  (`hwmon` do host, amostrada durante o build). Tabela neste design.
- As gerações antigas de `linux-<versão>-*` e `kbuild/<console>-*` são apagadas com o espaço numa
  linha; o `repo-clean` conhece o layout novo.

### D15. Proteção de calor do PC

Medido no PC do usuário (2026-11-16, parado): AMD Ryzen 7 5700G, 16 threads, `amd_pstate`
ativo, boost ligado, EPP `balance_performance`; `k10temp` Tctl 37 °C; NVMe 28 °C (crítico 89,85
°C); no `nct6798`, `AUXTIN0` 90 °C e `AUXTIN3` 97 °C **com o PC parado**: entradas auxiliares sem
sensor ligado, que não servem para medir nada. O limite do 5700G é 95 °C (Tjmax).

- **Sensor:** o hwmon do processador (`k10temp` Tctl, `zenpower`, ou `coretemp` Package em Intel),
  achado pelo nome; nunca as entradas auxiliares de chips da placa-mãe. `R36OS_TEMP_SENSOR`
  escolhe outro. Também o disco onde fica o cache do build, pelo volume de escrita: achado pelo
  `/proc/self/mountinfo` (o `st_dev` do btrfs é virtual) e lido do hwmon dele, `nvme` Composite
  ou `drivetemp` (SATA). **Correção do usuário (2026-11-17):** o sistema e o build ficam num SSD
  SATA (`sda`, Kingston SA400); o NVMe do PC não é usado pelo Linux, então a leitura dele não
  dizia nada (inclusive a coluna "Antes"). O SATA só tem sensor com o módulo `drivetemp`
  carregado; sem ele o build avisa no começo e segue só com a CPU.
- **Amostragem:** uma thread do `r36os` lê a cada 2 s durante todo o build e todo container.
- **Ação (histerese):** CPU ≥ `R36OS_TEMP_MAX` (padrão 85 °C) ou disco do build ≥ máximo dele − 5 °C →
  `podman pause` dos containers do build, com uma linha na saída; retoma com CPU ≤ máximo − 10 °C.
  Se a CPU passar de 92 °C mesmo pausado por 60 s (refrigeração com problema), o build aborta com
  a mensagem do que foi lido.
- **Resumo:** temperatura máxima da CPU e do disco do build, tempo acima do limite e tempo pausado, no
  resumo por etapa (D14).
- **Ordem das defesas:** (1) limite de tarefas (D8) reduz o calor; (2) a pausa evita o pico;
  (3) `CPUQuota` pelo `systemd-run --user` fica de reserva. Desligar o boost ou mudar o EPP durante o
  build esfria muito o Ryzen, mas exige root: fica documentado como ajuste manual opcional, nunca
  feito pelo `r36os`.
- Alternativa: diminuir o `-j` em tempo real. Rejeitada: o `make` e o `abuild` não mudam o `-j`
  no meio da execução; a pausa do container funciona com qualquer ferramenta.

### D16. Perfil de desenvolvimento na compressão

- `r36os build <fragmento>` monta os slots com zstd nível 3 (`-Xcompression-level 3`); o `build
  console` usa o 19 como hoje. O nível entra no hash de entradas do slot, então um slot de
  desenvolvimento nunca é confundido com o de liberação.
- O slot de desenvolvimento fica maior (a conta dos 448 MiB vale para os dois; se estourar, o
  build pontual usa o nível 19 nesse slot e avisa).
- Implementação (6.5): `build_console_slots(..., level=)`; o nível 19 (`slots.LEVEL_FULL`) é o
  do `build console` e o 3 (`slots.LEVEL_FAST`) é o que o build de fragmento passa. As opções do
  mksquashfs (com o nível) entram nas entradas da etapa `slots`, então trocar de nível refaz os
  slots e a mesma etapa não refaz nada quando o nível é o mesmo. Se o conjunto rápido passa dos
  448 MiB, a etapa roda de novo no 19 (com o aviso `warning: ...`) e o registro fica com o hash do
  19: um build completo seguinte reaproveita, e um rápido seguinte tenta o 3 de novo.
- Medido (2026-11-17, divisão real do `rootfs.tar` do GA36, mksquashfs do builder, 8 processadores,
  tempo inclui o início do container, ~0,2 s): `lume` 0,4 s no 19 (2,3 MiB) contra 0,2 s no 3
  (2,5 MiB); `base` 1,4 s (19,6 MiB) contra 0,3 s (21,7 MiB); `runtime` 10,8 s (259,0 MiB) contra
  0,9 s (272,2 MiB). Os três juntos: 12,6 s contra 1,4 s; o conjunto fica ~7% maior (283 contra
  300 MiB, mais o módulo do kernel), bem abaixo dos 448 MiB. O `lume` sozinho já é pequeno hoje,
  então o ganho do build pontual de um fragmento nele é de décimos de segundo; o ganho grande é
  quando o `runtime` é refeito.

### D17. As duas arquiteturas em paralelo

- O `build console` roda as esteiras do armv7 e do aarch64 ao mesmo tempo, cada uma com metade do
  limite de tarefas (o total continua o do D8), sob a mesma proteção de calor.
- A saída de cada uma ganha prefixo (`[armv7]`, `[aarch64]`); o resumo por etapa separa as duas.
- O que é comum (árvore do kernel, fragmentos noarch) é feito uma vez antes de dividir.
- Visto na implementação (2026-11-17): o `abuild` trabalha em `<aport>/src` e `<aport>/pkg`, dentro
  da pasta `aports/` que as duas esteiras montam. Com o `lume-launcher` compilado no PC (D7), as duas
  chegavam ao empacotamento com dois segundos de diferença e o pacote armv7 levou os binários do
  aarch64 (`libc.musl-aarch64.so.1: path not found`). O passo do `abuild` de cada fragmento por
  arquitetura agora segura uma trava por nome de aport: o mesmo aport nunca é empacotado por duas
  esteiras ao mesmo tempo. Também têm trava a preparação da árvore do kernel, o `lume.stage()` e a
  criação da imagem do builder.

### D18. Cartão único: um console por vez no cabo

- O teste usa **um só cartão para os dois consoles** (decisão do usuário, 2026-11-16): o cartão é
  passado do GA36 ao R36S e de volta, então nunca há dois consoles ligados ao PC ao mesmo tempo.
  O desenho anterior (uma sub-rede por console, `10.55.1.1` no R36S, comandos nos dois em paralelo)
  saiu da change: o endereço continua `10.55.0.1` nos dois, e a spec `usb-otg` não muda.
- `r36os push`, `r36os dev` e o `flash` dizem qual console respondeu (o console informa a placa
  dele); `--console ga36|r36s` confere e recusa quando o ligado é o outro, para um comando pensado
  para um console não rodar no outro por engano.
- Um push feito por qualquer console grava a `BOOT` inteira, com os arquivos e os slots dos dois
  (`ga36/`, `r36s/`): o cartão passado ao outro console inicia com o conjunto novo dele sem outro
  push. As provas "nos dois consoles" são sequenciais, trocando o cartão.
- Se um dia houver dois cartões ligados ao mesmo tempo, a sub-rede por console volta como
  pendência própria.

### D19. `r36os dev watch` e capturas de referência

- `r36os dev watch <fragmento>` observa os arquivos de entrada do fragmento (inotify no PC); a
  cada mudança, espera 1 s sem novas mudanças, faz o build pontual e o `push --hot`, e mostra o
  resultado numa linha. Só fragmentos que aceitam `--hot`.
- `r36os dev shot --compare <tela>` captura a tela e compara com `tests/device/shots/<console>/<tela>.png`
  (diferença por pixel acima de um limiar marca falha e grava a imagem de diferença em `./cache/`);
  `--update` grava a captura como referência nova. As telas são alcançadas por sequências de botões
  descritas junto da referência. Sem jogos de teste nas capturas (privacidade dos ROMs de teste):
  cartão de demonstração com nomes inventados.

### D20. Ganhos rápidos do boot (parte do P-58)

- `rc_parallel="YES"` no OpenRC.
- Depois do `frontend` (runlevel `default` com `after frontend`, ou um runlevel novo disparado por
  ele): Bluetooth, NetworkManager, playlists do RetroArch, `lume-index` e o resumo de hardware do
  `hwinfo` (o resumo da tela antes do frontend continua, spec `boot-runtime`). O `r36os-usb` continua
  antes: o `push` e o `dev` dependem dele.
- Medido no aparelho: `boot OK completed` antes e depois, nos dois consoles; nenhum jogo abre
  antes de o que ele usa estar pronto.
- O resto do P-58 (kernel, initramfs, launcher) continua numa change própria.
- Medido no GA36 (2026-11-17): `boot OK completed` de 33–34 s para 19,6–21,7 s (com a raiz em
  slots, 20,5–21,6 s). O "boot" que o `push` mostra (37–45 s) conta do pedido de reinício até
  confirmar o boot pelo ssh: além dos ~21 s do kernel ao frontend, entram o desligamento do
  sistema antigo e o boot0 + U-Boot de fábrica (~15 s, P-43 e P-58) e a espera do PC entre as
  perguntas ao console (~6 s, no boot 153 o `boot OK completed` saiu às :56 e o primeiro ssh do
  PC chegou às :02).

## Risks / Trade-offs

- [Make incremental errado depois de mudar o `.config`] → o fragmento entra no hash, o
  `olddefconfig` regenera o `auto.conf`; teste compara o `Image` incremental com o de um build
  limpo.
- [Hash de entradas incompleto deixa passar uma mudança] → entradas listadas num lugar só por
  etapa; teste que muda cada entrada; `--clean`.
- [Pacote noarch ou montado no x86 recusado pelo `apk` da arquitetura] → é a primeira prova da
  fase do esqueleto (tasks 3.x).
- [Arquivos sem dono mudam a base a cada build] → vão para o `lume`; teste de separação.
- [Mounts a mais no boot] → três no overlay (antes um) e os cores depois do frontend; medido no
  aparelho, com o tempo do `boot OK completed` antes e depois.
- [Conjunto misto depois de corte de energia] → manifesto único com rename, `SLOTS.old` e slots
  com nome pelo conteúdo; teste de `storage.sh` com o manifesto faltando ou citando arquivo ausente.
- [`--hot` deixa o console num estado que não é de nenhum build] → só na RAM, some no reboot, e o
  `events.log` registra.
- [Cross do Rust ou dos cores gera código diferente] → mesmo Rust e mesmo gcc do Alpine; o
  binário passa nos testes e roda no aparelho; o caminho emulado continua como reserva.
- [Sem a VM, uma regressão só aparece no aparelho] → `r36os dev check` nos dois consoles a cada
  fase; o `selftest` em modo aparelho cobre os serviços.
- [Change grande] → fases com o sistema funcionando ao fim de cada uma; o esqueleto ponta a ponta
  vem cedo.
- [Sensor errado faz a proteção de calor pausar sempre ou nunca] → só o hwmon do processador; o
  build diz no começo qual sensor e qual leitura está usando, e falha se não achar nenhum (sem
  `R36OS_TEMP_SENSOR`).
- [Pausa no meio de uma etapa com tempo limite] → nenhum passo do build usa tempo limite de
  relógio; o tempo pausado aparece no resumo.
- [Duas esteiras em paralelo esquentam mais] → o total de tarefas não muda e a proteção de calor
  vale para as duas.
- [Cartão único: um comando pensado para um console roda no outro] → todo comando diz qual
  console respondeu, e `--console` recusa o outro.
- [Serviços depois do frontend atrasam algo que o usuário usa logo] → só o que o jogo não usa;
  o launcher mostra Wi-Fi e Bluetooth como "iniciando" até ficarem prontos.

## Migration Plan

1. O primeiro build cria a árvore git do kernel e as pastas fixas e apaga as antigas.
2. O `rootfs/overlay/` vira aports noarch; a imagem gerada continua com os mesmos arquivos nos
   mesmos caminhos (conferido pelo manifesto).
3. O cartão: o initramfs novo aceita os dois layouts; o primeiro `push` ou `flash --update` grava
   `SLOTS` e `slot/`, e o `SYSTEM` antigo é apagado no push seguinte.
4. Reversão: um cartão com `SLOTS` não inicia com o initramfs antigo; voltar exige `flash
   --update` com uma imagem antiga (a `ROMS` fica intacta).

## Medições

| Caso | Antes | Depois |
|---|---|---|
| build completo (cache frio) | 31 min 34 s (`-j16`) | |
| build sem mudança | 12 min 04 s | |
| patch num driver | 13 min 45 s | |
| mudança num script | 12 min 47 s | |
| mudança no `lume-launcher` | 8 min 24 s (só o pacote armv7) | |
| push + boot (launcher) | GA36: push 4 min 07 s (descompacta 644 MiB, manda `SYSTEM`, `zImage`, o `Image` do R36S e `VERSION`) + boot 33,6 s; sem mudança: 35 s, sem reinício | |
| `boot OK completed` (GA36 / R36S) | 34,2 s e 33,6 s / 24,4 s | |
| temperatura máxima da CPU (`k10temp` Tctl) | 95,4 °C (cache frio, 1074 s acima de 85 °C); 75–82 °C nos outros | |
| temperatura máxima do disco do build | sem leitura (o 37,9 °C medido era do NVMe que o build não usa; o SATA precisa do `drivetemp`) | |
| tempo pausado pela proteção de calor | 0 s (só registrando) | |

Medido em 2026-11-16 (1.2), com o código de antes desta change e a proteção de calor só
registrando. "Cache frio" = sem `.cache/src`, `.cache/kbuild` e `.cache/ccache` (renomeadas para
`*.antes-1.2`), com os pacotes de `out/repo` reaproveitados; esse caso rodou com o `-j$(nproc)`
de hoje (16) e esquentou até o Tjmax do 5700G, então os outros rodaram com `-j8` (troca
temporária, desfeita) e com a CPU esfriada a ~50 °C antes de cada um. Patch de driver = um
comentário num arquivo só do GA36 (`ga36mb-gamepad.c`); script = um comentário no `session`;
launcher = um comentário no `lume-ui` e `r36os pkg ga36 lume-launcher`. Logs em `cache/measure/`.
