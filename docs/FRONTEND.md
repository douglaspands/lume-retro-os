# Trocar de frontend

O Lume Retro OS sobe o frontend por um serviço de sessão genérico. O frontend padrão é o
**lume-launcher** (`FRONTEND="lume"`, guia em [LAUNCHER.md](LAUNCHER.md)). O RetroArch
continua instalado: ele é o provedor dos cores, aberto pelo launcher com cada jogo, e
também o **frontend de reserva** (`FRONTEND="retroarch"`, o menu do RetroArch no boot).
Outro frontend pode tomar o lugar dos dois sem mexer na distro nem no contrato de jogos.

## O que um frontend recebe

| Item | Onde |
|---|---|
| Jogos | `/storage/roms/<id>/` (os `id` estão no catálogo) |
| BIOS | `/storage/bios/` |
| Saves e save states | `/storage/saves/<id>/` e `/storage/states/<id>/` |
| Capturas | `/storage/screenshots/` |
| Catálogo de sistemas e cores | `/usr/share/lume/systems.json` ([CATALOG.md](CATALOG.md)) |
| Cores libretro | `/usr/lib/libretro/<core>_libretro.so` |
| Listas de jogos do RetroArch | `lume-playlists` (opcional) |
| Listas de jogos no formato do EmulationStation | `roms/<id>/gamelist.xml`, mantidas pelo `lume-index` ([LAUNCHER.md](LAUNCHER.md)) |
| Cgroup v2 delegado ao usuário `game` | `/sys/fs/cgroup/lume/` (o frontend roda em `lume/session/`) |

## Contrato da sessão

1. O frontend é um executável em `/usr/libexec/lume/frontends/<nome>`, instalado por
   um pacote apk.
2. `/etc/conf.d/frontend` escolhe qual roda: `FRONTEND="<nome>"`.
3. O `lume-session` roda esse executável no `tty1`, como o usuário `game` (grupos
   `video`, `input`, `audio`), sem login e sem X11/Wayland. `HOME=/home/game` e
   `XDG_RUNTIME_DIR=/run/user/1000`.
4. Com cgroup v2 (`rc_cgroup_mode="unified"`), a sessão cria `/sys/fs/cgroup/lume/`, passa o
   diretório ao `game` e põe o frontend em `lume/session/` antes do `exec`. Assim o frontend
   pode criar um cgroup por jogo dentro de `lume/` e encerrar o jogo inteiro (`cgroup.kill`).
   Sem cgroup v2, a sessão registra o fato e o motivo (`no cgroup v2 for the games (...)` no
   log do kernel) e o frontend roda como antes. Quem monta o v2 é o serviço `cgroups` do
   OpenRC, que precisa estar no runlevel `sysinit` junto com o `sysfs`: sem o `sysfs` na
   mesma lista, o `cgroups` roda antes de `/sys` existir, não monta nada e ainda assim fica
   `started`.
5. Código de saída:
   - **0**: o usuário escolheu desligar (no launcher, o item Desligar das Configurações; no
     RetroArch de reserva, o item "Desligar"). A sessão grava o pendente
     (`/usr/libexec/lume/persist flush`), salva o relógio (`lume-clock save`), deixa o cartão
     limpo (para o `lume-logd` e remonta `/storage` só leitura) e desliga o aparelho. O botão
     de energia segurado (SIGUSR1 do `lume-sleep`) encerra o frontend e segue o mesmo caminho.
   - **66**: o usuário escolheu reiniciar (no launcher, Reiniciar no menu do sistema). A
     sessão faz os mesmos passos do desligar e chama `reboot` no lugar do `poweroff`; o
     `events.log` registra `frontend OK <frontend> closed by user: rebooting`. Se o botão de
     energia foi segurado enquanto isso, ele vence e o aparelho desliga.
   - **outro valor**: falha. A sessão reinicia o frontend; na 3ª falha em 60 s, ela
     para e deixa na tela o erro e o caminho do log (`ROMS/logs/frontend/boot-<n>.log`;
     só sem partição de jogos, `BOOT/logs/frontend-error.log`).
   - O fim de um jogo aberto pelo launcher nunca chega à sessão: quem roda o jogo é o
     supervisor do launcher (`lume-run`), que reabre a interface.
6. A saída padrão e de erro vão para `/var/log/frontend.log`, copiado em lote para
   `ROMS/logs/frontend/boot-<n>.log` (ver [LOGS.md](LOGS.md)). A sessão registra em
   `ROMS/logs/events.log` cada início, saída e falha do frontend. O `events.pending` é
   gravável pelo `game`, para o frontend registrar os jogos: o arquivo tem modo 666 e a pasta
   (`/run/lume/logs`) tem o grupo `game` e o sticky bit, porque cada flush move o arquivo
   para o cartão e o `game` precisa poder criá-lo de novo.
7. Configurações do frontend que devem sobreviver ao reboot precisam ir para
   `/storage/system/<frontend>/` com escrita atômica (temporário + `fsync` + `rename`).
   Só `~/.config/retroarch` é persistido automaticamente pelo `lume-persist`; o
   lume-launcher grava em `/storage/system/lume/`.

## lume-launcher (padrão)

`/usr/libexec/lume/frontends/lume` é uma linha: `exec /usr/bin/lume-run`. O `lume-run` roda a
interface (`lume-ui`) e, quando ela pede, o jogo, sempre como `game`:

