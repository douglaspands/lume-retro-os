# Tasks

Verificação desta change: testes de unidade (Python, Rust e shell, segundos) e o aparelho (GA36 e
R36S, com um único cartão passado de um console ao outro: nunca os dois ligados ao mesmo tempo). A imagem `vm` não é construída nem testada (D13). Cada fase termina com os dois consoles
iniciando e o `r36os dev check` verde, a partir da fase 4.

## Grafo de execução

Regras do projeto em `openspec/config.yaml` (`rules.tasks`, `operations.apply`).

**Recursos exclusivos:** `CPU` (um build pesado por vez, sob a proteção de calor da 1.1),
`ARCH:armv7` e `ARCH:aarch64` (um `r36os pkg` por arquitetura), `GA36`, `R36S`, `USUARIO` (ação
física ou olho humano), `MERGE` (um merge por vez em `feature/build-speed`, seguido de
`pytest tests/unit` e das suítes de shell).

**Executores:** `AG` = subagente em `out/worktrees/<nó>` (código e teste de unidade, testes com
`PYTHONPATH=src` e o `.venv` principal); `PR` = sessão principal (merge, build, aparelho);
`AG+PR` = código no AG, prova na PR, na janela de aparelho indicada.

**Ordem de merge que importa:** a 1.1 é mesclada antes de tudo, e a 1.2 (linha de base) roda
logo depois, antes de qualquer outro merge, para medir o código de hoje.

**Modelo** (só da parte AG; a parte PR usa o modelo da sessão principal, `—`): `opus` onde um
erro deixa o console sem boot, corrompe o build ou deixa passar uma versão errada (initramfs,
slots, push, kernel, hashes e versões, compilação cruzada, proteção de calor) ou onde a task é
uma prova com caminho incerto; `sonnet` para código bem especificado com teste de unidade claro,
documentação e mudanças mecânicas conferidas por manifesto; `haiku` só para buscas largas de
apoio, nunca para um nó.

