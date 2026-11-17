# Tasks

Verificação desta change: testes de unidade (Rust do `lume/`, Python em `tests/unit`, suítes
de shell), o protótipo do launcher no navegador a 640x480 (telas novas aprovadas pelo usuário)
e o aparelho (GA36 e R36S, com um único cartão passado de um console ao outro: nunca os dois
ligados ao mesmo tempo). A imagem `vm` segue fora do ciclo (P-81).

**Pré-requisito externo:** a change `lume-hud-actions` mesclada até a 2.1 dela (o
`r36os-input` mandando `fn_tap`, `fn_hold <tabela>` e `fn_release`, e o parser do protocolo no
`lume-core`). Os nós que não dependem disso (protótipo, cores, logos, código 66) podem andar
antes.

## Grafo de execução

Regras do projeto em `openspec/config.yaml` (`rules.tasks`, `operations.apply`).

**Recursos exclusivos:** `CPU` (um build pesado por vez, sob a proteção de calor),
`ARCH:armv7` e `ARCH:aarch64` (um `r36os pkg` por arquitetura), `GA36`, `R36S`, `USUARIO`
(ação física ou olho humano), `MERGE` (um merge por vez em `feature/launcher-adjustments`,
seguido de `cargo test` do `lume/`, `pytest tests/unit` e das suítes de shell).

**Executores:** `AG` = subagente em `out/worktrees/<nó>` (código e teste de unidade); `PR` =
sessão principal (merge, build, aparelho, aprovação do usuário).

**Ordem de merge que importa:** a 3.3 (o `session` e o `lume-run` com o código 66) é mesclada
antes da 3.2 (o menu que sai com 66), para nunca existir um build em que Reiniciar conta como
falha do frontend. A 3.2 tira o Desligar das Configurações e põe o menu do sistema no mesmo
commit, para nunca existir um build sem caminho para desligar.

| Nó | Depende de | Recursos | Executor | Modelo | Onda | Janela |
|---|---|---|---|---|---|---|
| 1.1 | — | — | AG | sonnet | 0 | |
| 1.2 | — | — | AG | sonnet | 0 | |
| 1.4 | — | — | AG | sonnet | 0 | |
| 1.3 | 1.4 | USUARIO | AG+PR | sonnet | 1 | |
| 2.2 | 1.1 | — | AG | sonnet | 1 | J1, J2 |
| 3.1 | `lume-hud-actions` 1.1 e 2.1 | — | AG | sonnet | 1 | J1, J2 |
| 3.3 | 1.2 | — | AG | opus | 1 | J1, J2 |
| 2.1 | 1.1, 1.3, 1.4 | — | AG | sonnet | 2 | J1, J2 |
| 3.2 | 1.2, 1.3, 3.1, 3.3 | — | AG | sonnet | 2 | J1, J2 |
| 3.4 | 1.3, 3.1 | — | AG | sonnet | 2 | J1, J2 |
| 4.1 | 2.1, 2.2, 3.2, 3.3, 3.4 | CPU, ARCH:armv7, ARCH:aarch64 | PR | — | 3 | |
| 4.2 | 4.1 | GA36, USUARIO | PR | — | 4 | J1 |
| 4.3 | 4.2 | R36S, USUARIO | PR | — | 5 | J2 |

Modelos aprovados pelo usuário em 2026-11-17.

**Trilhas e caminho crítico:**

```
  1.4 (cores oficiais) --> 1.3 (protótipo, USUARIO) --+--> 2.1 (cores no Dock) --------+
                                 ^                    |                                |
  1.1 (formato do tema) ---------+--------------------+--> 2.2 (logo colorido) --------+
                                                      |                                |
  lume-hud-actions --> 3.1 (eventos do Fn) -----------+--> 3.4 (dica) -----------------+--> 4.1 build
                                     |                |                                |      |
  1.2 (código 66) --> 3.3 (session, lume-run) --------+--> 3.2 (menu do sistema) ------+      v
                                                                                          4.2 GA36 (J1)
                                                                                              |
                                                                                              v
                                                                                          4.3 R36S (J2)

  caminho crítico: 1.4 -> 1.3 -> 3.2 -> 4.1 -> 4.2 -> 4.3
  (ou lume-hud-actions -> 3.1 -> 3.2, se ela terminar depois da 1.3)
```

**Ondas:**
- Onda 0: 1.1, 1.2, 1.4 (AG, em paralelo).
- Onda 1: 1.3 (termina com a aprovação do usuário), 2.2, 3.3, e 3.1 assim que a
  `lume-hud-actions` estiver mesclada.
- Onda 2: 2.1, 3.2, 3.4.
- Onda 3: 4.1 (build dos pacotes, fila única de CPU).
- Onda 4: 4.2 (janela J1). Onda 5: 4.3 (janela J2).

**Janelas de aparelho:**
- **J1** (GA36, build da 4.1): todas as telas contra o protótipo, o menu do sistema, a dica,
  Desligar e Reiniciar, as cores por console, as conferências da P-70 do GA36 e a P-71. O
  usuário navega, aperta o Fn e confere a tela.
