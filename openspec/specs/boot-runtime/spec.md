# boot-runtime Specification

## Purpose

Define como o sistema sobe a partir do cartão: montagem do sistema imutável, criação e verificação da partição de jogos, persistência seletiva, mensagens de boot, swap comprimido em ZRAM e logs.

## Requirements

### Requirement: Swap comprimido em ZRAM no boot
Em todos os alvos (`ga36`, `r36s` e `vm`), o sistema MUST configurar e ativar no boot um dispositivo de swap em ZRAM (`/dev/zram0`) com compressor `lz4`, tamanho descomprimido igual a 50% da memória RAM total (`MemTotal`) e prioridade máxima (`32767`). Caso o dispositivo ZRAM não esteja disponível, o boot MUST registrar um aviso e prosseguir normalmente sem bloquear o sistema.

#### Scenario: ZRAM ativo no GA36 (512 MiB)
- **WHEN** o GA36 com 512 MiB de RAM conclui o runlevel de boot
- **THEN** `/dev/zram0` está ativo em `/proc/swaps` com prioridade `32767`, algoritmo `lz4` em `/sys/block/zram0/comp_algorithm` e `disksize` igual à metade de `MemTotal` (~256 MiB)

#### Scenario: ZRAM ativo no R36S e na VM (1 GiB)
- **WHEN** o R36S ou a VM com 1 GiB de RAM conclui o runlevel de boot
- **THEN** `/dev/zram0` está ativo em `/proc/swaps` com prioridade `32767`, algoritmo `lz4` e `disksize` igual à metade de `MemTotal` (~512 MiB)

#### Scenario: Falha no ZRAM não interrompe o boot
- **WHEN** `/dev/zram0` não existe e o módulo `zram` não pode ser carregado
- **THEN** o serviço registra o aviso no log do sistema, encerra com código `0` e o frontend inicia normalmente sem swap

### Requirement: Parâmetros de memória virtual ajustados para ZRAM
O sistema MUST configurar no boot `vm.swappiness=100` e `vm.page-cluster=0` via `sysctl`, para priorizar o envio de páginas anônimas e `tmpfs` frias ao ZRAM sem leituras especulativas de múltiplas páginas em cada page fault.

#### Scenario: Valores de sysctl aplicados no boot
- **WHEN** o sistema conclui o runlevel de boot
- **THEN** `/proc/sys/vm/swappiness` vale `100` e `/proc/sys/vm/page-cluster` vale `0`

### Requirement: Raiz imutável com camada gravável em RAM
O boot MUST montar `SYSTEM` como somente leitura e sobrepor uma camada gravável em RAM limitada a 32 MiB. Nada gravado fora dos caminhos persistidos MUST sobreviver a um reboot.

#### Scenario: Escrita fora da persistência some
- **WHEN** um arquivo é criado em `/var/tmp/teste` e o sistema é reiniciado
- **THEN** o arquivo não existe após o reboot e o `SYSTEM` não foi modificado

#### Scenario: Desligamento abrupto
- **WHEN** a energia é cortada com o sistema em uso e ele é ligado de novo
- **THEN** o sistema sobe normalmente até o frontend, sem precisar reparar o sistema de arquivos raiz

### Requirement: BOOT montada somente leitura
A partição `BOOT` MUST ficar montada somente leitura em `/boot` durante o uso. Ela MUST ser remontada como gravável só nos momentos de gravar logs ou aplicar uma atualização, voltando a somente leitura em seguida.

#### Scenario: BOOT protegida
- **WHEN** o frontend está em execução
- **THEN** `/boot` aparece montada como somente leitura

### Requirement: Criação da partição de jogos no primeiro boot
Quando o cartão não tiver a partição 2, o boot MUST criá-la ocupando todo o espaço após a `BOOT`, formatá-la em exFAT com rótulo `ROMS` e criar a estrutura de pastas do contrato de jogos, antes de montar a raiz.

#### Scenario: Primeiro boot
- **WHEN** o sistema sobe de uma imagem recém-gravada que só tem a `BOOT`
- **THEN** a partição 2 passa a existir, exFAT com rótulo `ROMS`, ocupando o resto do cartão, com as pastas `roms/`, `bios/`, `saves/`, `states/`, `screenshots/` e `system/`, e uma mensagem na tela informa a criação

