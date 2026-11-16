# Design

## Context

Ver `proposal.md` (Why). O estado que molda o desenho:

- `src/r36os/kernel.py`: `source_tree()` cria `.cache/src/linux-<versão>-<hash dos patches>` a
  partir do tarball e aplica os patches com `git apply` (com `GIT_CEILING_DIRECTORIES`, porque o
  cache fica dentro do repositório); `build_kernel()` usa `.cache/kbuild/<console>-<hash>` e
  `ccache` em `.cache/ccache/kernel-<console>`, dentro do container `cross` (x86_64). O kernel
  embute o initramfs (`CONFIG_INITRAMFS_SOURCE`) e a data do build vem do último commit das
  entradas (`build_stamp`), para o mesmo conteúdo dar o mesmo `Image`.
- `src/r36os/build.py`: por camada, pacotes locais que faltam (`abuild` num container da
  arquitetura do console, sob qemu), initramfs, kernel e DTBs, rootfs (`apk add --root` no
  container da arquitetura) e `SYSTEM` (`mksquashfs` zstd 19 no x86). Nada é pulado por conteúdo,
  só os pacotes locais por nome e versão.
- `src/r36os/container.py`: todo container é `podman run --rm` sem limite de CPU nem prioridade.
- `r36os push` já compara os arquivos da `BOOT` por SHA256 e manda só os que mudaram; a imagem
  sai igual para as mesmas entradas, e isso tem de continuar.
- Os pacotes locais (`aports/`) vão para `out/repo/<arch>/`, assinados com a chave de
  `.cache/abuild/`.

## Goals / Non-Goals

**Goals:**
- Um patch num driver recompila um arquivo e o link, em menos de 1 minuto por console.
- Um build sem mudança termina em poucos segundos (só confere hashes e monta a imagem).
- O PC fica usável e mais frio durante qualquer build.

**Non-Goals:**
- Compilar os `aports/` em cross em vez de emulados (P-36).
- Cache do `cargo` do `lume-launcher` (P-61).
- Instalar pacotes com o `apk` dentro do console (o `SYSTEM` é somente leitura e a `BOOT` é FAT;
  a instalação pelo cabo continua sendo o `r36os push`).

## Decisions

### D1. Uma árvore do kernel com o histórico do git

A árvore fica em `.cache/src/linux-<versão>/` (sem hash), como um repositório git próprio: um
commit com o tarball intocado (tag `upstream`) e, por cima, um commit por patch (`git am` ou
`git apply` + commit). Quando os patches mudam, o build faz `git checkout upstream`, aplica a
série nova num branch novo e compara com o anterior: o git só regrava os arquivos que mudaram de
conteúdo, então só eles ganham data nova. A pasta de build vira `.cache/kbuild/<console>/` (fixa),
e o `make` incremental recompila o que depende desses arquivos.

- Alternativa: manter o hash no nome e confiar no `ccache`. Rejeitada: é o que existe hoje, e
  cada arquivo ainda passa pelo pré-processador.
- Alternativa: reverter (`patch -R`) a série antiga e aplicar a nova. Rejeitada: toca todos os
  arquivos de todos os patches, mesmo os que não mudaram.
- A árvore continua com `GIT_CEILING_DIRECTORIES` para o git não achar o repositório do projeto.

### D2. Hash de entradas por etapa

Cada etapa calcula um hash do que entra nela e grava ao lado da saída (`<saída>.inputs`):

| Etapa | Entradas |
|---|---|
| kernel de um console | versão do tarball, conteúdo dos patches, fragmento, script de build, hash do initramfs |
| DTBs de um SoC | os `.dts`/`.dtsi` do board e de `dts-vendor/`, os patches (bindings), o script |
| initramfs | os arquivos do `initramfs/`, os pacotes que ele usa (nome e versão), o board |
| rootfs e `SYSTEM` | lista de pacotes, `APKINDEX` do repositório local e do espelho do Alpine, overlay, idioma, script |
| imagem de módulos | o `modules.tar` do kernel |

