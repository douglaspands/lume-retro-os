# Design

## Context

Motivação em `proposal.md`; requisitos nos deltas `specs/game-launcher` e
`specs/frontend-session`.

Estado atual que o desenho reaproveita:

- **Eventos do Fn**: a change `lume-hud-actions` (D13) faz o `lume-input` decidir os gestos e
  mandar `fn_tap`, `fn_hold <tabela>` e `fn_release` a todos os clientes de
  `/run/lume/input.sock`. Com o launcher na tela, o `lume-ui` recebe e ignora esses eventos;
  esta change passa a usá-los. **Pré-requisito:** a `lume-hud-actions` mesclada.
- **Socket no `lume-ui`**: `lume/lume-ui/src/input.rs:293-340` já mantém uma thread que lê o
  socket (`volume`, `brightness`) e manda eventos ao laço principal (`Ev::Volume`,
  `Ev::Brightness`, `main.rs:120`).
- **Folhas**: `draw_sheet` (`app.rs:1961`) desenha as folhas do protótipo (menu do jogo, opções
  do console, Desligar com Cancelar primeiro). Um só campo `overlay: Option<Overlay>`
  (`app.rs:156`) guarda a folha aberta: `Menu`, `Slots`, `Keyboard`, `Confirm`.
- **Desligar hoje**: `SetRow::Power` na lista das Configurações (`app.rs:1067`, `1318`) abre
  `Overlay::Confirm`; confirmado, o `lume-ui` sai com 0 (`main.rs:214`, `_exit` por causa do
  P-71), o `lume-run` sai com 0 (`lume-run/src/main.rs:5`), e o `session`
  (`aports/lume-core/files/usr/libexec/lume/session:139-145`) grava (`persist flush`, `sync`)
  e chama `poweroff`. Códigos 64 e 65 são do `lume-run` (abrir jogo, menu do RetroArch);
  qualquer outro código conta como falha no `session`.
- **Ícones do Dock**: `app.rs:1570` pinta o tile com `icon_bg`/`icon_fg` (ou `icon_sel_*` no
  foco); o conteúdo é o logo do cartão lido como máscara (`themes/<id>/icons/<sistema>.png`,
  `docs/lume-launcher/formato-de-tema.md:39-53`) ou a sigla.
- **Protótipo e régua**: toda tela nova entra primeiro no protótipo
  (`docs/lume-launcher/prototipo/`) e é medida a 640x480; as medidas viram as constantes e os
  testes de tela (`tests/ui.rs`).

## Goals / Non-Goals

**Goals:**
- O Fn com o mesmo significado dentro e fora do jogo: toque abre o menu de quem está na tela
  (Lume no jogo, sistema no launcher), segurar mostra os atalhos.
- Desligar e Reiniciar num só lugar, por um caminho do contrato de sessão que serve a qualquer
  frontend.
- Cores por console sem trazer logotipo de fabricante na imagem.

**Non-Goals:**
- Mudar os gestos do Fn ou o `lume-input` (são da `lume-hud-actions`).
- Um menu do sistema dentro do jogo (é o menu do Lume, da `lume-hud-actions`).
- Wi-Fi, Bluetooth, tema Lume novo, miniaturas e wallpaper (P-66, P-67, P-13, P-17).

## Decisions

### D1. Menu do sistema como camada própria no `lume-ui`

Um campo novo, `system: Option<SystemMenu>`, separado do `overlay`. Ele é desenhado depois de
tudo (por cima de qualquer tela ou folha) e recebe a entrada antes do resto. Assim o menu abre
sobre a grade, a busca, as Configurações ou uma folha já aberta, e ao fechar a tela de baixo
continua exatamente como estava, sem salvar e restaurar estado.

```
 Ev::FnTap --> system == None ? abre (foco em Desligar... ver D2) : fecha
 Ev::FnHold(tabela) --> system == None ? mostra a dica (D4) : ignora
 Ev::FnRelease --> esconde a dica
 com system aberto:  cima/baixo foco, A escolhe, B fecha
   Desligar  --> confirmação (Cancelar em foco) --> Sim: exit(0)
   Reiniciar --> confirmação (Cancelar em foco) --> Sim: exit(66)
   Configurações --> fecha o menu, abre as Configurações lembrando a tela de origem;
                     B nas Configurações volta a ela
```

