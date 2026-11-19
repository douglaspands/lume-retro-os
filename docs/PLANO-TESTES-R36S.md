# Plano de testes no R36S (todas as changes do branch)

Plano em grafo (regras em `openspec/config.yaml`, `rules.tasks`) das provas que faltam **só no
R36S** nas quatro changes abertas do branch `feature/virtual-gamepad`: `device-fixes`,
`lume-hud-actions`, `virtual-gamepad` e `game-governor`. Escrito em 2026-11-19, com o GA36
fechado pelas conferências do usuário ("tudo funcionando aparentemente") e o cartão indo para
o R36S. A fonte de verdade continua sendo o `tasks.md` de cada change: este arquivo só ordena.

**Regras de sempre:** um cartão para os dois consoles (nunca os dois ligados); o R36S no cabo
pela porta OTG (carga só pela DC); nenhum nome de jogo nem caminho de ROM em nenhum registro;
um build por vez com o monitor de calor; subagente só com o modelo aprovado pelo usuário antes
de cada onda; horários para o usuário em UTC-3; avisar antes de cada momento de olhar o console.

## Estado de partida

- Cartão com o build `20261118-233509` (GA36) e o lado do R36S de `20261118-230848` (RetroArch
  com o patch 0015, kernel e initramfs da 9.16).
- Feito em 2026-11-19: `lume build --console r36s lume-input lume-audio lume-launcher` (7.2,
  7.5, 9.15 e 7.6 no R36S), terminou bem. Falta só o `push` (nó R0).
- Pendência de teste P-103 (`docs/PENDENCIAS.md`) resume as mesmas provas.

## Grafo

Recursos: `R36S` (aparelho no cabo), `USUARIO` (olho e mãos), `CPU` (build), `MERGE`.

