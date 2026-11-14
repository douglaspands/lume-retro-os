# Spec Delta

## MODIFIED Requirements

### Requirement: Atualização pelo cabo USB
O `r36os push` MUST atualizar a `BOOT` de um console ligado pela porta OTG, pelo acesso root
do cabo: enviar o build para uma área temporária, conferir o SHA256 de cada arquivo no
próprio console, trocar os arquivos só depois de todos conferidos e reiniciar. Da área de
boot antes da `BOOT`, só a imagem de boot do GA36 no setor 172032 MAY ser regravada, e
conferida por leitura de volta; a `ROMS` só recebe a área temporária, apagada ao final. A
troca MUST NOT apagar um arquivo que o sistema em execução mantém aberto (o `SYSTEM` e a
imagem de módulos do console), para que nenhum espaço da `BOOT` se perca e a `BOOT` volte a
somente leitura antes do reboot.

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

#### Scenario: Troca do SYSTEM em uso sem perder espaço
- **WHEN** o `push` troca o `SYSTEM` ou a imagem de módulos do console em que roda
- **THEN** o arquivo antigo continua na `BOOT` como `<arquivo>.old` até o push seguinte, a `BOOT` volta a somente leitura antes do reboot e, depois do reboot, um `fsck.vfat -n` da `BOOT` não acha cadeias perdidas

#### Scenario: Espaço do build anterior devolvido
- **WHEN** o `push` encontra arquivos `*.old` na `BOOT`, deixados por um push anterior
- **THEN** ele os apaga antes de copiar os novos, conta o espaço liberado na verificação de espaço da `BOOT` e não os inclui na comparação de SHA256 com o build

#### Scenario: Clusters perdidos avisados
- **WHEN** o espaço usado da `BOOT` passa em mais de 32 MB o que os arquivos dela ocupam
- **THEN** o `push` mostra um aviso com o tamanho perdido e as duas formas de recuperar pelo PC (`fsck.vfat -a` com os `FSCK*.REC` apagados, ou `r36os flash --update`), e segue com a atualização

#### Scenario: Corte de energia no meio da troca do SYSTEM
- **WHEN** o console inicia com a `BOOT` sem o `<console>/SYSTEM` (ou sem a imagem de módulos) e com o `<arquivo>.old` correspondente
- **THEN** o boot usa o `.old` e registra no log de boot uma linha `ERROR` dizendo que usou o arquivo do build anterior, em vez de parar no modo de resgate
