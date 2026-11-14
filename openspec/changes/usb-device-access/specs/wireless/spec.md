# Spec Delta

## Purpose

Define o Wi-Fi e o Bluetooth dos consoles, que não têm rádio próprio: um dongle USB na porta
OTG (papel host), configurado pelo menu do RetroArch, sem expor serviços do console na rede
sem fio.

## ADDED Requirements

### Requirement: Dongles suportados
Os dois consoles MUST reconhecer, pela porta OTG com adaptador, os dongles Wi-Fi Realtek do
driver `rtw88` (inclusive o RTL8821CU, `0bda:c820`), os da família `rtl8xxxu` e os Atheros do
`ath9k_htc`, e o Bluetooth USB do `btusb` (inclusive o do RTL8821CU), com o firmware desses
chips na imagem. Dongles fora dessa lista MAY não funcionar.

#### Scenario: RTL8821CU ligado
- **WHEN** um dongle RTL8821CU é ligado ao adaptador OTG
- **THEN** aparecem uma interface Wi-Fi e um controlador Bluetooth, sem erro de firmware no log do kernel

### Requirement: Wi-Fi pelo menu do RetroArch
O RetroArch MUST listar as redes Wi-Fi e conectar a uma rede escolhida no menu, pedindo a
senha pelo teclado da tela. A rede USB do cabo (`usb0`) MUST NOT ser gerenciada pelo serviço
de Wi-Fi.

#### Scenario: Conectar a uma rede
- **WHEN** o usuário escolhe uma rede no menu de Wi-Fi do RetroArch e digita a senha
- **THEN** o console obtém um endereço por DHCP nessa rede, e a conexão volta sozinha no boot seguinte

#### Scenario: Cabo USB e Wi-Fi juntos
- **WHEN** o console está com o Wi-Fi conectado e o cabo do PC na porta OTG
- **THEN** a rede USB continua com `10.55.0.1` e o PC continua com `10.55.0.2`

### Requirement: Bluetooth pelo menu do RetroArch
O RetroArch MUST procurar, parear e conectar aparelhos Bluetooth (controles, teclados) pelo
menu, e um controle pareado MUST voltar a conectar sem novo pareamento.

#### Scenario: Parear um controle
- **WHEN** o usuário põe um controle Bluetooth em modo de pareamento e o escolhe no menu de Bluetooth do RetroArch
- **THEN** o controle é pareado, conectado e reconhecido como jogador seguinte ao do console

### Requirement: Nada do console exposto na rede sem fio
Com o Wi-Fi conectado, nenhum serviço do console MUST aceitar conexões pela rede sem fio: os
comandos de rede do RetroArch (UDP 55355) MUST escutar só em `127.0.0.1`, o SSH só na rede
USB e o MTP só no cabo.

#### Scenario: Comandos do RetroArch
- **WHEN** outro aparelho da rede Wi-Fi manda `GET_STATUS` para a porta UDP 55355 do console
- **THEN** não há resposta, e o `logd` do próprio console continua recebendo a resposta por `127.0.0.1`
