# Proposal

## Why

O `r36os build console` refaz quase tudo a cada execução, mesmo quando só um arquivo mudou, e
ocupa todos os núcleos do PC em prioridade normal: na change `boot-dtb-select` (2026-11-16) cada
ajuste de um driver custou um build longo, a máquina ficou lenta durante ele e a CPU chegou a
90 °C. As próximas changes (governor do processador e cenários do frontend) dependem de muitas
iterações no aparelho, então o ciclo editar → build → `push` precisa ficar curto e frio antes
delas.

O que o código faz hoje (`src/r36os/kernel.py`, `build.py`, `rootfs.py`):

- A árvore do kernel e as pastas de build levam no nome o hash de **todos** os patches
  (`.cache/src/linux-6.18.62-<hash>`, `.cache/kbuild/<console>-<hash>`). Mudar um patch apaga a
  árvore, extrai de novo o tarball (2 GB), reaplica os 34 patches e recompila **os dois** kernels
  numa pasta vazia: o `ccache` evita parte da compilação, mas cada arquivo ainda passa pelo
  pré-processador. Um patch que só toca um driver do GA36 recompila o kernel do R36S também.
- As gerações antigas não são apagadas: 4 de cada console somavam 13 GB em `.cache/kbuild`.
- O `make -j$(nproc)`, o `abuild` e o `mksquashfs` rodam com prioridade normal e todos os núcleos.
- Cada build reinstala os ~163 pacotes do rootfs de cada console (`apk add` na arquitetura do
  console) e refaz o `SYSTEM` com `mksquashfs` zstd nível 19, mesmo sem nenhum pacote novo; e
  recompila e valida os ~170 DTBs (`dt-mk-schema` + `dt-validate`) mesmo sem mudança nos DTS.

## What Changes

- **Kernel incremental:** uma árvore só do kernel por versão, guardada com o histórico do git
  (base intocada + um commit por patch), e uma pasta de build fixa por console. Quando os patches
  mudam, só os arquivos que mudaram de conteúdo ganham data nova, e o `make` recompila só esses e o
  que depende deles. O kernel de um console só recompila quando os patches ou o fragmento dele
  mudam o que ele compila.
- **Tudo o que é compilado vira pacote `.apk`** (pedido do usuário, 2026-11-16): o kernel e os
  módulos de cada console, os DTBs (nativos e convertidos) e o que hoje é montado fora do `apk`
  passam a ser pacotes versionados no repositório local (`out/repo/<arch>/`), como os `aports/`
  já são. A versão do pacote vem das entradas dele, então o build reaproveita um pacote que já
  existe com as mesmas entradas em vez de recompilar, e a imagem tira os arquivos dos pacotes.
  Os pacotes também servem para instalar ou atualizar uma parte só, num console ou noutra
  máquina, sem refazer a imagem.
- **Versão automática dos pacotes locais**, inclusive o `lume-launcher`: a versão sobe sozinha
  quando o pacote muda, e o log do console mostra a versão de cada pacote do projeto.
- **Atualização pontual** (pedido do usuário, 2026-11-16: "atualizar pontualmente pedaços"): o
  `SYSTEM` de cada console vira camadas squashfs montadas umas sobre as outras (base do Alpine,
  RetroArch com os cores, e o projeto: `lume-launcher`, scripts e serviços), como os módulos do
  kernel já são um arquivo à parte; o `r36os push` deixa de descompactar a imagem inteira (hoje
  644 MiB a cada push) e manda só os arquivos que mudaram, a partir do que o build registrou. Uma
  mudança no launcher passa a ir ao console como uma camada de poucos MB. Instalar pacote com o
  `apk` dentro do console continua fora (exigiria uma camada gravável persistente no boot; fica
  com a atualização A/B, P-14).
- **Etapas puladas quando as entradas não mudaram:** o rootfs e o `SYSTEM` de cada console, os
  DTBs com a validação, o initramfs e a imagem de módulos são refeitos só quando o hash do que
  entra neles muda; o build diz em uma linha o que pulou.
- **Build gentil com o PC:** todos os containers do build e do `r36os pkg` rodam em prioridade
  baixa (`nice` e `ionice`), com um número de tarefas paralelas limitado por padrão e ajustável
  (opção e variável de ambiente), para a máquina continuar usável e mais fria.
- **Cache sem gerações velhas:** o build apaga as árvores e pastas de build que não correspondem
  mais à versão em uso; o `repo-clean` e a documentação do cache refletem isso.
- **Medição:** o tempo de cada etapa aparece no fim do build, e a change registra o antes e o
  depois (build completo, build sem mudança, mudança num driver) com a temperatura máxima da CPU.
- Continua igual: o mesmo conteúdo gera os mesmos arquivos (o `r36os push` segue pulando o que
  não mudou), e o build continua falhando em opção do fragmento que não pega e em warning nos
  nossos drivers.

**Fora do escopo:** compilar os pacotes ARM em cross em vez de emulados (P-36, change própria já
decidida) e o cache do `cargo` do `lume-launcher` (P-61); esta change só lhes dá a prioridade
baixa e o limite de tarefas.

## Capabilities

### New Capabilities
- `build-performance`: tempo e carga do build no PC — recompilação incremental do kernel,
  etapas puladas quando as entradas não mudam, prioridade e limite de tarefas dos containers e a
  medição de tempo por etapa.
- `build-packages`: o que o projeto compila (kernel, módulos, DTBs, ferramentas do initramfs)
  sai como pacote `.apk` versionado pelas entradas, reaproveitado entre builds e instalável sem
  refazer a imagem.

- `system-update`: atualização do console pelo cabo só com os pedaços que mudaram (camadas e
  arquivos da `BOOT`), sem descompactar a imagem, e as versões de cada pedaço no log do console.

### Modified Capabilities
- `build-cache`: o cache passa a não guardar gerações antigas das árvores e pastas de build do
  kernel.
- `system-image`: o sistema de cada console deixa de ser um único `SYSTEM` e passa a ser
  dividido em camadas squashfs.

## Impact

- Código: `src/r36os/kernel.py` (árvore e build), `src/r36os/build.py` (etapas e medição),
  `src/r36os/rootfs.py`, `src/r36os/initramfs.py`, `src/r36os/container.py` (prioridade e
  tarefas), `src/r36os/cli.py` (opção de tarefas), a skill `repo-clean`.
- Testes: unidade do build (hashes de entrada, árvore incremental, argumentos do podman) e um
  teste de reprodutibilidade (dois builds sem mudança dão os mesmos arquivos da `BOOT`).
- Documentação: `docs/` do build e do cache, `README.md` (como ajustar as tarefas),
  `docs/PENDENCIAS.md` (tema 11).
- Novos pacotes no repositório local (`out/repo/aarch64/`, `out/repo/armv7/`), assinados com a
  mesma chave dos `aports/`.
- Cartão: a `BOOT` de cada console ganha as camadas novas ao lado do `SYSTEM` (o initramfs
  monta todas); o resto dos arquivos fica nos mesmos lugares, agora vindos de pacotes. Um cartão
  antigo é atualizado pelo `push` ou pelo `flash --update`.
- `initramfs/init` e `initramfs/lib/storage.sh` (montagem das camadas, com o `.old` de cada uma),
  `src/r36os/push.py` (comparação sem descompactar), `src/r36os/image.py` e `rootfs.py`
  (camadas).
