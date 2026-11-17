# Proposal

## Why

O boot roda a verificação completa do exFAT da `ROMS` em todo boot (`fsck.exfat -p`,
`initramfs/lib/storage.sh`). No GA36 ela custou 0,87 s com o cartão quase vazio, e cresce com a
biblioteca, porque percorre todos os diretórios. Isso vai contra a prioridade do boot rápido
(P-58). O aparelho não tem relógio de verdade (P-07), então não dá para agendar verificação ou
manutenção por data. E o usuário não tem como pedir manutenção do cartão (TRIM, verificação)
sem tirá-lo do console. Pendência P-64, itens 1, 2 e 4; o item 3 (bateria fraca) foi para a
change do governor por decisão do usuário (2026-11-17).

## What Changes

- **Verificação só quando precisa**: o initramfs lê o bit *VolumeDirty* (e o *MediaFailure*) do
  setor de boot do exFAT, um setor só, e roda o reparo (`fsck.exfat -p`) só quando o volume
  está sujo ou quando o usuário pediu a verificação. Num boot limpo, nenhuma verificação.
  **BREAKING** para o requisito "Verificação da partição de jogos a cada boot".
- **Item "Cartão" nas Configurações do launcher**: mostra o espaço livre e em que boot foram a
  última otimização e a última verificação (contador de boots, sem data); "Otimizar agora" roda
  o TRIM da `ROMS` com o progresso e o resultado na tela; "Verificar no próximo boot" deixa um
  pedido que o boot seguinte consome.
- **Serviço root pequeno** que executa só esses dois pedidos do launcher, que roda como o
  usuário `game`, sem custo enquanto ninguém pede nada.
- **Read-ahead do cartão** maior que os 128 KiB de hoje, por regra do udev, com o valor escolhido
  pela medição da carga de uma ROM grande.
- **Prova de que o desligamento deixa o volume limpo**: se o desligamento normal deixar o bit
  ligado, a verificação continuaria em todo boot, então a change corrige o desligamento antes
  de depender do bit.

Fora do escopo: desligamento por bateria fraca (change do governor), verificação agendada por
data (sem relógio, P-07), troca do exFAT por outro sistema de arquivos.

## Capabilities

### New Capabilities
- `card-maintenance`: a manutenção do cartão pedida pelo usuário (TRIM e verificação no próximo
  boot), o registro de quando cada uma rodou e o read-ahead do cartão.

### Modified Capabilities
- `boot-runtime`: a verificação da `ROMS` deixa de rodar em todo boot e passa a rodar com o
  volume sujo ou a pedido.
- `game-launcher`: as Configurações do aparelho ganham o item "Cartão".

## Impact

- `initramfs/lib/storage.sh` e `initramfs/init` (leitura do bit, pedido de verificação);
  testes do initramfs.
- Desligamento (`session` e o OpenRC), se a prova mostrar o volume sujo depois de um
  desligamento normal.
- `lume/lume-ui` (item "Cartão", textos en/pt/es) e o protótipo do launcher
  (`docs/lume-launcher/prototipo/`), pela regra da régua.
- Um serviço novo no pacote `lume-saves` ou `lume-core` (verbos `trim` e `check-next-boot`) e
  uma regra do udev do read-ahead no `lume-power`.
- `docs/LOGS.md` (eventos `roms` novos), `docs/LAUNCHER.md`, guias de bring-up, P-64 e P-58
  (frente 3) atualizados.
- Provas no GA36 e no R36S (o mesmo cartão, um console de cada vez), incluindo corte de energia.
