# Tasks

Verificação desta change: testes de unidade (Python, Rust e shell, incluindo os do initramfs com
imagens de partição de teste), o protótipo do launcher no navegador (painel Cartão) e o aparelho
(GA36 e R36S, com um único cartão passado de um console ao outro: nunca os dois ligados ao mesmo
tempo). A imagem `vm` segue fora do ciclo (P-81).

## Grafo de execução

Regras do projeto em `openspec/config.yaml` (`rules.tasks`, `operations.apply`).

**Recursos exclusivos:** `CPU` (um build pesado por vez, sob a proteção de calor),
`ARCH:armv7` e `ARCH:aarch64` (um `r36os pkg` por arquitetura), `GA36`, `R36S`, `USUARIO`
(ação física ou olho humano), `MERGE` (um merge por vez em `feature/card-health`, seguido de
`pytest tests/unit`, `cargo test` do `lume/` e das suítes de shell).

**Executores:** `AG` = subagente em `out/worktrees/<nó>` (código e teste de unidade); `PR` =
sessão principal (merge, build, aparelho, aprovação do usuário).

**Ordem de merge que importa:** a 2.1 (pular a verificação com o volume limpo) só é mesclada
depois de a 1.1 mostrar o bit limpo após um desligamento normal, ou junto da 2.2, que o deixa
limpo. Nunca existe um build que pula a verificação com o desligamento deixando o volume sujo.

| Nó | Depende de | Recursos | Executor | Modelo | Onda | Janela |
|---|---|---|---|---|---|---|
| 1.1 | — | GA36, R36S, USUARIO | PR | — | 0 | J1 |
| 1.2 | — | — | AG | sonnet | 0 | |
| 2.1 | — | — | AG | opus | 0 | J2, J3 |
| 2.2 | 1.1 | — | AG | opus | 1 | J2, J3 |
| 3.1 | 1.2 | — | AG | sonnet | 1 | J2, J3 |
| 4.1 | — | USUARIO | AG+PR | sonnet | 0 | |
| 4.2 | 1.2, 4.1 | — | AG | sonnet | 1 | J2, J3 |
| 5.1 | — | GA36, R36S, USUARIO | PR | — | 0 | J1 |
| 5.2 | 5.1 | — | AG | sonnet | 1 | J2, J3 |
| 6.1 | 2.1, 2.2, 3.1, 4.2, 5.2 | CPU, ARCH:armv7, ARCH:aarch64 | PR | — | 2 | |
| 6.2 | 6.1 | GA36, USUARIO | PR | — | 3 | J2 |
| 6.3 | 6.2 | R36S, USUARIO | PR | — | 4 | J3 |

Modelos: propostos, aguardando aprovação do usuário.

**Trilhas e caminho crítico:**

```
  1.1 (prova do bit, J1) --> 2.2 (desligamento limpo) --+
  2.1 (initramfs: bit e pedido) ------------------------+
  1.2 (pedidos) --+--> 3.1 (serviço r36os-card) --------+--> 6.1 build --> 6.2 GA36 (J2) --> 6.3 R36S (J3)
                  +--> 4.2 (painel Cartão) -------------+
  4.1 (protótipo, USUARIO) --^                          |
  5.1 (medição read-ahead, J1) --> 5.2 (regra udev) ----+

  caminho crítico: 1.1 -> 2.2 -> 6.1 -> 6.2 -> 6.3
```

**Ondas:**
- Onda 0: 1.2, 2.1, 4.1 (AG, em paralelo; a 4.1 termina com a aprovação do usuário); 1.1 e 5.1
  (PR, janela J1 com o build atual).
- Onda 1: 2.2, 3.1, 4.2, 5.2.
- Onda 2: 6.1. Onda 3: 6.2 (janela J2). Onda 4: 6.3 (janela J3).

**Janelas de aparelho:**
- **J1** (build atual, sem código novo; GA36 e depois R36S, o mesmo cartão): o usuário desliga
  pelo menu, desliga pelo botão e corta a energia (tirar a bateria não é preciso: segurar o
  botão até desligar à força); depois de cada um, o bit é lido pelo cabo no boot seguinte, antes
  da verificação de hoje (o log do initramfs, ou `dd` do setor da `ROMS` com o console no
  launcher). Na mesma janela, a medição do read-ahead (5.1).
- **J2** (GA36, build da 6.1): boot limpo sem verificação, corte de energia com verificação,
  pedido consumido uma vez, TRIM, painel Cartão, read-ahead aplicado.
- **J3** (R36S, o mesmo cartão): as mesmas provas da J2.

## 1. Prova do bit e pedidos

- [ ] 1.1 Janela J1: ler o `VolumeFlags` (deslocamento 106 do setor de boot da `ROMS`) depois de um desligamento pelo menu, de um pelo botão e de um corte de energia, no GA36 e no R36S. Verificação: tabela no `docs/BRINGUP-GA36.md` e no `docs/BRINGUP-R36S.md` com o bit em cada caso, e a decisão do D2 (remontar ou não) anotada no `design.md`.
- [ ] 1.2 Congelar os pedidos (D4): a pasta `/run/r36os/card/` (grupo `game`), os verbos `trim` e `check-next-boot`, o formato do `status` (`running`, `ok <bytes>`, `ok`, `fail <motivo>`) e os arquivos `ROMS/system/card/last-trim`, `last-check` e `check-next-boot` (número do boot em texto). Documentado em `docs/LAUNCHER.md` e num módulo Rust no `lume-core` com o leitor do `status` e dos `last-*`. Verificação: testes de unidade do leitor (cada estado, arquivo ausente vira "nunca", conteúdo inválido ignorado).

## 2. Boot e desligamento

