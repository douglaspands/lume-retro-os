# Spec Delta

## Purpose

Fazer de tudo o que o projeto compila um pacote `.apk` versionado pelas próprias entradas, para
o build reaproveitar o que já existe e para instalar ou atualizar uma parte sem refazer a imagem.

## ADDED Requirements

### Requirement: O que é compilado sai como pacote
O kernel e os módulos de cada console, os DTBs de cada SoC (nativos e convertidos) e as
ferramentas do initramfs MUST sair como pacotes `.apk` no repositório local do projeto, assinados
com a chave dos pacotes locais, e a imagem MUST tirar esses arquivos dos pacotes.

#### Scenario: Pacotes depois de um build
- **WHEN** `r36os build console` termina
- **THEN** `out/repo/aarch64/` e `out/repo/armv7/` têm o pacote do kernel e dos módulos do console, o dos DTBs do SoC e o das ferramentas do initramfs, e o índice do repositório os lista

#### Scenario: Mesmo conteúdo no cartão
- **WHEN** a imagem é gerada a partir dos pacotes
- **THEN** a `BOOT` e o `SYSTEM` têm os mesmos arquivos, nos mesmos caminhos, que a imagem gerada antes desta mudança

### Requirement: Versão do pacote pelas entradas
A versão de cada pacote compilado MUST mudar quando, e só quando, mudam as entradas dele (código-fonte
fixado, patches, configuração e scripts de build), e o build MUST reaproveitar o pacote já existente
com as mesmas entradas em vez de recompilar.

#### Scenario: Entradas sem mudança
- **WHEN** o build roda e o pacote do kernel do R36S com as entradas atuais já está no repositório
- **THEN** o build usa esse pacote e não recompila o kernel do R36S

#### Scenario: Entrada mudou
- **WHEN** o fragmento de kernel do GA36 muda
- **THEN** o pacote do kernel do GA36 ganha versão nova e o do R36S fica o mesmo

### Requirement: Versão automática dos pacotes locais
Os pacotes de `aports/` (inclusive o `lume-launcher`) MUST ganhar versão nova quando as entradas
deles mudam, sem subir o `pkgrel` à mão, e o log de boot do console MUST registrar a versão de
cada pacote do projeto instalado.

#### Scenario: Mudança no lume-launcher
- **WHEN** o código do `lume-launcher` muda e o build roda
- **THEN** o pacote sai com versão maior que a anterior, sem edição do `APKBUILD`, e o `hw/boot-<n>.txt` do console mostra essa versão depois do `push`

#### Scenario: Sem mudança
- **WHEN** nenhuma entrada do `lume-launcher` muda
- **THEN** o build reaproveita o pacote existente e a versão continua a mesma

### Requirement: Instalação de uma parte sem refazer a imagem
Um pacote compilado MUST poder ser instalado num console pelo cabo USB, ou extraído noutra
máquina, sem gerar a imagem inteira, e o console MUST registrar no log a versão instalada.

#### Scenario: Atualizar só o kernel de um console
- **WHEN** só o kernel do GA36 mudou e o usuário atualiza o console pelo cabo
- **THEN** só os arquivos do pacote do kernel do GA36 mudam no cartão, e o log do boot seguinte mostra a versão do pacote
