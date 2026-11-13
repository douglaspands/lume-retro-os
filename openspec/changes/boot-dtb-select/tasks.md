# Tasks

## 1. Provas no aparelho antes do código

- [ ] 1.1 R36S: um `boot.ini` de teste que usa `if test -e mmc 1:1 <arquivo>` para escolher entre dois caminhos e faz `fatwrite` de um arquivo marcador na `BOOT`. Verificação: o marcador aparece na `BOOT` pelo PC e o log de boot mostra o caminho escolhido; resultado anotado no Context do `design.md` (se não houver `if`/`test`, anotar que a otimização no `boot.ini` fica descartada).
- [ ] 1.2 R36S: descobrir quais teclas ficam nos pinos C0, C2 e C5 que o U-Boot de fábrica lê e o que ele faz com cada uma segurada ao ligar (Vol-, Vol+, Start, Select, A). Verificação: tabela tecla → comportamento do U-Boot anotada no D7 do `design.md` e em `docs/BRINGUP-R36S.md`.
- [ ] 1.3 GA36: ligar segurando cada tecla candidata (Vol-, Vol+, Start, Select, A) e anotar qual cai na faixa `recovery` (0x10–0x13) ou `fastboot` (0x2–0x8) do LRADC; ler da tabela `softw411` se existe a partição `recovery` e onde fica. Verificação: tabela tecla → comportamento anotada no D7 e em `docs/BRINGUP-GA36.md`.
- [ ] 1.4 GA36: um env de teste (CRC recalculado) com `bootcmd` que faz `fatload mmc 0:1` de um BMP e de um arquivo de texto da `BOOT`, `sunxi_bmp_display` e `env import -t`, antes do boot normal. Verificação: o BMP da `BOOT` aparece na tela e o boot segue até o menu; endereço, dispositivo e resultado de cada comando anotados no D9 (se falhar, ajustar o spec `system-image` como diz o D9).
- [ ] 1.5 kexec nos dois consoles: build de bring-up com `CONFIG_KEXEC`, `kexec-tools` e um serviço temporário que, com a flag `ROMS/system/etc/kexectest`, faz um kexec do mesmo kernel com o mesmo DTB uma vez e registra no log. Verificação: nos dois aparelhos o segundo início chega ao frontend com tela, som, controle e cartão funcionando (log `trace` do boot); falha no GA36 anotada nos Riscos com o caminho alternativo escolhido.
- [ ] 1.6 Watchdog através do kexec (D11), nos dois consoles: armar `/dev/watchdog` (60 s), fechar sem `V`, fazer o kexec e não abrir no segundo início. Verificação: o aparelho reinicia sozinho em cerca de 60 s e o kernel novo não alimenta o watchdog (sem `CONFIG_WATCHDOG_OPEN_TIMEOUT` ele alimentaria); o driver e o tempo máximo de cada SoC anotados no D11, ou a falha nos Riscos.
- [ ] 1.7 Número de série do SoC (D6): ler `/sys/devices/soc0/serial_number` nos dois consoles, em dois boots. Verificação: valor presente e igual nos dois boots de cada aparelho, anotado no D6 e no bring-up de cada console; sem ele, anotar que o estado fica por SoC.

## 2. Layout da BOOT e logo único

- [x] 2.1 `src/r36os/image.py`: pastas `dtbs/a33/` e `dtbs/rk3326/` com os DTBs do build, `ga36/zImage` (sem DTB anexado), fim de `ga36/dtbs/` e de `r36s/<dtb>`; `board/r36s/boot.ini` carrega `dtbs/rk3326/rk3326-r36s-v5.dtb`. Verificação: `tests/unit/test_console_boot.py` e `tests/integration/test_image_console.py` atualizados para o layout novo e passando.
- [ ] 2.2 `src/r36os/vendor.py`: ler o env do GA36 (tamanho e cópia redundante pela tabela `softw411`), reescrever só o `bootcmd` conforme o D9 com o CRC32 recalculado, e trocar o `bootlogo.bmp` da FAT interna pelo `logo.bmp` de fábrica do R36S. Verificação: testes unitários do env (CRC confere, demais variáveis iguais) e do `bootlogo.bmp` (idêntico ao `BOOT/logo.bmp`); teste de imagem com o cenário "Bootloader do GA36" do spec.
- [ ] 2.3 Documentar o layout novo e o logo único em `docs/BRINGUP-GA36.md` e `docs/BRINGUP-R36S.md` (tabela da `BOOT`, como trocar o logo pelo PC). Verificação: as tabelas batem com a listagem da `BOOT` do teste de imagem.

