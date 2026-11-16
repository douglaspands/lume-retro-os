# Spec Delta

## MODIFIED Requirements

### Requirement: Sistema como arquivo squashfs
O sistema de arquivos raiz de cada sistema MUST ser entregue como arquivos squashfs dentro da `BOOT`. Na `vm`, ele MUST ser um único arquivo `SYSTEM` de no máximo 768 MiB. Na `console`, o sistema de cada console MUST ser dividido em camadas (`<console>/SYSTEM` com a base e as camadas que mudam com mais frequência em arquivos próprios na mesma pasta), montadas umas sobre as outras no boot; a soma das camadas de um console MUST ter no máximo 448 MiB, e a soma de todos os arquivos da `BOOT` MUST deixar ao menos 64 MiB livres.

#### Scenario: SYSTEM dentro do limite
- **WHEN** uma imagem é gerada
- **THEN** cada camada é um squashfs válido, a soma das camadas de cada console está dentro do limite, a `BOOT` da `console` tem ao menos 64 MiB livres, e o build falha se algum limite for ultrapassado

#### Scenario: Camadas montadas no boot
- **WHEN** um console inicia
- **THEN** a raiz do sistema mostra o conteúdo de todas as camadas daquele console, a camada de cima prevalecendo, e o log do boot lista cada camada montada com a versão dela
