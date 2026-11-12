# Design

## Context

O RetroArch tem dois lugares de configuração na imagem: `retroarch-lume.cfg` (chaves fixas,
regravadas pelo frontend a cada início) e `factory/retroarch/retroarch.cfg` (padrões do
usuário, copiados para um cartão sem configuração). A chave `menu_timedate_enable` controla
a data e a hora no topo do Ozone.

## Decisions

### D1. Padrão de fábrica, não chave fixa

`menu_timedate_enable = "false"` vai para a configuração de fábrica. Uma chave fixa
desligaria o relógio para sempre, mesmo para quem ligasse no menu (o frontend regrava as
chaves fixas a cada início). Assim o usuário decide, e a escolha persiste com o resto da
configuração na `ROMS`.

## Risks / Trade-offs

- **[Cartões existentes continuam com o relógio]** → A configuração de fábrica só vale para
  cartões novos (P-04); o usuário desliga uma vez no menu. Documentado na proposta.