- [ ] 2.1 `initramfs/lib/storage.sh` (D1, D3): `volume_flags` lê os 2 bytes do `VolumeFlags`; o caso `check` verifica só com `VolumeDirty` ou `MediaFailure` ligados ou com o pedido `system/card/check-next-boot` (lido com a `ROMS` montada, desmontando para o `fsck` e montando de novo); o pedido é apagado e o número do boot gravado em `system/card/last-check`; eventos `clean: check skipped`, `dirty: checked ...` e `requested: checked ...`; `docs/LOGS.md` com os eventos. Verificação: testes do initramfs com imagens de partição exFAT de teste (limpa, suja, com falha de mídia, limpa com pedido), cada uma com o resultado e o log esperados; spec `boot-runtime`. Mesclada só depois da 1.1 ou junto da 2.2 (ordem de merge acima).
- [ ] 2.2 Desligamento limpo (D2), conforme a 1.1: se o bit ficou ligado depois do desligamento normal, o fim da sessão remonta `/storage` como somente leitura depois do `sync` e antes do `poweroff` (desmontando, se a prova mostrar que remontar não basta), registrando a falha sem impedir o desligamento; se o bit já ficava limpo, a task registra isso e fica marcada. Verificação: teste do shell do `session` (ordem `sync`, remontar, `poweroff`; falha registrada e desligamento segue); no aparelho, o bit limpo depois do desligamento pelo menu e pelo botão (J2, J3).

## 3. Serviço de manutenção

- [ ] 3.1 Serviço `r36os-card` (D4) no `lume-saves`: `inotifyd` em `/run/r36os/card/`, verbos `trim` (`fstrim -v /storage`, um por vez, `status` e `last-trim`) e `check-next-boot` (cria o pedido na `ROMS`); outro nome recusado com uma linha no log; eventos `card OK trim`/`card FAIL trim` no `events.log`; sobe depois do `frontend`. Verificação: testes do shell com `fstrim` falso (sucesso, falha, pedido em dobro, verbo desconhecido) e com a `ROMS` numa pasta de teste; no aparelho, o serviço sem CPU parado e o TRIM pelo painel (J2, J3).

## 4. Painel Cartão no launcher

- [ ] 4.1 Painel Cartão no protótipo (`docs/lume-launcher/prototipo/`, D5), no molde do painel Sistema: espaço livre, última otimização e última verificação pelo número do boot ("nunca" quando não houver), "Otimizar agora" com os estados em andamento, concluído e falha, e "Verificar no próximo boot" com a confirmação de que ficou pedido, nos temas e nos três idiomas; medidas a 640x480 anotadas no `docs/lume-launcher/design-das-telas.md`. Verificação: o usuário aprova no navegador a 640x480 (aprovação anotada com a data).
- [ ] 4.2 `lume-ui` (D5): `SetRow::Card` entre Sistema e Games; painel com o espaço livre (`statvfs`), `last-trim` e `last-check`; A nas ações escreve o pedido na pasta do D4; com o TRIM em andamento e o painel aberto, lê o `status` a cada segundo, e não lê nada com o painel fechado; textos en/pt/es no `i18n`. Verificação: testes de tela em `lume/lume-ui/tests/ui.rs` (painel com e sem histórico, cada estado do TRIM, pedido escrito na pasta) e o teste de régua `card_matches_the_prototype_ruler` (1 px a 640x480); no aparelho, J2 e J3.

## 5. Read-ahead

- [ ] 5.1 Janela J1: medir o tempo de abrir uma ROM grande de PS1 e uma de arcade com `read_ahead_kb` em 128, 256, 512 e 1024, com o cache do kernel limpo entre as medidas (`echo 3 > /proc/sys/vm/drop_caches` pelo cabo), três vezes cada, nos dois consoles. Verificação: tabela no `design.md` (D6) só com os tempos por sistema, sem nome de jogo, e o valor escolhido (ou "nenhum ganho claro").
- [ ] 5.2 Regra do udev no `lume-power` com o valor da 5.1 (ou nenhuma regra, registrado na task, se a medição não mostrou ganho). Verificação: teste da regra como o da `90-lume-backlight.rules`; no aparelho, o `read_ahead_kb` do cartão com o valor depois do boot e `mem_avail_mb` num jogo pesado anotado (J2, J3).

## 6. Build e provas nos consoles

- [ ] 6.1 Build dos pacotes mudados (initramfs, `lume-saves`, `lume-power`, `lume-launcher`, `lume-core`) nas duas arquiteturas, um `r36os pkg` por vez sob a proteção de calor, e `r36os push` para o cartão. Verificação: os `.apk` e o initramfs novos com a versão nova no repositório local e o `push` terminando com `ok`.
- [ ] 6.2 Janela J2 no GA36: três boots depois de desligar pelo menu com `roms OK clean: check skipped` e o tempo do boot comparado com o de antes (o ganho anotado no P-58, frente 3); um corte de energia seguido de boot com `dirty: checked`; "Verificar no próximo boot" consumido no boot seguinte e não no outro; "Otimizar agora" com o resultado na tela e no `events.log`; o painel comparado com o protótipo; o serviço sem CPU parado 5 minutos; o `read_ahead_kb` aplicado. Verificação: resultado anotado no `docs/BRINGUP-GA36.md`.
- [ ] 6.3 Janela J3 no R36S, com o mesmo cartão: as mesmas provas da 6.2. Verificação: resultado anotado no `docs/BRINGUP-R36S.md`; P-64 movido para "Concluídas" no `docs/PENDENCIAS.md` (itens 1, 2 e 4, com o item 3 apontando para a change do governor) e a frente 3 do P-58 atualizada.

## Workflow follow-up

- Arquivar a change depois das provas da J2 e da J3.
