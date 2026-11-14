# usb-otg Specification

## Purpose

Define a porta OTG dos consoles: como o papel da porta (host ou device) é escolhido e o que
um PC ligado a ela pode fazer: acesso aos arquivos e acesso root, os dois sem senha e só pelo
cabo.

## Requirements

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

### Requirement: Acesso root sem senha, só pelo cabo
No papel device, o console MUST oferecer uma rede USB com um servidor SSH que aceita login de
root sem senha e sem chave, em todo cartão, sem configuração no PC nem no cartão. O servidor
SSH MUST NOT escutar em outra interface além da rede USB e MUST NOT permitir encaminhamento
de portas nem de agente.

#### Scenario: Root pelo cabo
- **WHEN** o PC, ligado à porta OTG, abre `ssh root@<endereço do console>` pela rede USB
- **THEN** o login é aceito sem pedir senha nem chave e o `events.log` registra `usb OK ssh: login accepted: … for 'root' from <endereço>`

#### Scenario: Login recusado
- **WHEN** uma conexão termina antes de autenticar (por exemplo, outro usuário que não o root)
- **THEN** o `events.log` registra `usb FAIL ssh: login refused: from <endereço>…`

#### Scenario: Nenhuma outra interface
- **WHEN** o console tem outra interface de rede ativa
- **THEN** o servidor SSH não aceita conexões por ela

### Requirement: Endereços fixos da rede USB
A rede USB MUST usar endereços fixos e iguais nos dois consoles, conhecidos pelo PC sem
descoberta, e MUST NOT oferecer rota para outras redes nem encaminhamento de pacotes.

#### Scenario: PC configura a rede sozinho
- **WHEN** o cabo é conectado a um PC Linux com NetworkManager
- **THEN** o PC recebe um endereço na rede USB e alcança o console pelo endereço fixo documentado

### Requirement: Papel host com adaptador OTG
Com um adaptador OTG na porta (pino ID em nível baixo), a porta MUST assumir o papel host e
MUST fornecer os 5 V da porta, nos dois consoles. Sem o adaptador, os 5 V MUST ficar
desligados.

#### Scenario: Pendrive no adaptador
- **WHEN** um pendrive com uma partição `vfat`, `exfat` ou `ext4` é ligado ao adaptador OTG
- **THEN** a partição é montada em `/storage/usb/<rótulo ou sdXN>`, com leitura e escrita para o frontend, e o `events.log` registra `usb OK storage: mounted …`

#### Scenario: Pendrive retirado
- **WHEN** o pendrive é retirado
- **THEN** o ponto de montagem é liberado e o `events.log` registra `usb OK storage: removed …`

#### Scenario: Controle USB como jogador 2
- **WHEN** um controle USB (genérico, Xbox, PlayStation, Nintendo ou 8BitDo) é ligado ao adaptador com o RetroArch aberto
- **THEN** o RetroArch o reconhece e o atribui à porta seguinte, e o controle do console continua como jogador 1

#### Scenario: Teclado e mouse
- **WHEN** um teclado ou um mouse USB é ligado ao adaptador
- **THEN** o RetroArch passa a recebê-los (teclado no menu e nos cores; mouse no menu)

### Requirement: Funções iguais nos dois consoles
O GA36 e o R36S MUST expor as mesmas funções USB, com o mesmo nome de dispositivo e os mesmos
endereços, de modo que o PC use os mesmos comandos nos dois. O nome do dispositivo MUST
identificar o console (`GA36` ou `R36S`).

#### Scenario: Mesmo comando nos dois consoles
- **WHEN** o mesmo cartão é usado no GA36 e depois no R36S, ligados ao PC pela porta OTG
- **THEN** os dois aparecem por MTP e aceitam `ssh` no mesmo endereço, cada um com o nome do seu console
