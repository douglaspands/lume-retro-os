# Spec Delta

## ADDED Requirements

### Requirement: Sistema do próprio console no cartão único
No cartão da imagem `console`, o boot MUST montar como raiz o `SYSTEM` do console em que o cartão está (`BOOT/ga36/SYSTEM` no GA36, `BOOT/r36s/SYSTEM` no R36S). Se esse arquivo faltar, o boot MUST parar com uma mensagem na tela que nomeia o console e o arquivo esperado, sem tentar o `SYSTEM` do outro console.

#### Scenario: Mesmo cartão, sistemas diferentes
- **WHEN** o mesmo cartão inicia no GA36 e depois no R36S
- **THEN** no GA36 a raiz é o `SYSTEM` armv7 de `BOOT/ga36/` e no R36S é o `SYSTEM` aarch64 de `BOOT/r36s/`, e o `/etc/r36os/board` de cada um nomeia o próprio console

#### Scenario: SYSTEM do console ausente
- **WHEN** o R36S inicia um cartão cuja `BOOT` não tem `r36s/SYSTEM`
- **THEN** o boot para na tela de recuperação com uma mensagem que cita o R36S e `r36s/SYSTEM`

### Requirement: Logs dos dois consoles na mesma ROMS
Com o cartão único, os logs dos dois consoles MUST ficar na mesma `ROMS/logs/`, numa única sequência de boots, e cada arquivo de log de boot e de hardware MUST identificar o console que o gerou.

#### Scenario: Boots alternados
- **WHEN** o cartão inicia no GA36, depois no R36S e de novo no GA36
- **THEN** existem três logs de boot com números seguidos, nenhum sobrescreve outro, e cada um registra o console em que rodou