| Nó | Depende de | Recursos | Executor | Modelo | Onda | Janela |
|---|---|---|---|---|---|---|
| 1.1 | — | — | AG | opus | 0 | |
| 1.2 | 1.1 | CPU, GA36, R36S, USUARIO | PR | — | 1 | J1 |
| 2.1 | 1.1 | CPU (prova) | AG+PR | sonnet | 1 | |
| 2.2 | — | CPU (prova) | AG+PR | sonnet | 0 | |
| 2.3 | — | — | AG | sonnet | 0 | |
| 2.4 | 2.1, 2.2, 2.3 | — | AG | sonnet | 2 | |
| 3.1 | — | GA36, R36S | AG+PR | sonnet | 0 | J1 |
| 3.2 | 3.1 | GA36, R36S | AG+PR | sonnet | 1 | J1 |
| 3.3 | 3.1 | GA36, R36S | AG+PR | opus | 1 | J1 |
| 3.4 | 3.1 | GA36, R36S, USUARIO | AG+PR | opus | 7 | J4 |
| 3.5 | 3.1 | GA36, R36S | AG+PR | sonnet | 1 | J1 |
| 3.6 | 3.1, 3.2, 3.3, 3.5 | — | AG | sonnet | 2 | |
| 4.0 | — | — | AG | opus | 0 | |
| 4.1 | — | CPU (leve) | AG+PR | opus | 1 | |
| 4.2 | 4.1 | CPU | AG+PR | sonnet | 2 | |
| 4.3 | 3.3, 4.0 | — | AG | opus | 2 | J2 |
| 4.4 | 4.0, 4.2 | CPU | AG+PR | opus | 3 | |
| 4.5 | 4.0 | — | AG | opus | 2 | J2 |
| 4.6 | 4.3, 4.4, 4.5 | GA36, R36S | AG+PR | opus | 4 | J2 |
| 4.7 | 4.2–4.6, 3.2, 3.3 | CPU, GA36, R36S | PR | — | 5 | J2 |
| 5.1 | 3.1, 4.2 | GA36 | AG+PR | opus | 3 | J2 |
| 5.2 | 4.4, 4.5, 4.6 | GA36, R36S, USUARIO | AG+PR | opus | 6 | J3 |
| 5.3 | 5.1, 6.2 | GA36 | AG+PR | sonnet | 5 | J3 |
| 5.4 | 5.1, 5.2, 5.3 | — | AG | sonnet | 6 | |
| 6.1 | 4.1 | — | AG | opus | 2 | |
| 6.2 | 6.1, 4.4 | CPU (leve) | AG+PR | opus | 4 | |
| 6.3 | 2.3 | CPU (prova) | AG+PR | sonnet | 1 | |
| 6.4 | — | CPU (prova) | AG+PR | sonnet | 0 | |
| 6.5 | 4.4 | CPU (leve) | AG+PR | sonnet | 4 | |
| 6.6 | 2.1, 2.2, 6.3 | CPU | AG+PR | sonnet | 2 | |
| 7.1 | — | — | AG | opus | 0 | |
| 7.2 | 7.1 | CPU | AG+PR | opus | 1 | |
| 7.3 | 7.2, 6.1, 4.4 | CPU, R36S | AG+PR | opus | 4 | J3 |
| 7.4 | 7.2, 6.4 | CPU | PR | — | 2 | |
| 7.5 | 7.2 | — | AG | sonnet | 2 | |
| 8.1 | 4.7 | CPU, GA36, R36S | AG+PR | sonnet | 6 | J3 |
| 8.2 | 8.1, 6.1 | GA36, R36S | AG+PR | sonnet | 6 | J3 |
| 9.1 | — | CPU, ARCH:armv7 | AG+PR | opus | 1 | |
| 9.2 | 9.1 | CPU, ARCH:armv7, ARCH:aarch64, GA36, R36S | AG+PR | opus | 2 | J3 |
| 9.3 | — | CPU, ARCH:armv7, GA36 | AG+PR | opus | 1 | J3 |
| 9.4 | 9.3, 6.1 | CPU, ARCH:armv7, ARCH:aarch64, GA36, R36S | AG+PR | opus | 4 | J3 |
| 10.1 | — | GA36, R36S | AG+PR | opus | 0 | J2 |
| 10.2 | 10.1 | — | AG | sonnet | 7 | |
| 11.1 | todos | CPU, GA36, R36S, USUARIO | PR | — | 7 | J4 |
| 11.2 | todos | CPU, GA36, R36S, USUARIO | PR | — | 7 | J4 |

**Modelos aprovados pelo usuário em 2026-11-16** (com a troca da 10.1 para `opus`). Antes de
cada onda, os modelos dela são mostrados de novo para aprovação ou troca.

**Trilhas e caminho crítico:**

```
 A  PC        1.1 --> 2.1 --+--> 2.4          2.2, 2.3 --+--> 6.3 --> 6.6
                            |                            |
 B  kernel    7.1 --> 7.2 --+--> 7.4, 7.5     6.4 -------+
                            \--------------------------------> 7.3 (com 6.1, 4.4)
 C  aparelho  3.1 --+--> 3.2, 3.5 --> 3.6                      3.4 (cartao unico)
                    \--> 3.3 ---------\
 D  slots     4.0 --+--> 4.5 ----------+--> 4.6 --> 4.7 --> 8.1 --> 8.2
                    \--> 4.3 <---------/     ^
              4.1 --> 4.2 --> 4.4 -----------+--> 5.2 ; 6.2 --> 5.3 ; 6.5
                       \--> 5.1 ;  4.1 --> 6.1 --> 6.2, 7.3, 9.4
 E  compilar  9.1 --> 9.2          9.3 --> 9.4
 F  boot      10.1 --> 10.2

 caminho critico: 4.1 --> 4.2 --> 4.4 --> 4.6 --> 4.7 --> 8.1 --> 8.2 --> 11.x
                  (e 3.1 --> 3.3 --> 4.3 --> 4.6, em paralelo)
```