#### Scenario: Boots seguintes
- **WHEN** o sistema sobe e a partição 2 já existe
- **THEN** a partição não é recriada nem formatada, e o conteúdo existente é preservado

### Requirement: Nunca formatar dados existentes
O boot MUST NOT formatar, recriar ou redimensionar uma partição 2 que já exista, mesmo com sistema de arquivos desconhecido ou com erros.

#### Scenario: Partição 2 com outro sistema de arquivos
- **WHEN** a partição 2 existe mas não é exFAT
- **THEN** o boot não a modifica, mostra o erro na tela e no log e segue sem a partição de jogos

### Requirement: Verificação da partição de jogos a cada boot
Antes de montar a partição `ROMS`, o boot MUST rodar a verificação e o reparo automático do exFAT. A partição MUST ser montada em `/storage`, com dono no usuário do frontend.

#### Scenario: Partição marcada como suja
- **WHEN** o sistema sobe depois de um desligamento abrupto que deixou a `ROMS` marcada como suja
- **THEN** a verificação roda, o resultado aparece na tela e no log, e a `ROMS` é montada em `/storage`

### Requirement: Persistência seletiva em ROMS/system
Só os itens de uma lista explícita MUST persistir entre boots, guardados em `ROMS/system/`: a configuração do RetroArch (incluindo remaps e overrides), o fuso horário e o hostname. Gravar esses itens MUST ser atômico (arquivo temporário e renomeação).

#### Scenario: Configuração do RetroArch persiste
- **WHEN** o usuário muda uma opção no RetroArch, salva e reinicia o console
- **THEN** a opção continua com o valor salvo após o reboot

#### Scenario: Restaurar fábrica
- **WHEN** a pasta `system/` da partição `ROMS` é apagada pelo PC e o console é ligado
- **THEN** o sistema sobe com a configuração de fábrica e recria `system/`, sem tocar em `roms/`, `bios/`, `saves/` e `states/`

### Requirement: Boot verboso
Nesta versão, o boot MUST mostrar na tela as mensagens do kernel e de cada serviço iniciado, sem splash. Nos consoles, as mesmas mensagens MUST sair também na serial de debug.

#### Scenario: Mensagens visíveis
- **WHEN** o console ou a VM é ligado
- **THEN** a tela mostra as mensagens do kernel e a lista de serviços com o resultado de cada um, até o frontend assumir a tela

### Requirement: Logs centralizados em ROMS/logs
Todos os logs do sistema MUST ficar numa única pasta, `ROMS/logs/`, com uma subpasta por tipo, de modo que apagá-la limpe todos os logs sem afetar jogos, saves e configurações. A pasta MUST ser recriada no boot seguinte. A `BOOT` MUST permanecer somente leitura e só recebe o log de boot quando não há `ROMS`.

#### Scenario: Limpar os logs pelo PC
- **WHEN** o usuário apaga `ROMS/logs/` no PC e liga o console
- **THEN** o console sobe normalmente, recria `ROMS/logs/` com os logs desse boot e não toca em `roms/`, `bios/`, `saves/`, `states/` e `system/`

#### Scenario: Sem ROMS
- **WHEN** o console sobe com uma partição 2 que não é exFAT
- **THEN** o log desse boot é gravado em `BOOT/logs/`, mantendo os 10 mais recentes

### Requirement: Log de cada boot
Ao final de cada boot, o sistema MUST gravar em `ROMS/logs/boot/` um arquivo com as mensagens do kernel, dos serviços e o resumo de hardware daquele boot, com rotação pelo número de boots configurado.

#### Scenario: Log gravado e rotacionado
- **WHEN** o console completa um boot além do limite de boots guardados
- **THEN** `ROMS/logs/boot/` contém exatamente o limite configurado de logs, e o mais recente tem as mensagens do kernel e dos serviços desse boot

### Requirement: Logs de diagnóstico do sistema e do hardware
O sistema MUST registrar em `ROMS/logs/`, legível no PC, um retrato do hardware a cada boot, métricas periódicas do hardware e do frontend durante o uso, e eventos com sucesso ou falha.

#### Scenario: Retrato do hardware por boot
- **WHEN** o console termina um boot
- **THEN** existe `ROMS/logs/hw/boot-<n>.txt` com CPU, frequências, memória, zonas térmicas, bateria e armazenamento desse boot

