# Spec Delta

## MODIFIED Requirements

### Requirement: Runners declarativos
Cada forma de abrir um jogo MUST ser um runner descrito num arquivo de dados com o comando (lista de argumentos com marcadores como a ROM e o core), a política de encerramento, as ações do jogo que ele suporta (`app_menu`, `reset`, `save_state`, `load_state`, `screenshot`), cada uma com a forma de executá-la (comando de rede do RetroArch, tecla enviada pelo controle virtual ou sinal ao processo), e se sabe desenhar o menu do Lume. Adicionar um emulador MUST exigir só um arquivo de runner e uma entrada no catálogo, sem recompilar o launcher. Um runner sem ações declaradas MUST continuar válido.

#### Scenario: Emulador novo pelo cartão
- **WHEN** o usuário coloca um arquivo de runner em `ROMS/system/lume/runners.d/` e o cita num sistema
- **THEN** depois de "Atualizar listas de jogos" o emulador aparece no menu do jogo desse sistema e abre o jogo

#### Scenario: Nome de arquivo com espaço
- **WHEN** a ROM se chama `Meu Jogo (Rev 1).zip`
- **THEN** o emulador recebe o caminho inteiro como um único argumento

#### Scenario: Ação por tecla num emulador standalone
- **WHEN** o arquivo de um runner declara `save_state` pela tecla F2 e o usuário aperta Fn+R1 num jogo desse runner
- **THEN** o emulador recebe um toque de F2 pelo controle virtual

#### Scenario: Runner antigo sem ações
- **WHEN** um arquivo de runner do cartão só tem o comando e a política de encerramento
- **THEN** o runner continua aparecendo e abrindo jogos, Fn+B, Fn+R1, Fn+L1 e o toque no Fn não fazem nada nele, e Fn+Start continua encerrando

## REMOVED Requirements

### Requirement: Fn sozinho continua abrindo o menu
**Reason**: O Fn passa a ser o botão do sistema, à moda do botão Steam (capability `game-actions`): o toque abre o menu do Lume, segurar mostra a dica dos acordes, e o menu do emulador abre pelo Fn+B ou pelo item dele no menu do Lume, ações que valem para qualquer runner que as declare.
**Migration**: Usar Fn+B para abrir e fechar o menu do RetroArch durante o jogo, ou tocar o Fn e escolher "Menu do RetroArch". Segurar o Fn mostra os atalhos. Fn+Start continua encerrando o jogo sem abrir menu.