**Ondas** (nós de uma onda sem recurso em comum rodam em paralelo; os que disputam `CPU` ou
`ARCH` entram numa fila única, marcados com `*`):

```
 onda 0  1.1  2.2  2.3  3.1  4.0  6.4  7.1  10.1                (so codigo: 8 nos AG)
 onda 1  1.2* (logo apos o merge da 1.1)  2.1  3.2  3.3  3.5  4.1*  6.3  7.2*  9.1*  9.3*
 onda 2  2.4  3.6  4.2*  4.3  4.5  6.1  6.6*  7.4*  7.5  9.2*
 onda 3  4.4*  5.1
 onda 4  4.6  6.2*  6.5*  7.3*  9.4*
 onda 5  4.7*  5.3
 onda 6  5.2  5.4  8.1*  8.2
 onda 7  3.4  10.2  11.1*  11.2*
```

**Janelas de aparelho** (o usuário liga os consoles e faz as ações físicas uma vez por janela):

| Janela | Provas | Quando | O que o usuário faz |
|---|---|---|---|
| J1 | 1.2, 3.1, 3.2, 3.3, 3.5 | fim da onda 1 | liga o GA36 e depois o R36S no cabo, passando o cartão de um ao outro, confere as telas |
| J2 | 4.3, 4.5, 4.6, 4.7, 5.1, 10.1 | fim da onda 5 | push de cartão antigo e novo nos dois, olha o boot |
| J3 | 5.2, 5.3, 7.3, 8.1, 8.2, 9.2, 9.3, 9.4 | fim da onda 6 | abre um jogo por core nos dois, troca de core com jogo aberto |
| J4 | 3.4, 11.1, 11.2 | onda 7 | passa o cartão de um console ao outro entre as provas, corte de energia no meio de um push |

## 1. Proteção de calor e medição de partida (D15, D14)

- [x] 1.1 Módulo de proteção de calor: acha o hwmon do processador pelo nome (`k10temp` Tctl, `zenpower`, `coretemp` Package) e o do NVMe, nunca entradas auxiliares da placa-mãe; `R36OS_TEMP_SENSOR` e `R36OS_TEMP_MAX` (padrão 85 °C); amostra a cada 2 s; `podman pause` acima do limite e `unpause` 10 °C abaixo; aborta acima de 92 °C pausado por 60 s; diz no começo qual sensor e qual leitura usa. Verificação: testes de unidade com uma árvore `hwmon` falsa (inclusive um `nct6798` com `AUXTIN` a 97 °C, que tem de ser ignorado) e um relógio falso; um build real mostra o sensor `k10temp` e a leitura.
- [x] 1.2 Medir antes de qualquer outra mudança, já com o módulo 1.1 só registrando (sem pausar): build completo com cache frio, repetido sem mudança, depois de um patch de driver, depois de mudar um script do `rootfs/overlay`, depois de uma linha do `lume-ui`; para cada um o tempo total e a temperatura máxima da CPU e do NVMe; o `push` do caso do launcher (descompactar, enviar, reiniciar) e o `boot OK completed` no GA36 e no R36S. Verificação: coluna "Antes" da tabela "Medições" do design.

## 2. PC gentil (D8, D15)

- [x] 2.1 Ligar a pausa da proteção de calor em todo container do build e do `pkg`, com a temperatura máxima e o tempo pausado no resumo; documentar no `docs/BUILD.md` os limites, as variáveis e o ajuste manual opcional (boost ou EPP, com root) para quem quiser o PC mais frio. Verificação: teste de unidade do resumo; um build real com `R36OS_TEMP_MAX` baixo de propósito pausa e retoma, com as linhas na saída.
- [x] 2.2 `container.py`: o `podman` roda sob `nice -n 19 ionice -c 3`; `--jobs`/`R36OS_JOBS` em `build`, `pkg` e `push`, padrão metade dos núcleos, levado ao `make -j`, ao `JOBS` do `abuild`, ao `-processors` do `mksquashfs` e às threads do zstd; o build diz tarefas e prioridade no começo. Verificação: testes de unidade dos argumentos; durante um build, `ps -o ni,cmd` mostra `19` nos compiladores.
- [x] 2.3 Tempo por etapa no fim do build, com `skipped` e também em erro. Verificação: teste de unidade do resumo e a saída de um build real.
- [ ] 2.4 Documentar `--jobs`/`R36OS_JOBS` e o resumo no `README.md` e no `docs/BUILD.md` (novo). Verificação: o comando documentado roda como escrito.

