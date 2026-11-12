# Proposal

## Why

O usuário fez, no projeto anterior do GA36 ("R36S GA36-MB V1.2-20260416", features 54 e
55), três shaders próprios para Game Boy, Game Boy Color e Game Boy Advance, calibrados
para a tela de 640x480 e leves para a Mali-400. Ele quer esses shaders no Lume, à mão no
menu do RetroArch, sem ligar nada por padrão (decisão do usuário, 2026-11-11). Hoje a imagem
não tem nenhum shader e o RetroArch nem tem pasta de shaders configurada.

## What Changes

- Os três shaders, copiados sem alteração, numa pasta própria dentro da pasta de shaders
  do sistema: `/usr/share/libretro/shaders/lume-shaders/` com `gb/gb-modern-dmg`,
  `gbc/gbc-modern-remaster` e `gba/gba-modern-remaster` (preset `.glslp` e shader `.glsl`
  de cada um).
- A pasta de shaders do RetroArch passa a ser `/usr/share/libretro/shaders` (chave fixa
  `video_shader_dir`), para o menu "Shaders → Carregar" abrir nela. Vale nos dois consoles
  e na VM.
- Nenhum shader fica ligado por padrão: o usuário escolhe no menu, e a escolha é dele
  (o RetroArch salva o preset do jogo, do core ou da pasta de conteúdo na `ROMS`).
- Os serviços do projeto anterior que ligavam os shaders automaticamente
  (`r36-shader-*-prepara`, do EmuELEC) não vêm.

## Capabilities

### New Capabilities

Nenhuma.

### Modified Capabilities

- `frontend-session`: os shaders do Lume ficam disponíveis no menu do RetroArch, na pasta
  de shaders do sistema, desligados por padrão.

## Impact

- `rootfs/overlay/usr/share/libretro/shaders/lume-shaders/` (seis arquivos),
  `rootfs/overlay/usr/share/r36os/retroarch-lume.cfg` (`video_shader_dir`).
- Testes: `tests/unit/test_retroarch_cfg.py` (chave fixa nova) e um teste novo dos
  shaders (cada preset aponta para um `.glsl` que existe, nenhum preset ligado nas
  configurações de fábrica).
- `README.md`: a origem dos shaders (trabalho do próprio usuário no projeto anterior).
