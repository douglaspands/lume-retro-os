# Spec Delta

## MODIFIED Requirements

### Requirement: Cache dentro do projeto
Por padrão, o build MUST guardar o cache em `.cache/` na raiz do projeto. Quando
`$LUME_CACHE` estiver definida, o build MUST usar esse caminho no lugar do padrão, esteja ele
dentro ou fora do projeto. O build MUST NOT usar `$XDG_CACHE_HOME/lume` nem `~/.cache/lume`.

#### Scenario: Sem variável de ambiente
- **WHEN** um build roda sem `$LUME_CACHE` definida
- **THEN** fontes, árvores de build, ccache e as demais pastas do cache são criadas em `<projeto>/.cache/`

#### Scenario: Variável de ambiente definida
- **WHEN** um build roda com `LUME_CACHE=/outro/lugar`
- **THEN** o cache é lido e escrito em `/outro/lugar`, e nada é criado em `<projeto>/.cache/`

#### Scenario: Cache antigo não é usado
- **WHEN** existe `~/.cache/lume` com conteúdo e `$LUME_CACHE` não está definida
- **THEN** o build ignora esse caminho e usa `<projeto>/.cache/`


### Requirement: Worktrees usam o cache do repositório principal
Quando o build roda numa git worktree do projeto e `$LUME_CACHE` não está definida, ele MUST
usar o `.cache/` do repositório principal, sem criar um `.cache/` na worktree. Fora de um
repositório git, o build MUST usar o `.cache/` da própria pasta do projeto.

#### Scenario: Build numa worktree
- **WHEN** um build roda em `out/worktrees/<nome>` sem `$LUME_CACHE`
- **THEN** ele reaproveita as fontes e o ccache de `<repositório principal>/.cache/`, e `out/worktrees/<nome>/.cache/` não é criado

#### Scenario: Projeto sem git
- **WHEN** o projeto é usado a partir de um arquivo compactado, sem `.git`
- **THEN** o cache fica em `.cache/` dentro da pasta extraída
