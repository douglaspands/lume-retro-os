# Tasks

## 1. Medição de partida

- [ ] 1.1 Medir o build atual antes de qualquer mudança: (a) `build console` com cache frio, (b) repetido sem mudança, (c) depois de mudar um patch de driver, (d) depois de subir um pacote do rootfs; para cada um o tempo total e a temperatura máxima da CPU (lida do `hwmon` do host durante o build). Verificação: tabela "antes" no design (D5).

## 2. Prioridade e número de tarefas (D4)

- [ ] 2.1 `container.py`: todo script roda como `nice -n 19 ionice -c 3`; `R36OS_JOBS` e `--jobs` em `build`, `pkg` e `test-vm`, padrão metade dos núcleos, levados ao `make -j`, ao `JOBS` do `abuild` e ao `-processors` do `mksquashfs`; o build mostra tarefas e prioridade no começo. Verificação: testes de unidade dos argumentos do podman e do script; durante um build, `ps -o ni,cmd` mostra `19` nos compiladores.
- [ ] 2.2 Documentar `--jobs`/`R36OS_JOBS` no `README.md` e no guia do build. Verificação: o comando documentado roda como escrito.

## 3. Kernel incremental (D1)

- [ ] 3.1 `kernel.source_tree()`: árvore `.cache/src/linux-<versão>/` com git (commit `upstream` do tarball e um commit por patch); série nova aplicada a partir de `upstream`, e só os arquivos de conteúdo diferente ganham data nova; `GIT_CEILING_DIRECTORIES` mantido. Verificação: teste de unidade com uma árvore pequena (mudar um patch muda o mtime só do arquivo dele).
- [ ] 3.2 `build_kernel()`: pasta fixa `.cache/kbuild/<console>/`, sem hash; as verificações do fragmento e dos warnings dos nossos drivers continuam. Verificação: patch num driver do GA36 recompila esse arquivo e o link (log do `make`), o kernel do R36S não recompila e sai igual byte a byte.
- [ ] 3.3 Limpeza das gerações antigas (`linux-<versão>-*`, `kbuild/<console>-*`) com o espaço liberado numa linha; `repo-clean` e `docs/` do cache atualizados com o layout novo. Verificação: depois do primeiro build, `.cache/` tem uma árvore e uma pasta de build por console; spec `build-cache`.
- [ ] 3.4 Equivalência: o `Image`/`zImage` de um build incremental é igual ao de um build limpo com as mesmas entradas. Verificação: teste de integração (`r36os build --clean` contra incremental, mesmo SHA256).

## 4. Pacotes do que é compilado (D3, D3b)

- [ ] 4.1 Provar a montagem no x86 de um pacote para armv7 e aarch64 (`abuild` com `CARCH`, ou `apk mkpkg`, ou o escritor próprio de `.apk` v2) e que o `apk` da arquitetura do console o aceita e o indexa com a chave do projeto. Verificação: `apk add --root` num container da arquitetura instala o pacote de teste sem `--allow-untrusted`; decisão anotada no D3.
- [ ] 4.2 Pacotes `lume-kernel-<console>`, `lume-dtbs-<soc>` e `lume-initramfs-<console>` com o hash de entradas no campo `commit`; o build reaproveita o pacote com o mesmo hash e só compila quando não acha. Verificação: testes de unidade (hash igual → reaproveita; entrada mudou → `pkgrel` seguinte) e um build sem mudança que não chama o compilador.
- [ ] 4.3 `image.py` tira a `BOOT` desses pacotes; `VERSION` com a versão de cada um; `hwinfo` registra no log de boot as versões dos pacotes do projeto. Verificação: `tests/integration/test_image_console.py` com a mesma listagem e os mesmos SHA256 da `BOOT` de antes; `docs/LOGS.md` com o campo novo.
- [ ] 4.4 Versão automática dos `aports/` (inclusive `lume-launcher`): hash de entradas por `aport` comparado com o `commit` do pacote mais novo; diferente → compila com o `pkgrel` seguinte, sem editar o `APKBUILD`. Verificação: teste de unidade; mudar um arquivo do `lume-launcher` gera versão maior, e sem mudança nada é compilado; documentado no guia de pacotes.

## 5. Etapas puladas por hash de entradas (D2)

- [ ] 5.1 Hash de entradas e `<saída>.inputs` para rootfs e `SYSTEM`, DTBs com validação, initramfs e imagem de módulos; a etapa é pulada quando bate, com uma linha dizendo isso; `r36os build --clean` força tudo. Verificação: teste de unidade que muda cada entrada e confere que a etapa roda de novo; dois builds seguidos sem mudança dão `BOOT` e `SYSTEM` iguais byte a byte.
- [ ] 5.2 Tempo por etapa no fim do build (inclusive `skipped` e em caso de erro). Verificação: teste de unidade do resumo e a saída de um build real.

## 6. Atualização pontual (D6)

- [ ] 6.1 `r36os push` sem descompactar a imagem: lê os arquivos das saídas do build pela lista da `BOOT` com SHA256, manda só os diferentes e mostra bytes enviados e tempo; sem diferença, não envia nem reinicia. Verificação: testes de `tests/unit/test_push.py` (nada mudou, um arquivo mudou) e um `push` real sem a linha `unpacking`.
- [ ] 6.2 Camadas `<console>/lume`, `<console>/retroarch` e `<console>/SYSTEM` montadas a partir do rootfs completo pela lista de arquivos de cada grupo de pacotes, cada uma com hash de entradas; limites de tamanho somados. Verificação: teste de unidade da separação (todo arquivo do rootfs está em exatamente uma camada) e um build em que só o `lume-launcher` muda e só a camada `lume` muda de SHA256.
- [ ] 6.3 `initramfs`: monta as camadas como `lowerdir` do overlay, com o `.old` de cada uma no corte de energia, e registra cada camada com a versão no log de boot; spec `system-image` (cenários das camadas) e `docs/LOGS.md`. Verificação: `tests/initramfs/test_storage.sh` e o `test-vm` verde; no aparelho, o log lista as camadas.
- [ ] 6.4 Atualização de cartões antigos (um só `SYSTEM`) pelo `push` e pelo `flash --update`, sem deixar o arquivo antigo ocupando espaço. Verificação: teste do `push` com a `BOOT` antiga e conferência da `BOOT` depois.
- [ ] 6.5 Medir o ciclo de uma mudança no `lume-launcher`: do build ao console reiniciado, contra o de hoje. Verificação: tempos anotados no D6.

## 7. Verificação integrada

- [ ] 7.1 Repetir as quatro medições da 1.1 e anotar o "depois" no design, com a meta do design (patch num driver em menos de 1 minuto por console; build sem mudança em segundos) e a temperatura máxima. Verificação: tabela antes/depois no D5.
- [ ] 7.2 `r36os build vm`, `r36os test-vm` e `r36os build console` verdes, e nos dois consoles um `push` depois de uma mudança num driver e outro depois de uma mudança no `lume-launcher` mandam só o que mudou e o console sobe normal. Verificação: saídas dos comandos, a lista `sent:` dos pushes e o log de boot.

## Workflow follow-up

- Fazer depois do archive da `boot-dtb-select`, no mesmo bloco da change do governor e dos cenários do frontend (decisão do usuário, 2026-11-16).
- Anotar o P-36 e o P-61 em `docs/PENDENCIAS.md` com o que esta change resolveu, e anotar no P-14 (tema 1) a instalação de pacotes com o `apk` dentro do console (camada persistente), que ficou fora.
