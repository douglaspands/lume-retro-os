# Spec Delta

## MODIFIED Requirements

### Requirement: Ejeção segura do dispositivo pós-gravação
O comando `lume flash` MUST suportar o argumento opcional `--eject`. Quando `--eject` for especificado, após a escrita e a verificação SHA256 dos blocos gravados, a ferramenta MUST desmontar eventuais partições do dispositivo e solicitar a desconexão/ejeção segura ao sistema operacional através de `udisksctl power-off -b <dispositivo>` (com fallback para `eject <dispositivo>`).

#### Scenario: Gravação com flag --eject
- **WHEN** o usuário executa `lume flash <alvo> <dispositivo> --eject` (com ou sem `--update`)
- **THEN** a gravação e a validação SHA256 são concluídas com sucesso e o dispositivo é ejetado/desligado com segurança antes do término do comando


### Requirement: Bootloader na área reservada
Na imagem `console`, o build MUST montar a área de 128 MiB antes da `BOOT` a partir das áreas de fábrica dos dois consoles, lidas de cópias dos cartões originais e conferidas por SHA256, fora do git: a do GA36 (`LUME_GA36_FACTORY`) e a do R36S (`LUME_R36S_FACTORY`). No setor 172032 MUST ir a imagem de boot Android do painel 1 do GA36. Na área do GA36, o build MUST NOT alterar a FAT interna nem o env do U-Boot de fábrica. Na VM, MUST gravar um bootloader que leia o `extlinux.conf`. O U-Boot mainline dos consoles fica para depois (P-19, P-34 e P-43).

#### Scenario: Bootloader do GA36
- **WHEN** a imagem `console` é gerada
- **THEN** a área de 8 KiB até a `BOOT` é igual à área de fábrica do GA36, exceto o boot0 encolhido (setores 16 a 63), a cadeia do R36S nos setores que ela ocupa no cartão original do R36S e a imagem de boot no setor 172032; e a tabela MBR do setor 0 é a nossa

#### Scenario: Bootloader da VM
- **WHEN** a imagem `vm` sobe no QEMU com firmware BIOS
- **THEN** o bootloader lê `extlinux/extlinux.conf` da `BOOT` e carrega o kernel e o initramfs indicados nele


### Requirement: Tamanho mínimo do cartão
A imagem MUST caber em um cartão de 4 GB, deixando ao menos 2 GB para a partição de jogos, criada pelo `lume flash` com todo o resto do cartão (ou no primeiro boot, se faltar).

#### Scenario: Cartão de 4 GB
- **WHEN** a imagem é gravada em um cartão de 4 GB com `lume flash --full`
- **THEN** a partição de jogos tem pelo menos 2 GB livres


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
