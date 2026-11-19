# system-image Specification

## Purpose

Define a gravação segura de imagens nos cartões de memória via ferramenta de host `r36os flash`, garantindo a integridade dos dados e o desligamento/ejeção segura do dispositivo após a escrita.

## Requirements

### Requirement: Ejeção segura do dispositivo pós-gravação
O comando `lume flash` MUST suportar o argumento opcional `--eject`. Quando `--eject` for especificado, após a escrita e a verificação SHA256 dos blocos gravados, a ferramenta MUST desmontar eventuais partições do dispositivo e solicitar a desconexão/ejeção segura ao sistema operacional através de `udisksctl power-off -b <dispositivo>` (com fallback para `eject <dispositivo>`).

#### Scenario: Gravação com flag --eject
- **WHEN** o usuário executa `lume flash <alvo> <dispositivo> --eject` (com ou sem `--update`)
- **THEN** a gravação e a validação SHA256 são concluídas com sucesso e o dispositivo é ejetado/desligado com segurança antes do término do comando

### Requirement: Uma imagem por alvo a partir da mesma base
O build MUST gerar duas imagens: `console` (um cartão único para o GA36, armv7, e o R36S V5, aarch64) e `vm` (x86_64). Os três sistemas (`ga36`, `r36s` e `vm`) MUST usar a mesma versão do Alpine, a mesma lista de pacotes de userland, a mesma configuração e os mesmos cores. Só a camada de hardware MUST variar: kernel, DTBs, bootloader e firmware.

#### Scenario: Mesma lista de pacotes nos dois alvos
- **WHEN** a imagem `console` e a imagem `vm` são geradas a partir da mesma revisão
- **THEN** o manifesto de pacotes de userland do `SYSTEM` do GA36, do `SYSTEM` do R36S e do `SYSTEM` da VM lista os mesmos nomes e versões, exceto os pacotes declarados como camada de hardware

#### Scenario: Alvo desconhecido
- **WHEN** o build é chamado com um alvo fora de `console` e `vm`
- **THEN** o build falha antes de gerar qualquer arquivo e lista os alvos válidos

### Requirement: Tabela de partições MBR com BOOT FAT32
A imagem gravada MUST ter tabela MBR com uma única partição: `BOOT`, FAT32, rótulo `BOOT`, com 1 GiB na VM e 2 GiB na imagem `console`. A área antes da `BOOT` MUST ficar livre de partições, reservada aos bootloaders: 16 MiB na VM (a `BOOT` começa no setor 32768) e 128 MiB na imagem `console`, a área de boot dos dois consoles (a `BOOT` começa no setor 262144). A assinatura de disco da imagem `console` MUST ser a mesma dos cartões do GA36 gravados antes desta versão (`4c554d32`).

#### Scenario: Layout da imagem recém-gerada
- **WHEN** a tabela de partições de uma imagem gerada é lida
- **THEN** ela é MBR, tem só a partição 1, FAT32 com rótulo `BOOT`, de 1 GiB começando no setor 32768 na `vm` e de 2 GiB começando no setor 262144 na `console`, e a assinatura de disco da `console` é `4c554d32`

### Requirement: Conteúdo da partição BOOT
A partição `BOOT` MUST conter o `VERSION` do build e um `SYSTEM` por sistema da imagem. Na VM, MUST conter também o kernel, o initramfs e a configuração de boot no formato extlinux (`extlinux/extlinux.conf`). Na imagem `console`, MUST conter só o que os consoles leem: uma pasta por console, `ga36/` com o `SYSTEM` e o kernel como arquivo, e `r36s/` com o `SYSTEM` e o kernel; uma pasta de DTBs por SoC, `dtbs/a33/` e `dtbs/rk3326/` (ver `dtb-selection`), onde o arquivo opcional `dtbs/force` é lido se existir; e, na raiz, o `boot.ini` lido pelo U-Boot do R36S, os dois DTBs do RG351 de fábrica (`rg351mp-kernel.dtb` e `rg351p-kernel.dtb`) que esse U-Boot exige para iniciar, e o `logo.bmp` dos dois consoles. As imagens de boot dos dois painéis do GA36 (gravadas no setor 172032 com `dd`) MUST NOT ficar na `BOOT`: elas MUST ser arquivadas com o build, ao lado da imagem do cartão, com o SHA256 no `SHA256SUMS`. Os logs não ficam na `BOOT` (ver `boot-runtime`).

