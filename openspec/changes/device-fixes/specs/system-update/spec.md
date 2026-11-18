# Spec Delta

## MODIFIED Requirements

### Requirement: Push pontual sem descompactar
O `lume push` MUST mandar ao console só os arquivos e slots cujo SHA256 difere do que está no
cartão, lidos do arquivo do build, de qualquer build arquivado, e MUST NOT descompactar a imagem do
cartão para isso.

#### Scenario: Atualização só do launcher
- **WHEN** só o slot do projeto mudou e o usuário roda `lume push`
- **THEN** só esse slot, o manifesto e o `VERSION` são enviados, não há etapa de descompactar, e o resumo mostra os bytes enviados e o tempo

#### Scenario: Nada mudou
- **WHEN** o cartão já tem os arquivos do build, salvo o `VERSION`
- **THEN** o `push` termina sem enviar nada e sem reiniciar, dizendo que o console já está no build

#### Scenario: Cartão único nos dois consoles
- **WHEN** o `push` é feito pelo GA36 e o cartão depois é passado ao R36S
- **THEN** o R36S inicia com o conjunto novo dele, sem outro `push`


### Requirement: Push em RAM para iterar
O `lume push --hot <fragmento>` MUST instalar os arquivos do fragmento na camada gravável em RAM,
reiniciar só os serviços do fragmento e registrar isso no log, sem gravar no cartão nem reiniciar
o console; kernel, módulos e base MUST NOT aceitar `--hot`.

#### Scenario: Script alterado
- **WHEN** o usuário roda `lume push --hot lume-usb` depois de mudar um script dele
- **THEN** o serviço `lume-usb` reinicia com o script novo, o `events.log` tem a linha `push hot lume-usb <versão>`, e depois de um reboot o console volta ao conjunto do cartão

#### Scenario: Kernel recusado
- **WHEN** o usuário roda `lume push --hot lume-kernel`
- **THEN** o comando recusa e diz para usar o `push` normal
