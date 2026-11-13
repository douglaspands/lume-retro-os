# Spec Delta

## ADDED Requirements

### Requirement: Configuração do RetroArch compartilhada entre consoles
A configuração do RetroArch persistida na `ROMS` MUST servir aos dois consoles. As chaves que dependem do aparelho MUST ser reaplicadas pelo console a cada início do frontend, de modo que um valor gravado num console nunca valha no outro. Toda chave fixada para um console MUST ter também um valor fixado para o outro.

#### Scenario: Taxa de atualização por console
- **WHEN** o RetroArch inicia no GA36, grava a configuração na `ROMS` e o cartão vai para o R36S
- **THEN** no R36S o `video_refresh_rate` em uso é o do painel do R36S, e ao voltar para o GA36 é de novo o do painel do GA36

#### Scenario: Escolhas do usuário passam entre consoles
- **WHEN** o usuário muda no GA36 uma opção que não depende do aparelho (o idioma do menu, por exemplo) e leva o cartão ao R36S
- **THEN** o R36S abre com a mesma escolha

#### Scenario: Chave fixada em só um console
- **WHEN** os arquivos de chaves fixas por console são conferidos pelos testes
- **THEN** o teste falha se uma chave estiver fixada para um console e não para o outro
