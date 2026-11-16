# lume-launcher: README para quem vai construir a interface

> Leia este arquivo primeiro. Ele diz o que é o lume-launcher, em que ordem ler a documentação, qual protótipo usar e quais passos seguir para criar o app real. Escrito em 2026-11-14.

> **Origem:** notas de planejamento e protótipo candidato copiados para o repositório em 2026-11-14 (antes ficavam num cofre de notas pessoal, fora do git). Esta pasta é a fonte; não há cópia de referência em outro lugar. Ficaram de fora, de propósito: `prototipo/catalog.js` e `prototipo/fs.js` (gerados da coleção pessoal de jogos), `prototipo/assets/logos/` (logos de marcas registradas, que a spec `frontend-session` não deixa a distro trazer) e as versões anteriores do protótipo (histórico em [Protótipos](prototipos.md)). Sem `catalog.js` e sem logos, o protótipo usa dados de demonstração e a sigla de cada console. Os três são gerados localmente pelo `tools/build-catalog.js` e estão no `.gitignore`.
>
> **Change que implementa:** `openspec/changes/lume-launcher/`. As decisões dela (frontend pelo contrato de sessão, runners, saída por Fn+Start, scan das listas) valem sobre o que estas notas supõem do dArkOS.

## O que é
Launcher (interface de jogos) para o console R36S e clones. Mostra um Dock de consoles, a grade de capas, o menu do jogo e as configurações do aparelho. Requisito principal: **baixo consumo de CPU e RAM** em clones fracos, com tema versátil e trocável.

- **Protótipo** (HTML/JS): só valida telas, navegação e temas. **Não é o app.**
- **App real**: Rust + SDL2, com motor de UI separado do tema ([Opções de tecnologia](opcoes-de-tecnologia.md)). Ainda não foi iniciado.

## Protótipo a usar
**Candidato oficial `20261114-033157`**, em `prototipo/` (nesta pasta).

1. Ler `CANDIDATO.md`: o que inclui, o que foi verificado e as pendências.
2. Abrir `index.html` no navegador para ver o comportamento.
3. Para dados reais: `node tools/build-catalog.js <pasta-das-roms>` (use `asdf exec node`).

As versões anteriores não foram copiadas; o histórico delas está em [Protótipos](prototipos.md).

## Ordem de leitura
1. [Visão geral](visao-geral.md): decisões tomadas e índice.
2. [Escopo v1](escopo-v1.md): o que entra e o que fica fora da primeira versão.
3. [Design das telas](design-das-telas.md): Dock, grade, menu do jogo.
4. [Formato de tema](formato-de-tema.md): o tema é declarativo; o tema Lume (padrão) e 2 temas Material (escuro e claro).
5. [Orçamento de performance](orcamento-de-performance.md): metas de memória, CPU e carregamento. São estimativas, não medidas.
6. [Gamelist e capas](gamelist-e-capas.md): de onde vêm lista de jogos e capas (`gamelist.xml` do EmulationStation, campos `name` e `image`).
7. [Emuladores por console e por jogo](emuladores-por-console-e-por-jogo.md): emulador, core, aspecto e shader em 3 camadas (jogo, console, padrão).
8. [Configurações](configuracoes.md): Wi-Fi, Bluetooth, idioma, tema, volume, brilho, sistema, desligar.
9. [Opções de tecnologia](opcoes-de-tecnologia.md) e [Decisão - refatorar ou criar do zero](decisao-refatorar-ou-criar-do-zero.md): por que Rust + SDL2 e tema próprio.
10. [Pesquisa de interfaces](pesquisa-de-interfaces.md) e [Arquitetura](arquitetura.canvas): contexto e diagrama (opcionais).

## Passos para criar a interface
1. **Ler** a documentação na ordem acima e o `CANDIDATO.md`.
2. **Ver o protótipo rodando** e anotar o comportamento de cada tela.
3. **Reconciliar com o projeto de destino.** A documentação assume dArkOS com EmulationStation e o launcher no menu Ports. O projeto de destino pode ser outro sistema (ex.: Lume Retro OS, em Alpine, sem EmulationStation). Antes de planejar, confirmar:
   - como o launcher é iniciado (contrato de sessão do frontend, ou item de Ports);
   - de onde vêm `gamelist.xml` e capas nessa imagem;
   - como abrir o jogo já com core, aspecto, shader e save state (RetroArch e standalone).
4. **Resolver conflitos com as specs do projeto.** O protótipo usa logos de marcas registradas (uso pessoal) e capas. Se o projeto proíbe logotipos de fabricantes ou miniaturas, trocar por ícones livres ou próprios e atualizar a spec.
5. **Propor o change** (OpenSpec) com proposta, design, specs e tarefas, citando as notas desta pasta.
6. **Implementar em Rust + SDL2**, mantendo as fronteiras do protótipo:
   - motor de UI sem conhecimento de tema, dados ou sistema (`src/engine.js`);
   - tema declarativo (`src/themes.js`, `temas/*.js`), virando arquivo TOML ou JSON;
   - dados via scanner com índice em cache (`tools/build-catalog.js`), com `readdir` sob demanda no lugar de `fs.js`;
   - adaptador de sistema isolado (`src/system.js`): Wi-Fi, Bluetooth, métricas, desligar;
   - idiomas em arquivos por idioma (`src/i18n.js`), conferidos por script (`tools/check-i18n.js`).
7. **Medir no aparelho**, no R36S e no clone mais fraco: memória, CPU, tempo até a primeira tela e mapeamento real do gamepad. Só então ajustar as metas.

## Princípios a manter
- Renderização por evento: sem laço de animação; só redesenha quando há input.
- Só as linhas visíveis da grade existem; capas com cache LRU e miniaturas pré-escaladas.
- Animação e transparência vêm do tema (o Modo lite saiu em 2026-11-14).
- Layout em unidades relativas, independente de resolução (640x480, 854x480, 720x720).
- Validar a assinatura da imagem na indexação (na coleção usada no protótipo, 186 capas não eram imagem; usar uma caixa gerada).

## Pendências conhecidas
Nada foi verificado no aparelho. Lista completa em `prototipo/CANDIDATO.md`, seção "Pendências e limites conhecidos".