#### Scenario: Arquivos presentes na BOOT
- **WHEN** a partição `BOOT` de uma imagem gerada é listada
- **THEN** existe `VERSION`, sem pasta `logs/`; na `vm` também `SYSTEM`, o kernel, o `initramfs` e `extlinux/extlinux.conf`; na `console` também `boot.ini`, `rg351mp-kernel.dtb`, `rg351p-kernel.dtb`, `logo.bmp`, `ga36/SYSTEM`, o kernel do GA36, `r36s/SYSTEM`, o kernel do R36S, `dtbs/a33/` com os DTBs dos dois painéis do GA36 e `dtbs/rk3326/` com o DTB do R36S V5, sem `dtbs/force` e sem `ga36/android-boot/`

#### Scenario: Imagens de boot dos painéis arquivadas
- **WHEN** a imagem `console` é gerada
- **THEN** a pasta do build em `out/images/console/<build>/` tem `ga36-android-boot-panel1.img` e `ga36-android-boot-panel2.img`, com o SHA256 de cada uma no `SHA256SUMS`

### Requirement: Sistema como arquivo squashfs
O sistema de arquivos raiz de cada sistema MUST ser entregue como arquivos squashfs dentro da `BOOT`. Na `vm`, ele MUST ser um único arquivo `SYSTEM` de no máximo 768 MiB. Na `console`, o sistema de cada console MUST ser um conjunto de slots em `<console>/slot/`, com nomes pelo conteúdo, descrito pelo manifesto `<console>/SLOTS` (ver `system-update`); a soma dos slots de um console MUST ter no máximo 448 MiB, e a soma de todos os arquivos da `BOOT`, contando o conjunto anterior que o `push` guarda, MUST deixar ao menos 64 MiB livres.

#### Scenario: SYSTEM dentro do limite
- **WHEN** uma imagem é gerada
- **THEN** cada slot é um squashfs válido, a soma dos slots de cada console está dentro do limite, a `BOOT` da `console` tem ao menos 64 MiB livres, e o build falha se algum limite for ultrapassado

#### Scenario: Slots montados no boot
- **WHEN** um console inicia
- **THEN** a raiz do sistema mostra o conteúdo dos slots do boot daquele console, o de cima prevalecendo, e o log do boot lista cada slot montado com a versão dele

#### Scenario: Cartão antigo com SYSTEM único
- **WHEN** um console inicia com uma `BOOT` sem `<console>/SLOTS` e com `<console>/SYSTEM`
- **THEN** o boot monta o `SYSTEM` como antes

### Requirement: Bootloader na área reservada
Na imagem `console`, o build MUST montar a área de 128 MiB antes da `BOOT` a partir das áreas de fábrica dos dois consoles, lidas de cópias dos cartões originais e conferidas por SHA256, fora do git: a do GA36 (`LUME_GA36_FACTORY`) e a do R36S (`LUME_R36S_FACTORY`). No setor 172032 MUST ir a imagem de boot Android do painel 1 do GA36. Na área do GA36, o build MUST NOT alterar a FAT interna nem o env do U-Boot de fábrica. Na VM, MUST gravar um bootloader que leia o `extlinux.conf`. O U-Boot mainline dos consoles fica para depois (P-19, P-34 e P-43).

