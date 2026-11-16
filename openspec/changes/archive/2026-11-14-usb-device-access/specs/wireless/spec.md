# Spec Delta

## Purpose

Define o Wi-Fi e o Bluetooth dos consoles, que não têm rádio próprio: um dongle USB na porta
OTG (papel host), gerenciado por serviços do sistema que qualquer frontend usa (NetworkManager
e bluez) e configurado pelo frontend (hoje, o menu do RetroArch; o RetroArch deve deixar de
ser o frontend no futuro, P-44), sem expor serviços do console na rede sem fio.

## ADDED Requirements

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
Com o Wi-Fi conectado, nenhum serviço do console MUST aceitar conexões pela rede sem fio: os
comandos de rede do frontend (hoje, o UDP 55355 do RetroArch) MUST escutar só em
`127.0.0.1`, o SSH só na rede USB e o MTP só no cabo.

#### Scenario: Comandos do RetroArch
- **WHEN** outro aparelho da rede Wi-Fi manda `GET_STATUS` para a porta UDP 55355 do console
- **THEN** não há resposta, e o `logd` do próprio console continua recebendo a resposta por `127.0.0.1`
