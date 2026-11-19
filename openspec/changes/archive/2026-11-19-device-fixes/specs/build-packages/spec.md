# Spec Delta

## MODIFIED Requirements

### Requirement: Tudo o que o projeto entrega é um fragmento
O kernel, os módulos, os DTBs, os pacotes de `aports/` e os arquivos que hoje vêm de
`rootfs/overlay/` MUST sair como pacotes `.apk` no repositório local de cada arquitetura,
assinados com a chave dos pacotes locais, e o sistema do console MUST ser montado só a partir de
pacotes.

#### Scenario: Pacotes depois de um build
- **WHEN** `lume build console` termina
- **THEN** `out/repo/armv7/` e `out/repo/aarch64/` têm `lume-kernel`, `lume-modules`, `lume-dtbs` e os fragmentos do projeto, e os índices os listam

#### Scenario: Mesmo conteúdo no cartão
- **WHEN** a imagem é gerada a partir dos fragmentos
- **THEN** o sistema montado de cada console tem os mesmos arquivos, nos mesmos caminhos e com o mesmo conteúdo, que a imagem gerada antes desta mudança, exceto os metadados do `apk`
