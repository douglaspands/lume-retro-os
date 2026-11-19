# Spec Delta

## ADDED Requirements

### Requirement: Conjunto de jogos de teste padrão
O PC MUST guardar um conjunto de jogos de teste padrão fora do git, organizado como a `ROMS`
(`roms/<sistema>/` com `gamelist.xml` e `images/`), e um comando do `lume` MUST copiá-lo para o
cartão do console no cabo, conferindo o SHA256 de cada arquivo, sem apagar nem sobrescrever o que
já está no cartão. O comando, a saída e os logs MUST NOT trazer nome de jogo nem caminho de ROM.

#### Scenario: Cartão recém-limpo
- **WHEN** o cartão foi gravado do zero e o comando roda com o console no cabo
- **THEN** cada sistema do conjunto aparece no launcher com os jogos, os nomes e as capas, e a saída diz só quantos arquivos foram copiados e conferidos por sistema

#### Scenario: Cartão que já tem jogos
- **WHEN** o cartão já tem jogos e listas próprias num sistema do conjunto
- **THEN** os jogos do cartão continuam, os do conjunto que faltam são copiados, e a lista do sistema ganha só as entradas novas

#### Scenario: Cópia corrompida
- **WHEN** o SHA256 de um arquivo no cartão difere do PC depois da cópia
- **THEN** o comando copia de novo esse arquivo e termina com erro se a diferença continuar

### Requirement: Uso do conjunto de teste nas provas de desempenho
As medições de linha de base e de ajuste por core MUST usar jogos do conjunto de teste padrão,
escolhidos por sistema e posição na lista, para que medições em datas diferentes usem a mesma
carga.

#### Scenario: Mesma carga em duas datas
- **WHEN** a linha de base do `fbneo` é medida num dia e um ajuste é medido noutro
- **THEN** as duas medições usam o mesmo jogo do conjunto, escolhido pela mesma posição