## 3. Teste no aparelho como ferramenta (D12)

- [x] 3.1 `r36os dev wait | sh | shot | keys | log`, com as opções de ssh do cabo, botões por `input_event` (pad virtual e combinações no pad do kernel) e os eventos lidos de `/proc/bus/input/devices` em cada console. Verificação: testes de unidade da montagem dos comandos e dos eventos; no GA36 e no R36S, `shot` traz a tela e `keys` move o foco do launcher.
- [ ] 3.2 Modo de aparelho do `selftest` (sem os casos só da VM) e `r36os dev check`, que o roda e devolve passou ou falhou com a lista. Verificação: teste do shell do `selftest`; `dev check` verde nos dois consoles com o build atual e vermelho com um serviço parado de propósito.
- [ ] 3.3 O `push` espera o console voltar e confere `boot OK completed` e o `VERSION` novo no log, com tempos de envio e de boot; `--no-wait` pula. Verificação: testes de `tests/unit/test_push.py` (volta certo, não volta, versão errada); um `push` real nos dois consoles termina com `ok`.
- [ ] 3.4 Console identificado pelo cabo, com cartão único (D18): o endereço continua `10.55.0.1` nos dois; `push`, `dev` e `flash` dizem qual console respondeu (GA36 ou R36S, pelo que o console informa) e `--console ga36|r36s` confere e recusa quando o ligado é o outro. Verificação: testes de unidade da identificação e da recusa; com o mesmo cartão, `r36os dev check --console r36s` recusa no GA36 e passa no R36S.
- [ ] 3.5 `r36os dev shot --compare <tela>` e `--update`, com as referências em `tests/device/shots/<console>/` e as sequências de botões de cada tela, num cartão de demonstração com nomes inventados (D19). Verificação: teste de unidade da comparação (igual, diferente com a imagem da diferença em `./cache/`); referências das telas principais do launcher gravadas nos dois consoles.
- [ ] 3.6 Documentar `r36os dev`, a conferência do `push`, os endereços e as capturas no `docs/BUILD.md`, no `docs/LOGS.md` e nos guias de bring-up. Verificação: os comandos documentados rodam como escritos.

## 4. Esqueleto ponta a ponta: um fragmento noarch em slot (D1, D2, D9, D10)