O desenho é uma folha (`draw_sheet`) com título "Sistema", na família do Desligar de hoje, com
a capa sem imagem (`Cover::None`) e as medidas da régua (D5).

*Alternativa descartada:* uma pilha de `Overlay`. Mexeria em todos os pontos que hoje casam
com `self.overlay`, para ganhar só o caso "folha sobre folha", que o campo separado já resolve.

### D2. Itens e foco do menu

Ordem: Desligar, Reiniciar, Configurações. O foco começa em **Configurações** (o item sem
risco), e Desligar e Reiniciar sempre passam pela confirmação com Cancelar em foco; nenhum
toque de A por engano desliga o console.

### D3. Reiniciar pelo contrato de sessão: código de saída 66

O `lume-ui` sai com **66** para reiniciar. O `lume-run` repassa o 66 como repassa o 0 (hoje só
trata 64 e 65). O `session` ganha um ramo ao lado do `rc -eq 0`:

```
 rc 0  --> "closed by user: shutting down"   --> persist flush, sync, poweroff
 rc 66 --> "closed by user: rebooting"        --> persist flush, sync, reboot
 outro --> falha (como hoje)
```

O código entra no `docs/FRONTEND.md` como parte do contrato: um frontend que nunca sai com 66
continua igual (o RetroArch como frontend não muda). O evento no `events.log` é `frontend OK`,
não `FAIL`, e o boot seguinte registra `shutdown OK previous clean` como no desligar.

*Alternativa descartada:* o frontend gravar um arquivo em `/run` pedindo o reinício e sair com
0. Precisa de permissão do usuário `game` num diretório do sistema e pode deixar um pedido
velho se o processo cair entre a gravação e a saída; o código de saída é atômico.

### D4. Dica dos atalhos no launcher

O `fn_hold` traz a tabela do perfil (`B=app_menu R1=save_state ... Vol=brightness`). No
launcher valem só os acordes que o launcher trata; nesta versão, `Vol=brightness`. A dica
lista sempre "Fn (toque): Menu do sistema" e, da tabela, os acordes que o launcher reconhece,
com o glifo do botão e o nome no idioma do usuário. É um painel pequeno no centro, nas cores
de folha do tema, que não recebe entrada; some no `fn_release` ou quando chega o evento de um
acorde (`brightness`).

### D5. Protótipo antes do código

Três telas novas no protótipo, medidas a 640x480 nos temas do protótipo e nos três idiomas,
com a aprovação do usuário anotada em `docs/lume-launcher/design-das-telas.md`: o menu do
sistema (e as duas confirmações), a dica no launcher e o Dock com as cores por console. O
rodapé do Dock ganha a dica do Fn (glifo + "Menu"), medida na mesma régua. As medidas viram os
testes de tela do `lume-ui`.

### D6. Cores por console: tokens por sistema (opção "a")

O `theme.toml` aceita uma tabela por sistema com os quatro tokens do ícone:

```toml
[systems.snes]
icon_bg = "#4f43ae"
icon_fg = "#ffffff"
icon_sel_bg = "#ffffff"
icon_sel_fg = "#4f43ae"
```

- Resolução de cada token do item do Dock: `systems.<id>.<token>` do tema, depois de cada tema
  da cadeia `extends`, depois o `<token>` geral, que já tem a cadeia até o `base.toml`. Uma
  chave por vez: um tema pode mudar só o `icon_bg` de um sistema.
- A máscara (logo do cartão) e a sigla usam o `icon_fg`/`icon_sel_fg` resolvido do sistema.
- Validação no carregamento: sistema que não está no catálogo vira aviso no log (o tema pode
  ser de outra versão); cor inválida vira erro no log e o token cai para o herdado; chave
  fora dos quatro tokens vira aviso.
