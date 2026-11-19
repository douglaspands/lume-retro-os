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

### Requirement: Serviços em segundo plano sem processo novo a cada volta
Os serviços do sistema que vigiam um estado em laço (o cabo USB, os saves, a configuração persistida, o SSH pelo Wi-Fi) MUST esperar e ler sem criar um processo novo a cada volta, e todos juntos MUST usar menos de 1% de um núcleo, medido em 60 segundos com o launcher parado e com um jogo aberto. Com o launcher parado, o sistema inteiro MUST criar menos de um processo novo por segundo.

#### Scenario: Launcher parado
- **WHEN** o console fica 60 segundos no launcher sem nenhum botão e sem mudança no cabo
- **THEN** o contador `processes` de `/proc/stat` sobe menos de 60, e os laços somam menos de 1% de um núcleo

#### Scenario: Durante o jogo
- **WHEN** um jogo roda por 60 segundos
- **THEN** os laços somam menos de 1% de um núcleo, e o cabo, o MTP, o SSH pelo cabo, a gravação dos saves e a configuração persistida continuam funcionando como antes

#### Scenario: Hora do log depois do fuso
- **WHEN** o fuso do cartão é aplicado depois de o coletor subir
- **THEN** as linhas seguintes do coletor saem na hora local, como as do `lume-run`
