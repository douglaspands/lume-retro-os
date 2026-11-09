# Proposta: distro Alpine com RetroArch para R36S e GA36

## Why

Não existe hoje uma distro leve, com kernel mainline, que sirva ao mesmo tempo ao R36S oficial e ao clone GA36 e que possa ser testada rapidamente no PC. Esta change cria essa distro sobre o **Alpine Linux**, com os mesmos pacotes nas três arquiteturas, um sistema imutável que resiste a desligamentos abruptos e o RetroArch como interface. O requisito central é que **toda build possa ser validada numa VM x86_64** antes de ir para o console.

## What Changes

- **Três alvos com a mesma base Alpine:** R36S oficial (RK3326, `aarch64`), clone GA36-MB V1.2 (Allwinner A33, `armv7`) e uma VM de teste (`x86_64`). A mesma lista de pacotes, configuração e layout de cartão em todos. Só muda a camada de hardware: kernel, DTB e bootloader.
- **Kernel mainline (LTS) nos dois consoles**, com device trees próprios escritos para ele. Os dados de hardware (pinos, painel, joypad, bateria, áudio) foram copiados para o `design.md`, a partir de fontes públicas: os DTBs de fábrica da coleção dArkOSRE-R36 e o projeto goodluckOS (GPL-2.0). DTBs de fábrica não vão para o cartão.
- **Variantes desta versão:** R36S "V5" e GA36-MB V1.2 com os painéis 1 e 2. A variante é escolhida pela entrada padrão do `extlinux.conf`, editável no PC.
- **Cartão com 2 partições (MBR):**
  - `BOOT`, FAT32 de 1 GiB: kernel, initramfs, DTBs, `extlinux.conf`, logs e o sistema como arquivo `SYSTEM` (squashfs).
  - `ROMS`, exFAT com o resto do cartão: criada no primeiro boot. Guarda jogos, BIOS, saves, estados e a configuração persistente em `system/`.
- **Sistema imutável:** `SYSTEM` somente leitura, com camada gravável em RAM. Só persiste uma lista explícita: configuração do RetroArch, fuso horário e hostname. Restaurar a fábrica é apagar `ROMS/system/`; atualizar é trocar o arquivo `SYSTEM`.
- **Boot verboso nesta change:** mensagens do kernel e dos serviços na tela, um resumo de hardware antes do frontend e o log de cada boot em `BOOT/logs/`. Não há splash.
- **RetroArch com cores até o PS1:** NES, SNES, Master System, Mega Drive, GB, GBC, GBA, arcades dos anos 80/90 e PS1. Usa KMS/DRM e GLES, sem X11 nem Wayland. Os mesmos cores nos três alvos, com core padrão mais leve no GA36 onde fizer diferença.
- **Contrato estável de jogos:** catálogo de sistemas em formato de dados e pastas fixas (`roms/<sistema>`, `bios`, `saves`, `states`). As listas de jogos do RetroArch são geradas a partir desse contrato, para que o frontend possa ser trocado no futuro.
- **Frontend inicial = RetroArch**, num serviço de sessão genérico que sobe direto, sem login. Usa o menu XMB com o tema novo **Lume**: fonte Plus Jakarta Sans, ícones Lucide, ícones redondos por sistema e fundo Aurora 640x480, com ajustes de desempenho e modo kiosk. Sair do RetroArch desliga o console.
- **Validação contínua por VM:** a imagem `x86_64` usa o mesmo layout e o mesmo fluxo de boot. Um teste automatizado de aceitação na VM é condição para liberar as imagens dos consoles.

**Fora do escopo** (próximas changes): splash de boot, Lume Console (frontend próprio), atualização A/B, Wi-Fi e Bluetooth, overclock, segundo slot de cartão do R36S, outras revisões do R36S, GA36 com A23, miniaturas e wallpaper por sistema.

## Capabilities

### New Capabilities

- `system-image`: as imagens por alvo (`r36s`, `ga36`, `vm`), o layout de partições, o `SYSTEM` squashfs e a área do bootloader.
- `boot-runtime`: o fluxo de boot com raiz imutável, a criação e verificação da `ROMS`, a persistência seletiva, o boot verboso, o resumo de hardware e os logs.
- `device-support`: o suporte de hardware de cada console (kernel mainline, device trees, variantes, vídeo, controle, áudio, bateria e serial).
- `game-library`: o contrato de pastas, o catálogo de sistemas e cores, as listas de jogos e o tratamento de saves.
- `frontend-session`: o serviço de sessão substituível, o RetroArch como frontend inicial, o tema Lume, o modo kiosk, os atalhos e a regra de que sair desliga o console.
- `vm-validation`: a VM equivalente aos consoles, o comando para rodá-la e o teste automatizado de aceitação.

### Modified Capabilities

Nenhuma: o projeto ainda não tem specs.

## Impact

- **Este repositório** passa a conter o sistema de build: receitas de imagem, pacotes Alpine próprios (kernel, U-Boot, cores que o Alpine estável não tem e o tema Lume), o initramfs, os serviços OpenRC, os device trees, os drivers de painel e controle do GA36 e o harness da VM.
- **Fontes públicas usadas:** Linux e U-Boot mainline; goodluckOS (GPL-2.0) para o GA36; a coleção dArkOSRE-R36 para os dados do R36S, de livre distribuição segundo o dono do projeto; e o `lume-tv-launcher` para fontes (OFL), ícones Lucide (ISC) e o wallpaper Aurora, criado pelo dono do projeto.
- **Base Alpine:** branch estável v3.24 e seus repositórios binários. Os cores ausentes no estável viram pacotes locais.
- **Build:** containers rootless (podman). Montar os sistemas ARM exige emulação de usuário (`qemu-user` via binfmt) no host, um pré-requisito que precisa de confirmação na primeira vez. A VM roda QEMU com KVM e virgl.
- **Hardware:** cartão de 4 GB no mínimo; adaptador serial recomendado para a primeira subida em cada console.
