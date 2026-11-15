## MODIFIED Requirements

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

## ADDED Requirements

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