Se o hash gravado bate com o atual e a saída existe, a etapa é pulada. O kernel ainda passa
pelo `make` quando a etapa roda, e o `make` incremental decide o resto.

### D3. Pacotes `.apk` montados no x86, versionados pelas entradas

O resultado de cada etapa compilada vira um pacote no repositório local da arquitetura do
console:

| Pacote | Conteúdo |
|---|---|
| `lume-kernel-<console>` | `Image`/`zImage`, `config`, `release` e o arquivo de módulos (`<console>/modules`) |
| `lume-dtbs-<soc>` | os DTBs nativos e `vendor/` do SoC |
| `lume-initramfs-<console>` | o `initramfs.cpio` que o kernel embute (para conferência e reuso) |

- **Versão:** `pkgver` = versão do componente (kernel `6.18.62`; DTBs e initramfs a versão do
  projeto) e `pkgrel` crescente; o hash de entradas do D2 vai no campo `commit` do `.PKGINFO`.
  O build procura no repositório um pacote com o mesmo hash: se acha, extrai dele em vez de
  compilar; se não, compila e publica com o `pkgrel` seguinte.
- **Montagem sem emulação:** o pacote só empacota arquivos já prontos, então é montado no
  container x86 (`abuild` com `CARCH` do console, sem `strip` nem rastreio de dependências, ou o
  `apk mkpkg` do apk-tools 3). A primeira tarefa prova qual dos dois gera um pacote que o `apk`
  da arquitetura do console aceita; o reserva é escrever o `.apk` v2 direto (tar.gz de controle e
  de dados, assinatura RSA com a chave do projeto).
- **Imagem:** `image.py` passa a tirar a `BOOT` desses pacotes (extração), e o `r36os push`
  continua mandando só o que mudou; o `VERSION` da `BOOT` ganha a versão de cada pacote, e o
  `hwinfo` a registra no log do boot.
- Alternativa: só o hash de entradas, sem pacote. Dá o mesmo ganho de tempo, mas não serve entre
  worktrees nem máquinas e não registra versão no console (pedido do usuário de 2026-11-16).

### D3b. Versão automática dos `aports/`

O `r36os pkg` calcula o hash de entradas de cada `aport` (o `APKBUILD`, os arquivos dele e o código
que ele empacota de dentro do repositório, como `lume-launcher/`) e o compara com o campo
`commit` do pacote mais novo no repositório: igual, nada a fazer; diferente, compila com o
`pkgrel` seguinte (sem editar o `APKBUILD` no git; o `pkgrel` do arquivo vira o mínimo). O
`hwinfo` grava no log de boot a versão de cada pacote `lume-*`/`r36os-*` instalado.

Instalar um pacote com o `apk` **dentro do console** fica fora: o `SYSTEM` é somente leitura e a
camada gravável é RAM, então exigiria uma camada de pacotes persistente aplicada no boot (vai
com a atualização A/B, P-14). A atualização pontual vem das camadas do D6.

### D6. `SYSTEM` em camadas e `push` pontual

Pedido do usuário (2026-11-16): atualizar pedaços, com o build e a atualização rápidos.

- **Camadas por console** na `BOOT`, cada uma um squashfs zstd, montadas no initramfs como
  `lowerdir` do overlay (de cima para baixo):
  1. `<console>/lume`: pacotes do projeto (`lume-*`, `r36os-*`) e o `rootfs/overlay/`;
  2. `<console>/retroarch`: RetroArch, cores e shaders;
  3. `<console>/SYSTEM`: o resto (base do Alpine e bibliotecas).

  Cada camada é montada a partir dos mesmos pacotes de hoje: o rootfs completo continua sendo
  montado por `apk add --root`, e a separação é por lista de arquivos de cada grupo de pacotes
  (do banco do `apk` instalado), então nenhuma dependência muda. Cada camada tem o próprio hash
  de entradas (D2) e o próprio `.old` no `push` (como o `SYSTEM` e os módulos já têm). Montar
  duas camadas a mais custa milissegundos no boot.