| Nó | O quê | Change e tarefa | Depende de | Recursos | Executor | Modelo | Onda | Janela |
|---|---|---|---|---|---|---|---|---|
| R0 | `lume push --console r36s --yes` do build parcial e conferir o boot (`lume dev log`, `events.log`), nomes `lume` no R36S pela primeira vez | todas | build parcial | R36S, CPU | PR | — | 0 | J1 |
| R1 | Suspensão: `/sys/power/mem_sleep`, `freeze` e `mem` (se houver) 10 vezes cada pelo botão, a corrente suspenso; o carregador acorda ou não | `device-fixes` 2.3 (e a nota da 10.3 sobre o `rk817_charger`) | R0 | R36S, USUARIO | PR | — | 1 | J1 |
| R2 | RTC: acertar pelo cabo, desligar 5 min sem cabo, ler o `rtc0` | `device-fixes` 2.4 | R0 | R36S, USUARIO | PR | — | 1 | J1 |
| R3 | Read-ahead: abrir uma ROM grande de PS1 e uma de arcade com `read_ahead_kb` 128/256/512/1024, cache limpo, 3 vezes cada | `device-fixes` 2.2 | R0 | R36S | PR | — | 1 | J1 |
| R4 | Áudio pelo I2C: registradores de ganho do classe D e do fone do RK817 com um tom tocando, o zumbido de cada um (P-45), a corrente com o amplificador ligado e desligado; o volume novo (`Master` digital) do mínimo ao máximo, limpo | `device-fixes` 2.5 | R0 | R36S, USUARIO | PR | — | 1 | J1 |
| R5 | GPU e bateria: `drm-engine-*` no `fdinfo` do RetroArch com o `panfrost`, com e sem `profiling`; campos da bateria do RK817 (sinal do `current_now` carregando e descarregando) | `lume-hud-actions` 4.1 | R0 | R36S | PR | — | 1 | J1 |
| R6 | Menu do Lume pelo sistema no `rockchip`: RetroArch num jogo, um Port ou LÖVE, RetroArch travado; plano livre do VOP; `pidfd_getfd` como `game` | `lume-hud-actions` 4.6, `device-fixes` 9.14 | R0 | R36S, USUARIO | PR | — | 1 | J1 |
| R7 | Bit do exFAT pelos eventos da 5.1: desligar pelo menu, pelo botão segurado e corte de energia | `device-fixes` 2.1 | R0 | R36S, USUARIO | PR | — | 1 | J1 |
| C1 | Kernel do R36S: controles ALSA do ganho analógico do RK817 (se o R4 achou) ou registro no P-45 | `device-fixes` 7.1 | R4 | — | AG | opus | 2 | |
| C2 | Regra do udev do read-ahead com o valor do R3, ou nenhuma | `device-fixes` 5.5 | R3 | — | AG | sonnet | 2 | |
| C3 | Regra do udev do `profiling` do `panfrost` gravável pelo grupo `video`, se o R5 pediu | `lume-hud-actions` 4.4 | R5 | — | AG | sonnet | 2 | |
| C4 | Se o R1 mostrou que o carregador acorda a suspensão: patch do `rk817_charger`; e o modo de suspensão escolhido no `lume-sleep` | `device-fixes` 2.3, 8.x | R1 | — | AG | opus | 2 | |
| C6 | Bateria do RK817: barra (`hud.rs`) e `logd` (C e shell) leem `voltage_avg`/`current_avg` quando não há `*_now` (achado do R5) | `lume-hud-actions` 4.2, `game-governor` 1.2 | R5 | — | AG | sonnet | 2 | |
| B1 | Build dos nós C1 a C4 e C6 (kernel e pacotes do R36S) e `push` | — | C1, C2, C3, C4 | CPU, MERGE | PR | — | 3 | |
| G1 | Medição dos perfis de energia: as sessões do D5 por classe e candidato no modo manual, com e sem o controlador nos pesados, tabela do `lume power report` | `game-governor` 6.1 (e as partes "no R36S" de 1.2, 2.2, 2.3, 4.2: `logd` < 1% de um núcleo, SNES no `snes9x2005_plus` com um save state antigo) | B1 | R36S, USUARIO | PR | — | 4 | J2 |
| C5 | `r36s.conf` com os perfis escolhidos no G1, validador contra a tabela de OPP do R36S copiada do aparelho | `game-governor` 6.2 | G1 | — | AG | sonnet | 5 | |
| B2 | Build do `lume-power` do R36S e `push` | `game-governor` 6.3 | C5 | CPU | PR | — | 6 | |
| V2 | Controle virtual: `dev keys`, gravação de 60 s repetida (atraso ≤ 10 ms), roteiros `open-close-*` e `launcher-screens`, replay do RetroArch duas vezes, `play` como `game` recusado | `virtual-gamepad` 4.3 | B1 | R36S | PR (o usuário só olha) | — | 4 | J2 |
| J3 | Janela final, mesmo cartão: a lista da `device-fixes` 10.2 que vale para o R36S (cartão, suspensão pelo botão 20 vezes, desligar segurando, menu do sistema pelo Fn, menu do Lume e barra no LÖVE, Port e RetroArch, trava do Quick Menu, volume e fone pelo `jack`, ganho da 7.1, zumbido do P-45, hora e NTP, analógicos, nós só leitura com os botões no RetroArch, rede USB, temperatura na barra, notificações do RetroArch desligadas, brilho salvo desde o boot), mais a `lume-hud-actions` 6.3 (as provas da 6.2 com a GPU com número na barra), a `game-governor` 6.4 (as provas da 5.5: eventos `power`, tela escurece em 2 min, aviso e desligamento com bateria crítica, controlador, `reload`) | `device-fixes` 10.3, `lume-hud-actions` 6.3, `game-governor` 6.4 | B1, B2 | R36S, USUARIO | PR | — | 7 | J3 |
| F1 | Fechar: marcar as tarefas, resultados no `docs/BRINGUP-R36S.md` sem nome de jogo, mover as pendências citadas para "Concluídas" (P-62, P-86, P-20 etapa 1, P-60, P-78, P-83, P-103, os itens da `device-fixes` 10.3), arquivar as quatro changes (`/opsx:archive`) | todas | J3, V2 | MERGE | PR | — | 8 | |

