# Proposal

## Why

Hoje o Lume só roda no GA36, e cada console precisaria do próprio cartão: a ROMS (jogos,
saves, configuração) não passa de um aparelho para o outro. O usuário tem os dois consoles
em mãos (GA36 e R36S "V5") e quer **um único cartão que inicie nos dois, sem regravar**.
Em 2026-11-11 isso foi provado no aparelho: com o boot0 do GA36 encolhido para os setores
16 a 63 e o `idbloader` do R36S no setor 64, o mesmo primeiro 1 MiB iniciou o ArkOS no
R36S e o Lume no GA36 (P-21 em `docs/PENDENCIAS.md`). Esta change junta o suporte ao
R36S (P-27) e o cartão único (P-21), porque um não existe sem o outro: o R36S ainda não
tem imagem, e definir o layout depois quebraria os cartões já gravados.

## What Changes

- **Imagem única dos consoles (`console`)**: um build gera um cartão que inicia no GA36 e
  no R36S. A área de boot reúne as duas cadeias de fábrica: a do GA36 (boot0 encolhido
  para 24 KiB, com a soma eGON recalculada no build, U-Boot 2017 e imagem de boot
  Android) e a do R36S (`idbloader`, `uboot.img` e `trust.img`), cada uma nos setores que
  o seu BROM ou U-Boot lê.
- **BREAKING**: as imagens `ga36` e `r36s` deixam de ser produtos separados: viram camadas
  de hardware da imagem `console`. O comando passa a ser `r36os build console` e
  `r36os flash console <dispositivo>`. A `vm` continua com imagem própria.
- **Cadeia de boot do próprio R36S**: os binários fechados do bootloader do R36S vêm de
  uma cópia do cartão original do aparelho (`R36OS_R36S_FACTORY`), conferidos por SHA256 e
  fora do git, como o GA36 já faz. O U-Boot mainline do R36S fica como pendência própria.
- **BOOT com dois sistemas**: a `BOOT` (FAT32, 2 GiB, em 128 MiB) leva um `SYSTEM` por
  console, o kernel e o DTB do R36S e o `boot.ini` que o U-Boot do R36S lê. O initramfs
  embutido em cada kernel monta o `SYSTEM` do próprio console. Os 2 GiB deixam espaço
  para o crescimento previsto (catálogo, Wi-Fi, um terceiro sistema, atualização A/B).
- **Cartões do GA36 já gravados precisam de gravação completa**: a imagem `console`
  mantém a assinatura de disco e o início da `BOOT` do GA36, mas a `BOOT` passa de 1 GiB
  para 2 GiB (decisão do usuário em 2026-11-11), então o `--update` recusa esses cartões e
  pede gravação completa. Copiar jogos e saves antes.
- **Suporte ao R36S V5** (o antigo grupo 10): kernel mainline aarch64 com config própria,
  DTS `rk3326-r36s-v5`, variante do painel no `panel-sitronix-st7703`, `r36os-padmerge`
  (um único "R36S Gamepad"), áudio do RK817, bateria, luz de fundo, autoconfiguração do
  controle e `docs/BRINGUP-R36S.md`. Os mesmos 9 sistemas e 11 cores da base, compilados
  para aarch64 com as flags padrão do Alpine.
- **Configuração do RetroArch compartilhada**: a configuração do usuário fica na ROMS e
  passa entre os consoles; as chaves que dependem do aparelho (taxa de atualização, por
  exemplo) são reaplicadas pelo console a cada início.

Fora do escopo: o catálogo extra do R36S (P-24), o U-Boot mainline do R36S e do GA36
(P-19), o segundo slot de cartão e outras revisões do R36S (P-16), a otimização de flags
por CPU (P-10), compatibilidade de *save states* entre armv7 e aarch64.

## Capabilities

### New Capabilities

Nenhuma. O cartão único é um contrato da imagem (`system-image`) e o R36S entra nas
capacidades que já existem.

### Modified Capabilities

- `system-image`: imagem `console` única para GA36 e R36S no lugar das imagens por alvo;
  layout da área de boot com as duas cadeias de fábrica; `BOOT` com um `SYSTEM` por
  console, 2 GiB e novo limite de tamanho; cartões do GA36 antigos pedem gravação completa.
- `device-support`: o R36S V5 passa a ser suportado (painel, GPU `panfrost`, controle,
  áudio, bateria, frequência e serial), ao lado do GA36.
- `boot-runtime`: o boot escolhe o `SYSTEM` do console em que o cartão está; logs e ROMS
  são compartilhados pelos dois consoles.
- `frontend-session`: a configuração do RetroArch persistida na ROMS serve aos dois
  consoles, com as chaves específicas de cada aparelho reaplicadas a cada início.

## Impact

- **Código**: `src/r36os/` (`targets.py`, `build.py`, `image.py`, `vendor.py`, novo módulo
  da cadeia do R36S, `kernel.py`, `initramfs.py`, `flash.py`, `archive.py`, `cli.py`),
  `initramfs/init`, `board/r36s/` (DTS, `kernel.config`, `boot.ini`, `hw-packages.txt`),
  `kernel/patches/` (variante do painel ST7703), `aports/` (`r36os-padmerge` e o build
  aarch64 dos pacotes locais), `rootfs/overlay/` (`retroarch-r36s.cfg`, autoconfig do
  "R36S Gamepad", padrões do mixer do RK817).
- **Testes**: unitários do layout da área de boot (boot0 encolhido e soma eGON, regiões
  sem sobreposição), da `BOOT` com dois sistemas, da recusa do `--update` em cartões antigos, da
  config do kernel e do DTS do R36S, das chaves fixas do RetroArch; testes de imagem e de
  paridade de manifestos `ga36` × `r36s`.
- **Host**: build aarch64 sob `qemu-user` (binfmt) e cross-compile aarch64 do kernel.
  Variável nova `R36OS_R36S_FACTORY`, com uma cópia do cartão original do R36S.
- **Usuário**: o fluxo muda para `build console` / `flash console`. Um cartão do GA36
  gravado antes precisa de `flash console <dispositivo>` (gravação completa, apaga a ROMS);
  cartões de 2 GB deixam de servir.
- **Documentação**: `README.md` (uso, Agradecimentos), `docs/BRINGUP-R36S.md`,
  `docs/LOGS.md` (logs dos dois consoles na mesma ROMS) e `docs/PENDENCIAS.md` (P-21 e P-27
  viram esta change; U-Boot mainline do R36S como pendência nova).