- [x] 4.0 Congelar as interfaces compartilhadas antes dos consumidores: formato do `SLOTS` (nome, arquivo, sha256, versões dos fragmentos, sha dos slots de baixo), da `boot-files.sha256` com os objetos, do `.lume-content` e do `out/repo/<arch>/hashes.json`, num módulo Python com leitura e escrita, e o leitor do `SLOTS` em shell para o initramfs. Verificação: testes de unidade de ida e volta (Python) e de leitura (shell, busybox), com os casos de manifesto ausente, truncado e citando arquivo que falta; formato documentado no D9 e no D10.
- [ ] 4.1 Provar no x86 um pacote noarch (`abuild` no `builder` x86_64) publicado igual em `out/repo/armv7/` e `out/repo/aarch64/`, aceito pelo `apk` de cada arquitetura sem `--allow-untrusted`, e a checagem de ELF. Verificação: `apk add --root` num container de cada arquitetura instala o pacote de teste; teste de unidade da checagem de ELF.
- [ ] 4.2 Primeiro fragmento: `aports/lume-core` noarch com os arquivos do `rootfs/overlay/` que o D2 lista para ele (os outros continuam no overlay por enquanto); `rootfs/packages.txt` o inclui. Verificação: manifesto do rootfs com os mesmos arquivos e SHA256 de antes nos dois consoles.
- [ ] 4.3 Arquivo do build por conteúdo (`out/images/objects/`, `boot-files.sha256` por build) e `push` lendo dele sem descompactar; `VERSION` fora da comparação e enviado só com outro arquivo; `flash` monta a imagem dos objetos quando não há `.img.zst`; compressão da imagem com threads. Verificação: testes de `test_push.py` (nada mudou, um arquivo mudou, build antigo arquivado); um `push` real sem a linha `unpacking`.
- [ ] 4.4 Slots e manifesto no build: `rootfs/slots.toml`, separação do rootfs por dono no banco do `apk` (sem dono e banco do `apk` no `lume`), slots `base`, `runtime`, `lume` e `modules` com nome pelo conteúdo, `SLOTS` com sha256, versões e os sha dos slots de baixo, limites somados. Verificação: teste de unidade de que todo arquivo está em exatamente um slot; dois builds sem mudança dão os mesmos slots.
- [ ] 4.5 Initramfs: lê `SLOTS` (ou `SLOTS.old`), monta `lume`, `runtime` e `base` como `lowerdir` e o `modules`; sem `SLOTS`, o `SYSTEM` antigo; registra cada slot e versão no log de boot. Verificação: `tests/initramfs/test_storage.sh` (manifesto bom, ausente, citando arquivo que falta, cartão antigo); spec `system-image`; `docs/LOGS.md`.
- [ ] 4.6 `push` dos slots: copia os slots novos, confere, troca `SLOTS.new` → `SLOTS` com o antigo em `SLOTS.old`, apaga os slots que nenhum dos dois cita; migra o cartão antigo (o `SYSTEM` some no push seguinte); `flash --update` grava o layout novo; `check_room` conta o conjunto anterior. Verificação: testes de `test_push.py`; no GA36 e no R36S, push de cartão antigo, push seguinte e `dev check` verde.
- [ ] 4.7 Prova ponta a ponta: mudar um script de `lume-core`, `r36os build lume-core`, `push`, e o console volta com o slot `lume` novo e a versão nova do `lume-core` no log, nos dois consoles. Verificação: saída do `push` com `ok` e tempos anotados no design.

## 5. Push em RAM e cores sem reinício (D11)

- [ ] 5.1 `r36os push --hot <fragmento>`: extrai os arquivos na camada em RAM, reinicia os serviços do fragmento (`init.d` dele ou `_lume_restart`), linha `push hot` no `events.log`; recusa kernel, módulos e base. Verificação: testes de `test_push.py`; no GA36, `--hot lume-core` com um script mudado e o serviço reiniciado; depois do reboot, o arquivo do cartão volta.
- [ ] 5.2 Slots `core-<nome>` fora do overlay: serviço `lume-cores` depois do `frontend` monta em `/run/lume/cores/<nome>/`; o runner acha o core lá e espera se ainda não montou; o push troca um core sem reinício (remonta, ou no fim do jogo se em uso). Verificação: teste do runner com o core ausente e depois presente; no aparelho, jogo aberto logo após o boot, e troca de um core com e sem jogo aberto; `boot OK completed` sem piora.
- [ ] 5.3 `r36os dev watch <fragmento>` (D19): inotify nos arquivos de entrada, 1 s de calma, build pontual e `push --hot`, uma linha por ciclo; recusa fragmentos sem `--hot`. Verificação: teste de unidade do agrupamento das mudanças; no GA36, salvar um script do `lume-core` e ver o serviço reiniciado em segundos.
- [ ] 5.4 Documentar `--hot`, `dev watch`, a política de reinício e os cores no `docs/BUILD.md` e no `docs/LOGS.md`. Verificação: comandos documentados rodam como escritos.

## 6. Esteira: versão pelo conteúdo e etapas puladas (D3, D4, D6)

