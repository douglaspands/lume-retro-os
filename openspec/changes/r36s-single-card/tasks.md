# Tasks

## 1. Investigações no aparelho antes do código

- [ ] 1.1 Descobrir como o U-Boot de fábrica do R36S usa o `boot.ini` (design D5): no cartão do ArkOS restaurado do backup, trocar o `boot.ini` por um com um parâmetro marcador no `bootargs` e conferir em `/proc/cmdline` do ArkOS; depois testar um `boot.ini` que carrega um DTB com nome nosso (cópia do `rg351mp-kernel.dtb`). Registrar no design qual caminho vale (o `boot.ini` é lido, ou o caminho B com os nomes que o U-Boot procura). Verificação: resultado dos dois testes anotado no D5.
- [x] 1.2 Conferir que o host roda binários aarch64 sob `qemu-user` (binfmt registrado) e que o container de cross-compile tem `gcc-aarch64-linux-gnu`; se faltar algo no host, pedir confirmação antes de instalar. Verificação: `podman run --platform linux/arm64` de um Alpine responde `uname -m` = `aarch64`.

## 2. Área de boot combinada (sem aparelho)

- [x] 2.1 Módulo da cadeia de fábrica do R36S (D4): lê `R36OS_R36S_FACTORY` (imagem crua ou `.img.zst`), extrai `[64, 406)` e `[16384, 32768)`, confere o SHA256 de cada região contra o cartão medido e guarda no cache; mensagens claras para variável ausente e SHA256 diferente. Verificação: testes unitários com dados sintéticos (ok, ausente, SHA diferente, `.zst`).
- [x] 2.2 Boot0 encolhido (D3): confere `eGON.BT0`, exige `0xFF` de 24 KiB a 32 KiB, grava o tamanho 24576 e recalcula a soma. Verificação: teste unitário que reproduz a soma de fábrica com o algoritmo e falha com boot0 maior que 24 KiB.
- [x] 2.3 Tabela declarativa das regiões e montagem da área de 128 MiB (D2): área do GA36 + boot0 encolhido + regiões do R36S, com a conferência de sobreposição (setor do R36S só em setor zerado do GA36 ou em 64-277). Verificação: testes unitários do layout (setores 16, 64, 16384, 24576, 38192 e 172032 nos lugares certos) e do erro que lista os setores em conflito.

## 3. Alvo `console` na CLI, no build e no flash

- [x] 3.1 `targets`/`cli`: alvos de imagem `console` e `vm`; `ga36` e `r36s` viram camadas internas; alvo desconhecido lista `console` e `vm`. Verificação: `tests/unit/test_targets.py` atualizado.
- [x] 3.2 `build console`: as duas camadas em sequência, um `VERSION` e um timestamp por build, `build.json` com as duas camadas (kernel, patches, `system_bytes`, bootloaders), arquivo em `out/images/console/<timestamp>/`; a ordem `--all` passa a ser `vm` → `test-vm` → `console`. Verificação: testes de `version`/`release` atualizados.
- [x] 3.3 `flash console`: assinatura `4c554d32` e `BOOT` em 262144 como constantes da imagem (sai o `board/r36s/disk-id`); `--update` aceita um cartão gravado com a imagem `ga36` antiga e recusa outros layouts com a mensagem de gravação completa. Verificação: `tests/unit/test_flash.py` com MBR sintético de cartão `ga36` (aceito) e de `vm` (recusado).
- [ ] 3.4 Atualizar o `README.md` (uso: `build console`, `flash console`, `R36OS_R36S_FACTORY`, migração de cartões do GA36 com `--update`). Verificação: os comandos documentados existem na ajuda da CLI (`r36os --help`).

## 4. Kernel e device tree do R36S

- [ ] 4.1 `kernel.KERNEL_TARGETS` com `r36s` (`arm64`, `aarch64-linux-gnu-`, `defconfig`, `Image`) e o fragmento `board/r36s/kernel.config` (D7: DSI/VOP, ST7703, panfrost, RK817, SARADC, io-channel-mux, adc-joystick, gpio-keys, pwm-backlight, embutidos, `INITRAMFS_SOURCE`, `CMDLINE_FORCE` com `root=PARTUUID=4c554d32-01 console=ttyS2,1500000 console=tty1`). Verificação: `tests/unit/test_r36s_kernel_config.py` cobre as opções e o kernel compila em cross.
- [ ] 4.2 Patch numerado da variante do painel no `panel-sitronix-st7703` (sequência do Apêndice C da change anterior, binding junto), sem warning no build. Verificação: o patch aplica na árvore fixada, `OWN_DRIVER_FILES` inclui o arquivo e o build não tem warning dele.
- [ ] 4.3 `board/r36s/dts/rk3326-r36s-v5.dts` com os valores do Apêndice A (painel, luz de fundo, `gpio-keys`, `adc-joystick` sobre `io-channel-mux`, RK817 com codec, carregador e `simple-battery`, LEDs, SD, `cpu-supply`), OPPs e térmica do `rk3326.dtsi` sem alteração; `DTS_VENDOR` com `("arm64", "rockchip")`. Verificação: o DTB compila e um teste unitário confere os GPIOs e os valores do Apêndice A no DTS.
- [ ] 4.4 Primeira subida no R36S (D7, risco do BL31): `boot.ini` conforme a tarefa 1.1, kernel do build com initramfs mínimo que acende o LED azul e mostra uma mensagem no `fbcon`. Verificação: no aparelho, o LED acende e as mensagens do kernel aparecem no painel; anotar o resultado no `docs/BRINGUP-R36S.md`.

## 5. Initramfs, BOOT e imagem `console`

