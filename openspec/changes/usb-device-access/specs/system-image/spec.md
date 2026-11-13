# Spec Delta

## ADDED Requirements

### Requirement: Chave SSH na BOOT só por opção explícita
O `r36os flash` MUST gravar `BOOT/ssh/` (a chave pública do usuário e a chave de host do
console, única por PC) só quando o usuário passar a opção explícita com a chave pública.
Sem a opção, a `BOOT` MUST NOT ter `ssh/`, e o `flash --update` MUST preservar uma `ssh/`
que já esteja no cartão. A opção MUST recusar uma chave privada.

#### Scenario: Build e flash sem a opção
- **WHEN** o usuário roda `r36os build console` e `r36os flash console <dispositivo> --full` sem a opção da chave
- **THEN** a `BOOT` gravada não tem a pasta `ssh/`

#### Scenario: Mesma chave de host em todos os cartões do PC
- **WHEN** o usuário grava dois cartões com a opção da chave, a partir do mesmo PC
- **THEN** os dois consoles apresentam a mesma chave de host, e o `ssh` do PC não avisa de troca de chave ao alternar entre eles

#### Scenario: Flash com a chave do PC
- **WHEN** o usuário roda `r36os flash console <dispositivo> --update` com a opção apontando para `~/.ssh/id_ed25519.pub`
- **THEN** a `BOOT` gravada tem `ssh/authorized_keys` com essa chave, conferida por SHA256 depois da gravação

#### Scenario: Chave privada recusada
- **WHEN** a opção aponta para um arquivo de chave privada
- **THEN** o comando para antes de gravar, com uma mensagem que explica que só a chave pública é aceita

#### Scenario: Update preserva a chave
- **WHEN** o usuário roda `flash --update` sem a opção num cartão que já tem `BOOT/ssh/authorized_keys`
- **THEN** a chave continua no cartão depois da gravação

### Requirement: Atualização pelo cabo USB
O `r36os push` MUST atualizar a `BOOT` de um console ligado pela porta OTG com o acesso root
por chave: enviar o build para uma área temporária, conferir o SHA256 de cada arquivo no
próprio console, trocar os arquivos só depois de todos conferidos e reiniciar. Da área de
boot antes da `BOOT`, só a imagem de boot do GA36 no setor 172032 MAY ser regravada, e
conferida por leitura de volta; a `ROMS` só recebe a área temporária, apagada ao final.

#### Scenario: Atualização conferida
- **WHEN** o usuário roda `r36os push` com um console ligado e acessível por SSH
- **THEN** os arquivos da `BOOT` no cartão passam a ter o SHA256 do build, o console reinicia e o próximo boot registra a versão nova no `events.log`

#### Scenario: Kernel novo no GA36
- **WHEN** o build traz uma imagem de boot do GA36 diferente da gravada no setor 172032 e o `push` é feito com o cartão no GA36
- **THEN** a imagem do painel 1 é gravada no setor 172032, lida de volta com o mesmo SHA256, e nenhum outro setor antes da `BOOT` muda

#### Scenario: Falha na conferência
- **WHEN** algum arquivo enviado tem SHA256 diferente do build
- **THEN** nenhum arquivo da `BOOT` é trocado, o console não reinicia e o comando termina com erro nomeando o arquivo

#### Scenario: Console sem acesso root
- **WHEN** o usuário roda `r36os push` e o console não aceita a chave (ou não tem `authorized_keys`)
- **THEN** o comando termina com erro antes de enviar qualquer arquivo e explica como gravar a chave com o `flash`

#### Scenario: Sem espaço para a área temporária
- **WHEN** a `ROMS` não tem espaço livre para o build enviado
- **THEN** o comando termina com erro antes de enviar qualquer arquivo, sem apagar nada do usuário
