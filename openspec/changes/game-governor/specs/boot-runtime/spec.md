# Spec Delta

## ADDED Requirements

### Requirement: Coleta de métricas com custo baixo
A coleta periódica de métricas e eventos, somando os processos que ela dispara, MUST usar menos de 1% de um núcleo no GA36 e no R36S, medido numa janela de 60 segundos com o launcher parado e com um jogo aberto.

#### Scenario: Launcher parado
- **WHEN** o console fica 60 segundos no launcher sem nenhum botão
- **THEN** o coletor e os processos dele usam menos de 1% de um núcleo nesse intervalo

#### Scenario: Durante o jogo
- **WHEN** um jogo roda por 60 segundos com as métricas ligadas
- **THEN** o coletor e os processos dele usam menos de 1% de um núcleo, e as colunas das métricas continuam as mesmas do formato documentado
