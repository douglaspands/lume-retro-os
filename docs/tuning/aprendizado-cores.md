# Aprendizado de cores: fica no aparelho

O que as medições ensinam sobre qual core roda melhor cada jogo é **dado do aparelho**, não do
projeto (decisão do usuário, 2026-11-20): cada hardware tem o seu resultado, e o projeto vai
chegar a outros consoles. O repositório guarda só o **método** e o **formato**; o resultado vive
no cartão, em `ROMS/system/lume/cores-learned.toml`, para uma funcionalidade usar como parâmetro
(P-116). Os números agregados de cada console continuam no relatório de medição dele
([`ga36.md`](ga36.md), `r36s.md`), sem nome de jogo.

## Como se mede

`tests/device/tuning_ab.py` com um plano de comparação de cores (`tests/device/tuning/*.toml`,
variantes `core = "..."`): cada jogo roda no core padrão da pasta (A1), em cada core alternativo
(B, pela opção por jogo do launcher, devolvida depois) e de novo no padrão (A2), 30 s de
aquecimento e 60 s de medição. Conta: se abre, velocidade do core (≥ 99% é cheia), quadros
mostrados por segundo, clock médio escolhido pelo governor (menor = menos bateria), temperatura e
falhas de som. O vencedor de um jogo é o de menor clock entre os de velocidade cheia; sem nenhum
de velocidade cheia, o mais rápido.

## O arquivo no cartão

`ROMS/system/lume/cores-learned.toml`, gravado por `tests/device/cores_learned.py <console>` depois
de cada comparação (lê `out/tuning/<console>-cores.jsonl`, o índice do launcher no cartão para o
arquivo de cada posição, o `gamelist.xml` e o mapa privado de famílias do conjunto de teste):

```toml
schema = 1

[[game]]
system = "<id do sistema>"
file = "<arquivo da ROM na pasta do sistema>"
name = "<nome do jogo>"
board = "<placa de hardware>"
console = "<ga36 | r36s | ...>"      # um cartão serve vários consoles: um [[game]] por console
date = "AAAA-MM-DD"
default_core = "<core padrão da pasta>"
best = "<core escolhido>"

[[game.result]]
core = "<core>"
opens = true                       # false com `reason` quando o romset não abre
speed = 1.002                      # 1.0 = velocidade cheia
fps = 54.4                         # quadros mostrados por segundo
clock_mhz = 816                    # clock médio da CPU
audio_failures = 0                 # segundos com falha de som
temp_c = 49.8
```

O arquivo é do cartão: o nome dos jogos nunca vai para o repositório.

**Espaço no cartão (pedido do usuário, 2026-11-20):** o arquivo só substitui, nunca acumula. Há
uma entrada por jogo e por console, a medição nova troca a antiga, e as entradas dos outros
consoles são mantidas como estão. Ele cresce com o número de jogos medidos (~800 bytes por jogo e
console: 24 jogos = 19 KB; 1000 jogos nos dois consoles ≈ 1,6 MB) e nunca com o número de
medições. Gravação atômica (arquivo temporário e `mv`) e um teto de 1 MiB: acima disso nada é
gravado e o motivo aparece. Quem escrever nesse arquivo no futuro (P-116) segue as mesmas
regras.

## Perguntas em aberto

- A mesma placa se comporta igual com outros jogos? (medir mais jogos por placa)
- Um core por placa resolve, ou há jogos da mesma placa que pedem cores diferentes?
- O próprio console pode descobrir o melhor core de um jogo (P-116)?
- Quanto da escolha é limitado pela versão do romset, e não pela velocidade do core?
