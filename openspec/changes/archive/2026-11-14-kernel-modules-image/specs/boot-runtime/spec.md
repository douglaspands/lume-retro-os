# Spec Delta

## ADDED Requirements

### Requirement: Módulos do kernel do próprio console
No cartão da imagem `console`, o boot MUST montar `BOOT/<console>/modules` do console em que o cartão está em `/lib/modules` da raiz, somente leitura, antes de iniciar o sistema, e MUST conferir que a pasta de versão do arquivo é igual à versão do kernel em execução. Os módulos ficam disponíveis desde o primeiro serviço do sistema.

#### Scenario: Módulos carregados no boot
- **WHEN** o GA36 ou o R36S inicia um cartão com `<console>/modules` do mesmo build do kernel
- **THEN** `/lib/modules/$(uname -r)/modules.dep` existe, o `modprobe` de um módulo da imagem funciona, e o log de boot registra a montagem dos módulos

#### Scenario: Módulos do outro console nunca são usados
- **WHEN** o mesmo cartão inicia no GA36 e depois no R36S
- **THEN** cada console monta só a imagem de módulos da sua pasta (`ga36/modules` ou `r36s/modules`)

### Requirement: Boot sem módulos quando faltam ou não batem
Se o arquivo de módulos do console faltar, não montar ou tiver uma versão diferente da do kernel em execução, o boot MUST seguir sem módulos (os drivers de boot estão embutidos no kernel) e MUST registrar um erro no log de boot que nomeia o arquivo e, na diferença de versão, as duas versões.

#### Scenario: Arquivo de módulos ausente
- **WHEN** o console inicia um cartão cuja `BOOT` não tem `<console>/modules`
- **THEN** o sistema chega ao frontend, `/lib/modules` fica vazio, e o log de boot tem uma linha `ERROR` com o caminho do arquivo esperado

#### Scenario: Versão diferente do kernel
- **WHEN** o kernel em execução tem versão diferente da pasta de versão do arquivo de módulos (por exemplo, um `push` interrompido entre os dois arquivos)
- **THEN** o arquivo não fica montado em `/lib/modules`, o sistema chega ao frontend, e o log de boot tem uma linha `ERROR` com as duas versões