- [ ] 6.1 Hash de entradas e de conteúdo por fragmento (`.PKGINFO`, `.lume-content`, `out/repo/<arch>/hashes.json`): entradas iguais → não compila; conteúdo igual → não publica; diferente → `pkgrel` seguinte, sem editar o `APKBUILD`; ao publicar, as versões antigas de cada pacote saem de `out/repo/<arch>/` (fica a mais nova e a anterior, para o `push` de um build arquivado), com o espaço liberado numa linha e o índice refeito. Verificação: testes de unidade (cada caso, inclusive a limpeza), e mudar um arquivo do `lume-launcher` gera versão maior enquanto um build sem mudança não compila nada; depois do primeiro build, `out/repo/armv7/` tem no máximo duas versões de cada pacote.
- [ ] 6.2 `r36os build <fragmento>... [--console]`: compila só os pedidos e os que dependem deles, remonta só os slots afetados e grava um conjunto novo sem imagem. Verificação: teste de unidade do plano (fragmento → slots); `r36os build lume-core` real termina em segundos.
- [x] 6.3 `<saída>.inputs` e etapa pulada para DTBs (só os patches que tocam device tree ou bindings), initramfs, rootfs e slots, com uma linha por etapa; `--clean` força tudo. Verificação: teste que muda cada entrada e confere que a etapa roda; build repetido sem mudança não chama compilador nem `mksquashfs`.
- [x] 6.4 Data fixa do kernel (`KBUILD_BUILD_TIMESTAMP` da versão do kernel). Verificação: commitar um patch que só toca o armv7 não muda o `Image` do aarch64.
- [ ] 6.5 Compressão rápida no build pontual (zstd 3) e máxima no `build console` (zstd 19), com o nível no hash do slot e o 19 de reserva quando o slot rápido estoura o limite (D16). Verificação: teste de unidade (o slot rápido não é reaproveitado no build completo); tempo de remontar o slot `lume` nos dois níveis anotado no design.
- [ ] 6.6 As duas arquiteturas em paralelo no `build console`, cada uma com metade das tarefas, prefixo na saída e resumo separado; o que é comum feito uma vez antes (D17). Verificação: teste de unidade da divisão de tarefas; um `build console` real com `ps` mostrando as duas esteiras e o total de tarefas dentro do limite, sob a proteção de calor.

## 7. Kernel incremental e fragmentos do kernel (D5, D2, D3)

- [x] 7.1 `kernel.source_tree()`: árvore `.cache/src/linux-<versão>/` com git, série nova montada num índice temporário e aplicada com `read-tree -m -u`, só os arquivos de conteúdo diferente com data nova; `GIT_CEILING_DIRECTORIES` mantido. Verificação: teste de unidade com uma árvore pequena (mudar um patch muda o mtime só do arquivo dele).
- [x] 7.2 `build_kernel()` por arquitetura em `.cache/kbuild/<arch>/`, com as verificações do fragmento e dos warnings. Verificação: patch num driver do GA36 recompila esse arquivo e o link (log do `make`); o kernel aarch64 sai igual byte a byte.
- [ ] 7.3 Pacotes `lume-kernel`, `lume-modules` e `lume-dtbs` por arquitetura, com versão pelo conteúdo; a `BOOT` e o slot `modules` saem deles. Verificação: testes de unidade; um patch de driver do GA36 muda só os pacotes do armv7, e o `push` ao R36S não envia nada.
- [ ] 7.4 Equivalência: o `Image`/`zImage` incremental é igual ao de um build limpo com as mesmas entradas. Verificação: `r36os build --clean` contra incremental, mesmo SHA256.
- [ ] 7.5 Limpeza das gerações antigas com o espaço liberado numa linha; `repo-clean` e `docs/BUILD.md` com o layout novo. Verificação: depois do primeiro build, `.cache/` tem uma árvore e uma pasta de build por arquitetura; spec `build-cache`.

## 8. Fragmentar o resto (D2)

