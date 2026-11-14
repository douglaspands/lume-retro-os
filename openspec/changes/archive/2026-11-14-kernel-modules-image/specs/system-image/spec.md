# Spec Delta

## ADDED Requirements

### Requirement: Módulos do kernel fora do SYSTEM no console
Na imagem `console`, os módulos do kernel de cada console MUST ficar num arquivo squashfs próprio da `BOOT`, `<console>/modules` (`ga36/modules`, `r36s/modules`), com os módulos só do kernel daquele console, e o `SYSTEM` do console MUST NOT conter módulos do kernel. Os dois builds da mesma revisão MUST gerar o mesmo arquivo de módulos. A imagem `vm` fica como está.

#### Scenario: Arquivo de módulos na BOOT
- **WHEN** a `BOOT` de uma imagem `console` é listada
- **THEN** existem `ga36/modules` e `r36s/modules`, cada um um squashfs com uma única pasta de versão igual ao `release` do kernel do seu console, e nenhum dos dois `SYSTEM` tem arquivos em `/lib/modules`

#### Scenario: Mudança só no kernel
- **WHEN** dois builds diferem só no kernel de um console (patch ou configuração)
- **THEN** o `SYSTEM` dos dois consoles tem o mesmo SHA256 nos dois builds, e só o kernel, a imagem de módulos e, no GA36, as imagens de boot dos painéis daquele console mudam

#### Scenario: Atualização pelo cabo de um kernel novo
- **WHEN** o `r36os push` envia um build que só mudou o kernel do console ligado
- **THEN** ele manda o kernel, a imagem de módulos e o `VERSION` (e, no GA36, a imagem de boot do painel 1), sem mandar nenhum `SYSTEM`

#### Scenario: Limite da BOOT com os arquivos de módulos
- **WHEN** a imagem `console` é gerada
- **THEN** a conta dos 64 MiB livres da `BOOT` inclui os dois arquivos de módulos, e o build falha se o limite for ultrapassado
