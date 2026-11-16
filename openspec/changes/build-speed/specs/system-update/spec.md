# Spec Delta

## Purpose

Atualizar um console pelo cabo mandando só os pedaços que mudaram, sem refazer nem descompactar a
imagem inteira, para o ciclo de uma mudança até o aparelho levar segundos.

## ADDED Requirements

### Requirement: Camadas separadas pelo ritmo de mudança
O sistema de cada console MUST ser dividido de modo que o que o projeto muda com frequência (o
`lume-launcher`, os scripts e serviços do projeto) fique numa camada separada da base do Alpine e
do RetroArch com os cores, e uma camada MUST mudar só quando os pacotes ou arquivos dela mudam.

#### Scenario: Só o launcher mudou
- **WHEN** só o `lume-launcher` muda e o build roda
- **THEN** só a camada do projeto daquele console muda de conteúdo, e a base e a camada do RetroArch saem iguais byte a byte

### Requirement: Push pontual
O `r36os push` MUST mandar ao console só os arquivos da `BOOT` cujo SHA256 difere do que está no
cartão, e MUST NOT descompactar a imagem do build para isso: ele compara com os arquivos e os
SHA256 que o build já registrou.

#### Scenario: Atualização só do launcher
- **WHEN** só a camada do projeto mudou e o usuário roda `r36os push`
- **THEN** só essa camada é enviada, a etapa de descompactar a imagem não existe, e o resumo do push mostra os bytes enviados e o tempo

#### Scenario: Nada mudou
- **WHEN** o cartão já tem os arquivos do build
- **THEN** o `push` termina sem enviar nada e sem reiniciar o console, dizendo que o console já está no build

### Requirement: Versões no console
O console MUST registrar no log de boot a versão de cada camada e de cada pacote do projeto, para
saber o que um `push` pontual trocou.

#### Scenario: Depois de um push pontual
- **WHEN** o console inicia depois de um push que trocou só a camada do projeto
- **THEN** o `hw/boot-<n>.txt` mostra a versão nova dessa camada e as mesmas versões de antes nas outras