- **J2** (R36S, o mesmo cartão): as mesmas provas e as medições da P-70 do R36S.

## 1. Interfaces congeladas e protótipo

- [ ] 1.1 Congelar o formato do tema para as cores e os logos (D6, D7): tabela `[systems.<id>]` com `icon_bg`, `icon_fg`, `icon_sel_bg` e `icon_sel_fg`, resolução chave a chave (sistema no tema, na cadeia `extends`, depois o token geral), e `icons/<sistema>.color.png` com prioridade sobre a máscara do mesmo tema; parser e validação no carregamento do tema (sistema fora do catálogo é aviso, cor inválida é erro e cai para o herdado, chave desconhecida é aviso); `docs/lume-launcher/formato-de-tema.md` atualizado (tabela de tokens, exemplo, ordem de busca do logo colorido, "a distro não traz logos coloridos"). Verificação: testes de unidade do tema (herança de uma chave só, sistema sem tabela usa o geral, cor inválida cai para o herdado e registra erro, `.color.png` antes da máscara, busca na cadeia `extends`).
- [ ] 1.2 Congelar o código de saída 66 no contrato de sessão (D3): `docs/FRONTEND.md` com 0 (desligar), 66 (reiniciar) e qualquer outro (falha), e a constante nos dois lados (`lume-ui` e `lume-run`, junto de 64 e 65). Verificação: teste de unidade que confere a mesma constante nos dois crates e o texto do `docs/FRONTEND.md` (o teste lê o documento).
- [ ] 1.3 Telas novas no protótipo (`docs/lume-launcher/prototipo/`, D5): menu do sistema (Desligar, Reiniciar, Configurações, foco em Configurações) e as confirmações de Desligar e Reiniciar com Cancelar em foco; a dica do Fn no launcher; a dica do Fn no rodapé do Dock; o Dock do tema Lume com as cores por console da 1.4; nos temas do protótipo e nos três idiomas; medidas a 640x480 numa tabela no `docs/lume-launcher/design-das-telas.md`. Verificação: o usuário aprova as telas no navegador a 640x480 (aprovação anotada na tabela com a data).
- [ ] 1.4 Tabela das cores oficiais dos logos dos sistemas do catálogo (D6): para cada sistema com logo oficial conhecido, `icon_bg`/`icon_fg` e o par de foco, com a fonte de cada cor (guia de marca ou logo oficial publicado) e o contraste entre `icon_fg` e `icon_bg` de pelo menos 3:1; a tabela vai para o `theme.toml` do tema Lume como `[systems.*]`, com a fonte em comentário. Verificação: teste de unidade que lê o tema Lume e confere o contraste de cada sistema e que todo sistema da tabela existe no catálogo; a revisão das cores é a aprovação da 1.3.

## 2. Cores e logos no Dock

- [ ] 2.1 `lume-ui`, cores por console (D6): o tile, a máscara do logo e a sigla usam os tokens resolvidos do sistema, normal e em foco; temas sem `[systems.*]` desenham como hoje. Verificação: testes de tela em `lume/lume-ui/tests/ui.rs` com o tema Lume (cor do SNES e do Mega Drive no tile e no foco, conferidas contra a tabela da 1.3) e com o Material escuro (cor geral em todos); no aparelho, captura do Dock comparada com o protótipo (J1, J2).
- [ ] 2.2 `lume-ui`, logo colorido do cartão (D7): `icons/<sistema>.color.png` desenhado como imagem RGBA, reduzido ao tamanho do tile na decodificação, com prioridade sobre a máscara e a mesma busca na cadeia `extends`; o teto do cache de ícones vale para os dois tipos; teste do pacote que recusa qualquer PNG em `themes/` da imagem. Verificação: testes de unidade (um tema de teste com `snes.color.png` e `nes.png`: SNES colorido, NES em máscara; cache dentro do teto com logos grandes) e o teste do pacote; no aparelho, um tema do cartão com um logo colorido (J1).

## 3. Menu do sistema, Reiniciar e dica

