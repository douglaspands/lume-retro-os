# Spec Delta

## Purpose

Fazer de tudo o que o projeto entrega um fragmento: um pacote `.apk` por arquitetura ou noarch,
versionado pelo próprio conteúdo, compilado sozinho e instalável sem refazer a imagem.

## ADDED Requirements

### Requirement: Tudo o que o projeto entrega é um fragmento
O kernel, os módulos, os DTBs, os pacotes de `aports/` e os arquivos que hoje vêm de
`rootfs/overlay/` MUST sair como pacotes `.apk` no repositório local de cada arquitetura,
assinados com a chave dos pacotes locais, e o sistema do console MUST ser montado só a partir de
pacotes.

#### Scenario: Pacotes depois de um build
- **WHEN** `r36os build console` termina
- **THEN** `out/repo/armv7/` e `out/repo/aarch64/` têm `lume-kernel`, `lume-modules`, `lume-dtbs` e os fragmentos do projeto, e os índices os listam

#### Scenario: Mesmo conteúdo no cartão
- **WHEN** a imagem é gerada a partir dos fragmentos
- **THEN** o sistema montado de cada console tem os mesmos arquivos, nos mesmos caminhos e com o mesmo conteúdo, que a imagem gerada antes desta mudança, exceto os metadados do `apk`

### Requirement: Binário por arquitetura, resto noarch
Um fragmento com binário ELF MUST ser publicado por arquitetura, com o mesmo nome nas duas; um
fragmento sem ELF MUST ser noarch, montado uma vez e publicado igual em todas as arquiteturas. O
build MUST falhar se um fragmento noarch contiver ELF.

#### Scenario: Script do projeto
- **WHEN** um fragmento noarch (por exemplo `lume-usb`) é montado
- **THEN** o mesmo arquivo `.apk`, com o mesmo SHA256, está em `out/repo/armv7/` e em `out/repo/aarch64/`, e foi montado sem emulação

#### Scenario: ELF num fragmento noarch
- **WHEN** um fragmento noarch passa a conter um executável ELF
- **THEN** o build falha nomeando o fragmento e o arquivo

### Requirement: Versão pelo conteúdo
A versão de um fragmento MUST subir quando, e só quando, o conteúdo do pacote muda, sem edição
manual do `pkgrel`; o build MUST reaproveitar o pacote existente quando as entradas não mudaram,
sem compilar.

#### Scenario: Entradas sem mudança
- **WHEN** o build roda e as entradas do `lume-launcher` não mudaram
- **THEN** o build não compila o `lume-launcher` e a versão continua a mesma

#### Scenario: Entradas mudaram, conteúdo igual
- **WHEN** um patch que só afeta o kernel armv7 muda
- **THEN** o `lume-kernel` do aarch64 é recompilado incrementalmente, sai com o mesmo conteúdo e mantém a versão

#### Scenario: Mudança no launcher
- **WHEN** o código do `lume-launcher` muda e o build roda
- **THEN** o pacote sai com versão maior que a anterior, sem edição do `APKBUILD`

### Requirement: Versões dos fragmentos no console
O log de boot do console MUST registrar a versão de cada fragmento do projeto instalado.

#### Scenario: Depois de um push
- **WHEN** o console inicia depois de um `push` que trocou um fragmento
- **THEN** o `hw/boot-<n>.txt` mostra a versão nova desse fragmento e as mesmas versões de antes nos outros
