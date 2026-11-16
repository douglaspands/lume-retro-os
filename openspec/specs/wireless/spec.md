# wireless Specification

## Purpose

Define o Wi-Fi e o Bluetooth dos consoles, que não têm rádio próprio: um dongle USB na porta
OTG (papel host), gerenciado por serviços do sistema que qualquer frontend usa (NetworkManager
e bluez) e configurado pelo frontend (hoje, o menu do RetroArch; o RetroArch deve deixar de
ser o frontend no futuro, P-44), sem expor serviços do console na rede sem fio.

## Requirements

### Requirement: Dongles suportados
Os dois consoles MUST reconhecer, pela porta OTG com adaptador, os dongles Wi-Fi Realtek do
driver `rtw88` (inclusive o RTL8821CU, `0bda:c820`), os da família `rtl8xxxu` e os Atheros do
`ath9k_htc`, e o Bluetooth USB do `btusb` (inclusive o do RTL8821CU), com o firmware desses
chips na imagem. Dongles fora dessa lista MAY não funcionar.

#### Scenario: RTL8821CU ligado
- **WHEN** um dongle RTL8821CU é ligado ao adaptador OTG
- **THEN** aparecem uma interface Wi-Fi e um controlador Bluetooth, sem erro de firmware no log do kernel

### Requirement: Wi-Fi pelo frontend
O Wi-Fi MUST ser gerenciado por um serviço do sistema independente do frontend, que guarda as
redes conhecidas, e o frontend MUST listar as redes e conectar a uma rede escolhida pelo
usuário, pedindo a senha pelo teclado da tela (hoje, o menu do RetroArch pelo `nmcli`). A
rede USB do cabo (`usb0`) MUST NOT ser gerenciada pelo serviço de Wi-Fi.

#### Scenario: Conectar a uma rede
- **WHEN** o usuário escolhe uma rede no menu de Wi-Fi do frontend e digita a senha
- **THEN** o console obtém um endereço por DHCP nessa rede, e a conexão volta sozinha no boot seguinte

#### Scenario: Cabo USB e Wi-Fi juntos
- **WHEN** o console está com o Wi-Fi conectado e o cabo do PC na porta OTG
- **THEN** a rede USB continua com `10.55.0.1` e o PC continua com `10.55.0.2`

### Requirement: Bluetooth pelo frontend
O Bluetooth MUST ser gerenciado por um serviço do sistema independente do frontend, que
guarda os pareamentos, e o frontend MUST procurar, parear e conectar aparelhos Bluetooth
(controles, teclados) pelo menu (hoje, o menu do RetroArch pelo `bluetoothctl`). Um controle
pareado MUST voltar a conectar sem novo pareamento.

#### Scenario: Parear um controle
- **WHEN** o usuário põe um controle Bluetooth em modo de pareamento e o escolhe no menu de Bluetooth do frontend
- **THEN** o controle é pareado, conectado e reconhecido como jogador seguinte ao do console

### Requirement: Nada do console exposto na rede sem fio
Com o Wi-Fi ou uma ligação Wi-Fi Direct conectados, nenhum serviço do console MUST aceitar
conexões pela rede sem fio: os comandos de rede do frontend (o UDP 55355 do RetroArch) MUST
escutar só em `127.0.0.1`, o SSH só na rede USB e o MTP só no cabo. A transmissão para a TV
MUST aceitar só a TV escolhida, e só enquanto transmite. A única exceção é o SSH pela rede
Wi-Fi, ligado pelo usuário, com o código mostrado na tela do console ou uma chave do cartão
(requisito "SSH pela rede Wi-Fi"); ele MUST NOT escutar na ligação Wi-Fi Direct.

#### Scenario: Comandos do RetroArch
- **WHEN** outro aparelho da rede Wi-Fi manda `GET_STATUS` para a porta UDP 55355 do console
- **THEN** não há resposta, e o `logd` do próprio console continua recebendo a resposta por `127.0.0.1`

#### Scenario: SSH pela rede só no endereço do Wi-Fi
- **WHEN** o SSH pela rede está ligado e outro aparelho tenta a porta 22 por uma ligação Wi-Fi Direct
- **THEN** a conexão é recusada, e pelo endereço da rede Wi-Fi ela só entra com o código da tela ou uma chave do cartão

### Requirement: SSH pela rede Wi-Fi
O usuário MUST poder ligar o SSH pela rede Wi-Fi nas Configurações, desligado de fábrica e
salvo entre boots. Ligado, o console MUST mostrar na tela o comando e um código, que é a
senha; o código MUST ficar o mesmo, também depois do boot, até o usuário pedir outro nas
Configurações. A senha vazia do root MUST NOT valer pela rede. O serviço MUST escutar só no endereço da rede
Wi-Fi conectada e parar quando o Wi-Fi cai ou a opção é desligada.

#### Scenario: Entrar com o código da tela
- **WHEN** o usuário liga "SSH pela rede" com o Wi-Fi conectado e digita no PC o comando e o código mostrados no painel
- **THEN** ele entra no console, e o mesmo código continua valendo nas próximas vezes, também depois do boot

#### Scenario: Novo código pedido pelo usuário
- **WHEN** o usuário escolhe "Gerar novo código" no painel do Wi-Fi
- **THEN** o painel mostra outro código, e o antigo não entra mais

#### Scenario: Root sem senha pela rede
- **WHEN** alguém tenta `ssh root@<endereço do Wi-Fi>` com a senha vazia
- **THEN** a entrada é recusada

#### Scenario: Chave do cartão (avançado)
- **WHEN** há uma chave pública em `system/ssh/authorized_keys` no cartão e o SSH pela rede está ligado
- **THEN** quem tem a chave entra sem o código

#### Scenario: Troca de endereço e queda do Wi-Fi
- **WHEN** o roteador dá outro endereço ao console, ou o Wi-Fi desconecta
- **THEN** o SSH passa a escutar no endereço novo, ou deixa de escutar

#### Scenario: Cabo USB sem mudança
- **WHEN** o SSH pela rede está desligado e o cabo do PC está ligado
- **THEN** o SSH do cabo continua como root sem senha, só em `10.55.0.1`

#### Scenario: Desligado de fábrica
- **WHEN** um cartão novo conecta no Wi-Fi
- **THEN** a porta 22 do endereço Wi-Fi não aceita conexão
