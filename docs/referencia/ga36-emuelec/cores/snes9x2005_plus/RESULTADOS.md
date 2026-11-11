# snes9x2005_plus no A33: resultados

Avaliação das variantes recompiladas (`receita.toml`) contra o `snes9x2005_plus`
da base, jogando o Yoshi's Island (Super FX 2). Os builds estão em
`builds.jsonl`, e o perfil do PGO em `pgo/`.

Desde a segunda rodada, a avaliação compara também o `snes9x2010` e as variantes
dele (`cores/snes9x2010/`). O motivo é um defeito de som num ponto do Yoshi que
apareceu igual no 2005_plus original e nas variantes, ou seja, um defeito da
emulação e não das flags.

## Protocolo

### Preparo, antes de cada sessão

- Aparelho frio (desligado por alguns minutos) e bateria acima de 50%.
- No EmulationStation, para o Yoshi's Island: o core da sessão (opções do jogo >
  core) e **máximo desempenho ligado** (`maxperf`, opção por jogo), para o clock
  ficar fixo. Os outros jogos continuam no `snes9x2005_plus`.
- O máximo desempenho tem que ser ligado **no ES**. O "CPU governor" do menu do
  RetroArch não vale, porque o `cpu_scaling_mode` dele está desligado. Na
  primeira rodada a chave não foi gravada, e as sessões rodaram em `ondemand`.
  Com o cartão no PC, a `emuelec.conf` (na `R36-STORAGE`) deve ter a linha
  `snes["<nome da ROM>"].maxperf=1`, e o resumo deve mostrar `performance`.
- No RetroArch, FPS na tela: *Settings > On-Screen Display > Notifications >
  Display Framerate* (ou Select + direita).

### Sessão

- Jogar as fases **1-1 e 1-2** inteiras.
- Anotar a percepção (engasgos, áudio) e o FPS nos trechos pesados.
- **Sair pelo menu do RetroArch** (*Quit RetroArch*), não pelo Select + Start. No
  treino do PGO isso é obrigatório: o perfil só é gravado quando o core é
  descarregado normalmente, e se o processo for morto nada é gravado.

### Ordem

| # | Gravação | Sessões |
|---|---|---|
| 1 | imagem com `--keep-roms --wipe-storage` | `snes9x2005_plus` original, `_o2`, `_o3`; `snes9x2010` original, `_o2`, `_o3`: escolhe o vencedor e anota em quais o defeito de som aparece |
| 2 | `--part system` (chega o `_pgo_treino`) | treino: Yoshi 1-1 e 1-2; opcionalmente DKC e Kirby Super Star por cerca de 3 min |
| 3 | `--part system` (chega o `_pgo`) | `_pgo`; fumaça: Star Fox, Mega Man X2, Super Mario Kart e Kirby Super Star, 2–3 min cada |

**Aviso:** até a gravação 2, o `_pgo_treino` e o `_pgo` aparecem na lista de
cores do ES sem binário, e até a gravação 3 o `_pgo` continua sem binário.
Escolher um core sem binário só faz o jogo voltar ao menu. Isso é o preço de
gravar o `--wipe-storage` uma vez só.

Depois do treino, com o cartão no PC, confira que existe
`R36-ROMS/pgo/snes9x2005_plus/` com os `.gcda` e importe:

```bash
./cores.sh perfil snes9x2005_plus <R36-ROMS>/pgo/snes9x2005_plus
```

### Resumo térmico

Com o cartão no PC:

```bash
./cores.sh resumo <R36-ROMS>/r36-thermal.csv --roms <R36-ROMS>
```

A tabela sai em Markdown, uma linha por sessão (`boot`, `core`, `rom`), e vai
abaixo. Descarte sessões com temperatura inicial muito acima das outras.

### Critério

- Se um core engasga e o outro não, ganha o que não engasga.
- Se os dois rodam lisos, ganha o de menor ocupação média de CPU no resumo.
- Diferença abaixo de **5%** é empate, e o empate favorece o `-O2` (menor e mais
  perto da base).
- O `_pgo` só ganha se superar o vencedor sem perfil por esse mesmo critério.
  PGO igual ou pior também é resultado e fica registrado.
- Entre o 2005_plus e o 2010: se o 2010 corrige o defeito de som e roda liso, ele
  ganha mesmo usando mais CPU. O PGO do 2010 só entra depois dessa decisão.

## Sessões

### Rodada 1 (imagem `20261017-224101-test`): descartada para a decisão

Sessões no Yoshi's Island (U) (M3) (V1.1), CRC32 `cf98ddaa`, no mesmo boot.

