# Trocar de frontend

O Lume Retro OS sobe o frontend por um serviço de sessão genérico. O RetroArch é só o
frontend inicial: outro frontend pode tomar o lugar dele sem mexer na distro nem no
contrato de jogos.

## O que um frontend recebe

| Item | Onde |
|---|---|
| Jogos | `/storage/roms/<id>/` (os `id` estão no catálogo) |
| BIOS | `/storage/bios/` |
| Saves e save states | `/storage/saves/<id>/` e `/storage/states/<id>/` |
| Capturas | `/storage/screenshots/` |
| Catálogo de sistemas e cores | `/usr/share/r36os/systems.json` ([CATALOG.md](CATALOG.md)) |
| Cores libretro | `/usr/lib/libretro/<core>_libretro.so` |
| Listas de jogos do RetroArch | `r36os-playlists` (opcional) |

## Contrato da sessão

1. O frontend é um executável em `/usr/libexec/r36os/frontends/<nome>`, instalado por
   um pacote apk.
2. `/etc/conf.d/frontend` escolhe qual roda: `FRONTEND="<nome>"`.
3. O `r36os-session` roda esse executável no `tty1`, como o usuário `game` (grupos
   `video`, `input`, `audio`), sem login e sem X11/Wayland. `HOME=/home/game` e
   `XDG_RUNTIME_DIR=/run/user/1000`.
4. Código de saída:
   - **0**: o usuário escolheu sair. A sessão grava o pendente
     (`/usr/libexec/r36os/persist flush`) e desliga o aparelho.
   - **diferente de 0**: falha. A sessão reinicia o frontend; na 3ª falha em 60 s, ela
     para e deixa na tela o erro e o caminho do log (`ROMS/logs/frontend/boot-<n>.log`;
     só sem partição de jogos, `BOOT/logs/frontend-error.log`).
5. A saída padrão e de erro vão para `/var/log/frontend.log`, copiado em lote para
   `ROMS/logs/frontend/boot-<n>.log` (ver [LOGS.md](LOGS.md)). A sessão registra em
   `ROMS/logs/events.log` cada início, saída e falha do frontend.
6. Configurações do frontend que devem sobreviver ao reboot precisam ir para
   `/storage/system/<frontend>/` com escrita atômica (temporário + `fsync` + `rename`).
   Só `~/.config/retroarch` é persistido automaticamente pelo `r36os-persist`.

## Idioma

O idioma da interface é o `user_language` do RetroArch, escolhido pelo usuário em
Configurações → Usuário → Idioma e persistido em `ROMS/system/retroarch/retroarch.cfg`.
O padrão de fábrica vem do `--lang` do build (`r36os build <alvo> --lang pt_BR`; sem ele,
inglês) e fica na configuração de fábrica do usuário, não no `retroarch-lume.cfg`, para
a escolha no menu valer. O idioma do build também vale para cartões que já têm
configuração: a cada boot o `r36os-persist` compara o idioma do build com o último que
rodou no cartão (`ROMS/system/etc/language`) e, só quando mudou, troca o `user_language`.
Com o mesmo idioma de build, a escolha feita no menu nunca é tocada. As mensagens do sistema para o usuário (como a
tela de falha do frontend) seguem esse valor (`ui_lang` em `lib.sh`), com texto em
inglês, português e espanhol; os outros idiomas caem no inglês. Os logs são sempre em
inglês ([LOGS.md](LOGS.md)). Um frontend alternativo que tenha um idioma próprio não
muda as mensagens do sistema.

## Exemplo

```sh
# /usr/libexec/r36os/frontends/meufrontend
#!/bin/sh
exec /usr/bin/meufrontend --roms /storage/roms --catalog /usr/share/r36os/systems.json
```

```
# /etc/conf.d/frontend
FRONTEND="meufrontend"
```

Como o sistema é imutável, `/etc/conf.d/frontend` muda numa nova imagem (pacote do
frontend + `rootfs/overlay/etc/conf.d/frontend`), não no aparelho.

O self-test da VM verifica a troca: instala um frontend falso, aponta o
`/etc/conf.d/frontend` para ele e confere que ele sobe como `game` no lugar do
RetroArch (`frontend-swap`).
