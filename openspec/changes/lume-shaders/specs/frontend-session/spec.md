# Spec Delta

## ADDED Requirements

### Requirement: Shaders do Lume no menu
A imagem MUST trazer os shaders do Lume para Game Boy, Game Boy Color e Game Boy Advance numa pasta `lume-shaders` dentro da pasta de shaders do sistema, e o RetroArch MUST abrir essa pasta de shaders ao carregar um shader pelo menu. Nenhum shader MUST ficar ligado por padrão.

#### Scenario: Escolher o shader de GBA no menu
- **WHEN** o usuário abre um jogo de GBA e vai em Shaders → Carregar
- **THEN** o menu abre na pasta de shaders do sistema, com `lume-shaders/` e dentro dela os presets de GB, GBC e GBA, e o preset de GBA carrega

#### Scenario: Sem shader de fábrica
- **WHEN** um cartão novo abre um jogo pela primeira vez
- **THEN** o jogo aparece sem shader, até o usuário escolher um