| core | duração | governor | clock | bateria | temp. | ocupação média | núcleo mais ocupado (média) |
|---|---|---|---|---|---|---|---|
| `snes9x2005_plus` | 7 min 9 s | ondemand | 1200 MHz | 35 → 27% | 49 → 54 °C | 36,5% | 45,2% |
| `snes9x2005_plus_a33_o2` | 5 min 19 s | ondemand | 1200 MHz | 27 → 21% | 55 → 55 °C | 34,0% | 42,8% |
| `snes9x2005_plus_a33_o3` | 4 min 56 s | ondemand | 912 MHz (fixo) | 20 → 15% | 57 → 57 °C | 35,6% | 43,8% |

- Percepção: um defeito de som num mesmo momento do jogo nos três cores.
- Descartada porque o máximo desempenho não foi gravado (governor `ondemand`), a
  bateria ficou abaixo de 50% e o `_o3` rodou a 912 MHz, provavelmente por
  limite do kernel com bateria em 20% ou menos.
- Indício, não decisão: a 1200 MHz, o `_o2` ocupou cerca de 5–7% menos que o
  original.

### Rodada 2 (imagem `20261017-233302-test`)

Sessões no Yoshi's Island (U) (M3) (V1.1), CRC32 `cf98ddaa`, SHA1
`34612a93741f156d6e497462ab7f253cb8a959a0`, no mesmo boot (`37707fd0`), nesta
ordem. A `emuelec.conf` do cartão tem `snes["…Yoshi's Island…"].maxperf=1`.

| core | duração | governor | clock | temp. | ocupação média | núcleo mais ocupado (média / máx.) | percepção |
|---|---|---|---|---|---|---|---|
| `snes9x2010` | 4 min 20 s | ondemand | 1200 MHz | 45 → 54 °C | 39,2% | 60,4% / 100% | pior que o 2005_plus |
| `snes9x2010_a33_o2` | 2 min 58 s | performance | 1200 MHz | 54 → 55 °C | 35,5% | 66,5% / 100% | pior que o 2005_plus |
| `snes9x2010_a33_o3` | 3 min 5 s | performance | **1104 MHz** | 56 → 57 °C | 37,1% | 80,2% / 100% | o pior de todos |
| `snes9x2005_plus` | 2 min 53 s | performance | 1104 MHz | 59 → 59 °C | 34,0% | 41,5% / 54% | |
| `snes9x2005_plus_a33_o2` | 3 min 13 s | performance | 1104 MHz | 59 → 59 °C | **32,9%** | 42,5% / 58% | **aparentemente o melhor** |
| `snes9x2005_plus_a33_o3` | 4 min 3 s | performance | 1104 MHz | 61 → 60 °C | 37,4% | 45,0% / 55% | |

- **Defeito de som:** apareceu nos seis cores, inclusive nos dois `snes9x2010`.
  Não é do 2005_plus nem das flags; fica fora desta change.
- **Condições:** a bateria ficou entre 14% e 22%, carregando, abaixo dos 50% do
  protocolo. A partir da 3ª sessão (56 °C ou mais) o clock ficou em 1104 MHz
  mesmo em `performance`, provavelmente por limite térmico ou da bateria do
  kernel. As três sessões do 2005_plus rodaram todas a 1104 MHz, em
  `performance` e na mesma faixa de temperatura, então são comparáveis entre si.
- **snes9x2010:** satura um núcleo (100% em vários momentos) nas três versões,
  o que bate com a percepção de que se saiu pior. O `_o3` rodou a 1104 MHz
  contra 1200 MHz do `_o2`, o que piora a comparação dele, mas o núcleo mais
  ocupado ficou em 100% na mediana.
- **snes9x2005_plus:** `_o2` 3,2% abaixo do original na ocupação média (empate
  pelo limiar de 5%, e o empate favorece o `-O2`); `_o3` 10% acima do original.
  Uma explicação provável para o `-O3` pior é o código maior (663 KB contra
  556 KB), que pressiona o cache de instruções de 32 KB do Cortex-A7.

### Treino do PGO (imagem `20261018-001638-test`)

`snes9x2005_plus_a33_pgo_treino` (`-O2` com `-fprofile-generate`), boot
`1b83f481`, `performance`, bateria entre 27% e 33%, carregando.

| ROM (CRC32) | duração | clock | temp. | núcleo mais ocupado (média / mediana) |
|---|---|---|---|---|
| Yoshi's Island (U) (M3) (V1.1) (`cf98ddaa`) | 7 min 50 s | 1200 MHz | 52 → 58 °C | 98,2% / 100% |
| Donkey Kong Country (USA) (`c946dca0`) | 1 min 55 s | 1200 MHz | 58 → 59 °C | 77,7% / 100% |
| Kirby Super Star (U) [!] (`89d0f7dc`) | 2 min 48 s | 1104 MHz | 58 → 60 °C | 96,7% / 100% |

- O instrumentado satura um núcleo, como esperado. O perfil conta proporções,
  não tempo, então isso não o invalida.
