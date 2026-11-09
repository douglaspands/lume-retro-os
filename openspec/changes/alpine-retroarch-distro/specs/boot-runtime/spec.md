# Spec Delta

## Purpose

Define como o sistema sobe a partir do cartão: montagem do sistema imutável, criação e verificação da partição de jogos, persistência seletiva, mensagens de boot e logs.

## ADDED Requirements

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
- **THEN** `ROMS/logs/metricas/boot-<n>.csv` tem amostras com temperatura, frequência e ocupação durante o jogo, e `ROMS/logs/eventos.log` tem a abertura e o fechamento do jogo com o core e a duração

#### Scenario: Desligamento abrupto registrado
- **WHEN** a energia é cortada sem desligar e o console é ligado de novo
- **THEN** `ROMS/logs/eventos.log` registra que o desligamento anterior foi abrupto, e as métricas até o último lote gravado continuam lá

### Requirement: Gravação dos logs sem desgaste nem perda de desempenho
Os logs de diagnóstico MUST ser gravados em lote a partir da RAM e MUST ter rotação por tipo com um teto total configurável pelo PC, para não encher o cartão nem afetar o desempenho dos jogos.

#### Scenario: Rotação limita o espaço
- **WHEN** os logs passariam do teto configurado
- **THEN** os mais antigos são apagados primeiro e `ROMS/logs/` fica dentro do teto

#### Scenario: Logs desligados pelo PC
- **WHEN** o usuário põe `enable=0` em `ROMS/system/etc/logs.conf` e liga o console
- **THEN** nenhum coletor roda e só o log de boot da `BOOT` é gravado

### Requirement: Resumo de hardware antes do frontend
Antes de iniciar o frontend, o boot MUST imprimir um resumo com o estado de vídeo (driver de GPU), áudio, controle, bateria e partição de jogos, marcando cada item como ok ou falha.

#### Scenario: Resumo na VM
- **WHEN** a VM sobe
- **THEN** o resumo mostra o driver de vídeo virtual como ok, o controle virtual ou teclado como ok e a partição de jogos como ok, e a bateria como ausente sem bloquear o boot
