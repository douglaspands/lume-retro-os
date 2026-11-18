# Proposal

## Why

Antes de seguir com funções novas, o usuário quer corrigir de uma vez o que já incomoda no
uso do aparelho (decisão de 2026-11-18, na branch `feature/virtual-gamepad`, entregue junto
das changes em curso). São quatro tipos de problema:

- **Tela:** o GA36 quebra a imagem com brilho alto (P-95) e o painel roda a 55,7 Hz (P-25),
  então quadros se perdem.
- **Som:** o volume do usuário é só digital, com o ganho analógico fixo, e o chiado e o
  zumbido ficam sempre no máximo (P-29, P-45). O fone não troca a saída (P-42).
- **Cartão:** o boot verifica o exFAT inteiro toda vez, e não há como fazer manutenção do
  cartão sem tirá-lo do console (P-64).
- **Uso diário:** não existe suspensão; os menus verticais aceitam esquerda e direita para
  mover o foco; o console sobe em 1970. Além disso, há bugs pequenos espalhados.

Esta change nasceu como `card-health` (P-64, itens 1, 2 e 4) e foi ampliada e renomeada a
pedido do usuário.

## What Changes

**Cartão (escopo original, sem mudança)**
- A `ROMS` só é verificada com o *VolumeDirty* ou o *MediaFailure* ligados, ou a pedido do
  usuário; num boot limpo não há verificação. **BREAKING** para o requisito "Verificação da
  partição de jogos a cada boot".
