# device-support Specification

## Purpose

Define o suporte de hardware do console desta versão, o GA36-MB V1.2: kernel mainline, device trees, escolha da variante de painel e os periféricos que precisam funcionar para jogar.

## Requirements

### Requirement: Consoles e variantes suportados
Esta versão MUST suportar o GA36-MB V1.2 (Allwinner A33) com as duas variantes de painel JD9366 (1 e 2) e o R36S "V5" (Rockchip RK3326) com o painel da família Sitronix ST7703 desta revisão. Outros consoles e revisões, inclusive outras revisões do R36S, MUST NOT ser anunciados como suportados (pendência P-16).

#### Scenario: Variantes na imagem
- **WHEN** a imagem `console` é inspecionada
- **THEN** a imagem de boot do painel 1 do GA36 está no setor 172032 (a variante padrão), as imagens de boot dos dois painéis do GA36 estão em `BOOT/ga36/android-boot/` e o DTB do R36S V5 está em `BOOT/r36s/`

### Requirement: Kernel mainline
O console MUST usar um kernel Linux mainline da série LTS, com device trees escritos para esse kernel. Device trees de kernels de fabricante MUST NOT ser usados pelo kernel do sistema. A única exceção são os DTBs do RG351 do cartão de fábrica do R36S na raiz da `BOOT`, que só o U-Boot de fábrica lê, para identificar a placa antes de carregar o `boot.ini`.

#### Scenario: Origem dos DTBs
- **WHEN** os DTBs da `BOOT` e os anexados às imagens de boot do GA36 são inspecionados
- **THEN** todos os que o kernel carrega foram compilados pelo build a partir dos fontes do repositório, para o kernel do próprio console, e os únicos DTBs de fábrica na imagem são os do RG351 na raiz da `BOOT`, que o kernel não usa

### Requirement: Troca de variante pelo PC
A variante de painel do GA36 MUST poder ser trocada num PC, sem recompilar a imagem: a imagem de boot de cada painel fica em `BOOT/ga36/android-boot/`, e gravar a do painel desejado no setor 172032 troca o painel (o bootloader do fabricante lê a imagem de boot desse setor).

#### Scenario: Trocar o painel do GA36
- **WHEN** o usuário grava `BOOT/ga36/android-boot/android-boot-panel2.img` no setor 172032 pelo PC e liga o GA36
- **THEN** o kernel sobe com o DTB do painel 2

### Requirement: Vídeo no painel interno
O painel interno MUST mostrar imagem a 640x480 desde as mensagens do kernel, com aceleração GLES pelo driver mainline da GPU (Mali-400 com `lima` no GA36, Mali-G31 com `panfrost` no R36S) e brilho ajustável.

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

#### Scenario: Controle do R36S
- **WHEN** o R36S termina o boot
- **THEN** existe um único dispositivo de entrada de jogo chamado "R36S Gamepad", com os botões e os eixos dos dois analógicos, e o RetroArch o configura sozinho

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
O console MUST mandar as mensagens do bootloader e do kernel para sua serial de debug, numa única velocidade do início ao fim: 115200 baud no GA36 e 1500000 baud no R36S, a velocidade do bootloader de fábrica do R36S.

#### Scenario: Console serial
- **WHEN** um adaptador serial na velocidade do console é ligado à serial de debug e o console é ligado
- **THEN** as mensagens do bootloader e do kernel aparecem no adaptador sem trocar de velocidade

### Requirement: Bootloader de fábrica do R36S
O R36S MUST iniciar pela cadeia de boot do próprio aparelho (`idbloader`, `uboot.img` e `trust.img` do cartão original), que lê o `boot.ini` da `BOOT` e carrega o kernel e o DTB do Lume. Nenhum kernel ou initramfs do cartão de fábrica MUST ser usado, e os DTBs do RG351 de fábrica na raiz da `BOOT` MUST servir só ao U-Boot, que os lê para identificar a placa; o kernel sobe com o DTB do Lume.

#### Scenario: Kernel do Lume no R36S
- **WHEN** o R36S é ligado com um cartão da imagem `console`
- **THEN** o kernel que sobe é o do build (a versão aparece no log de boot com o sufixo do projeto) e o DTB é o `rk3326-r36s-v5` compilado pelo build
