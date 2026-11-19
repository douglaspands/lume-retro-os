# Spec Delta

## ADDED Requirements

### Requirement: Cartão usado em outro console durante a suspensão
Ao acordar, o sistema MUST conferir, antes de qualquer gravação na partição `ROMS`, se o cartão
foi iniciado em outro lugar enquanto o console dormia (o contador de boots do cartão, lido do
cartão sem o cache de página, difere do guardado antes de suspender). Se o cartão mudou, o
console MUST reiniciar na hora, sem gravar nada no cartão, e o boot seguinte MUST registrar o
motivo no `events.log`. Se o cartão não mudou, o despertar segue como antes, sem atraso
perceptível.

#### Scenario: Cartão levado ao outro console e devolvido
- **WHEN** o GA36 está suspenso, o cartão é tirado, inicia no R36S, volta ao GA36 e o GA36 acorda
- **THEN** o GA36 reinicia sem gravar no cartão, nenhuma lista de jogos nem log fica corrompido, e o `events.log` do boot seguinte diz que o cartão mudou durante a suspensão

#### Scenario: Despertar normal
- **WHEN** o console acorda com o mesmo cartão, que não foi usado em outro lugar
- **THEN** o jogo ou o menu continua de onde parou, como antes
