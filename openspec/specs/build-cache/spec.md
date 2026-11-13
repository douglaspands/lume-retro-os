# build-cache Specification

## Purpose

Define onde o build guarda o que baixa e o que compila entre uma execução e outra (fontes,
árvores de build, ccache, chaves do abuild, áreas de fábrica e disco da VM), para que quem
clona o projeto encontre tudo dentro dele, sem configuração escondida na máquina.

## Requirements

### Requirement: Cache dentro do projeto
Por padrão, o build MUST guardar o cache em `.cache/` na raiz do projeto. Quando
`$R36OS_CACHE` estiver definida, o build MUST usar esse caminho no lugar do padrão, esteja ele
dentro ou fora do projeto. O build MUST NOT usar `$XDG_CACHE_HOME/r36os` nem `~/.cache/r36os`.

#### Scenario: Sem variável de ambiente
- **WHEN** um build roda sem `$R36OS_CACHE` definida
- **THEN** fontes, árvores de build, ccache e as demais pastas do cache são criadas em `<projeto>/.cache/`

#### Scenario: Variável de ambiente definida
- **WHEN** um build roda com `R36OS_CACHE=/outro/lugar`
- **THEN** o cache é lido e escrito em `/outro/lugar`, e nada é criado em `<projeto>/.cache/`

#### Scenario: Cache antigo não é usado
- **WHEN** existe `~/.cache/r36os` com conteúdo e `$R36OS_CACHE` não está definida
- **THEN** o build ignora esse caminho e usa `<projeto>/.cache/`

### Requirement: Cache fora do git
O `.cache/` MUST ser ignorado pelo git: nenhum arquivo dele aparece no `git status` nem pode
ser adicionado por engano com `git add .`.

#### Scenario: Status limpo depois de um build
- **WHEN** um build completo termina numa árvore sem mudanças
- **THEN** `git status` não lista nada dentro de `.cache/`

### Requirement: Cache No-COW quando o sistema de arquivos permite
Ao criar o diretório de cache, o build MUST tentar marcá-lo como No-COW (atributo `C` do
Btrfs), para que o que for criado dentro dele herde o atributo. Num sistema de arquivos sem
suporte, o build MUST avisar numa linha e seguir normalmente.

#### Scenario: Projeto num Btrfs
- **WHEN** o primeiro build cria `.cache/` num Btrfs
- **THEN** `lsattr -d .cache` mostra o atributo `C`

#### Scenario: Projeto num sistema de arquivos sem No-COW
- **WHEN** o primeiro build cria `.cache/` num ext4 ou xfs
- **THEN** o build mostra um aviso de uma linha dizendo que o No-COW não foi aplicado e continua até o fim

#### Scenario: Cache já existente
- **WHEN** `.cache/` já existe
- **THEN** o build usa o diretório como está, sem tentar mudar atributos

### Requirement: Worktrees usam o cache do repositório principal
Quando o build roda numa git worktree do projeto e `$R36OS_CACHE` não está definida, ele MUST
usar o `.cache/` do repositório principal, sem criar um `.cache/` na worktree. Fora de um
repositório git, o build MUST usar o `.cache/` da própria pasta do projeto.

#### Scenario: Build numa worktree
- **WHEN** um build roda em `out/worktrees/<nome>` sem `$R36OS_CACHE`
- **THEN** ele reaproveita as fontes e o ccache de `<repositório principal>/.cache/`, e `out/worktrees/<nome>/.cache/` não é criado

#### Scenario: Projeto sem git
- **WHEN** o projeto é usado a partir de um arquivo compactado, sem `.git`
- **THEN** o cache fica em `.cache/` dentro da pasta extraída