- Item "Cartão" nas Configurações (espaço livre, "Otimizar agora" com o TRIM, "Verificar no
  próximo boot"), atendido por um serviço root pequeno que só executa esses dois pedidos.
- Read-ahead do cartão maior, com o valor escolhido por medição.
- Prova de que o desligamento deixa o volume limpo.

**Tela**
- **P-95:** achar a causa da imagem quebrada com brilho alto no GA36, pelos experimentos de
  alimentação, corrente, calor e DSI. A trava fixa `backlight_max` sai; o limite seguro é
  aprendido pelo que o aparelho registra (com o relato do usuário por atalho) e fica só no
  registro, sem marca na tela (o pontinho vermelho foi dispensado pelo usuário em
  2026-11-18). O padrão do GA36 é o nível 7.
- **P-25:** o painel do GA36 a ~60 Hz, se o PLL, o JD9366 e a taxa do DSI permitirem. É o
  mesmo modo do painel que os experimentos de DSI do P-95 tocam.
- **P-30:** o Mega Drive (picodrive) mostra a imagem no GA36. **P-26:** o arcade é conferido
  no GA36.

**Som**
- **Volume analógico nos dois consoles (P-29, P-45):** as teclas de volume mexem no ganho
  analógico da saída ativa, e o DAC fica em 0 dB. O volume 0 é mudo de verdade e o
  **amplificador desliga no volume 0 e no silêncio**, que é onde está o ganho de energia. A
  linha do volume mostra esse nível. O zumbido do R36S em silêncio é verificado com esse
  caminho.
- **Fone (P-42):** o `r36os-jack` lê o estado do fone (`iface=CARD`) e para de cair em laço.
  Ao encaixar e tirar o fone, a saída troca nos dois sentidos e nos dois consoles, e cada
  saída guarda o próprio volume.

**Energia**
- **Suspensão:** um **toque curto no botão de energia suspende** e **segurar desliga**. Outro
  toque acorda o console no mesmo ponto, com o jogo pausado antes, o `sync` do cartão, a
  tela, a luz e o som desligados, e o cenário `suspend` no governor. "Suspender" fica no menu
  do sistema do launcher. A profundidade (`s2idle` ou `deep`) sai de um spike no aparelho que mede a
  corrente de cada modo.

**Relógio**
- **P-07, uma hora que só anda para a frente:** o Wi-Fi é um acessório opcional e os consoles
  não têm bateria para o relógio, então nenhuma fonte de hora é garantida. A hora é gravada no
  cartão ao desligar e ao suspender. No boot, vale a maior entre a hora gravada, a data do
  build e o RTC (se ele trouxer uma hora válida). Uma fonte real, quando aparecer (NTP com o
  dongle de Wi-Fi, ou o PC pelo cabo), corrige a hora, mas nada depende dela. Os saves deixam
  de ganhar datas que voltam a 1970. Os logs continuam ordenados pelo número do boot. Nada
  aparece na tela.

**Nomes `lume-` (P-94, incluído pelo usuário em 2026-11-18)**
- Motivo: a mistura de `r36os-*` e `lume-*` está atrapalhando as correções; não fica claro o
  que o projeto criou e o que veio do Alpine ou do upstream. Tudo o que o projeto criou passa a
  ter o prefixo `lume-`. Os pacotes do Alpine e do upstream ficam como estão.
- **Apps do console:** os 24 nomes `r36os-*` da imagem (APKs, serviços do OpenRC e
  ferramentas, a lista do P-94) viram `lume-*`.
- **Pastas do sistema:** `/usr/libexec/r36os`, `/usr/share/r36os`, `/etc/r36os` e
  `/run/r36os` viram `.../lume`.
- **Ferramenta do PC:** `r36os build/push/dev/...` vira `lume ...`.
- **Ordem:** a troca de nomes é a **primeira onda**. Assim as correções desta change e as
  tarefas ainda abertas da `game-governor`, da `lume-hud-actions` e da `virtual-gamepad` já
  nascem com os nomes novos, e essas tarefas são reescritas com os nomes novos.
- **Atualização sem perda:** um `push` de um build com os nomes novos sobre um console com os
  antigos chega ao menu sem deixar serviços velhos ativos. Os dados do cartão com caminhos
  (logs, `power.conf`, `logs.conf`) são mantidos ou migrados uma vez.
- **Prova:** um teste que falha se achar `r36os` num nome do console ou da ferramenta do PC,
  além do `test-vm` verde e de um boot nos dois consoles.

**Menu do sistema pelo Fn (trazido da `launcher-adjustments`, usuário, 2026-11-18)**
- No launcher, o toque no Fn abre o menu do sistema: Configurações, Suspender, Reiniciar e
  Desligar (os dois últimos com confirmação). O rodapé do Dock mostra a dica do Fn, e segurar
  o Fn mostra os atalhos. Reiniciar usa o código de saída 66 do contrato de sessão.
- As Configurações perdem Desligar e o item RetroArch (o menu completo do RetroArch fora do
  jogo volta pela opção de liberar, P-101).

**Interface e pequenos**
- **Menus verticais:** só cima e baixo movem o foco. Esquerda e direita não mudam a escolha
  numa lista ou confirmação vertical (no launcher e no menu do jogo). Numa linha com seletor
  de valor, esquerda e direita continuam mudando o valor.
- **P-87:** os nós `/dev/input` deixam de ser graváveis pelo usuário dos jogos.
- **P-47 (6.8):** os analógicos são calibrados no início, pelo repouso lido de cada aparelho.
- **P-50:** o link `flashed` aponta para o build gravado, não para o `latest`.
- A tarefa 2.1 da `hide-clock` (relógio do RetroArch escondido) é conferida na mesma janela.

**Fora do escopo:** shaders (a tarefa 2.2 da `lume-shaders` e o P-89, depois); desligamento
por bateria fraca (`game-governor`); aprendizado da bateria (P-98); relógio na tela e acerto
manual da hora (sem fonte garantida, a hora não aparece na tela); troca do exFAT por outro sistema de arquivos.

## Capabilities

### New Capabilities
- `card-maintenance`: a manutenção do cartão pedida pelo usuário (TRIM e verificação no
  próximo boot), o registro de quando cada uma rodou e o read-ahead.
- `system-sleep`: a suspensão e o despertar pelo botão de energia (toque curto suspende,
  segurar desliga), o estado do jogo, do som e do cartão em volta dela, e a profundidade
  usada em cada console.
- `audio-output`: o volume analógico por saída, o mudo e o desligamento do amplificador no
  silêncio, e a troca automática entre o alto-falante e o fone.
- `display-brightness`: o limite seguro do brilho aprendido por aparelho, sem trava fixa, e
  como ele é mostrado e registrado.

### Modified Capabilities
- `boot-runtime`: a verificação da `ROMS` só com o volume sujo ou a pedido; a hora só anda
  para a frente; os nós de entrada passam a ser só leitura para o grupo `input`.
- `device-support`: o requisito do áudio passa a ser volume analógico; o brilho deixa de ter
  teto fixo; o desligamento passa a ser o botão segurado; o painel do GA36 passa a uns 60 Hz,
  se a prova permitir; os analógicos são calibrados no início.
- `game-launcher`: o menu do sistema pelo Fn (Configurações, Suspender, Reiniciar, Desligar),
  as dicas do Fn, o item "Cartão", as Configurações sem Desligar e sem RetroArch, e a regra de
  navegação dos menus verticais.
- `frontend-session`: o reiniciar pelo código de saída 66 (trazido da `launcher-adjustments`).

- Nomes `lume-`: só entram deltas nas specs cujos requisitos citam um nome ou caminho
  `r36os`: `system-image`, `system-update`, `device-testing`, `build-performance`,
  `build-cache`, `build-packages`, `boot-runtime`, `vendor-dtb-compat` e `vm-validation`.
  Uma troca só de nome, sem mudança de comportamento, é o mesmo requisito com o nome novo.
  Esses deltas são escritos na tarefa 1.4, dentro da onda `TREE`.

O menu do jogo (`lume-run`) é da capability `game-actions`, que ainda está na change
`lume-hud-actions`. A regra de navegação vertical entra nela no `design.md`, e o delta só é
escrito depois que aquela change for arquivada.

## Impact

- **initramfs:** `storage.sh` e `init` (bit do exFAT, pedido de verificação).
- **Sessão e desligamento:** `session` e o OpenRC; o serviço de energia (suspensão, botão de
  energia) e o `lume-power` (cenário `suspend`, regra do read-ahead).
- **`r36os-input`:** gesto do botão de energia, `backlight_max` removido dos perfis,
  calibração dos analógicos. Os pacotes do R36S já construídos para o ciclo pausado
  precisam ser refeitos.
- **Áudio:** `lume-audio` (`mixer`, `jack`) e o patch de volume do RetroArch (0005), que
  passa a ser analógico; testes de `tests/audio/`.
- **Kernel:** DTS do GA36 (tensão do painel nos experimentos, modo do JD9366 no patch 0005)
  e o que a suspensão exigir nos dois kernels.
- **`lume-ui`:** "Cartão", "Suspender", as linhas de brilho e volume, a navegação vertical.
  Também o `lume-run` (confirmação do menu do jogo) e o protótipo, pela regra da régua a
  640x480.
- **Nomes `lume-`:** todos os `aports/r36os-*`, `rootfs/overlay` (serviços, `libexec`, `conf.d`,
  regras do udev), `initramfs`, a ferramenta do PC (`src/r36os`, entrada no `pyproject.toml`),
  os testes, a documentação, o `policy.toml` do `ctx`, as memórias do projeto e as tarefas
  abertas da `game-governor`, da `lume-hud-actions` e da `virtual-gamepad`. Como um nome
  errado num serviço do boot deixa o console sem subir, cada troca é provada na VM antes do
  aparelho.
- **Outros:** regra do udev dos nós de entrada; `src/r36os/flash.py` (P-50); a hora gravada no
  cartão (sessão e initramfs ou um serviço depois do frontend).
- **Documentação:** `docs/LOGS.md`, `docs/LAUNCHER.md`, guias de bring-up, `PENDENCIAS.md`
  (os P-NN deste pacote apontam para `device-fixes`).
- **Provas:** no GA36 e no R36S, com o mesmo cartão e um console de cada vez, juntas em
  janelas de aparelho. Há várias provas que só o olho e o ouvido do usuário fecham (brilho,
  chiado, fone, suspensão).
