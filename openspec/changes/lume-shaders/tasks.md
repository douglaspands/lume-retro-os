# Tasks

## 1. Shaders na imagem

- [x] 1.1 Copiar sem alteração os presets e shaders `gb-modern-dmg`, `gbc-modern-remaster` e `gba-modern-remaster` do projeto anterior para `rootfs/overlay/usr/share/libretro/shaders/lume-shaders/{gb,gbc,gba}/`. Verificação: teste novo confere cada preset (aponta para um `.glsl` que existe na mesma pasta, um passe) e o SHA256 de cada arquivo contra o do projeto de origem, registrado no teste.
- [x] 1.2 `video_shader_dir = "/usr/share/libretro/shaders"` como chave fixa em `retroarch-lume.cfg`; nenhum shader ligado na configuração de fábrica. Verificação: `tests/unit/test_retroarch_cfg.py` (conjunto de chaves fixas e ausência de `video_shader` ligado na fábrica).
- [x] 1.3 `README.md`: a origem dos shaders nos Agradecimentos. Verificação: o teste dos shaders confere a menção.

## 2. Verificação

- [x] 2.1 Build `vm` e `test-vm`: os arquivos estão no `SYSTEM` em `/usr/share/libretro/shaders/lume-shaders/`. Verificação: manifesto de arquivos do rootfs ou listagem do `SYSTEM`.
- [ ] 2.2 No aparelho (GA36 e R36S): Shaders → Carregar abre em `/usr/share/libretro/shaders`, e cada preset carrega num jogo do seu sistema. Verificação: anotar no `docs/BRINGUP-R36S.md` e no `docs/BRINGUP-GA36.md`.

## Workflow follow-up

- Branch `feature/lume-shaders`, criado a partir do `feature/r36s-single-card`; o merge na `main` é por PR com squash, só quando o usuário pedir.