- Saída pelo menu do RetroArch: os 31 `.gcda` esperados apareceram em
  `R36-ROMS/pgo/snes9x2005_plus/` e foram importados com `./cores.sh perfil`
  (`pgo/perfil.json` tem os hashes). `data.c` e `globals.c` não têm funções e
  não geram perfil.

### Rodada 3: PGO (imagem `20261018-004615-test`)

Boot `0c39dac4`, bateria entre 37% e 44%, carregando. As três sessões do Yoshi
rodaram em `performance` a 1200 MHz, em sequência, e por isso são as mais
comparáveis da avaliação. As aberturas de poucos segundos no `_pgo_treino` e no
original (troca de core) ficaram de fora.

| core | ROM (CRC32) | duração | clock | temp. | ocupação média | núcleo mais ocupado (média / máx.) | contra o original |
|---|---|---|---|---|---|---|---|
| `snes9x2005_plus` | Yoshi (`cf98ddaa`) | 3 min 32 s | 1200 MHz | 53 → 56 °C | 35,2% | 42,6% / 54% | — |
| `snes9x2005_plus_a33_o2` | Yoshi (`cf98ddaa`) | 3 min 31 s | 1200 MHz | 56 → 57 °C | **31,6%** | 40,2% / 56% | **−10,2%** |
| `snes9x2005_plus_a33_pgo` | Yoshi (`cf98ddaa`) | 2 min 58 s | 1200 MHz | 58 → 58 °C | 33,2% | 43,6% / 60% | −5,7% |
| `snes9x2005_plus_a33_pgo` | Star Fox (U) (V1.2) (`8fc4e6d0`) | 1 min 25 s | 1104 MHz | 60 → 61 °C | 37,0% | 59,1% / 98% | fumaça |
| `snes9x2005_plus_a33_pgo` | Donkey Kong Country (USA) (`c946dca0`) | 1 min 27 s | 1104 MHz | 60 → 58 °C | 27,4% | 30,7% / 38% | fumaça |

- **`_o2` contra o original:** 10,2% menos ocupação. Passa do limiar de 5%; na
  rodada 2, a 1104 MHz, foram 3,2%.
- **`_pgo` contra o `_o2`:** 5,1% **mais** ocupação. O PGO não supera o
  vencedor sem perfil e fica descartado. Ele rodou na sessão mais quente
  (58 °C), mas ainda no mesmo clock.
- **Fumaça:** Star Fox e Donkey Kong Country rodaram no `_pgo` (o Star Fox
  satura um núcleo em picos, 98%, a 1104 MHz); Mega Man X2, Super Mario Kart e
  Kirby Super Star não foram jogados nesta rodada. Como o PGO perdeu, a fumaça
  dele não decide nada.
- **Percepção do usuário:** nenhuma diferença perceptível entre o original, o
  `_o2` e o `_pgo`. Era o esperado: no 2005_plus o Yoshi não passa de 60% num
  núcleo, então 10% a menos de CPU não aparece na tela.
- **Defeito de tela:** em algum momento da rodada, a parte de baixo da tela
  piscou mostrando a parte de cima, um defeito que o usuário já tinha visto e
  atribui ao calor. Nesta rodada, a temperatura passou de 58 °C e o clock caiu
  para 1104 MHz. Não é do core (já aparecia antes); fica para a investigação
  do limite de clock e temperatura.

## Resumos térmicos

(colar aqui a saída do `./cores.sh resumo` de cada gravação)

## Decisões

- Vencedor sem PGO (rodada 2): **`snes9x2005_plus_a33_o2`**. Empata com o
  original pelo critério (3,2% menos ocupação), e o empate favorece o `-O2`; o
  usuário também o percebeu como o melhor. O `_o3` ficou pior que o original.
  As variantes de PGO usam `base = "o2"`.
- `snes9x2010` (rodada 2): descartado. É mais pesado no A33 (satura um núcleo),
  rodou pior nas três versões e não corrige o defeito de som. Sem PGO para ele.
- PGO contra o vencedor e contra o original (rodada 3): o `_pgo` ficou 5,7%
  abaixo do original, mas 5,1% **acima** do `_o2`. Não ganha; o perfil fica
  guardado em `pgo/`, mas o PGO não é promovido.
- Candidato para a promoção a padrão do SNES: **`snes9x2005_plus_a33_o2`**
  (−10,2% contra o original na rodada 3, −3,2% na rodada 2).
- **Promovido nesta mesma change, por decisão do usuário:** o `_o2` virou o
  core `snes9x2005_plus_a33` (o mesmo binário, sha256 `a3c438e1…250c8`) e o
  padrão do SNES (`snes.core` na `emuelec.conf`). As variantes perdedoras
  (`_o3`, `_pgo_treino`, `_pgo` e as duas do `snes9x2010`) saíram da imagem;
  as receitas, o `builds.jsonl` e o perfil continuam aqui.
