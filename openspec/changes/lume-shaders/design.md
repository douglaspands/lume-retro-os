# Design

## Context

Ver `proposal.md`. O RetroArch da imagem é compilado com GLES (`--enable-opengles`), que
inclui os shaders GLSL (`.glslp`/`.glsl`); os três shaders são GLSL de um passe, escritos
para GLES 2 (Mali-400 do GA36) e válidos também na Mali-G31 do R36S e no virgl da VM. A
configuração do usuário fica em `~/.config/retroarch`, que o `r36os-persist` copia de e
para `ROMS/system/retroarch`; as chaves fixas do sistema estão em `retroarch-lume.cfg` e
são escritas pelo frontend a cada início.

## Decisions

### D1. Shaders no sistema, não na pasta do usuário

Os arquivos vão para `/usr/share/libretro/shaders/lume-shaders/` (no `SYSTEM`, só
leitura) e `video_shader_dir` vira chave fixa apontando para `/usr/share/libretro/shaders`.
Assim os shaders chegam a todo cartão a cada atualização e não ocupam a `ROMS`.

- *Alternativa descartada:* `~/.config/retroarch/shaders/lume-shaders/` pela configuração
  de fábrica: só chegaria a cartões novos, e a cópia ficaria na `ROMS`, desatualizada a
  cada versão nova dos shaders.
- Consequência: a pasta de shaders do menu é só leitura. Os presets que o usuário salva
  ("Salvar preset do jogo/core") vão para a pasta de configuração do RetroArch, que
  continua na `ROMS`.

### D2. Cópia sem alteração e nada ligado

Os seis arquivos são copiados como estão no projeto anterior (o teste confere o
conteúdo pelo SHA256 dos fontes copiados). Os serviços que ligavam os shaders por
padrão ficam de fora: a escolha é do usuário.

## Risks / Trade-offs

- **[Shader pesado no GA36]** → Os três foram medidos no projeto anterior na Mali-400
  (um passe, uma leitura de textura); e são opcionais.
- **[Pasta de shaders só leitura]** → Presets do usuário vão para a pasta de
  configuração, que é gravável e persiste na `ROMS`.