#### Scenario: Bootloader do GA36
- **WHEN** a imagem `console` é gerada
- **THEN** a área de 8 KiB até a `BOOT` é igual à área de fábrica do GA36, exceto o boot0 encolhido (setores 16 a 63), a cadeia do R36S nos setores que ela ocupa no cartão original do R36S e a imagem de boot no setor 172032; e a tabela MBR do setor 0 é a nossa

#### Scenario: Bootloader da VM
- **WHEN** a imagem `vm` sobe no QEMU com firmware BIOS
- **THEN** o bootloader lê `extlinux/extlinux.conf` da `BOOT` e carrega o kernel e o initramfs indicados nele

### Requirement: Build reproduzível e isolado do host
O build MUST rodar dentro de containers rootless e não instalar nada no host sem confirmação explícita. Dois builds da mesma revisão MUST gerar manifestos de pacotes iguais.

#### Scenario: Manifesto estável
- **WHEN** o mesmo alvo é gerado duas vezes a partir da mesma revisão do repositório
- **THEN** o manifesto de pacotes e versões das duas imagens é idêntico

### Requirement: Tamanho mínimo do cartão
A imagem MUST caber em um cartão de 4 GB, deixando ao menos 2 GB para a partição de jogos, criada pelo `lume flash` com todo o resto do cartão (ou no primeiro boot, se faltar).

#### Scenario: Cartão de 4 GB
- **WHEN** a imagem é gravada em um cartão de 4 GB com `lume flash --full`
- **THEN** a partição de jogos tem pelo menos 2 GB livres

### Requirement: Cartão único para os dois consoles
O mesmo cartão gravado com a imagem `console` MUST iniciar no GA36 e no R36S V5, sem regravar nada entre um e outro, e os dois MUST usar a mesma partição `ROMS` (jogos, BIOS, saves e configuração).

#### Scenario: Trocar o cartão de console
- **WHEN** um cartão gravado com a imagem `console` é usado no GA36 e depois colocado no R36S
- **THEN** o R36S inicia o Lume e mostra os mesmos jogos e saves que o GA36 mostrava

#### Scenario: Ida e volta
- **WHEN** o cartão volta do R36S para o GA36
- **THEN** o GA36 inicia normalmente, e um save feito no R36S aparece no GA36

### Requirement: Boot0 do GA36 encolhido
Na área de boot da `console`, o boot0 do GA36 MUST ocupar só os setores 16 a 63, com o tamanho do cabeçalho eGON em 24 KiB e a soma recalculada pelo build. O build MUST falhar se o boot0 de fábrica tiver conteúdo diferente de `0xFF` depois dos primeiros 24 KiB.

#### Scenario: Cabeçalho válido
- **WHEN** a área de boot da `console` é inspecionada
- **THEN** o setor 16 tem a assinatura `eGON.BT0`, o tamanho declarado é 24576 bytes e a soma eGON confere com os 24 KiB gravados

#### Scenario: Boot0 maior que o espaço
- **WHEN** o build recebe uma área de fábrica cujo boot0 tem código além dos primeiros 24 KiB
- **THEN** o build falha com uma mensagem que explica o motivo, sem gerar a imagem

### Requirement: Cadeias de boot sem sobreposição
O build MUST garantir que nenhuma região usada pela cadeia de boot de um console sobrescreva dados não vazios da área de boot do outro, além do boot0 encolhido e do bloco de fábrica do GA36 nos setores 80 a 277, que não é usado. O `idbloader` do R36S MUST ficar no setor 64, o único que o BROM do RK3326 lê no cartão.

#### Scenario: Regiões conferidas no build
- **WHEN** a área de boot da `console` é montada
- **THEN** o build confere que as regiões do R36S (do setor 64 ao fim do `idbloader` e as do `uboot.img` e do `trust.img`) caem em setores vazios da área do GA36 ou nos setores 64 a 277, e falha listando os setores em conflito se não caírem

