# Spec Delta

## MODIFIED Requirements

### Requirement: Consoles e variantes suportados
Esta versão MUST suportar o GA36-MB V1.2 (Allwinner A33) com as duas variantes de painel JD9366 (1 e 2) e o R36S "V5" (Rockchip RK3326) com o painel da família Sitronix ST7703 desta revisão. Outros consoles e revisões, inclusive outras revisões do R36S, MUST NOT ser anunciados como suportados (pendência P-16).

#### Scenario: Variantes na imagem
- **WHEN** a imagem `console` é inspecionada
- **THEN** a imagem de boot do painel 1 do GA36 está no setor 172032 (a variante padrão), as imagens de boot dos dois painéis do GA36 estão em `BOOT/ga36/android-boot/` e o DTB do R36S V5 está em `BOOT/r36s/`

### Requirement: Kernel mainline
O console MUST usar um kernel Linux mainline da série LTS, com device trees escritos para esse kernel. Device trees de kernels de fabricante MUST NOT ser gravados na imagem.

#### Scenario: Origem dos DTBs
- **WHEN** os DTBs da `BOOT` e os anexados às imagens de boot do GA36 são inspecionados
- **THEN** todos foram compilados pelo build a partir dos fontes do repositório, para o kernel do próprio console, e nenhum DTB do cartão de fábrica do R36S está na imagem

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

### Requirement: Serial de debug
O console MUST mandar as mensagens do bootloader e do kernel para sua serial de debug, numa única velocidade do início ao fim: 115200 baud no GA36 e 1500000 baud no R36S, a velocidade do bootloader de fábrica do R36S.

#### Scenario: Console serial
- **WHEN** um adaptador serial na velocidade do console é ligado à serial de debug e o console é ligado
- **THEN** as mensagens do bootloader e do kernel aparecem no adaptador sem trocar de velocidade

## ADDED Requirements

### Requirement: Bootloader de fábrica do R36S
O R36S MUST iniciar pela cadeia de boot do próprio aparelho (`idbloader`, `uboot.img` e `trust.img` do cartão original), que lê o `boot.ini` da `BOOT` e carrega o kernel e o DTB do Lume. Nenhum kernel, DTB ou initramfs do cartão de fábrica MUST ser usado.

#### Scenario: Kernel do Lume no R36S
- **WHEN** o R36S é ligado com um cartão da imagem `console`
- **THEN** o kernel que sobe é o do build (a versão aparece no log de boot com o sufixo do projeto) e o DTB é o `rk3326-r36s-v5` compilado pelo build
