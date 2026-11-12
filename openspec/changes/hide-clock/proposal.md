# Proposal

## Why

Os consoles não têm bateria de RTC nem rede: sobem com o relógio em 1970, e o relógio no
topo do menu do RetroArch mostra uma hora sem sentido. O usuário pediu para tirá-lo da tela
(P-31 em `docs/PENDENCIAS.md`, 2026-11-11).

## What Changes

- O padrão de fábrica do RetroArch passa a esconder a data e a hora do menu
  (`menu_timedate_enable = "false"` na configuração de fábrica).
- É um padrão do usuário, não uma chave fixa: quem quiser o relógio religa em
  Configurações → Interface do usuário → Mostrar data e hora, e a escolha fica no cartão.
- Cartões que já têm configuração salva não mudam (a configuração de fábrica só vale para
  cartões novos, P-04); nesses, o usuário desliga uma vez no menu.

Fora do escopo: a hora persistente entre boots (P-07).

## Capabilities

### New Capabilities

Nenhuma.

### Modified Capabilities

- `frontend-session`: o menu, por padrão, não mostra data e hora.

## Impact

- `rootfs/overlay/usr/share/r36os/factory/retroarch/retroarch.cfg` (uma chave).
- `tests/unit/test_retroarch_cfg.py` (padrão de fábrica, nunca chave fixa).
- `docs/PENDENCIAS.md`: o P-31 aponta para esta change.
