# Spec Delta

## ADDED Requirements

### Requirement: Atualização pelo cabo USB
O `r36os push` MUST atualizar a `BOOT` de um console ligado pela porta OTG, pelo acesso root
do cabo: enviar o build para uma área temporária, conferir o SHA256 de cada arquivo no
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

#### Scenario: Console fora do cabo
- **WHEN** o usuário roda `r36os push` e o console não responde pela rede USB (desligado, cabo na porta de carga ou adaptador OTG na porta)
- **THEN** o comando termina com erro antes de enviar qualquer arquivo e diz para ligar o console com o cabo na porta OTG

#### Scenario: Bateria baixa
- **WHEN** o console está com a bateria abaixo de 20%
- **THEN** o comando termina com erro antes de enviar qualquer arquivo

#### Scenario: Sem espaço para a área temporária
- **WHEN** a `ROMS` não tem espaço livre para o build enviado
- **THEN** o comando termina com erro antes de enviar qualquer arquivo, sem apagar nada do usuário