### Requirement: Atualização de cartões para a imagem única
Um cartão gravado antes com a imagem `console` MUST aceitar `lume flash console <dispositivo> --update`, que grava só a área de boot e a `BOOT`, sem tocar no setor 0 nem na `ROMS`. Um cartão gravado com a imagem `ga36` antiga (`BOOT` de 1 GiB) MUST ser recusado pelo `--update`, com a mensagem de gravação completa.

#### Scenario: Cartão da imagem console
- **WHEN** o usuário roda `lume flash console <dispositivo> --update` num cartão gravado antes com a imagem `console`
- **THEN** a gravação é aceita, a `ROMS` fica intacta e o cartão inicia no GA36 e no R36S

#### Scenario: Cartão antigo do GA36
- **WHEN** o usuário roda `lume flash console <dispositivo> --update` num cartão gravado antes com a imagem `ga36`, de `BOOT` com 1 GiB
- **THEN** o comando recusa a gravação e explica que o cartão precisa de uma gravação completa

#### Scenario: Cartão de outro layout
- **WHEN** o usuário roda `--update` da `console` num cartão cuja partição 1 tem outro início, tamanho ou assinatura
- **THEN** o comando recusa a gravação e explica que o cartão precisa de uma gravação completa

### Requirement: Atualização pelo cabo USB
O `lume push` MUST atualizar a `BOOT` de um console ligado pela porta OTG, pelo acesso root
do cabo: enviar o build para uma área temporária, conferir o SHA256 de cada arquivo no
próprio console, trocar os arquivos só depois de todos conferidos e reiniciar. Da área de
boot antes da `BOOT`, só a imagem de boot do GA36 no setor 172032 MAY ser regravada, e
conferida por leitura de volta; a `ROMS` só recebe a área temporária, apagada ao final. A
troca MUST NOT apagar um arquivo que o sistema em execução mantém aberto (o `SYSTEM` e a
imagem de módulos do console), para que nenhum espaço da `BOOT` se perca e a `BOOT` volte a
somente leitura antes do reboot.

#### Scenario: Atualização conferida
- **WHEN** o usuário roda `lume push` com um console ligado e acessível por SSH
- **THEN** os arquivos da `BOOT` no cartão passam a ter o SHA256 do build, o console reinicia e o próximo boot registra a versão nova no `events.log`

#### Scenario: Kernel novo no GA36
- **WHEN** o build traz uma imagem de boot do GA36 diferente da gravada no setor 172032 e o `push` é feito com o cartão no GA36
- **THEN** a imagem do painel 1 é gravada no setor 172032, lida de volta com o mesmo SHA256, e nenhum outro setor antes da `BOOT` muda

#### Scenario: Falha na conferência
- **WHEN** algum arquivo enviado tem SHA256 diferente do build
- **THEN** nenhum arquivo da `BOOT` é trocado, o console não reinicia e o comando termina com erro nomeando o arquivo

#### Scenario: Console fora do cabo
- **WHEN** o usuário roda `lume push` e o console não responde pela rede USB (desligado, cabo na porta de carga ou adaptador OTG na porta)
- **THEN** o comando termina com erro antes de enviar qualquer arquivo e diz para ligar o console com o cabo na porta OTG

#### Scenario: Bateria baixa
- **WHEN** o console está com a bateria abaixo de 20%
- **THEN** o comando termina com erro antes de enviar qualquer arquivo

#### Scenario: Sem espaço para a área temporária
- **WHEN** a `ROMS` não tem espaço livre para o build enviado
- **THEN** o comando termina com erro antes de enviar qualquer arquivo, sem apagar nada do usuário

#### Scenario: Troca do SYSTEM em uso sem perder espaço
- **WHEN** o `push` troca o `SYSTEM` ou a imagem de módulos do console em que roda
- **THEN** o arquivo antigo continua na `BOOT` como `<arquivo>.old` até o push seguinte, a `BOOT` volta a somente leitura antes do reboot e, depois do reboot, um `fsck.vfat -n` da `BOOT` não acha cadeias perdidas

