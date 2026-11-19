# Spec Delta

## ADDED Requirements

### Requirement: Core único do SNES
O Super Nintendo MUST ter um único core, o `snes9x2005_plus` (Snes9x 1.43 com o APU blargg), padrão em todas as arquiteturas e em todos os consoles, compilado com as opções padrão do upstream, sem flags otimizadas por CPU. O catálogo MUST NOT listar outro core de SNES, nem como alternativo nem por arquitetura.

#### Scenario: Mesmo core nos dois consoles
- **WHEN** o mesmo jogo de SNES é aberto no GA36 e depois no R36S, com o mesmo cartão
- **THEN** os dois abrem no `snes9x2005_plus`, e o `events.log` de cada um registra esse core

#### Scenario: Catálogo sem alternativo
- **WHEN** o catálogo de sistemas é lido
- **THEN** o SNES tem `snes9x2005_plus` como core padrão, nenhum core alternativo e nenhuma troca por arquitetura
