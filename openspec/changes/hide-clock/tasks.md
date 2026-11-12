# Tasks

## 1. Configuração

- [x] 1.1 `menu_timedate_enable = "false"` na configuração de fábrica do RetroArch, nunca em `retroarch-lume.cfg`. Verificação: `tests/unit/test_retroarch_cfg.py::test_menu_has_no_clock_by_default`.
- [x] 1.2 `docs/PENDENCIAS.md`: o P-31 aponta para esta change. Verificação: a linha do P-31 cita `hide-clock`.

## 2. Aparelho

- [ ] 2.1 Num cartão gravado com `flash --full`, o menu abre sem relógio; ligar "Mostrar data e hora" no menu e reiniciar mantém o relógio. Verificação: conferido no GA36 ou no R36S e anotado no guia de bring-up.

## Workflow follow-up

- Branch `feature/hide-clock`, criado a partir do `feature/r36s-single-card` e trazido para ele por fast-forward (entra no próximo cartão, decisão do usuário em 2026-11-11).
