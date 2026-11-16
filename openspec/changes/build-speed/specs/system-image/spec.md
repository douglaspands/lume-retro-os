# Spec Delta

## MODIFIED Requirements

### Requirement: Sistema como arquivo squashfs
O sistema de arquivos raiz de cada sistema MUST ser entregue como arquivos squashfs dentro da `BOOT`. Na `vm`, ele MUST ser um único arquivo `SYSTEM` de no máximo 768 MiB. Na `console`, o sistema de cada console MUST ser um conjunto de slots em `<console>/slots/`, com nomes pelo conteúdo, descrito pelo manifesto `<console>/SLOTS` (ver `system-update`); a soma dos slots de um console MUST ter no máximo 448 MiB, e a soma de todos os arquivos da `BOOT`, contando o conjunto anterior que o `push` guarda, MUST deixar ao menos 64 MiB livres.

#### Scenario: SYSTEM dentro do limite
- **WHEN** uma imagem é gerada
- **THEN** cada slot é um squashfs válido, a soma dos slots de cada console está dentro do limite, a `BOOT` da `console` tem ao menos 64 MiB livres, e o build falha se algum limite for ultrapassado

#### Scenario: Slots montados no boot
- **WHEN** um console inicia
- **THEN** a raiz do sistema mostra o conteúdo dos slots do boot daquele console, o de cima prevalecendo, e o log do boot lista cada slot montado com a versão dele

#### Scenario: Cartão antigo com SYSTEM único
- **WHEN** um console inicia com uma `BOOT` sem `<console>/SLOTS` e com `<console>/SYSTEM`
- **THEN** o boot monta o `SYSTEM` como antes
