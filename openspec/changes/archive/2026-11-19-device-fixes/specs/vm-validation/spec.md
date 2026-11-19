# Spec Delta

## MODIFIED Requirements

### Requirement: Validação antes de liberar uma build de console
Uma build de console MUST ser liberada apenas se a conferência no aparelho (`lume dev check` e o push que confere o boot) tiver passado no GA36 e no R36S. O teste de aceitação da imagem `vm` deixa de ser exigido para liberar uma build de console.

#### Scenario: VM reprovada bloqueia o console
- **WHEN** a imagem `vm` do mesmo build foi gerada e o teste de aceitação dela falhou
- **THEN** a imagem `console` desse build não é marcada como liberada

#### Scenario: Aparelho reprovado bloqueia o console
- **WHEN** a conferência no aparelho falha no GA36 ou no R36S num build
- **THEN** a imagem `console` desse build não é marcada como liberada

#### Scenario: Sem imagem vm
- **WHEN** um build de console é feito sem gerar nem testar a imagem `vm`
- **THEN** ele pode ser liberado se a conferência nos dois aparelhos passou