- [ ] 3.1 `lume-ui`, eventos do Fn: a thread do socket (`lume/lume-ui/src/input.rs`) passa a ler `fn_tap`, `fn_hold <tabela>` e `fn_release` pelo parser do `lume-core` (da `lume-hud-actions`) e manda `Ev::FnTap`, `Ev::FnHold(tabela)` e `Ev::FnRelease` ao laço principal; as mensagens dos acordes do jogo continuam ignoradas. Verificação: testes de unidade da leitura do socket (as três mensagens viram os três eventos, a tabela do `fn_hold` chega em pares, `save_state` e `quit` são ignorados).
- [ ] 3.2 `lume-ui`, menu do sistema (D1, D2): camada `system` desenhada por cima de qualquer tela ou folha e com a entrada antes do resto; `Ev::FnTap` abre e fecha; foco inicial em Configurações; Desligar e Reiniciar com confirmação e Cancelar em foco, saindo com 0 e 66; Configurações abre as Configurações lembrando a tela de origem, e B volta a ela; `SetRow::Power` sai da lista das Configurações; a dica do Fn no rodapé do Dock; textos en, pt e es; `docs/LAUNCHER.md` (menu do sistema, atalhos do Fn no launcher). Verificação: testes de tela e de estado em `tests/ui.rs` (menu sobre a grade e volta com o foco no mesmo jogo, menu sobre uma folha aberta, outro toque fecha, Cancelar é o padrão nas duas confirmações, Configurações a partir da grade e B volta à grade, as Configurações sem Desligar e dando a volta em RetroArch, medidas iguais à tabela da 1.3, rodapé do Dock com a dica); o teste antigo da folha de Desligar das Configurações sai; no aparelho, J1 e J2.
- [ ] 3.3 Reiniciar pelo contrato de sessão (D3): o `lume-run` repassa o código 66 do `lume-ui` como repassa o 0; o `session` (`aports/lume-core/files/usr/libexec/r36os/session`) ganha o ramo `rc 66`: `kmsg` e `event frontend OK "... closed by user: rebooting"`, `persist flush`, `sync` e `reboot`; os outros códigos continuam como hoje. Verificação: teste do `lume-run` (filho que sai com 66 faz o `lume-run` sair com 66; 64 e 65 sem mudança) e suíte de shell do `session` com `poweroff` e `reboot` falsos no `PATH` (0 chama `poweroff`, 66 chama `reboot`, os dois depois do `persist flush` e do `sync`, 1 conta falha); no aparelho, Reiniciar volta ao launcher e o boot seguinte registra `shutdown OK previous clean` (J1, J2).
- [ ] 3.4 `lume-ui`, dica dos atalhos (D4): `Ev::FnHold` mostra o painel com "Fn (toque): Menu do sistema" e os acordes da tabela que o launcher reconhece (nesta versão, `Vol=brightness`), no idioma do usuário; some no `Ev::FnRelease`, no evento de brilho ou ao abrir o menu; com o menu do sistema aberto, o `fn_hold` é ignorado. Verificação: testes de tela (dica com os dois itens, medidas iguais à tabela da 1.3; some no `FnRelease` sem abrir o menu; some no `brightness`; ignorada com o menu aberto); no aparelho, J1 e J2.

## 4. Build e provas nos consoles

- [ ] 4.1 Build dos pacotes mudados (`lume-launcher`, `lume-core` e o pacote do tema, se separado) nas duas arquiteturas, um `r36os pkg` por vez sob a proteção de calor, e `r36os push` para o cartão. Verificação: os `.apk` novos com o `pkgrel` novo no repositório local e o `push` terminando com `ok`.
- [ ] 4.2 Janela J1 no GA36 (D8): (a) telas contra o protótipo com capturas pelo `r36os-shot`: Dock com as cores por console e a dica do Fn no rodapé, grade, busca, menu do jogo em folha, opções do console, Configurações sem Desligar e com o foco no painel, Sistema com a temperatura, menu do sistema, as duas confirmações, a dica ao segurar o Fn; (b) toque no Fn abre e fecha o menu no Dock, na grade, na busca e nas Configurações, e a tela volta igual; Fn+Vol muda o brilho sem abrir o menu (teto no nível 7, linha branca à esquerda); (c) a linha de volume e brilho sobre um jogo do RetroArch, nas cores do tema; (d) tempo até o primeiro quadro de um jogo; (e) Desligar apaga a tela e o boot seguinte registra `shutdown OK previous clean` (fecha a P-71 no GA36); Reiniciar três vezes, voltando ao launcher, sem desligar; (f) um tema do cartão com um logo colorido. Verificação: resultado anotado no `docs/BRINGUP-GA36.md`, sem nome de jogo; o que falhar vira tarefa aqui; P-71 movido para "Concluídas" no `docs/PENDENCIAS.md`.
- [ ] 4.3 Janela J2 no R36S, com o mesmo cartão: as mesmas provas da 4.2, mais as medições da 9.6 da `lume-launcher` (CPU e memória com o launcher parado, tempo do fim do jogo até a grade, tempo de boot), o nome do sensor de temperatura no painel Sistema (`soc-thermal` esperado), Fn+Vol sem teto (anotar se a luz pisca nos níveis altos, como no GA36; se piscar, `backlight_max` no `aports/r36os-input/r36s.conf`) e a mancha clara nas bordas num fundo liso (observar; se aparecer, captura e registro na P-70). Verificação: resultado anotado no `docs/BRINGUP-R36S.md`, sem nome de jogo; P-70, P-72, P-74 e P-84 movidos para "Concluídas" no `docs/PENDENCIAS.md` com o nome desta change (o que sobrar da P-70 vira P-NN nova).

## Workflow follow-up

- Arquivar a change depois das provas da J1 e da J2.
