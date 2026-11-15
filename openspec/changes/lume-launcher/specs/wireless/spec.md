## MODIFIED Requirements

### Requirement: Wi-Fi pelo frontend
O Wi-Fi MUST ser gerenciado por um serviço do sistema independente do frontend, que guarda as
redes conhecidas, e o frontend MUST ligar e desligar o Wi-Fi, listar as redes, conectar a uma
rede escolhida pelo usuário, pedindo a senha pelo teclado da tela, e esquecer uma rede salva
(o launcher, pelo serviço de Wi-Fi). Uma rede conhecida MUST voltar a conectar sozinha no boot
e quando o adaptador é ligado. A rede USB do cabo (`usb0`) MUST NOT ser gerenciada pelo
serviço de Wi-Fi.

#### Scenario: Conectar a uma rede
- **WHEN** o usuário escolhe uma rede no menu de Wi-Fi do frontend e digita a senha
- **THEN** o console obtém um endereço por DHCP nessa rede, e a conexão volta sozinha no boot seguinte

#### Scenario: Adaptador ligado depois do boot
- **WHEN** o adaptador Wi-Fi é ligado com o console já na tela do launcher e há uma rede conhecida por perto
- **THEN** o console conecta nessa rede sem o usuário abrir as Configurações

#### Scenario: Cabo USB e Wi-Fi juntos
- **WHEN** o console está com o Wi-Fi conectado e o cabo do PC na porta OTG
- **THEN** a rede USB continua com `10.55.0.1` e o PC continua com `10.55.0.2`

### Requirement: Bluetooth pelo frontend
O Bluetooth MUST ser gerenciado por um serviço do sistema independente do frontend, que
guarda os pareamentos, e o frontend MUST ligar e desligar o Bluetooth, procurar (só quando o
usuário pede), parear, conectar e esquecer aparelhos Bluetooth (fones, controles, teclados)
pelo menu (o launcher, pelo serviço de Bluetooth). Um aparelho pareado MUST voltar a conectar
sem novo pareamento.

#### Scenario: Parear um controle
- **WHEN** o usuário põe um controle Bluetooth em modo de pareamento e o escolhe no menu de Bluetooth do frontend
- **THEN** o controle é pareado, conectado e reconhecido como jogador seguinte ao do console

#### Scenario: Fone volta sozinho
- **WHEN** um fone já pareado é ligado perto do console com o Bluetooth ligado
- **THEN** o fone conecta sem novo pareamento

### Requirement: Nada do console exposto na rede sem fio
Com o Wi-Fi ou uma ligação Wi-Fi Direct conectados, nenhum serviço do console MUST aceitar
conexões pela rede sem fio: os comandos de rede do frontend (o UDP 55355 do RetroArch) MUST
escutar só em `127.0.0.1`, o SSH só na rede USB e o MTP só no cabo. A transmissão para a TV
MUST aceitar só a TV escolhida, e só enquanto transmite.

#### Scenario: Comandos do RetroArch
- **WHEN** outro aparelho da rede Wi-Fi manda `GET_STATUS` para a porta UDP 55355 do console
- **THEN** não há resposta, e o `logd` do próprio console continua recebendo a resposta por `127.0.0.1`

#### Scenario: Outro console ligado
- **WHEN** dois consoles estão ligados por Wi-Fi Direct e um deles tenta abrir conexões nas portas do outro
- **THEN** nenhuma porta do outro console aceita a conexão

## ADDED Requirements

### Requirement: Som no fone Bluetooth
Com um fone Bluetooth conectado, o som do launcher e dos jogos MUST sair no fone, e MUST
voltar ao alto-falante do console quando o fone desconecta, sem reiniciar o jogo. Os botões de
volume MUST controlar o volume do fone enquanto ele está conectado.

#### Scenario: Fone conectado durante o jogo
- **WHEN** um jogo está rodando e o fone pareado conecta
- **THEN** o som do jogo passa para o fone e o alto-falante fica mudo

#### Scenario: Fone desconecta
- **WHEN** o fone desliga durante o jogo
- **THEN** o som volta ao alto-falante e o jogo continua

### Requirement: Ligação Wi-Fi Direct entre consoles
Dois consoles com adaptador Wi-Fi que aceite Wi-Fi Direct MUST conseguir se ligar diretamente,
sem roteador, com aceite no console convidado, e cada um MUST se mostrar ao outro pelo nome do
console. A ligação MUST NOT desfazer a rede USB do cabo.

#### Scenario: Convite aceito
- **WHEN** o console A está visível e o console B o convida
- **THEN** A pede confirmação e, aceito, os dois ficam com um endereço na mesma ligação

#### Scenario: Convite recusado
- **WHEN** o console A recusa o convite
- **THEN** nenhum dos dois fica ligado e B mostra que o convite foi recusado

### Requirement: Miracast como fonte
Se a prova de viabilidade passar, o console MUST transmitir a tela e o som para uma TV ou um
adaptador Miracast escolhido pelo usuário, por Wi-Fi Direct, com o jogo continuando jogável no
console. A prova MUST registrar o custo de CPU e o atraso medidos nos dois consoles; se
reprovar, este requisito sai do change e volta ao P-52 com as medidas.

#### Scenario: Transmissão com jogo
- **WHEN** o console transmite para uma TV e um jogo de NES está rodando
- **THEN** a TV mostra o jogo com som e o jogo no console mantém a velocidade normal
