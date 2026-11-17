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
- **Cores e RetroArch (P-36):** uma prova decide o caminho entre (a) `distcc` com compiladores
  x86 que geram código musl da arquitetura, com o mesmo gcc do Alpine 3.24, mantendo o `abuild` no
  container da arquitetura, e (b) cross completo do `abuild` (`CBUILD`/`CHOST`). Começa por (a),
  que muda menos o pipeline. Critério: o mesmo `manifest`, e os cores rodam iguais no aparelho.
  Com o D3, um core só recompila quando muda.
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
   slots/base-<sha12>         base do Alpine (bibliotecas, busybox, OpenRC)
   slots/runtime-<sha12>      RetroArch, mesa/drivers de video, SDL
   slots/lume-<sha12>         fragmentos do projeto + banco do apk + saidas de triggers
   slots/modules-<sha12>      modulos do kernel
   slots/core-<nome>-<sha12>  um por core
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
- **Coerência:** cada slot grava o sha dos slots de baixo contra os quais foi montado; o
  manifesto só é gerado com um conjunto coerente, e o push nunca manda um slot sem o resto do
  conjunto que ele exige.
- **Cores fora do caminho do boot:** os slots `core-*` não entram no overlay. Um serviço
  (`lume-cores`, no runlevel `default`, depois do `frontend`) os monta em `/run/lume/cores/<nome>/`;
  o runner acha o core lá e espera o mount se o jogo abrir antes.
- **Formato do `SLOTS` (tarefa 4.0):** texto por linhas, campos separados por um espaço, sem
  JSON, para o `awk` do busybox. Leitores iguais em `src/r36os/manifests.py` (`read_slots`,
  `write_slots`) e `initramfs/lib/slots.sh`:

  ```
  lume-slots 1
  build 20261116-214233
  console ga36
  slot base slots/base-<sha12> <sha256> <bytes> -
  pkg base musl 1.2.5-r10
  slot runtime slots/runtime-<sha12> <sha256> <bytes> base=<sha256>
  slot lume slots/lume-<sha12> <sha256> <bytes> base=<sha256>,runtime=<sha256>
  pkg lume lume-core 1.0-r3
  slot modules slots/modules-<sha12> <sha256> <bytes> -
  slot core-snes9x slots/core-snes9x-<sha12> <sha256> <bytes> base=<sha256>,runtime=<sha256>
  end 5 2
  ```

  - Cabeçalho fixo: `lume-slots <formato>` (hoje 1), `build <id>`, `console <nome>` (o leitor
    recusa o manifesto de outro console).
  - `slot <nome> <arquivo> <sha256> <bytes> <de baixo>`: o arquivo é relativo a
    `<console>/` e é sempre `slots/<nome>-<12 primeiros dígitos do sha256>`; `<de baixo>` é `-`
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
- **Sem reinício:** (1) slots de core — o push troca o arquivo e pede ao `lume-cores` para
  remontar; com o core em uso, a troca acontece quando o jogo fecha; (2) `push --hot <fragmento>` —
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
  escolhe outro. Também o NVMe (`nvme` Composite), pelo volume de escrita do build.
- **Amostragem:** uma thread do `r36os` lê a cada 2 s durante todo o build e todo container.
- **Ação (histerese):** CPU ≥ `R36OS_TEMP_MAX` (padrão 85 °C) ou NVMe ≥ máximo dele − 5 °C →
  `podman pause` dos containers do build, com uma linha na saída; retoma com CPU ≤ máximo − 10 °C.
  Se a CPU passar de 92 °C mesmo pausado por 60 s (refrigeração com problema), o build aborta com
  a mensagem do que foi lido.
- **Resumo:** temperatura máxima da CPU e do NVMe, tempo acima do limite e tempo pausado, no
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

### D17. As duas arquiteturas em paralelo

- O `build console` roda as esteiras do armv7 e do aarch64 ao mesmo tempo, cada uma com metade do
  limite de tarefas (o total continua o do D8), sob a mesma proteção de calor.
- A saída de cada uma ganha prefixo (`[armv7]`, `[aarch64]`); o resumo por etapa separa as duas.
- O que é comum (árvore do kernel, fragmentos noarch) é feito uma vez antes de dividir.

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
   `SLOTS` e `slots/`, e o `SYSTEM` antigo é apagado no push seguinte.
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
| temperatura máxima do NVMe | 37,9 °C | |
| tempo pausado pela proteção de calor | 0 s (só registrando) | |

Medido em 2026-11-16 (1.2), com o código de antes desta change e a proteção de calor só
registrando. "Cache frio" = sem `.cache/src`, `.cache/kbuild` e `.cache/ccache` (renomeadas para
`*.antes-1.2`), com os pacotes de `out/repo` reaproveitados; esse caso rodou com o `-j$(nproc)`
de hoje (16) e esquentou até o Tjmax do 5700G, então os outros rodaram com `-j8` (troca
temporária, desfeita) e com a CPU esfriada a ~50 °C antes de cada um. Patch de driver = um
comentário num arquivo só do GA36 (`ga36mb-gamepad.c`); script = um comentário no `session`;
launcher = um comentário no `lume-ui` e `r36os pkg ga36 lume-launcher`. Logs em `cache/measure/`.