- [ ] 5.1 Initramfs por camada com o nome do console embutido; o `init` monta `/boot/<console>/SYSTEM` (VM continua `/boot/SYSTEM`) e cai na recuperação com o console e o arquivo na mensagem se faltar. Verificação: `tests/initramfs/test_storage.sh` (ou suíte nova em busybox) cobre os dois consoles e o arquivo ausente.
- [ ] 5.2 Montagem da `BOOT` da `console` (D5): `VERSION`, `boot.ini`, `ga36/` (`SYSTEM`, `dtbs/`, `android-boot/`) e `r36s/` (`SYSTEM`, `Image`, DTB); limites de 448 MiB por `SYSTEM` e 64 MiB livres na `BOOT`, com falha clara se passar. Verificação: teste unitário dos limites e teste de integração que lista a `BOOT` da imagem gerada (sucessor do `test_image_ga36.py`).
- [ ] 5.3 Gerar `console.img` com a área de boot do grupo 2, a imagem de boot do painel 1 no setor 172032 e a `BOOT` em 262144. Verificação: teste de integração confere MBR (`4c554d32`, só a partição 1), o cabeçalho eGON de 24 KiB, o `idbloader` em 64, o `uboot.img` em 16384 e o `android-boot` em 172032.
- [ ] 5.4 Atualizar o `LEIA-ME.txt` gerado (cartão único: o mesmo cartão nos dois consoles; *save states* podem não passar entre eles, saves `.srm` passam). Verificação: `tests/unit/test_leiame.py` cobre o texto nos três idiomas.

## 6. Userland do R36S

- [ ] 6.1 Pacotes locais para aarch64 (`arch=` dos `aports/` usados pela imagem, `pcsx_rearmed` com o dynarec aarch64 e sem as flags do armv7); `ppsspp` segue desativado. Verificação: `r36os pkg` compila todos para aarch64 e `tests/integration/test_local_repo.py` acha os 11 cores.
- [ ] 6.2 `aports/r36os-padmerge` (C, `uinput`): junta `gpio-keys` e `adc-joystick` em "R36S Gamepad", serviço OpenRC antes do frontend, entra em `board/r36s/hw-packages.txt`. Verificação: teste na VM com dispositivos falsos por `uinput` mostra um único controle com os botões e os quatro eixos.
- [ ] 6.3 Autoconfiguração do RetroArch para "R36S Gamepad" e padrões do mixer do RK817 em `/usr/libexec/r36os/mixer`. Verificação: `tests/audio/test_mixer.sh` cobre o `r36s`; teste unitário confere o arquivo de autoconfiguração.
- [ ] 6.4 `retroarch-r36s.cfg` com as chaves fixas do R36S (`input_enable_hotkey`, `video_refresh_rate` calculado pelo timing, ~59,02 Hz, a medir) e um teste que falha se uma chave estiver fixada num console e não no outro. Verificação: `tests/unit/test_retroarch_cfg.py` com o teste novo.
- [ ] 6.5 Paridade de manifestos `ga36` × `r36s` (mesmos pacotes de userland, exceto a camada de hardware). Verificação: `tests/unit/test_manifest_parity.py` cobre o par.

## 7. Logs dos dois consoles

- [ ] 7.1 O log de boot e o `events.log` registram o console no início de cada boot; a numeração continua única na `ROMS`. Verificação: `tests/logs/test_logs.sh` com dois boots de consoles diferentes.
- [ ] 7.2 Atualizar `docs/LOGS.md` (os dois consoles na mesma `ROMS/logs/`, como saber de qual console é cada log). Verificação: `tests/unit/test_logs_doc.py` passa.

## 8. Documentação do R36S e pendências

- [ ] 8.1 `docs/BRINGUP-R36S.md`: cadeia de boot de fábrica, `boot.ini`, layout do cartão único, checagens de hardware e o que foi medido no aparelho. Verificação: o documento cita as tarefas 1.1 e 4.4 com os resultados.
- [ ] 8.2 `docs/PENDENCIAS.md`: P-21 e P-27 apontando para esta change; pendência nova para o U-Boot mainline do R36S; Agradecimentos do `README.md` com a origem da cadeia de fábrica do R36S. Verificação: os IDs novos são únicos e o arquivo segue o formato da tabela.

## 9. Verificação nos dois aparelhos

- [ ] 9.1 Gravar `console.img` num cartão e iniciar no GA36 e no R36S: os dois chegam ao menu do RetroArch, com o controle e o som funcionando. Verificação: logs de boot dos dois consoles na `ROMS/logs/`, sem `FAIL` no `events.log`.
- [ ] 9.2 Ida e volta: um save feito no R36S aparece no GA36 e vice-versa; uma opção do menu (idioma) passa entre os consoles e o `video_refresh_rate` em uso é o de cada painel. Verificação: anotar no `docs/BRINGUP-R36S.md`.
- [ ] 9.3 Nenhum bootloader grava na área do outro: SHA256 dos primeiros 128 MiB do cartão antes e depois de iniciar em cada console. Verificação: os hashes batem.
- [ ] 9.4 Migração: um cartão gravado com a imagem `ga36` antiga, com jogos e saves, recebe `flash console --update` e passa a iniciar nos dois, com a `ROMS` intacta. Verificação: os saves de antes continuam lá nos dois consoles.
- [ ] 9.5 No R36S, um jogo de cada core do catálogo roda 5 minutos sem travar e em velocidade cheia pelas métricas; medir a taxa real do painel e confirmar F1-F5. Verificação: métricas do `logd` e ajuste final do `retroarch-r36s.cfg` e da autoconfiguração.

## Workflow follow-up

- Arquivar a change depois da verificação nos dois aparelhos e da revisão do usuário.
- O merge na `main` é por PR com squash, só quando o usuário pedir.
