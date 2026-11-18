# Spec Delta

## MODIFIED Requirements

### Requirement: Vídeo no painel interno
O painel interno MUST mostrar imagem a 640x480 desde as mensagens do kernel, com aceleração GLES pelo driver mainline da GPU (Mali-400 com `lima` no GA36, Mali-G31 com `panfrost` no R36S) e brilho ajustável até o máximo do hardware, sem teto fixo (o limite seguro de cada aparelho é da capability `display-brightness`).

#### Scenario: Primeiras mensagens no painel
- **WHEN** o console é ligado
- **THEN** as mensagens do kernel aparecem no painel interno antes da inicialização dos serviços

#### Scenario: GPU disponível para o frontend
- **WHEN** o frontend inicia no console
- **THEN** ele usa renderização GLES acelerada pela GPU, e não renderização por software

#### Scenario: Brilho até o máximo
- **WHEN** o usuário sobe o brilho até o fim em qualquer console
- **THEN** a luz de fundo chega ao nível máximo do hardware

### Requirement: Controle integrado
O console MUST expor seus botões e direcionais como um único controle de jogo do Linux, com A, B, X, Y, L1, R1, L2, R2, Start, Select, direcional e os analógicos presentes no aparelho. Os analógicos MUST ser calibrados no início, pelo repouso lido no próprio aparelho, para que um stick solto fique no centro em qualquer unidade do mesmo modelo.

#### Scenario: Controle serial do GA36
- **WHEN** o GA36 termina o boot
- **THEN** o handshake com o microcontrolador dos analógicos foi concluído e os eixos dos dois analógicos variam ao mover os sticks

#### Scenario: Controle do R36S
- **WHEN** o R36S termina o boot
- **THEN** existe um único dispositivo de entrada de jogo chamado "R36S Gamepad", com os botões e os eixos dos dois analógicos, e o RetroArch o configura sozinho

#### Scenario: Stick solto no centro
- **WHEN** o console termina o boot com os sticks soltos
- **THEN** os eixos dos dois analógicos ficam no centro, dentro da zona morta

#### Scenario: Stick segurado no boot
- **WHEN** o usuário segura um analógico durante o boot
- **THEN** o console usa o centro de fábrica para esse eixo e registra o aviso no log

### Requirement: Áudio
Cada console MUST reproduzir som no alto-falante interno e na saída de fone, com volume ajustável pelos botões de volume do aparelho. Onde o hardware oferecer, o volume MUST ser o ganho analógico da saída ativa, com o volume digital em 0 dB (capability `audio-output`).

#### Scenario: Volume pelos botões
- **WHEN** o botão de aumentar volume é pressionado durante um jogo
- **THEN** o volume do sistema aumenta e o som continua saindo

#### Scenario: Volume analógico no GA36
- **WHEN** o botão de baixar volume é pressionado no GA36
- **THEN** o ganho analógico da saída cai e o volume digital continua em 0 dB

### Requirement: Bateria e desligamento
Cada console MUST informar o nível de bateria pela interface padrão de fonte de energia do Linux e cortar a energia de fato ao desligar. Segurar o botão de energia por 2 s MUST desligar o console pelo caminho limpo, e um toque curto MUST suspender (capability `system-sleep`).

#### Scenario: Desligar corta a energia
- **WHEN** o sistema executa o desligamento
- **THEN** a tela e a luz de fundo se apagam e o aparelho para de consumir energia, sem ficar travado com a tela acesa

#### Scenario: Leitura de bateria
- **WHEN** o nível de bateria é consultado em uso
- **THEN** o sistema informa uma porcentagem entre 0 e 100

#### Scenario: Desligar pelo botão segurado
- **WHEN** o usuário segura o botão de energia por 2 s
- **THEN** o pendente é gravado e o aparelho desliga como pelo item Desligar