- Alternativa: camada de pacotes persistente no cartão aplicada no boot. Rejeitada aqui: custa
  tempo em todo boot e trata falha de instalação, o que é o problema do A/B (P-14).
- Alternativa: delta binário do `SYSTEM` (rsync de blocos). Rejeitada: o squashfs comprimido
  muda quase inteiro com qualquer alteração, e o console teria de reconstruir o arquivo.
- **`push` sem descompactar:** o build já grava a lista da `BOOT` com os SHA256
  (`image.BOOT_LIST`); o `push` lê os arquivos das saídas do build (`out/<console>/...`) por essa
  lista, compara com o cartão e manda só os diferentes. A imagem `.zst` continua para o `flash`.
  O resumo do `push` mostra bytes enviados e tempo.

### D4. Prioridade e número de tarefas

- Todo container roda o script como `nice -n 19 ionice -c 3 sh -euc …` (o `nice` vale para o
  escalonador do host mesmo dentro do container rootless; o `ionice` do busybox ou do util-linux).
- `R36OS_JOBS` ou `--jobs N` (em `build`, `pkg` e `test-vm`) define as tarefas; o padrão é metade
  dos núcleos (mínimo 1). Vira `-j` do `make`, `JOBS` do `abuild` e `-processors` do `mksquashfs`.
- O build mostra no começo as tarefas e a prioridade.
- Alternativa: `podman --cpus`. Limita por cota de tempo, mas não dá preferência ao usuário; e no
  rootless depende da delegação do controlador de CPU. Fica como reserva se o `nice` não bastar.

### D5. Limpeza e medição

- Ao criar a árvore e as pastas de build do D1, o build apaga `linux-<versão>-*` e
  `kbuild/<console>-*` antigos e diz quanto liberou; o `repo-clean` passa a conhecer o layout novo.
- Cada etapa mede o próprio tempo, e o fim do build imprime a tabela (etapa, tempo ou `skipped`,
  total), inclusive quando falha.
- Medição da change: build completo (cache frio), build sem mudança, patch num driver e mudança
  só no rootfs, com o tempo total e a temperatura máxima da CPU (lida do `hwmon` do host durante o
  build), antes e depois. Os números ficam no design.

## Risks / Trade-offs

- [Make incremental errado depois de mudar o `.config`] → o fragmento entra no hash; quando a
  configuração muda, o `make olddefconfig` regenera o `auto.conf` e o kbuild recompila o que
  depende das opções; um teste compara o `Image` incremental com o de um build limpo (mesmo
  conteúdo, mesmo arquivo).
- [Hash de entradas incompleto deixa passar uma mudança] → cada etapa lista as entradas num lugar
  só (D2), e um teste muda cada entrada e confere que a etapa roda de novo; `r36os build --clean`
  força tudo.
- [Pacote montado no x86 recusado pelo `apk` do console] → a primeira tarefa prova a montagem
  com o `apk` da arquitetura alvo; há o reserva do D3.
- [Menos tarefas deixam o build completo mais lento] → o padrão só vale sem opção; com o kernel
  incremental e as etapas puladas, o build comum faz muito menos trabalho.
- [`ionice` sem efeito em certos agendadores de disco] → a prioridade de CPU já resolve o uso do
  PC; o `ionice` é complemento.

## Migration Plan

1. O primeiro build depois da mudança cria a árvore com git e as pastas fixas, apaga as antigas e
   compila tudo uma vez (cache frio).
2. Os pacotes novos entram no repositório local ao lado dos `aports/`; nada muda no cartão.
3. Reversão: voltar o commit; o build antigo recria as pastas com hash a partir do tarball.
