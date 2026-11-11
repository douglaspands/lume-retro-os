# vm-validation Specification

## Purpose

Garante que toda build possa ser validada numa VM x86_64 local antes de ir para um console, com o mesmo layout de cartão, o mesmo fluxo de boot e o mesmo userland.

## Requirements

### Requirement: VM equivalente aos consoles
A imagem `vm` MUST usar o mesmo layout da `BOOT` e da `ROMS`, o mesmo fluxo de boot (initramfs, `SYSTEM`, camada em RAM, criação da `ROMS`), os mesmos serviços, os mesmos cores e a mesma configuração do RetroArch do console. Só kernel, bootloader (e a área reservada a ele antes da `BOOT`) e drivers (incluindo o Mesa com virgl da VM) MUST mudar.

#### Scenario: Diferenças restritas ao hardware
- **WHEN** os manifestos das imagens `vm` e `ga36` do mesmo build são comparados
- **THEN** as diferenças se limitam a pacotes da camada de hardware e à arquitetura

### Requirement: Execução local da VM
O projeto MUST oferecer um comando que roda a imagem `vm` localmente, em janela com aceleração 3D virtual e áudio, na resolução 640x480 dos consoles, com teclado e controle USB do PC como entrada.

#### Scenario: Rodar a VM em janela
- **WHEN** o comando de VM é executado numa sessão gráfica do PC
- **THEN** abre uma janela de 640x480 mostrando o boot verboso e, ao final, o menu do RetroArch

#### Scenario: Teclado como controle
- **WHEN** o usuário usa as setas e as teclas mapeadas na janela da VM
- **THEN** o RetroArch responde como se fosse o controle integrado do console

#### Scenario: Controle do PC
- **WHEN** há um controle USB conectado ao PC que o usuário pode capturar
- **THEN** ele é repassado à VM sem configuração e navega o RetroArch

### Requirement: Jogos do PC na VM
O comando de VM MUST aceitar uma pasta de jogos do PC e mostrá-la à VM somente leitura, sem copiar os arquivos para o disco da VM.

#### Scenario: Pasta de ROMs do PC
- **WHEN** a VM é iniciada com uma pasta do PC que contém as pastas dos sistemas
- **THEN** os jogos aparecem nas listas do RetroArch e nenhum arquivo dessa pasta é alterado pela VM

### Requirement: Rodar sem tela
O comando de VM MUST ter um modo sem janela, que mostra o console serial no terminal, para uso em testes automatizados e em máquinas sem sessão gráfica.

#### Scenario: Modo sem janela
- **WHEN** o comando de VM é executado no modo sem janela
- **THEN** as mensagens do kernel e dos serviços aparecem no terminal pela serial

### Requirement: Teste automatizado de aceitação
O projeto MUST ter um teste automatizado que, a partir de uma imagem `vm` recém-gerada, verifica no mínimo: criação da `ROMS` no primeiro boot, presença do resumo de hardware, início do frontend, abertura de um jogo de teste com cada core instalado, persistência de uma opção após reboot, perda de escrita fora da persistência e o desligamento ao sair.

#### Scenario: Build aprovada
- **WHEN** o teste de aceitação roda sobre uma imagem `vm` correta
- **THEN** todas as verificações passam e o teste termina com sucesso, informando o tempo de boot até o frontend

#### Scenario: Build com defeito
- **WHEN** alguma verificação falha
- **THEN** o teste termina com erro, nomeia a verificação que falhou e guarda o log serial completo da VM

### Requirement: Conteúdo de teste livre
Os jogos usados no teste MUST ter licença que permita redistribuição, ou ser gerados pelo próprio build, e MUST NOT ir para as imagens dos consoles.

#### Scenario: Imagem de console sem conteúdo de teste
- **WHEN** a partição `BOOT` e o `SYSTEM` da imagem `ga36` são inspecionados
- **THEN** não contêm nenhum jogo de teste

### Requirement: Validação antes de liberar uma build de console
Uma build de console MUST ser liberada apenas se o teste de aceitação da imagem `vm` do mesmo build tiver passado.

#### Scenario: VM reprovada bloqueia o console
- **WHEN** o teste de aceitação da VM falha num build
- **THEN** a imagem `ga36` desse build não é marcada como liberada
