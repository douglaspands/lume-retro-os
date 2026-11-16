# Proposal

## Why

O ciclo editar → build → aparelho está lento demais para as próximas changes (governor e
cenários do frontend), que dependem de muitas iterações nos dois consoles. Hoje qualquer
mudança, mesmo num script, refaz a imagem inteira; um patch de driver recompila os dois kernels
do zero; o `lume-launcher` leva 8 min no armv7 sob qemu (P-61) e os cores levam horas (P-36);
o build ocupa todos os núcleos em prioridade normal (CPU a 90 °C na `boot-dtb-select`); o
`r36os push` descompacta 644 MiB a cada envio, manda o `SYSTEM` inteiro por uma mudança pequena
e reinicia sem conferir se o boot deu certo; e os helpers de teste no aparelho são reescritos a
cada sessão.

Pedido do usuário (2026-11-16): "builds mais rápidos (pontuais, somente do necessário) e
atualizações mais rápidas (pontuais, somente o necessário) — drivers, apps, cores, tudo que der
para fragmentar". A esteira (fragmentar) e a entrega (atualizar) ficam na mesma change, porque um
fragmento só está provado quando chega ao console e funciona.

## What Changes

- **Fragmentos:** tudo o que o projeto entrega passa a ser um pacote `.apk` com versão própria
  no repositório local. Os binários (kernel, módulos, DTBs, `lume-launcher`, RetroArch, cores e
  ferramentas) saem **por arquitetura** (`armv7`, `aarch64`), com o mesmo nome nos dois
  repositórios. O que não é binário (scripts, serviços, configuração, temas, i18n, shaders,
  autoconfig) sai **noarch**, montado uma vez no x86 e publicado nos dois. O `rootfs/overlay/`
  é dividido em fragmentos por funcionalidade.
- **Versão pelo conteúdo:** o hash das entradas decide se um fragmento compila; o hash do
  conteúdo decide se a versão sobe. Ninguém sobe `pkgrel` à mão, inclusive no `lume-launcher`.
- **Build pontual:** `r36os build <fragmento>` compila só aquele fragmento (e o que depende dele)
  e remonta só os slots afetados, sem gerar a imagem do cartão; `r36os build console` continua
  gerando a imagem para o `flash`. Cada etapa é pulada quando as entradas não mudaram.
- **Kernel incremental:** uma árvore do kernel com histórico git e uma pasta de build fixa por
  arquitetura; um patch recompila só os arquivos que mudaram. A data do kernel passa a ser fixa,
  para um kernel sem mudança sair igual byte a byte.
- **Compilação sem emulação onde mais pesa:** o `lume-launcher` (P-61) e os cores (P-36) deixam
  de compilar sob qemu ou passam a reaproveitar o que já foi compilado.
- **Build gentil com o PC:** prioridade baixa (`nice`, `ionice`) e limite de tarefas ajustável
  (`--jobs`, `R36OS_JOBS`; padrão metade dos núcleos).
- **Proteção de calor** (pedido do usuário, 2026-11-16): o build lê a temperatura da CPU (sensor
  do processador, `k10temp`, não as entradas auxiliares da placa-mãe, que marcam 90–97 °C com o PC
  parado) e a do NVMe durante todo o build, pausa os containers acima de um limite e retoma
  abaixo de outro, aborta se a temperatura subir mesmo pausado, e mostra no fim o máximo e o tempo
  pausado.
- **Perfil de desenvolvimento:** no build pontual, os slots usam compressão rápida; o `build
  console` de liberação continua com zstd 19.
- **As duas arquiteturas em paralelo:** com o limite de tarefas dividido entre elas e sob a
  proteção de calor.
- **Slots no cartão** (**BREAKING** no layout da `BOOT` do console): o sistema de cada console
  deixa de ser um único `SYSTEM` e passa a ser um conjunto de slots squashfs (base do Alpine,
  runtime com o RetroArch, o projeto, os módulos, um por core), descritos num manifesto trocado
  de uma vez. O initramfs monta os slots do boot; os cores são montados depois do frontend, fora
  do caminho crítico do boot. Cartões antigos continuam iniciando e são migrados pelo `push` ou
  pelo `flash --update`.
- **Atualização pontual:** o `push` manda só os slots e arquivos que mudaram, lidos do arquivo
  do build (endereçado por conteúdo), sem descompactar imagem; reiniciar é o padrão (atômico).
  Sem reinício: os cores (trocados com o console ligado) e o `push --hot <fragmento>`, que
  instala na camada gravável em RAM e reinicia só os serviços do fragmento, para iterar.
