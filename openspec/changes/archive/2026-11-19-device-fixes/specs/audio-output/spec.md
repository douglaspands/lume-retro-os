# Spec Delta

## Purpose

Definir como o som sai do console: o volume pelo ganho analógico da saída ativa, o mudo, o
amplificador desligado quando não há som e a troca entre o alto-falante e o fone.

## ADDED Requirements

### Requirement: Volume pelo ganho analógico
Onde o hardware oferece ganho analógico acessível, as teclas de volume MUST mudar esse ganho
na saída ativa, com o volume digital fixo em 0 dB. O ruído de fundo MUST cair junto com o
volume. Onde não houver ganho analógico acessível, o volume MUST continuar digital, e o motivo
MUST ficar documentado no guia de bring-up do console.

#### Scenario: Volume baixo sem chiado no GA36
- **WHEN** o usuário baixa o volume do GA36 para 20% em silêncio
- **THEN** o ganho analógico do `Headphone` cai, o DAC continua em 0 dB e o chiado fica menor que com o volume a 100%

### Requirement: Volume zero é mudo
Com o volume em 0%, a saída MUST ficar desligada, sem nenhum som e sem ruído de fundo.

#### Scenario: Mudo de verdade
- **WHEN** o usuário baixa o volume até 0% com um jogo tocando
- **THEN** não sai som nem chiado do alto-falante

### Requirement: Amplificador desligado sem som
Com o jogo pausado, no menu do RetroArch, no launcher e na suspensão, o amplificador do
alto-falante MUST ficar desligado. O som MUST voltar ao retomar o jogo, sem que o começo do
som fique perceptivelmente cortado.

#### Scenario: Pausa desliga o amplificador
- **WHEN** o usuário pausa o jogo
- **THEN** o amplificador do alto-falante se desliga, e ao continuar o som volta

### Requirement: Troca entre o alto-falante e o fone
Encaixar o fone MUST levar o som para o fone, e tirá-lo MUST devolver o som ao alto-falante,
com um jogo rodando, nos consoles cujo hardware detecta o fone. Num console sem detecção, essa
limitação MUST ficar documentada no guia de bring-up.

#### Scenario: Fone encaixado no meio do jogo
- **WHEN** o usuário encaixa o fone no R36S com um jogo tocando
- **THEN** o som passa para o fone e o alto-falante fica mudo

#### Scenario: Fone tirado
- **WHEN** o usuário tira o fone
- **THEN** o som volta ao alto-falante

### Requirement: Volume próprio de cada saída
Cada saída (alto-falante e fone) MUST guardar o próprio volume, que MUST sobreviver ao reboot
e ser reaplicado ao trocar de saída.

#### Scenario: Volume do fone guardado
- **WHEN** o usuário deixa o fone em 30% e o alto-falante em 70%, tira o fone e reinicia
- **THEN** o alto-falante volta a 70%, e ao encaixar o fone ele fica em 30%

### Requirement: O nível mostrado é o nível aplicado
A linha de volume na tela e o percentual das Configurações MUST mostrar o nível da saída ativa,
o mesmo que está aplicado ao hardware.

#### Scenario: Nível na tela
- **WHEN** o usuário aperta volume + com o fone encaixado
- **THEN** a linha mostra o novo nível do fone
