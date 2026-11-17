# Spec Delta

## ADDED Requirements

### Requirement: Cache sem gerações antigas do kernel
O cache MUST guardar uma árvore de código do kernel por versão do kernel e uma pasta de build por
arquitetura, e o build MUST apagar as árvores e pastas de build que não correspondem mais à versão
em uso.

#### Scenario: Patches mudam várias vezes
- **WHEN** os patches do kernel mudam e o build roda várias vezes
- **THEN** `.cache/` continua com uma só árvore do kernel e uma só pasta de build por arquitetura

#### Scenario: Cache com gerações antigas de antes desta mudança
- **WHEN** o primeiro build depois desta mudança encontra pastas `linux-<versão>-<hash>` e `kbuild/<console>-<hash>` antigas
- **THEN** ele as apaga e diz numa linha quanto espaço liberou
