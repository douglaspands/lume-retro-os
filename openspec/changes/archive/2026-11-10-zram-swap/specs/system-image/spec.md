# Spec Delta

## Purpose

Define a gravação segura de imagens nos cartões de memória via ferramenta de host `r36os flash`, garantindo a integridade dos dados e o desligamento/ejeção segura do dispositivo após a escrita.

## ADDED Requirements

### Requirement: Ejeção segura do dispositivo pós-gravação
O comando `r36os flash` MUST suportar o argumento opcional `--eject`. Quando `--eject` for especificado, após a escrita e a verificação SHA256 dos blocos gravados, a ferramenta MUST desmontar eventuais partições do dispositivo e solicitar a desconexão/ejeção segura ao sistema operacional através de `udisksctl power-off -b <dispositivo>` (com fallback para `eject <dispositivo>`).

#### Scenario: Gravação com flag --eject
- **WHEN** o usuário executa `r36os flash <alvo> <dispositivo> --eject` (com ou sem `--update`)
- **THEN** a gravação e a validação SHA256 são concluídas com sucesso e o dispositivo é ejetado/desligado com segurança antes do término do comando