- O tema **Lume** da imagem ganha a tabela com as cores oficiais dos logos dos sistemas do
  catálogo. Cada cor tem a fonte anotada num comentário (guia de marca ou o logo oficial
  publicado), e o contraste entre `icon_fg` e `icon_bg` de cada sistema é de pelo menos 3:1
  (teste). Os temas Material não ganham a tabela e continuam com uma cor só.

### D7. Logo colorido só de tema do cartão (opção "b")

Um arquivo `icons/<sistema>.color.png` (RGBA) num tema do cartão é desenhado como imagem, com
as cores dele, no lugar da máscara; tem prioridade sobre o `icons/<sistema>.png` do mesmo
tema, e a busca segue a mesma ordem da máscara (tema, cadeia `extends`, tema padrão). O tile
continua com o `icon_bg`/`icon_sel_bg` do sistema, e o logo cabe nos mesmos 78% x 56%. Os
temas da imagem não trazem `.color.png`: um teste do pacote recusa qualquer PNG dentro de
`themes/` da imagem, mantendo a regra da `frontend-session` sobre logotipos.

A decodificação é a mesma das máscaras (já no cache de ícones), mas guardando os quatro
canais; o teto de memória do cache de ícones vale para os dois tipos.

*Alternativa descartada:* uma chave `icons = "color"` no `[theme]` valendo para todos os
logos. Um tema do cartão costuma misturar logos de uma cor e coloridos; o sufixo por arquivo
resolve sem configuração.

### D8. Conferência no aparelho

As provas da P-70 e da P-71 viram as janelas desta change, com o build que já tem tudo dela:

- **J1, GA36**: as telas contra o protótipo (Dock com as cores, grade, busca, menu do jogo,
  opções do console, Configurações sem Desligar, Sistema com a temperatura, menu do sistema,
  dica), capturas pelo `lume-shot`; Fn+Vol (teto no nível 7, linha branca à esquerda); a
  linha de volume e brilho sobre um jogo do RetroArch; tempo até o primeiro quadro de um jogo;
  Desligar (fecha a P-71 no GA36) e Reiniciar, com o `shutdown OK previous clean` no boot
  seguinte.
- **J2, R36S, o mesmo cartão**: as mesmas telas e o menu do sistema; as medições da 9.6 da
  `lume-launcher` (CPU e memória parados, tempo do jogo até a grade, boot), o nome do sensor
  de temperatura, o Fn+Vol sem teto (anotar se a luz pisca como no GA36), Desligar e
  Reiniciar; observar a mancha clara nas bordas (P-70).

O que falhar vira tarefa desta change; o que exigir change própria vira P-NN.

## Risks / Trade-offs

- [A `lume-hud-actions` atrasa e os eventos do Fn não existem] → Esta change não começa o
  código do menu antes do merge dela; o protótipo e as cores por console (D5, D6, D7) não
  dependem dela e podem andar antes.
- [Desligar some das Configurações e o usuário não acha] → A dica do Fn no rodapé do Dock e o
  `docs/LAUNCHER.md`; as Configurações continuam acessíveis pelo Dock e pelo menu.
- [Reinício que desliga em vez de voltar (o GA36 já desligou uma vez num reboot, boot 43→44)]
  → Prova repetida três vezes em cada console na janela; se repetir, vira P-NN com o log.
- [Código 66 confundido com uma falha por um `session` antigo] → O `session` e o `lume-run`
  vão no mesmo build; um `lume-ui` novo com um `session` velho reabre o frontend (falha
  contada), sem desligar nem perder dados.
- [Cor oficial com pouco contraste no foco] → O teste de contraste por sistema no tema Lume; o
  `icon_sel_*` pode inverter as cores do sistema.
- [Logo colorido grande estoura a memória do cache] → Mesmo teto em bytes do cache de ícones;
  o logo é reduzido ao tamanho do tile na decodificação.

## Migration Plan

1. Temas do cartão sem `[systems.*]` e sem `.color.png` continuam iguais.
2. As configurações gravadas não mudam (o Desligar não era uma preferência).
3. Voltar à versão anterior pelo `push` traz o Desligar de volta às Configurações.

## Open Questions

- Lista exata de sistemas com cor no tema Lume: decide a ordem do trabalho da tabela, não o
  formato (todos do catálogo com logo oficial conhecido).