**Caminho crítico:** R0 → R4 → C1 → B1 → G1 → C5 → B2 → J3 → F1.

**Janelas de aparelho (com o usuário):**
- **J1 (~1h30):** R0 a R7. O R1 e o R7 pedem toques no botão; o R4 pede ouvir o zumbido; o R6
  pede olhar o menu sobre o jogo. O R2 tem 5 min de espera sem cabo (dá para fazer o R3 antes).
- **J2 (~2h, pode ser em partes):** G1, as sessões de medição por classe de sistema (o
  usuário joga cada uma, o PC mede); o V2 roda sozinho pelo cabo enquanto isso não ocupa o
  aparelho.
- **J3 (~1h30):** a lista final.

## Andamento

- 2026-11-19, R0: push do build `20261118-234742`, boot 202 limpo, frontend em 16,8 s.
- R3: medido (tabela no D6 da `device-fixes`); escolha provisória: regra de 512 KiB só no R36S
  (C2, a confirmar pelo usuário).
- R5: `drm-engine-*` só com `profiling=1`, arquivo `root 0644` → C3 feito (regra
  `90-lume-gpu-profiling.rules`, conferida no aparelho: `root:video rw-rw-r--`). O RK817 só tem
  `current_avg`/`voltage_avg` (carregando: positivo) → C6 feito, com testes. Sem Yama no kernel.
  Descarregando: `current_avg` negativo (-228 mA na tela inicial, 3,79 V).
- R1 (parte automática): `mem_sleep` = `s2idle [deep]`; 10 de 10 em `freeze` e 10 de 10 em
  `mem` pelo alarme do RTC, nenhum despertar antes da hora (fora do carregador). Faltam: o
  despertar pelo botão, o carregador ligado durante a suspensão e a corrente suspenso
  (precisa de uma suspensão longa: o contador de carga do RK817 só atualiza de tempos em
  tempos).
- Fuso do cartão (`system/etc/timezone`) posto em `America/Sao_Paulo` a pedido do usuário; a
  hora UTC do R36S estava certa.

- Usuário aprovou (2026-11-19): C2 com 512 KiB só no R36S, C1 e C4 com `opus`. C2 feito
  (`90-lume-readahead.rules`, conferida no aparelho: 512). C1 decidido sem código: o `Master`
  digital fica, o ganho analógico vai para o P-45 (sem ferramenta de I2C no console). C4
  espera o R1 do usuário (carregador com o console suspenso).
- Testes automáticos das outras changes rodados (V2, menu do Lume, ações, barra, custo do
  `logd`, ociosidade, `reload`): resultados no `docs/BRINGUP-R36S.md`. B1 em build com C2,
  C3, C6 e a correção do Dock no `lume-ui`.

- **Decisão do usuário (2026-11-19): nas changes só ficam provas automatizáveis.** As provas
  à mão e de ouvido (R1 botão e carregador, R7, fone, suspensões do GA36, `flash --full`,
  VBUS falso, barra e dica legíveis, `fn_hold_ms`, botões segurados no GA36) foram feitas
  pelo usuário e anotadas em cada tarefa; o P-103 foi concluído. As janelas J2 e J3 que sobram
  são pelo cabo. Fica com o usuário só a sessão curta de volume da 7.7 (o 100% do R36S perto
  de estourar) e o R2 em andamento (5 min desligado).

## Fora deste plano (lembrar)

- No GA36 ainda abertos: a J2 da `device-fixes` (10.2, P-103), a V1 da `virtual-gamepad`
  (4.2), a 2.6 (relógio escondido num cartão do `flash --full`). Podem ir para uma janela
  própria do GA36 antes ou depois do R36S.
- P-95 (tela do GA36), `launcher-adjustments` e P-98 são changes futuras.