- **Teste no aparelho como ferramenta do projeto:** o `push` espera o console voltar e confere o
  boot e as versões no log; `r36os dev` (esperar, comando, tela, botões, conferência) substitui
  os helpers refeitos a cada sessão; `r36os dev watch <fragmento>` faz build pontual e
  `push --hot` a cada arquivo salvo; `r36os dev shot --compare` confere a tela com capturas de
  referência do launcher.
- **Os dois consoles no PC ao mesmo tempo** (**BREAKING** no endereço do R36S): cada console
  ganha a própria sub-rede USB, para `push` e `dev check` rodarem nos dois em paralelo.
- **Boot mais curto para o ciclo de teste** (ganhos rápidos do P-58): OpenRC em paralelo e os
  serviços que o jogo não usa (Bluetooth, NetworkManager, playlists do RetroArch, índice do
  launcher) depois do frontend. O resto do P-58 continua numa change própria.
- **Validação no aparelho no lugar da VM** (decisão do usuário, 2026-11-16, "para reduzir
  tempo"): nesta change o build e o teste da imagem `vm` (x86) saem do ciclo; a liberação de um
  build de console passa a exigir a conferência no GA36 e no R36S. Os testes de unidade (Python,
  Rust e shell), que levam segundos, continuam.
- **Medição:** tempo por etapa no fim do build; antes e depois para build, push, boot e
  temperatura.

**Fora do escopo:** instalar pacotes com o `apk` dentro do console (camada persistente; vai com a
atualização A/B, P-14); acelerar o boot em si (P-58); userland armv7 nos dois consoles (avaliar
na change do governor); voltar a VM ao ciclo (pendência nova).

## Capabilities

### New Capabilities
- `build-performance`: tempo e carga do build no PC — kernel incremental, etapas puladas por
  hash de entradas, prioridade e limite de tarefas, compilação sem emulação e tempo por etapa.
- `build-packages`: tudo o que o projeto entrega sai como fragmento `.apk` (por arquitetura ou
  noarch), versionado pelo conteúdo e compilado sozinho.
- `system-update`: slots do sistema no cartão, manifesto do conjunto, push pontual, troca de
  cores e push em RAM sem reinício, versões no log.
- `device-testing`: o teste no aparelho pelo cabo como ferramenta do projeto — esperar o boot,
  conferir o log e as versões, comandos, captura de tela, botões e auto-teste.

### Modified Capabilities
- `build-cache`: o cache passa a não guardar gerações antigas do kernel.
- `system-image`: o sistema de cada console passa a ser um conjunto de slots com manifesto.
- `vm-validation`: a liberação de um build de console passa a depender da conferência nos
  aparelhos, não do teste da VM.
- `usb-otg`: o endereço da rede USB passa a ser por console, não igual nos dois.
- `boot-runtime`: os serviços que o jogo não usa sobem depois do frontend, com o OpenRC em
  paralelo.

## Impact

- Código: `src/r36os/` (`kernel.py`, `build.py`, `rootfs.py`, `image.py`, `packages.py`,
  `container.py`, `push.py`, `archive.py`, `flash.py`, `cli.py`) e um módulo novo para
  `r36os dev`; `initramfs/init` e `initramfs/lib/storage.sh` (slots e manifesto); serviço novo
  que monta os cores; `game-runners` passa a achar o core no slot montado; módulo novo de
  proteção de calor; endereço USB do R36S (`lume-usb`, `r36os-usb`) e a ordem dos serviços do
  OpenRC (`rc.conf`, dependências dos `init.d`).
- Conflito possível com a change ativa `r36s-usb-proof` (prova da USB do R36S): a troca de
  endereço entra depois das provas dela, ou elas são refeitas com o endereço novo.
- Repositório: `rootfs/overlay/` vira aports noarch em `aports/lume-*`; novos pacotes
  `lume-kernel`, `lume-modules`, `lume-dtbs` em `out/repo/<arch>/`.
- Cartão: a `BOOT` de cada console ganha `<console>/SLOTS` e `<console>/slots/`; o `push` e o
  `flash --update` migram cartões antigos.
- Testes: unidade (hashes, versão pelo conteúdo, separação em slots, manifesto, push, argumentos
  do podman) e provas nos dois consoles; o `test-vm` sai do ciclo desta change.
- Documentação: `README.md`, `docs/LOGS.md`, `docs/BRINGUP-GA36.md`, `docs/BRINGUP-R36S.md`, guia
  novo `docs/BUILD.md` (esteira, fragmentos, push, `r36os dev`), skill `repo-clean`,
  `docs/PENDENCIAS.md` (temas 1 e 11).