#### Scenario: Espaço do build anterior devolvido
- **WHEN** o `push` encontra arquivos `*.old` na `BOOT`, deixados por um push anterior
- **THEN** ele os apaga antes de copiar os novos, conta o espaço liberado na verificação de espaço da `BOOT` e não os inclui na comparação de SHA256 com o build

#### Scenario: Clusters perdidos avisados
- **WHEN** o espaço usado da `BOOT` passa em mais de 32 MB o que os arquivos dela ocupam
- **THEN** o `push` mostra um aviso com o tamanho perdido e as duas formas de recuperar pelo PC (`fsck.vfat -a` com os `FSCK*.REC` apagados, ou `lume flash --update`), e segue com a atualização

#### Scenario: Corte de energia no meio da troca do SYSTEM
- **WHEN** o console inicia com a `BOOT` sem o `<console>/SYSTEM` (ou sem a imagem de módulos) e com o `<arquivo>.old` correspondente
- **THEN** o boot usa o `.old` e registra no log de boot uma linha `ERROR` dizendo que usou o arquivo do build anterior, em vez de parar no modo de resgate

### Requirement: Módulos do kernel fora do SYSTEM no console
Na imagem `console`, os módulos do kernel de cada console MUST ficar num arquivo squashfs próprio da `BOOT`, `<console>/modules` (`ga36/modules`, `r36s/modules`), com os módulos só do kernel daquele console, e o `SYSTEM` do console MUST NOT conter módulos do kernel. Os dois builds da mesma revisão MUST gerar o mesmo arquivo de módulos. A imagem `vm` fica como está.

#### Scenario: Arquivo de módulos na BOOT
- **WHEN** a `BOOT` de uma imagem `console` é listada
- **THEN** existem `ga36/modules` e `r36s/modules`, cada um um squashfs com uma única pasta de versão igual ao `release` do kernel do seu console, e nenhum dos dois `SYSTEM` tem arquivos em `/lib/modules`

#### Scenario: Mudança só no kernel
- **WHEN** dois builds diferem só no kernel de um console (patch ou configuração)
- **THEN** o `SYSTEM` dos dois consoles tem o mesmo SHA256 nos dois builds, e só o kernel, a imagem de módulos e, no GA36, as imagens de boot dos painéis daquele console mudam

#### Scenario: Atualização pelo cabo de um kernel novo
- **WHEN** o `lume push` envia um build que só mudou o kernel do console ligado
- **THEN** ele manda o kernel, a imagem de módulos e o `VERSION` (e, no GA36, a imagem de boot do painel 1), sem mandar nenhum `SYSTEM`

#### Scenario: Limite da BOOT com os arquivos de módulos
- **WHEN** a imagem `console` é gerada
- **THEN** a conta dos 64 MiB livres da `BOOT` inclui os dois arquivos de módulos, e o build falha se o limite for ultrapassado

### Requirement: Logo de boot único
Os dois consoles MUST mostrar no boot o mesmo logo, o `BOOT/logo.bmp`, que é o logo de fábrica do R36S, conferido por SHA256. No GA36, o `bootlogo.bmp` da FAT interna da área de fábrica MUST ser o mesmo arquivo (o firmware de fábrica dos dois traz a mesma imagem), e o build MUST conferir isso; o U-Boot de fábrica do GA36 não desenha um BMP da `BOOT`, então trocar o `BOOT/logo.bmp` pelo PC troca só o logo do R36S.

#### Scenario: Mesmo logo nos dois
- **WHEN** um cartão recém-gravado com a imagem `console` é ligado no GA36 e no R36S
- **THEN** os dois mostram o logo de fábrica do R36S, e o `bootlogo.bmp` da FAT interna do GA36 é idêntico ao `BOOT/logo.bmp`

#### Scenario: Logo trocado pelo PC
- **WHEN** o usuário troca o `BOOT/logo.bmp` por outro BMP de 640x480 e 24 bits e liga os dois consoles
- **THEN** o R36S mostra o logo novo e o GA36 continua com o logo da FAT interna
