# Spec Delta

## ADDED Requirements

### Requirement: Cartão usado em outro console durante a suspensão
Antes de suspender, o sistema MUST deixar a partição `ROMS` só leitura (nenhum processo grava
nela até a conferência) e guardar a impressão digital do cartão. Ao acordar, o sistema MUST
conferir, antes de qualquer gravação na `ROMS`, se o cartão mudou enquanto o console dormia: a
impressão digital, lida do dispositivo de bloco sem nenhum cache do kernel (contador de boots
`ROMS/logs/.boot` achado pelo diretório que está no cartão, a entrada dele e o bitmap de
alocação), difere da guardada antes de suspender, ou o cartão não pode ser lido. Se o cartão
mudou, o console MUST reiniciar na hora, sem gravar nada no cartão, e o boot seguinte MUST
registrar o motivo no `events.log`, pela marca da suspensão gravada antes de suspender; o
outro console que iniciar o cartão tirado de um console suspenso MUST registrar isso, e não
um corte de energia. Se o cartão não mudou, a `ROMS` volta a ser gravável e o despertar segue
como antes, sem atraso perceptível.

#### Scenario: Cartão levado ao outro console e devolvido
- **WHEN** o GA36 está suspenso, o cartão é tirado, inicia no R36S, volta ao GA36 e o GA36 acorda
- **THEN** o GA36 reinicia sem gravar no cartão, nenhuma lista de jogos nem log fica corrompido, e o `events.log` do boot seguinte diz que o cartão mudou durante a suspensão
- **AND** o primeiro boot do R36S com esse cartão registra que o cartão saiu de um console suspenso, e não um corte de energia

#### Scenario: Nenhuma gravação antes da conferência
- **WHEN** o console acorda e um processo (o `lume-logd`, o `lume-persist`, o launcher) tenta gravar na `ROMS` antes da conferência
- **THEN** a gravação não chega ao cartão (a `ROMS` está só leitura), e o pendente do `lume-logd` e do `lume-persist` fica na RAM até a `ROMS` voltar a ser gravável

#### Scenario: Despertar normal
- **WHEN** o console acorda com o mesmo cartão, que não foi usado em outro lugar
- **THEN** o jogo ou o menu continua de onde parou, como antes
