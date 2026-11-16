# Gamelist e capas

> Registrado em 2026-11-14. Responde: qual é o padrão de gamelist com capa? É o do RetroArch?

## Resposta curta
**Não.** O padrão para lista de jogos com capa em handhelds como o R36S é o do **EmulationStation** (`gamelist.xml`). O RetroArch usa outro mecanismo (playlists `.lpl` e pastas de thumbnails). O lume-launcher segue o do ES, porque o dArkOS já o gera e o usuário já tem o scraping feito ([Decisão - refatorar ou criar do zero](decisao-refatorar-ou-criar-do-zero.md)).

## EmulationStation: `gamelist.xml` (padrão adotado)
Um arquivo por pasta de sistema (`roms/<sistema>/gamelist.xml`):

```xml
<gameList>
  <game>
    <path>./Sonic.zip</path>
    <name>Sonic the Hedgehog</name>
    <desc>...</desc>
    <image>./images/Sonic-image.png</image>
    <thumbnail>./images/Sonic-thumb.png</thumbnail>
    <marquee>./images/Sonic-marquee.png</marquee>
    <video>./videos/Sonic-video.mp4</video>
    <releasedate>19910623T000000</releasedate>
    <developer>Sega</developer>
    <genre>Platform</genre>
    <players>1</players>
  </game>
</gameList>
```

- `path` é relativo à pasta do sistema.
- A **capa (caixa)** é o `<image>`. Na coleção usada no protótipo fica em `<sistema>/img/`.
- `<thumbnail>`, `<marquee>` e `<video>` são opcionais; o v1 só usa `<image>` e `<name>`.
- Os scrapers (Skraper, Skyscraper, scraper interno do ES) geram esse formato.

## RetroArch: playlists `.lpl` (não adotado)
- Playlist em JSON (`<Sistema>.lpl`) com `path`, `label`, `core_path`, `db_name`.
- Thumbnails fora da playlist, nomeadas pelo **label**: `thumbnails/<Sistema>/Named_Boxarts/<Label>.png` (também `Named_Snaps` e `Named_Titles`). Os caracteres `&*/:\`<>?|` do nome viram `_`.
- Base pública de imagens: libretro-thumbnails.
- Só serve como **fallback** possível: se faltar `<image>`, procurar `Named_Boxarts/<nome>.png`. Fica fora do v1.

## Como o protótipo trata
`tools/build-catalog.js` (candidato `20261114-033157`) lê `<sistema>/gamelist.xml` e usa só `<name>` e `<image>`:

1. Normaliza o caminho do `<image>` relativo à pasta do sistema.
2. **Valida a assinatura** do arquivo (PNG, JPEG ou WebP). Existem `.png` que são texto, de downloads que falharam (186 na coleção atual, 180 no SNES).
3. Capa inválida ou ausente: o launcher gera uma caixa em SVG no lugar.

Ver [Protótipos](prototipos.md) (seção "Dados reais da sua coleção").

## Para o app real (Rust + SDL2)
- Ler o `gamelist.xml` do ES em vez de reimplementar scraping ([Escopo v1](escopo-v1.md): scraping fica de fora).
- Pré-gerar miniaturas no tamanho do quadrado e guardar em cache; só as visíveis ficam na RAM, com LRU ([Orçamento de performance](orcamento-de-performance.md)).
- Validar a assinatura da imagem na indexação, não na hora de desenhar.
- Opcional depois: fallback `Named_Boxarts` e uso de `<thumbnail>` para o nível "lite" do tema ([Formato de tema](formato-de-tema.md)).

## Pontos em aberto
- Refazer o scraping das capas inválidas (principalmente SNES).
- Decidir se o fallback do RetroArch entra no v1.
- Tratar `<image>` com caminho absoluto ou fora da pasta do sistema.

Voltar: [Visão geral](visao-geral.md) · [Design das telas](design-das-telas.md)