## 3. Kernel e device trees

- [x] 3.1 `CONFIG_KEXEC` nos fragmentos `board/ga36/kernel.config` e `board/r36s/kernel.config`, e conferir que os drivers das teclas de seleção são embutidos. Verificação: os testes de config de kernel dos dois consoles cobrem as opções e o build falha se elas sumirem.
- [x] 3.2 Nó `lume-select` (D3) nos DTS dos dois painéis do GA36 e do R36S V5, com `name`, `priority` e `default` no padrão de cada SoC (sem regras enquanto não houver uma assinatura medida). Verificação: teste unitário que compila os DTS e confere um único `default` por SoC e nomes únicos.
- [ ] 3.3 `/etc/soc` e `board/<b>/bootsel-keys` gravados no initramfs pelo build, com as teclas das provas 1.2 e 1.3. Verificação: teste unitário do conteúdo do initramfs dos dois consoles.
- [ ] 3.4 Watchdog (D11): driver do watchdog de cada SoC embutido e `CONFIG_WATCHDOG_OPEN_TIMEOUT` nos dois fragmentos, com o valor da prova 1.6. Verificação: os testes de config de kernel dos dois consoles cobrem as opções.

## 4. Utilitário `lume-bootsel`

- [x] 4.1 Pacote local em `aports/` (C estático, `libfdt`) com `--root` e `--dry-run` (D5), e `kexec-tools` copiado para o initramfs. Verificação: o pacote compila para armv7 e aarch64 e o binário roda `--dry-run` numa árvore vazia registrando `no device tree`.
- [x] 4.2 Candidatos e regras: leitura da pasta do SoC, filtro por `compatible`, avaliação de `adc`, `gpio` e `i2c-present` só de leitura (D4), escolha por prioridade, padrão sem regra. Verificação: pytest com árvores falsas cobre regra que bate, sonda que falha, DTB de outro SoC e prioridade.
- [x] 4.3 Precedência e estado (D6): `force` válido e inválido, `manual`, `good`, `pending`, `bad`, sem `ROMS`. Verificação: pytest cobre cada cenário de `dtb-selection` (precedência, nome inválido, volta ao último que funcionou, escolha separada por SoC).
- [x] 4.4 Preparação do DTB e troca (D2): cópia do `/memory` em uso, `/chosen/lume,dtb-selected`, chamada do `kexec`, e saída sem escolha quando a propriedade já existe. Verificação: pytest confere o DTB preparado (com `fdtget`) e que um segundo início com a propriedade não escolhe de novo.
- [x] 4.5 Menu (D7): leitura da tecla por `EVIOCGKEY` com espera de no máximo 1 s, lista no `tty1` com `(auto)`, `(ok)` e `(forced)`, navegação e confirmação. Verificação: pytest com eventos simulados por `--root`; conferido no aparelho na tarefa 6.3.
- [x] 4.6 Registro (spec "Registro da escolha"): linhas em inglês no log de boot com leituras, candidatos, escolha e motivo. Verificação: pytest confere as linhas; `docs/LOGS.md` documenta o formato.
- [ ] 4.7 Estado por aparelho (D6): arquivo `dtb-<soc>-<serial>.conf` com o serial de `/sys/devices/soc0/serial_number`; sem serial, `dtb-<soc>.conf` e o aviso no log; o `force` de um DTB em `bad` naquele aparelho é ignorado. Verificação: pytest com dois seriais no mesmo cartão (escolhas independentes), sem serial e com o `force` descartado.
- [ ] 4.8 Confirmação na tela (D10): no segundo início com um DTB `pending`, a mensagem no `tty1` com contagem de 15 s; A grava `good` e segue; sem resposta, `bad` e kexec de volta ao `good` (ou ao padrão) com o motivo `reverted`; o terceiro início segue sem perguntar; sem tecla de confirmar, não pergunta. Verificação: pytest com eventos simulados (confirma, não responde, sem dispositivo) e o DTB da volta conferido com `fdtget`.
- [ ] 4.9 Watchdog (D11): antes do kexec para um DTB `pending`, abrir, ajustar 60 s e fechar sem `V`; no segundo início, reabrir, alimentar durante a pergunta e parar com `V` ao confirmar ou antes da volta. Verificação: pytest com um `/dev/watchdog` falso (arquivo comum) que registra as escritas.

