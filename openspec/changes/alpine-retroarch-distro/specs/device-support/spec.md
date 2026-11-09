# Spec Delta

## Purpose

Define o suporte de hardware de cada console nesta versão: kernel mainline, device trees, escolha da variante e os periféricos que precisam funcionar para jogar.

## ADDED Requirements

### Requirement: Consoles e variantes suportados
Esta versão MUST suportar o R36S "V5" (Rockchip RK3326, painel de 640x480) e o GA36-MB V1.2 (Allwinner A33) com as duas variantes de painel JD9366 (1 e 2). Outras revisões MUST NOT ser anunciadas como suportadas.

#### Scenario: Variantes listadas
- **WHEN** a configuração de boot da imagem `ga36` é aberta
- **THEN** existe uma entrada para o painel 1 e outra para o painel 2, e a do painel 1 é a padrão

#### Scenario: Variante do R36S
- **WHEN** a configuração de boot da imagem `r36s` é aberta
- **THEN** existe uma entrada para o R36S V5, que é a padrão

### Requirement: Kernel mainline
Os dois consoles MUST usar um kernel Linux mainline da série LTS, com device trees escritos para esse kernel. Device trees de kernels de fabricante MUST NOT ser gravados na imagem.

#### Scenario: Origem dos DTBs
- **WHEN** os DTBs da pasta `dtbs/` de uma imagem de console são inspecionados
- **THEN** todos foram compilados pelo build a partir dos fontes do repositório, para o kernel da própria imagem

### Requirement: Troca de variante pelo PC
A variante ativa MUST ser escolhida pela entrada padrão do `extlinux/extlinux.conf` na `BOOT`, editável num PC, sem recompilar a imagem.

#### Scenario: Trocar o painel do GA36
- **WHEN** o usuário muda a entrada padrão para o painel 2 no PC e liga o console
- **THEN** o kernel sobe com o DTB do painel 2

### Requirement: Vídeo no painel interno
Em cada console suportado, o painel interno MUST mostrar imagem a 640x480 desde as mensagens do kernel, com aceleração GLES pelo driver mainline da GPU (Mali-G31 no R36S, Mali-400 no GA36) e brilho ajustável.

#### Scenario: Primeiras mensagens no painel
- **WHEN** o console é ligado
- **THEN** as mensagens do kernel aparecem no painel interno antes da inicialização dos serviços

#### Scenario: GPU disponível para o frontend
- **WHEN** o frontend inicia no console
- **THEN** ele usa renderização GLES acelerada pela GPU, e não renderização por software

### Requirement: Controle integrado
Cada console MUST expor seus botões e direcionais como um único controle de jogo do Linux, com A, B, X, Y, L1, R1, L2, R2, Start, Select, direcional e os analógicos presentes no aparelho.

#### Scenario: Botões do R36S
- **WHEN** cada botão físico do R36S V5 é pressionado
- **THEN** o controle de jogo reporta o código de evento correspondente da tabela de botões do design

#### Scenario: Controle serial do GA36
- **WHEN** o GA36 termina o boot
- **THEN** o handshake com o microcontrolador dos analógicos foi concluído e os eixos dos dois analógicos variam ao mover os sticks

### Requirement: Áudio
Cada console MUST reproduzir som no alto-falante interno e na saída de fone, com volume ajustável pelos botões de volume do aparelho.

#### Scenario: Volume pelos botões
- **WHEN** o botão de aumentar volume é pressionado durante um jogo
- **THEN** o volume do sistema aumenta e o som continua saindo

### Requirement: Bateria e desligamento
Cada console MUST informar o nível de bateria pela interface padrão de fonte de energia do Linux e cortar a energia de fato ao desligar.

#### Scenario: Desligar corta a energia
- **WHEN** o sistema executa o desligamento
- **THEN** a tela e a luz de fundo se apagam e o aparelho para de consumir energia, sem ficar travado com a tela acesa

#### Scenario: Leitura de bateria
- **WHEN** o nível de bateria é consultado em uso
- **THEN** o sistema informa uma porcentagem entre 0 e 100

### Requirement: Frequência da CPU e proteção térmica
Cada console MUST variar a frequência da CPU conforme a carga, com a tabela de frequências e tensões e as temperaturas-limite do device tree mainline do SoC, sem valores próprios, e com o governor padrão do kernel. Acima do limite térmico, o clock MUST ser reduzido.

#### Scenario: Frequência acompanha a carga
- **WHEN** um jogo está rodando e depois o console volta ao menu parado
- **THEN** a frequência da CPU sobe durante o jogo e desce no menu, dentro da tabela do device tree

#### Scenario: Proteção térmica ativa
- **WHEN** as zonas térmicas são consultadas no console
- **THEN** existe uma zona da CPU com limite passivo ligado à CPU como dispositivo de resfriamento e um limite crítico

### Requirement: Serial de debug
Cada console MUST mandar as mensagens do bootloader e do kernel para sua serial de debug, numa única velocidade do início ao fim: 115200 baud no GA36 e 1500000 baud no R36S (padrão da Rockchip).

#### Scenario: Console serial
- **WHEN** um adaptador serial na velocidade do console é ligado à serial de debug e o console é ligado
- **THEN** as mensagens do bootloader e do kernel aparecem no adaptador sem trocar de velocidade
