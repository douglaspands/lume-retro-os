# device-support Specification

## Purpose

Define o suporte de hardware do console desta versão, o GA36-MB V1.2: kernel mainline, device trees, escolha da variante de painel e os periféricos que precisam funcionar para jogar.

## Requirements

### Requirement: Consoles e variantes suportados
Esta versão MUST suportar o GA36-MB V1.2 (Allwinner A33) com as duas variantes de painel JD9366 (1 e 2). Outros consoles e revisões MUST NOT ser anunciados como suportados; o R36S "V5" fica para uma change própria (pendência P-27).

#### Scenario: Variantes na imagem
- **WHEN** a imagem `ga36` é inspecionada
- **THEN** a imagem de boot do painel 1 está no setor 172032 (a variante padrão) e as imagens de boot dos dois painéis estão em `BOOT/android-boot/`

### Requirement: Kernel mainline
O console MUST usar um kernel Linux mainline da série LTS, com device trees escritos para esse kernel. Device trees de kernels de fabricante MUST NOT ser gravados na imagem.

#### Scenario: Origem dos DTBs
- **WHEN** os DTBs da pasta `dtbs/` e os anexados às imagens de boot do GA36 são inspecionados
- **THEN** todos foram compilados pelo build a partir dos fontes do repositório, para o kernel da própria imagem

### Requirement: Troca de variante pelo PC
A variante de painel MUST poder ser trocada num PC, sem recompilar a imagem: a imagem de boot de cada painel fica em `BOOT/android-boot/`, e gravar a do painel desejado no setor 172032 troca o painel (o bootloader do fabricante lê a imagem de boot desse setor).

#### Scenario: Trocar o painel do GA36
- **WHEN** o usuário grava `BOOT/android-boot/android-boot-panel2.img` no setor 172032 pelo PC e liga o console
- **THEN** o kernel sobe com o DTB do painel 2

### Requirement: Vídeo no painel interno
O painel interno MUST mostrar imagem a 640x480 desde as mensagens do kernel, com aceleração GLES pelo driver mainline da GPU (Mali-400, `lima`) e brilho ajustável.

#### Scenario: Primeiras mensagens no painel
- **WHEN** o console é ligado
- **THEN** as mensagens do kernel aparecem no painel interno antes da inicialização dos serviços

#### Scenario: GPU disponível para o frontend
- **WHEN** o frontend inicia no console
- **THEN** ele usa renderização GLES acelerada pela GPU, e não renderização por software

### Requirement: Controle integrado
O console MUST expor seus botões e direcionais como um único controle de jogo do Linux, com A, B, X, Y, L1, R1, L2, R2, Start, Select, direcional e os analógicos presentes no aparelho.

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
O console MUST mandar as mensagens do bootloader e do kernel para sua serial de debug, numa única velocidade do início ao fim: 115200 baud no GA36.

#### Scenario: Console serial
- **WHEN** um adaptador serial na velocidade do console é ligado à serial de debug e o console é ligado
- **THEN** as mensagens do bootloader e do kernel aparecem no adaptador sem trocar de velocidade