## 5. Integração no boot

- [x] 5.1 `initramfs/init`: chamar o `lume-bootsel` depois de montar a `BOOT` e a `ROMS`, desmontar antes do kexec e seguir quando não troca. Verificação: teste da VM (`test-vm`) passa sem mudança de tempo de boot e o log tem `no device tree`.
- [x] 5.2 `logd`: quando o frontend sobe, gravar `good` e apagar `pending` no arquivo do SoC; `hwinfo` ganha o campo do DTB em uso. Verificação: testes unitários do `logd` e do `hwinfo`; `docs/LOGS.md` atualizado.
- [ ] 5.3 `logd` com o estado por aparelho (D6, D10): usar o arquivo `dtb-<soc>-<serial>.conf` (ou `dtb-<soc>.conf` sem serial) e confirmar no frontend só o `pending` que a tela não pôde confirmar; `hwinfo` ganha o serial do SoC no campo do DTB; eventos `reverted` e da confirmação na tela. Verificação: suíte `tests/logs/test_logs.sh` cobre os dois arquivos e os eventos; `docs/LOGS.md` atualizado.
- [ ] 5.4 `README.md`: seção para o usuário sobre a escolha do device tree — o que é o `BOOT/dtbs/force` e quando usá-lo (tela preta), a lista pela tecla, a confirmação na tela no primeiro boot com um DTB novo (A em 15 s, ou volta sozinho), a escolha guardada por aparelho e onde ver no log. Verificação: o texto bate com o comportamento das tarefas 4.7 a 4.9 e com os bring-ups.

## 6. Verificação no aparelho

- [ ] 6.1 Cartão gravado com `flash console --full`: GA36 com painel 1 e R36S V5 sobem com o DTB padrão, sem kexec, e os dois mostram o logo de fábrica do R36S. Verificação: logs de boot dos dois com motivo `default` e anotação no bring-up de cada console.
- [ ] 6.2 Pelo PC: `ga36-panel2` em `BOOT/dtbs/force` faz o GA36 subir com o DTB do painel 2 (por kexec) e pedir a confirmação na tela; apertar A mantém, e apagar o arquivo volta ao padrão; trocar o `BOOT/logo.bmp` muda o logo dos dois. Verificação: logs com motivo `forced` e a confirmação, e anotação no `docs/BRINGUP-GA36.md`.
- [ ] 6.3 Tecla: segurando a tecla de seleção, a lista aparece nos dois consoles, a escolha vale no boot seguinte e a opção do automático apaga a escolha. Verificação: logs com motivo `manual` e anotação no bring-up de cada console.
- [ ] 6.4 Volta sozinho: (a) tela preta: forçar um candidato de teste com o painel desligado e não apertar nada; em 15 s o kernel volta ao padrão sem desligar; (b) travamento: um candidato de teste que trava o kernel antes da pergunta; o watchdog reinicia e o boot seguinte faz o fallback. Verificação: logs com `reverted` em (a) e `fallback` em (b), e o DTB descartado em `bad`.
- [ ] 6.5 Remover o serviço e a flag temporários da prova 1.5 e os candidatos de teste da 6.4. Verificação: `rg kexectest` não acha nada fora do `tasks.md`.
- [ ] 6.6 Cartão em outro aparelho do mesmo SoC (se houver um segundo GA36 ou R36S): a escolha confirmada no primeiro não vale no segundo, e volta a valer quando o cartão volta ao primeiro. Verificação: dois arquivos `dtb-<soc>-<serial>.conf` na `ROMS` e os logs dos dois aparelhos.

## Workflow follow-up

- Ao arquivar, mover o P-33 (parte da escolha do DTB) e anotar o P-43 em `docs/PENDENCIAS.md` com o resultado desta change.
- Commits pequenos (Conventional Commits) só com o OK do usuário; `main` via PR squash depois do archive.