| Saída do `lume-ui` | O que o `lume-run` faz |
|---|---|
| 0 (Desligar) | sai com 0: a sessão desliga |
| 64 | roda o jogo pedido em `$XDG_RUNTIME_DIR/lume/launch` e reabre a interface |
| 65 | abre o menu do RetroArch sem jogo e reabre a interface ao sair dele |
| 66 (Reiniciar) | sai com 66: a sessão reinicia o aparelho |
| outro | sai com 1: falha do frontend |

Contrato de sessão do `lume-run` (congelado): sai com **0** para desligar, **66** para
reiniciar e qualquer outro valor é falha. As constantes 64, 65 e 66 existem nos dois lados
(`lume-ui` e `lume-run`); `tests/unit/test_session_exit_codes.py` confere.

Durante o jogo, só o `lume-run` e o daemon de entrada (`lume-input`) ficam na memória.
**Fn+Start** encerra o jogo e volta ao launcher. Sair pelo menu do RetroArch também volta ao
launcher; com o launcher, o item do menu se chama "Sair", não "Desligar".

Atalhos do jogo (lume-hud-actions): o Fn nunca chega ao programa. O `lume-input` manda ao
`lume-run` o gesto (`fn_tap`, `fn_hold`, `fn_release`) ou a ação do acorde (`app_menu`,
`save_state`, `load_state`, `screenshot`, `hud`, `quit`), e o `lume-run` a executa pelo runner
(tabela em `docs/LAUNCHER.md`). O menu do RetroArch abre por **Fn+B** ou pelo item do menu do
Lume (toque no Fn); Start + Select é do jogo. Como frontend de reserva (`FRONTEND="retroarch"`,
sem `lume-run`), o script do frontend devolve o Start + Select ao menu, o único caminho até ele
dentro de um jogo.

## RetroArch (reserva)

Com `FRONTEND="retroarch"`, o boot cai direto no menu do RetroArch, como antes do launcher. O
item "Desligar" do menu desliga o console (com confirmação). O mesmo script
(`frontends/retroarch`) é o runner `retroarch` do launcher: ele grava as chaves fixas antes de
cada execução e, quando o launcher pede, as chaves de uma execução só (aspecto, slot).

Padrões de fábrica em cartões existentes (`game-experience-tuning`, D3): o RetroArch grava
todas as chaves no `retroarch.cfg` ao sair (e todas as opções do core no `.opt` dele), então
"acrescentar só o que falta" nunca traria um padrão novo. O script aplica cada chave do
`factory/retroarch/retroarch.cfg` (a cada início) e cada opção do
`factory/retroarch/config/<corename>/<corename>.opt` (num jogo daquele core) **uma única vez
por cartão**, por cima do valor gravado, e registra em `ROMS/system/lume/factory-applied` uma
linha `<arquivo> <chave>=<valor>` por padrão aplicado (`retroarch.cfg` ou `opt:<corename>`;
gravação atômica, só quando há padrão novo). Depois disso o valor do cartão é do usuário e não
muda mais; só volta o valor de fábrica de uma chave que sumiu do arquivo. Um padrão cujo valor
muda numa imagem nova tem outra linha e é aplicado de novo, uma vez. Um cartão novo (arquivo
nascido da cópia de fábrica) registra todos como aplicados. O `user_language` fica de fora: só
entra quando falta, para o idioma do build nunca trocar o escolhido (ver Idioma). As chaves
fixas entram depois, então uma chave da placa que também é padrão de fábrica (`video_threaded`)
fica sempre com o valor da placa. Sem cartão gravável, nada é aplicado. Custo por início: uma
leitura do registro num `awk` por par de arquivos, nada gravado quando não há padrão novo.

## Idioma

O idioma da interface é o `user_language` do RetroArch, persistido em
`ROMS/system/retroarch/retroarch.cfg`. No launcher, o item Idioma das Configurações grava o
idioma dele (`ROMS/system/lume/settings.toml`) e também esse `user_language`; no RetroArch de
reserva, o idioma é escolhido em Configurações → Usuário → Idioma. O padrão de fábrica vem do
`--lang` do build (`lume build <alvo> --lang pt_BR`; sem ele, inglês) e fica na configuração
de fábrica do usuário, não no `retroarch-lume.cfg`, para a escolha no menu valer. O idioma do
build só chega a cartões novos (sem `ROMS/system/retroarch/`), pela configuração de fábrica. A
escolha feita no menu nunca é sobrescrita, nem por um build com outro idioma: para trocar, use o menu. As mensagens do sistema para o usuário (como a
tela de falha do frontend) seguem esse valor (`ui_lang` em `lib.sh`), com texto em
inglês, português e espanhol; os outros idiomas caem no inglês. Os logs são sempre em
inglês ([LOGS.md](LOGS.md)). Um frontend alternativo que tenha um idioma próprio não
muda as mensagens do sistema.

## Exemplo

```sh
# /usr/libexec/lume/frontends/meufrontend
#!/bin/sh
exec /usr/bin/meufrontend --roms /storage/roms --catalog /usr/share/lume/systems.json
```

```
# /etc/conf.d/frontend
FRONTEND="meufrontend"
```

Como o sistema é imutável, `/etc/conf.d/frontend` muda numa nova imagem (pacote do
frontend + `rootfs/overlay/etc/conf.d/frontend`), não no aparelho.

O self-test da VM verifica a troca: instala um frontend falso, aponta o
`/etc/conf.d/frontend` para ele e confere que ele sobe como `game` no lugar do
frontend padrão (`frontend-swap`).