- [ ] 8.1 Dividir o restante do `rootfs/overlay/` nos aports noarch do D2 (`lume-usb`, `lume-net`, `lume-audio`, `lume-saves`, `lume-diag`, `lume-power`, `lume-games`, `lume-launcher-data`, `lume-retroarch-cfg`, `lume-shaders`), com `depends` e serviços de reinício; o `rootfs/overlay/` fica só com o que for da imagem. Verificação: manifesto do rootfs com os mesmos arquivos e SHA256 de antes; `dev check` verde nos dois consoles.
- [ ] 8.2 Versões dos fragmentos `lume-*`/`r36os-*` no `hw/boot-<n>.txt` (pelo `hwinfo`) e na conferência do `push`. Verificação: `docs/LOGS.md` com o campo; o `push` confere a versão do fragmento enviado.

## 9. Compilação sem emulação (D7)

- [x] 9.1 `lume-launcher`, passo 1: `target/` do cargo em `.cache/cargo/<arch>`, sem vazar entre arquiteturas. Verificação: uma linha do `lume-ui` mudada → build armv7 medido contra os 8 min de antes.
- [ ] 9.2 `lume-launcher`, passo 2: cross no x86 com a sysroot da arquitetura (`apk --root --arch --no-scripts`) e o Rust 1.96; o `abuild` só empacota. Verificação: build armv7 e aarch64 perto de 1 minuto; o launcher abre nos dois consoles e o `cargo test` passa.
- [ ] 9.3 Prova do P-36 com um core pequeno (`libretro-snes9x2005-plus`): `distcc` para compiladores x86 com o gcc do Alpine 3.24 (caminho a) e, se não servir, cross completo do `abuild` (caminho b). Verificação: mesmo conteúdo do pacote (ou diferença explicada) e o core roda um jogo no GA36; decisão anotada no D7.
- [ ] 9.4 Aplicar o caminho escolhido ao RetroArch e aos outros cores. Verificação: cada core abre um jogo do seu sistema nos dois consoles; tempo de recompilação de todos antes e depois.

## 10. Boot mais curto para o ciclo de teste (D20)

- [ ] 10.1 `rc_parallel="YES"` e os serviços que o jogo não usa (Bluetooth, NetworkManager, playlists do RetroArch, `lume-index`, o retrato de hardware do `hwinfo`) depois do `frontend`; a rede USB e o resumo de hardware da tela continuam antes. Verificação: `selftest` em modo aparelho verde; no GA36 e no R36S, o log do boot mostra a ordem nova e o `boot OK completed` antes e depois anotado no design; jogo aberto logo após o boot funciona; spec `boot-runtime`.
- [ ] 10.2 Atualizar o P-58 em `docs/PENDENCIAS.md` com o que entrou aqui e o tempo novo. Verificação: o item cita esta change e os números.

## 11. Verificação integrada

- [ ] 11.1 Repetir as medições da 1.2 e preencher a coluna "Depois", conferindo as metas do design (driver < 1 min por arquitetura, launcher ~1 min, script e build sem mudança em segundos), a temperatura máxima da CPU e do NVMe e o tempo pausado pela proteção de calor. Verificação: tabela preenchida no design.
- [ ] 11.2 Nos dois consoles, um de cada vez com o mesmo cartão: `push` depois de um patch de driver, de uma mudança no launcher, de um core e de um script (`--hot` e normal), cada um enviando só o que mudou e terminando com `ok`; depois de um push feito por um console, o cartão passado ao outro inicia com o conjunto novo dele sem outro push; `r36os dev check` verde nos dois; corte de energia simulado no meio de um push (tirar o cabo e desligar antes da troca do manifesto) volta ao conjunto antigo. Verificação: saídas dos comandos e log de boot.

## Workflow follow-up

- Fazer depois do archive da `boot-dtb-select` (feito), no mesmo bloco da change do governor e dos cenários do frontend (decisão do usuário, 2026-11-16).
- `docs/PENDENCIAS.md`: anotar no P-36 e no P-61 o que esta change resolveu; no P-14 (tema 1) a instalação com o `apk` dentro do console, que ficou fora; pendência nova no tema 11 para voltar a construir e testar a imagem `vm` (saiu do ciclo nesta change, D13); pendência nova no tema 6 para avaliar o userland armv7 nos dois consoles (desempenho por core).
