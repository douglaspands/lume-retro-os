# Spec Delta

## Purpose

Define a porta OTG dos consoles: como o papel da porta (host ou device) é escolhido e o que
um PC ligado a ela pode fazer, com acesso aos arquivos para qualquer usuário e acesso root
só com chave.

## ADDED Requirements

### Requirement: Papel da porta OTG
Em cada console, a porta marcada OTG MUST assumir o papel **device** quando um PC está ligado
nela e MUST NOT assumir esse papel só porque um carregador está ligado na porta de carga. A
detecção MUST ser a mesma que o papel host usará (P-38). Um adaptador OTG MUST NOT ativar o
papel device.

#### Scenario: PC ligado na porta OTG
- **WHEN** o console está ligado e um cabo do PC é conectado à porta OTG
- **THEN** a porta passa ao papel device em até 5 s e o `events.log` registra `usb OK device: connected`

#### Scenario: Carregador na porta de carga
- **WHEN** só um carregador está ligado na porta de carga (DC)
- **THEN** a porta OTG não entra no papel device e nenhuma função USB aparece

#### Scenario: Cabo do PC desconectado
- **WHEN** o cabo do PC é retirado da porta OTG
- **THEN** as funções do papel device são encerradas e o `events.log` registra `usb OK device: disconnected`

### Requirement: Arquivos da ROMS pelo cabo
No papel device, o console MUST expor ao PC, por MTP, o conteúdo da `ROMS` (jogos, BIOS,
saves, `logs/` e `system/`), para leitura e escrita, sem senha e sem parar o frontend. A
`BOOT` MUST NOT ser exposta por essa função.

#### Scenario: Copiar um jogo com o RetroArch aberto
- **WHEN** o usuário copia um arquivo do PC para a pasta de um sistema em `ROMS/roms/` com o RetroArch no menu
- **THEN** o arquivo aparece no cartão com o mesmo conteúdo e o RetroArch continua rodando

#### Scenario: Ler os logs pelo PC
- **WHEN** o usuário abre o console no gerenciador de arquivos do PC
- **THEN** a pasta `logs/` da `ROMS` aparece com os logs do boot atual já gravados

#### Scenario: A BOOT não aparece
- **WHEN** o usuário lista o que o console expõe por MTP
- **THEN** só o conteúdo da `ROMS` aparece, sem a `BOOT` nem o `SYSTEM`

### Requirement: Acesso root só com chave
No papel device, o console MUST oferecer uma rede USB com um servidor SSH que aceita login de
root **só** por chave pública listada em `BOOT/ssh/authorized_keys`. Login por senha MUST
ser recusado, e o servidor SSH MUST NOT escutar em outra interface além da rede USB.

#### Scenario: PC com a chave
- **WHEN** o cartão tem `BOOT/ssh/authorized_keys` com a chave do PC e o PC abre `ssh root@<endereço do console>` pela rede USB
- **THEN** o login é aceito sem senha e o `events.log` registra `usb OK ssh: root login from <endereço>`

#### Scenario: Cartão sem chave
- **WHEN** o cartão não tem `BOOT/ssh/authorized_keys`
- **THEN** o servidor SSH não é iniciado, a função de arquivos continua disponível e o `events.log` registra `usb OK ssh: disabled (no authorized_keys)`

#### Scenario: Chave desconhecida ou senha
- **WHEN** o PC tenta entrar com uma chave fora da lista ou com senha
- **THEN** o login é recusado e o `events.log` registra `usb FAIL ssh: login refused from <endereço>`

### Requirement: Endereços fixos da rede USB
A rede USB MUST usar endereços fixos e iguais nos dois consoles, conhecidos pelo PC sem
descoberta, e MUST NOT oferecer rota para outras redes nem encaminhamento de pacotes.

#### Scenario: PC configura a rede sozinho
- **WHEN** o cabo é conectado a um PC Linux com NetworkManager
- **THEN** o PC recebe um endereço na rede USB e alcança o console pelo endereço fixo documentado

### Requirement: Funções iguais nos dois consoles
O GA36 e o R36S MUST expor as mesmas funções USB, com o mesmo nome de dispositivo e os mesmos
endereços, de modo que o PC use os mesmos comandos nos dois. O nome do dispositivo MUST
identificar o console (`GA36` ou `R36S`).

#### Scenario: Mesmo comando nos dois consoles
- **WHEN** o mesmo cartão é usado no GA36 e depois no R36S, ligados ao PC pela porta OTG
- **THEN** os dois aparecem por MTP e aceitam `ssh` no mesmo endereço, cada um com o nome do seu console