#### Scenario: Métricas e eventos durante o uso
- **WHEN** um jogo é aberto, jogado por alguns minutos e fechado
- **THEN** `ROMS/logs/metrics/boot-<n>.csv` tem amostras com temperatura, frequência e ocupação durante o jogo, e `ROMS/logs/events.log` tem a abertura e o fechamento do jogo com o core e a duração

#### Scenario: Desligamento abrupto registrado
- **WHEN** a energia é cortada sem desligar e o console é ligado de novo
- **THEN** `ROMS/logs/events.log` registra que o desligamento anterior foi abrupto, e as métricas até o último lote gravado continuam lá

### Requirement: Gravação dos logs sem desgaste nem perda de desempenho
Os logs de diagnóstico MUST ser gravados em lote a partir da RAM e MUST ter rotação por tipo com um teto total configurável pelo PC, para não encher o cartão nem afetar o desempenho dos jogos.

#### Scenario: Rotação limita o espaço
- **WHEN** os logs passariam do teto configurado
- **THEN** os mais antigos são apagados primeiro e `ROMS/logs/` fica dentro do teto

#### Scenario: Logs desligados pelo PC
- **WHEN** o usuário põe `enable=0` em `ROMS/system/etc/logs.conf` e liga o console
- **THEN** o retrato do hardware e as métricas não são gravados, e o log de boot e os eventos continuam em `ROMS/logs/`

### Requirement: Idioma dos logs e das mensagens ao usuário
Os logs do sistema MUST ser em inglês: conteúdo, nomes de arquivos e pastas, categorias e resultados dos eventos e colunas das métricas. As mensagens do sistema para o usuário MUST seguir o idioma escolhido no menu do RetroArch (`user_language`), e um idioma sem tradução MUST cair no inglês.

#### Scenario: Logs em inglês com a interface em português
- **WHEN** o idioma do menu é português do Brasil e um jogo é aberto
- **THEN** `ROMS/logs/events.log` registra `game OK opened: ...` e as métricas usam as colunas em inglês

#### Scenario: Tela de falha no idioma escolhido
- **WHEN** o usuário escolheu espanhol no menu e o frontend falha 3 vezes seguidas
- **THEN** a tela de erro é mostrada em espanhol, e o evento correspondente em `events.log` continua em inglês

### Requirement: Resumo de hardware antes do frontend
Antes de iniciar o frontend, o boot MUST imprimir um resumo com o estado de vídeo (driver de GPU), áudio, controle, bateria e partição de jogos, marcando cada item como ok ou falha.

#### Scenario: Resumo na VM
- **WHEN** a VM sobe
- **THEN** o resumo mostra o driver de vídeo virtual como ok, o controle virtual ou teclado como ok e a partição de jogos como ok, e a bateria como ausente sem bloquear o boot

### Requirement: Sistema do próprio console no cartão único
No cartão da imagem `console`, o boot MUST montar como raiz o `SYSTEM` do console em que o cartão está (`BOOT/ga36/SYSTEM` no GA36, `BOOT/r36s/SYSTEM` no R36S). Se esse arquivo faltar, o boot MUST parar com uma mensagem na tela que nomeia o console e o arquivo esperado, sem tentar o `SYSTEM` do outro console.

#### Scenario: Mesmo cartão, sistemas diferentes
- **WHEN** o mesmo cartão inicia no GA36 e depois no R36S
- **THEN** no GA36 a raiz é o `SYSTEM` armv7 de `BOOT/ga36/` e no R36S é o `SYSTEM` aarch64 de `BOOT/r36s/`, e o `/etc/r36os/board` de cada um nomeia o próprio console

#### Scenario: SYSTEM do console ausente
- **WHEN** o R36S inicia um cartão cuja `BOOT` não tem `r36s/SYSTEM`
- **THEN** o boot para na tela de recuperação com uma mensagem que cita o R36S e `r36s/SYSTEM`

### Requirement: Logs dos dois consoles na mesma ROMS
Com o cartão único, os logs dos dois consoles MUST ficar na mesma `ROMS/logs/`, numa única sequência de boots, e cada arquivo de log de boot e de hardware MUST identificar o console que o gerou.

#### Scenario: Boots alternados
- **WHEN** o cartão inicia no GA36, depois no R36S e de novo no GA36
- **THEN** existem três logs de boot com números seguidos, nenhum sobrescreve outro, e cada um registra o console em que rodou
