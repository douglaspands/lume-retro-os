#!/bin/sh
# Tarefa 5.5: logs.sh (configuração, descarga em lote e rotação) em busybox, com os
# caminhos apontados para um diretório temporário. Também o ui_lang do lib.sh (idioma
# das mensagens para o usuário, lido do user_language do RetroArch).
set -u
cd "$(dirname "$0")/../.."
W=$(mktemp -d)
FAILS=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; FAILS=$((FAILS + 1)); fi; }

export LOGS_DIR=$W/storage/logs LOGS_RAM=$W/ram LOGS_CONF=$W/storage/system/etc/logs.conf
export LOGS_MOUNT=/ FRONTEND_LOG=$W/frontend.log
export RA_USER_CFG=$W/retroarch.cfg RA_FACTORY_CFG=$W/factory.cfg
. rootfs/overlay/usr/libexec/r36os/lib.sh
. rootfs/overlay/usr/libexec/r36os/logs.sh
mkdir -p "$LOGS_RAM" "$LOGS_DIR/boot" "$LOGS_DIR/hw" "$LOGS_DIR/metrics" "$LOGS_DIR/frontend" \
	"$(dirname "$LOGS_CONF")"
echo 7 > "$LOGS_RAM/boot-n"

### Configuração
logs_conf
check "conf: padrões sem arquivo" '[ "$LOG_ENABLE $LOG_INTERVAL $LOG_FLUSH $LOG_KEEP $LOG_MAX_MB" = "1 5 60 30 64" ]'
printf '%s\n' "$LOGS_CONF_DEFAULT" > "$LOGS_CONF"
logs_conf
check "conf: arquivo padrão = padrões" '[ "$LOG_ENABLE $LOG_INTERVAL $LOG_FLUSH $LOG_KEEP $LOG_MAX_MB" = "1 5 60 30 64" ]'
check "conf: arquivo padrão em inglês (ASCII)" '! LC_ALL=C grep -q "[^ -~]" "$LOGS_CONF"'
printf 'enable=0\ninterval = 2\nflush=1\nkeep_boots=12\nmax_mb=3\n# keep_boots=99\njunk\n' > "$LOGS_CONF"
logs_conf
check "conf: valores, espaços, comentário e limites" '[ "$LOG_ENABLE $LOG_INTERVAL $LOG_FLUSH $LOG_KEEP $LOG_MAX_MB" = "0 2 60 12 64" ]'
printf 'keep_boots=10\nmax_mb=8\n' > "$LOGS_CONF"

### Eventos e métricas em lote
event test OK "first event"
event test FAIL "second, with spaces"
check "evento: só na RAM antes da descarga" '[ ! -e $LOGS_DIR/events.log ] && [ "$(grep -c "" $LOGS_RAM/events.pending)" = 2 ]'
echo "time,uptime_s,frontend" > "$LOGS_RAM/metrics.header"
echo "2026-11-09T10:00:00,1.0,menu" >> "$LOGS_RAM/metrics.pending"
echo "2026-11-09T10:00:05,6.0,game" >> "$LOGS_RAM/metrics.pending"
echo "frontend line 1" > "$FRONTEND_LOG"
logs_flush
check "evento: descarregado com data, boot, categoria e resultado" 'grep -qE "^[0-9-]{10}T[0-9:]{8} 7 test FAIL second, with spaces$" $LOGS_DIR/events.log && [ ! -e $LOGS_RAM/events.pending ]'
check "métricas: cabeçalho uma vez + 2 linhas" '[ "$(grep -c "" $LOGS_DIR/metrics/boot-7.csv)" = 3 ] && head -n 1 $LOGS_DIR/metrics/boot-7.csv | grep -q "^time,uptime_s"'
echo "2026-11-09T10:00:10,11.0,menu" >> "$LOGS_RAM/metrics.pending"
logs_flush
check "métricas: append sem repetir cabeçalho" '[ "$(grep -c "" $LOGS_DIR/metrics/boot-7.csv)" = 4 ] && [ "$(grep -c "^time," $LOGS_DIR/metrics/boot-7.csv)" = 1 ]'
check "frontend: copiado para frontend/boot-7.log" 'grep -q "line 1" $LOGS_DIR/frontend/boot-7.log'
echo "line 2" >> "$FRONTEND_LOG"
logs_flush
check "frontend: recopiado quando cresce" 'grep -q "line 2" $LOGS_DIR/frontend/boot-7.log'
check "sem temporários" '[ -z "$(find $LOGS_DIR $LOGS_RAM -name "*.flush.*" -o -name "*.tmp.*")" ]'

### Teto de um CSV de métricas
METRICS_MAX_BYTES=200
i=0; while [ $i -lt 20 ]; do echo "2026-11-09T10:01:00,$i,menu" >> "$LOGS_RAM/metrics.pending"; i=$((i + 1)); done
logs_flush
size=$(stat -c %s $LOGS_DIR/metrics/boot-7.csv)
i=0; while [ $i -lt 20 ]; do echo "2026-11-09T10:02:00,$i,menu" >> "$LOGS_RAM/metrics.pending"; i=$((i + 1)); done
logs_flush
check "métricas: para de crescer no teto" '[ "$(stat -c %s $LOGS_DIR/metrics/boot-7.csv)" = "$size" ] && [ ! -e $LOGS_RAM/metrics.pending ]'
METRICS_MAX_BYTES=4194304

### Rotação por número de boots (keep_boots=10), em ordem numérica
for n in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do echo "boot $n" > "$LOGS_DIR/boot/boot-$n.log"; : > "$LOGS_DIR/hw/boot-$n.txt"; done
logs_rotate
check "rotação: 10 boots em boot/" '[ "$(ls $LOGS_DIR/boot | wc -l)" = 10 ]'
check "rotação: apaga os mais antigos (1-5), mantém 6-15" '[ ! -e $LOGS_DIR/boot/boot-5.log ] && [ -e $LOGS_DIR/boot/boot-6.log ] && [ -e $LOGS_DIR/boot/boot-15.log ] && [ -e $LOGS_DIR/boot/boot-10.log ]'
check "rotação: hw/ também" '[ "$(ls $LOGS_DIR/hw | wc -l)" = 10 ]'

### events.log gira em EVENTS_MAX_BYTES, mantendo 3
EVENTS_MAX_BYTES=100
for r in 1 2 3 4 5; do
	head -c 150 /dev/zero | tr '\0' x > "$LOGS_DIR/events.log"
	echo "round $r" >> "$LOGS_DIR/events.log"
	logs_rotate
done
check "eventos: gira e mantém 3 antigos" '[ ! -e $LOGS_DIR/events.log ] && [ -e $LOGS_DIR/events.3.log ] && [ ! -e $LOGS_DIR/events.4.log ] && grep -q "round 5" $LOGS_DIR/events.1.log && grep -q "round 3" $LOGS_DIR/events.3.log'
EVENTS_MAX_BYTES=1048576

### Teto total (max_mb=8): métricas antigas primeiro, nunca o boot atual (7)
rm -f $LOGS_DIR/metrics/*
for n in 3 4 5 6; do head -c 2097152 /dev/zero > "$LOGS_DIR/metrics/boot-$n.csv"; done
head -c 2097152 /dev/zero > "$LOGS_DIR/metrics/boot-7.csv"
logs_rotate
used=$(du -sk $LOGS_DIR | cut -f1)
check "teto: dentro de 8 MiB" '[ "$used" -le 8192 ]'
check "teto: apagou a métrica mais antiga" '[ ! -e $LOGS_DIR/metrics/boot-3.csv ]'
check "teto: manteve o boot atual" '[ -e $LOGS_DIR/metrics/boot-7.csv ]'
check "teto: logs de boot intactos enquanto há métrica antiga" '[ "$(ls $LOGS_DIR/boot | wc -l)" = 10 ]'

### Sem ROMS: nada vai para o cartão
LOGS_MOUNT=$W/not-mounted
mkdir -p "$LOGS_MOUNT"
event test OK "no roms"
logs_flush
check "sem ROMS: evento fica na RAM" 'grep -q "no roms" $LOGS_RAM/events.pending && ! grep -q "no roms" $LOGS_DIR/events*.log'

### Idioma das mensagens para o usuário (user_language do RetroArch)
check "ui_lang: sem configuração, inglês" '[ "$(ui_lang)" = en ]'
echo 'user_language = "7"' > "$RA_FACTORY_CFG"
check "ui_lang: padrão de fábrica pt_BR" '[ "$(ui_lang)" = pt ]'
printf 'menu_driver = "ozone"\nuser_language = "3"\n' > "$RA_USER_CFG"
check "ui_lang: escolha do usuário (espanhol) vence a fábrica" '[ "$(ui_lang)" = es ]'
echo 'user_language = "0"' > "$RA_USER_CFG"
check "ui_lang: inglês" '[ "$(ui_lang)" = en ]'
echo 'user_language = "4"' > "$RA_USER_CFG"
check "ui_lang: idioma sem texto (alemão) cai no inglês" '[ "$(ui_lang)" = en ]'
echo 'user_language = "8"' > "$RA_USER_CFG"
check "ui_lang: português de Portugal usa o texto em português" '[ "$(ui_lang)" = pt ]'

### Rastreio do frontend (trace/): descarga, teto no cartão e na RAM
LOGS_MOUNT=/
rm -f "$LOGS_RAM"/*.pending
mkdir -p "$LOGS_DIR/trace"
trace "hello trace"
check "trace: linha com hora na RAM" 'grep -qE "^[0-9:]{8} hello trace$" $LOGS_RAM/trace.pending'
logs_flush
check "trace: descarregado em trace/boot-7.log" 'grep -q "hello trace" $LOGS_DIR/trace/boot-7.log && [ ! -e $LOGS_RAM/trace.pending ]'
TRACE_MAX_BYTES=300
i=0; while [ $i -lt 100 ]; do trace "xxxxxxxxxxxxxxxxxxxx"; i=$((i + 1)); done
check "trace: buffer na RAM tem teto" '[ "$(stat -c %s $LOGS_RAM/trace.pending)" -lt 340 ]'
logs_flush
size=$(stat -c %s $LOGS_DIR/trace/boot-7.log)
i=0; while [ $i -lt 100 ]; do trace "yyyyyyyyyyyyyyyyyyyy"; i=$((i + 1)); done
logs_flush
check "trace: arquivo para de crescer no teto" '[ "$(stat -c %s $LOGS_DIR/trace/boot-7.log)" = "$size" ]'
TRACE_MAX_BYTES=2097152

### Teto total também alcança o rastreio (max_mb=8): o mais antigo sai, o boot atual fica
rm -f $LOGS_DIR/metrics/* $LOGS_DIR/trace/*
for n in 3 4 5 6 7; do head -c 2097152 /dev/zero > "$LOGS_DIR/trace/boot-$n.log"; done
logs_rotate
check "teto: rastreio dentro de 8 MiB" '[ "$(du -sk $LOGS_DIR | cut -f1)" -le 8192 ]'
check "teto: apagou o rastreio mais antigo" '[ ! -e $LOGS_DIR/trace/boot-3.log ]'
check "teto: manteve o rastreio do boot atual" '[ -e $LOGS_DIR/trace/boot-7.log ]'

### Log do frontend na RAM: passando do teto, fica só o fim
FRONTEND_RAM_MAX_BYTES=1000 FRONTEND_RAM_KEEP_BYTES=200
head -c 3000 /dev/zero | tr '\0' a > "$FRONTEND_LOG"
echo "last line" >> "$FRONTEND_LOG"
frontend_log_trim "$FRONTEND_LOG"
check "frontend na RAM: aparado para o fim" '[ "$(stat -c %s $FRONTEND_LOG)" = 200 ] && tail -n 1 $FRONTEND_LOG | grep -q "last line"'
frontend_log_trim "$FRONTEND_LOG"
check "frontend na RAM: abaixo do teto fica intacto" '[ "$(stat -c %s $FRONTEND_LOG)" = 200 ]'
FRONTEND_RAM_MAX_BYTES=8388608 FRONTEND_RAM_KEEP_BYTES=1048576

### logd: RetroArch vivo mas sem responder (processo falso chamado retroarch)
# Esta parte vale no busybox (pidof do console e do container); no pidof do PC não acha o script.
export LOGD_LIB=1 LOGD_LIBDIR="$PWD/rootfs/overlay/usr/libexec/r36os"
. rootfs/overlay/usr/libexec/r36os/logd
RECOVER_MAX=0   # the checks below only observe; the recovery (kill) is tested further down
rm -f "$LOGS_RAM"/*.pending "$LOGS_DIR"/events*.log "$LOGS_DIR"/trace/*
mkdir -p "$W/bin"
# Script chamado retroarch: o kernel dá a ele o nome (comm) retroarch, que é o que o pidof acha
printf '#!/bin/sh\nwhile :; do sleep 1; done\n' > "$W/bin/retroarch"
chmod +x "$W/bin/retroarch"
"$W/bin/retroarch" &
FAKE=$!
sleep 1
FE_STATE=no_answer
LOG_INTERVAL=5
trace_sample; trace_sample
check "logd: 2 amostras sem resposta ainda não são congelamento" '! grep -q "no answer" $LOGS_RAM/events.pending 2>/dev/null && ! grep -q "no answer" $LOGS_DIR/events.log 2>/dev/null'
trace_sample
check "logd: 3ª amostra declara o congelamento (evento de falha)" 'grep -q "frontend FAIL retroarch pid $FAKE alive but no answer for 15s" $LOGS_DIR/events.log'
check "logd: linha do rastreio com estado, threads e descritores DRM" 'grep -qE "fe=no_answer pid=$FAKE st=[A-Z] utime=[0-9]+ stime=[0-9]+ threads=[0-9]+ dri_fds=[0-9]+ gpu_mhz=[0-9]* vblank=[0-9]* pcm=[^ ]+ tasks=" $LOGS_DIR/trace/boot-7.log'
check "logd: instantâneo detalhado gravado de imediato no cartão" 'grep -q "=== snapshot of retroarch pid $FAKE" $LOGS_DIR/trace/boot-7.log && grep -q "^[0-9:]* thread $FAKE " $LOGS_DIR/trace/boot-7.log && { [ ! -s /proc/interrupts ] || grep -q " irq " $LOGS_DIR/trace/boot-7.log; }'
i=0; while [ $i -lt 40 ]; do trace_sample; i=$((i + 1)); done
check "logd: instantâneos limitados por boot (DEEP_MAX)" '[ "$(grep -c "=== snapshot of" $LOGS_DIR/trace/boot-7.log)" -le "$DEEP_MAX" ] && [ "$(grep -c "=== snapshot of" $LOGS_DIR/trace/boot-7.log)" -ge 2 ]'
FE_STATE=menu
trace_sample
check "logd: voltou a responder (evento OK)" 'grep -q "frontend OK retroarch answering again" $LOGS_DIR/events.log'
check "logd: rastreio dentro do teto de tamanho" '[ "$(stat -c %s $LOGS_DIR/trace/boot-7.log)" -le $((TRACE_MAX_BYTES + 65536)) ]'
kill "$FAKE" 2>/dev/null
FE_STATE=stopped
trace_sample
check "logd: sem retroarch, linha pid=-" 'tail -n 1 $LOGS_DIR/trace/boot-7.log | grep -q "fe=stopped pid=-"'

### logd: audio stalls reported by RetroArch (patch 0003) become events
AUDIO_LOG_POS=0
rm -f "$LOGS_RAM"/events.pending "$LOGS_DIR"/events*.log
echo "[INFO] [Core] Using content: x.gba" > "$FRONTEND_LOG"
audio_watch; logs_flush
check "audio: no stall line, no audio event" '! grep -q " audio " $LOGS_DIR/events.log 2>/dev/null'
echo "[ERROR] [ALSA] Playback stalled: no room in the buffer after 500 ms (hw_ptr not moving)." >> "$FRONTEND_LOG"
audio_watch; audio_watch; logs_flush
check "audio: a stall becomes one failure event, not one per sample" '[ "$(grep -c " audio FAIL playback stalled" $LOGS_DIR/events.log)" = 1 ]'
echo "[INFO] [ALSA] Playback consuming again, audio resumed." >> "$FRONTEND_LOG"
audio_watch; logs_flush
check "audio: the resume becomes an OK event" 'grep -q " audio OK playback consuming again" $LOGS_DIR/events.log'
echo "[ERROR] [ALSA] Playback stalled: no room in the buffer after 500 ms (hw_ptr not moving)." > "$FRONTEND_LOG"
audio_watch; logs_flush
check "audio: a new frontend log (shorter) is read from the start" '[ "$(grep -c " audio FAIL playback stalled" $LOGS_DIR/events.log)" = 2 ]'
audio_watch; logs_flush
check "audio: lines already read are not reported again" '[ "$(grep -c " audio FAIL playback stalled" $LOGS_DIR/events.log)" = 2 ]'
: > "$FRONTEND_LOG"
AUDIO_LOG_POS=0

### logd: game FPS from the GET_STATUS frame counter (RetroArch patch 0004)
pidof() { return 0; }
nc() { printf '%s' "$NC_REPLY"; }
NC_REPLY='GET_STATUS PLAYING game_boy_advance,Mario Kart (U) [!],crc32=1a2b3c,frames=1200
'
frontend_state
check "fps: GET_STATUS with frames gives core, content and counter" '[ "$FE_STATE" = game ] && [ "$FE_CORE" = game_boy_advance ] && [ "$FE_CONTENT" = "Mario Kart (U) [!]" ] && [ "$FE_FRAMES" = 1200 ]'
NC_REPLY='GET_STATUS PLAYING game_boy_advance,Mario Kart (U) [!],crc32=1a2b3c
'
frontend_state
check "fps: an older GET_STATUS without frames still parses" '[ "$FE_CONTENT" = "Mario Kart (U) [!]" ] && [ -z "$FE_FRAMES" ]'
unset -f pidof nc
rm -f "$LOGS_RAM"/events.pending "$LOGS_DIR"/events*.log
echo "[INFO] [Core] Geometry: 240x160, Aspect: 1.500, FPS: 59.73, Sample rate: 65536.00 Hz." > "$FRONTEND_LOG"
FE_STATE=game FE_CORE=gba FE_CONTENT=kart FE_FRAMES=100
game_track 10.00
check "fps: the first sample of a game only sets the baseline" '[ -z "$FPS" ] && [ "$GAME_NOMINAL" = 59.73 ]'
FE_FRAMES=550; game_track 17.50
check "fps: frames over time (450 frames in 7.5 s = 60.0)" '[ "$FPS" = 60.0 ]'
FE_FRAMES=900; game_track 25.00; logs_flush
check "fps: one slow sample (46.7) is not an event yet" '[ "$FPS" = 46.7 ] && ! grep -q " slow" $LOGS_DIR/events.log'
FE_FRAMES=1250; game_track 32.50; FE_FRAMES=1600; game_track 40.00; logs_flush
check "fps: two slow samples in a row give one slow event" '[ "$(grep -c "game FAIL slow: core=gba 46.7 fps (nominal 59.73) content=kart" $LOGS_DIR/events.log)" = 1 ]'
FE_FRAMES=2048; game_track 47.50; logs_flush
check "fps: back at full speed gives an OK event" 'grep -q "game OK full speed again: core=gba 59.7 fps (nominal 59.73)" $LOGS_DIR/events.log'
FE_STATE=paused FE_FRAMES=2100; game_track 55.00
check "fps: paused in the menu gives no FPS" '[ -z "$FPS" ] && [ -z "$FPS_PREV_FRAMES" ]'
FE_STATE=game FE_FRAMES=10; game_track 62.50
check "fps: after the pause the baseline starts again" '[ -z "$FPS" ] && [ "$FPS_PREV_FRAMES" = 10 ]'
FE_FRAMES=5; game_track 70.00
check "fps: a counter that went back (new video init) is not a negative FPS" '[ -z "$FPS" ] && [ "$FPS_PREV_FRAMES" = 5 ]'
FE_STATE=menu FE_CORE="" FE_CONTENT="" FE_FRAMES=""; game_track 77.50; logs_flush
check "fps: closing the game clears the nominal FPS" '[ -z "$GAME_KEY" ] && [ -z "$GAME_NOMINAL" ] && grep -q "game OK closed: core=gba content=kart" $LOGS_DIR/events.log'
: > "$FRONTEND_LOG"
FE_STATE=stopped

### logd: hung frontend (blocked, no CPU, no vblank): detection and recovery
reset_hang() {
	HANG=0 PREV_PID="" PREV_TICKS="" PREV_VB="" RECOVER_N=0 NOANS=0 DEEP_N=0 PREV_STATE=""
	KICK_N=0 KICK_WROTE="" SNAPPED="" KICKED_PID=""
	rm -f "$LOGS_RAM"/*.pending "$LOGS_DIR"/events*.log "$LOGS_DIR"/trace/*
}
# vblank counter from a fake /proc/interrupts: per-CPU counts of the lcd controller line
printf '           CPU0       CPU1\n 25:       9061       8051 GIC-0  29 Level     arch_timer\n171:       2842          7 GIC-0 118 Level     1c0c000.lcd-controller\n' > "$W/interrupts"
INTERRUPTS_FILE="$W/interrupts"
check "hang: vblank counter sums the per-CPU counts of the lcd controller" '[ "$(vblank_count)" = 2849 ]'
printf ' 25:       9061 GIC-0 29 Level arch_timer\n' > "$W/interrupts.none"
check "hang: no display controller gives an empty vblank counter" '[ -z "$(INTERRUPTS_FILE=$W/interrupts.none vblank_count)" ]'

# a blocked process whose vblank counter does not move is declared hung and killed
reset_hang
RECOVER_MAX=2
printf '#!/bin/sh\nwhile :; do sleep 1; done\n' > "$W/bin/retroarch"
"$W/bin/retroarch" &
FAKE=$!
sleep 1
FE_STATE=no_answer
trace_sample; trace_sample
check "hang: the first samples only set the baseline" '! grep -q " hung" $LOGS_DIR/events.log 2>/dev/null'
trace_sample
check "hang: the third sample (two blocked intervals) declares the hang" 'grep -q "frontend FAIL retroarch pid $FAKE hung: blocked with no CPU and no display vblank for 10s" $LOGS_DIR/events.log'
check "hang: the snapshot carries the display state" 'grep -q "=== snapshot of retroarch pid $FAKE" $LOGS_DIR/trace/boot-7.log && grep -q "regmaps:" $LOGS_DIR/trace/boot-7.log'
wait "$FAKE" 2>/dev/null
check "hang: the recovery killed the process and logged it" '! kill -0 $FAKE 2>/dev/null && grep -q "frontend OK recovery 1 of 2: killed the hung retroarch pid $FAKE" $LOGS_DIR/events.log'

# the same detection with RECOVER_MAX=0 only logs: the process stays alive
reset_hang
RECOVER_MAX=0
"$W/bin/retroarch" &
FAKE=$!
sleep 1
trace_sample; trace_sample; trace_sample
check "hang: with recovery off it only logs, the process stays alive" 'kill -0 $FAKE 2>/dev/null && grep -q " hung: blocked" $LOGS_DIR/events.log && ! grep -q "recovery" $LOGS_DIR/events.log'
kill -9 "$FAKE" 2>/dev/null
wait "$FAKE" 2>/dev/null

# a process that uses CPU (for example loading a big game) is never declared hung
reset_hang
RECOVER_MAX=2
printf '#!/bin/sh\nwhile :; do :; done\n' > "$W/bin/retroarch"
"$W/bin/retroarch" &
FAKE=$!
sleep 1
i=0; while [ $i -lt 4 ]; do trace_sample; sleep 1; i=$((i + 1)); done
check "hang: a busy process is not declared hung and is not killed" 'kill -0 $FAKE 2>/dev/null && ! grep -q " hung" $LOGS_DIR/events.log 2>/dev/null'
kill -9 "$FAKE" 2>/dev/null
wait "$FAKE" 2>/dev/null

# a process that is blocked but whose vblank keeps moving is not hung (the display lives)
reset_hang
RECOVER_MAX=2
printf '#!/bin/sh\nwhile :; do sleep 1; done\n' > "$W/bin/retroarch"
"$W/bin/retroarch" &
FAKE=$!
sleep 1
n=100
for k in 1 2 3 4; do
	printf '171:       %s          0 GIC-0 118 Level     1c0c000.lcd-controller\n' "$n" > "$W/interrupts"
	n=$((n + 50))
	trace_sample
done
check "hang: no CPU but a moving vblank is not a hang" 'kill -0 $FAKE 2>/dev/null && ! grep -q " hung" $LOGS_DIR/events.log 2>/dev/null'
kill -9 "$FAKE" 2>/dev/null
wait "$FAKE" 2>/dev/null

### logd: re-enabling the masked TCON vblank interrupt (a fake r36os-devmem)
# The register is the file $FAKE_REG. Writing it with FAKE_IRQ set "fires" the pending
# interrupt: the vblank counter in the fake /proc/interrupts moves.
cat > "$W/bin/fakedevmem" <<'EOF'
#!/bin/sh
echo "$*" >> "$FAKE_LOG"
if [ $# -ge 2 ]; then
	echo "$2" > "$FAKE_REG"
	[ -n "$FAKE_IRQ" ] && printf '171:       %s          0 GIC-0 118 Level     1c0c000.lcd-controller\n' "$FAKE_IRQ" > "$FAKE_INTERRUPTS"
fi
printf '0x%08x\n' "$(cat "$FAKE_REG")"
EOF
chmod +x "$W/bin/fakedevmem"
export FAKE_REG="$W/reg" FAKE_LOG="$W/devmem.log" FAKE_INTERRUPTS="$W/interrupts"
DEVMEM_BIN="$W/bin/fakedevmem"
frozen_tcon() {  # <GINT0 value> <irq after the write, or empty>
	echo "$1" > "$W/reg"
	: > "$W/devmem.log"
	printf '171:       100          0 GIC-0 118 Level     1c0c000.lcd-controller\n' > "$W/interrupts"
	FAKE_IRQ="$2"
	export FAKE_IRQ
	reset_hang
	printf '#!/bin/sh\nwhile :; do sleep 1; done\n' > "$W/bin/retroarch"
	"$W/bin/retroarch" &
	FAKE=$!
	sleep 1
	FE_STATE=no_answer
}
check "kick: the base address comes from the interrupt name" '[ "$(tcon_base)" = 0x1c0c000 ]'

# masked interrupts + an effective write: the display runs again and RetroArch is NOT killed
RECOVER_MAX=2
frozen_tcon 0x00000a00 4000
trace_sample; trace_sample
check "kick: masked vblank is re-enabled and the process keeps running" 'kill -0 $FAKE 2>/dev/null && grep -q "frontend OK recovery: re-enabled the masked display vblank interrupt; the display runs again, watching retroarch pid $FAKE" $LOGS_DIR/events.log && ! grep -q " hung" $LOGS_DIR/events.log'
check "kick: reads GINT0 (base + 4) and writes it with the three enable bits set" 'grep -qx "0x1c0c004" $W/devmem.log && grep -qx "0x1c0c004 0xc8000a00" $W/devmem.log && [ "$(cat $W/reg)" = 0xc8000a00 ]'
check "kick: the snapshot taken before the kick is on the card" 'grep -q "=== snapshot of retroarch pid $FAKE" $LOGS_DIR/trace/boot-7.log && grep -q "tcon GINT0 0x00000a00 masked: wrote 0xc8000a00" $LOGS_DIR/trace/boot-7.log'
kill -9 "$FAKE" 2>/dev/null
wait "$FAKE" 2>/dev/null

# the kick brings the vblank back but the process stays blocked with no CPU (GA36 image
# 214119): a moving vblank no longer saves it, it is killed two samples later
frozen_tcon 0x00000a00 4000
trace_sample; trace_sample
n=4100
for k in 1 2; do
	printf '171:       %s          0 GIC-0 118 Level     1c0c000.lcd-controller\n' "$n" > "$W/interrupts"
	n=$((n + 450))
	trace_sample
done
wait "$FAKE" 2>/dev/null
check "kick: a kicked process still blocked is killed although the vblank moves" 'grep -q "recovery: re-enabled the masked" $LOGS_DIR/events.log && grep -q "frontend FAIL retroarch pid $FAKE hung: blocked with no CPU for 10s although the display vblank runs again" $LOGS_DIR/events.log && ! kill -0 $FAKE 2>/dev/null'

# the kicked process that uses CPU again is left alone, and is again judged by the vblank
frozen_tcon 0x00000a00 4000
trace_sample; trace_sample
kill -9 "$FAKE" 2>/dev/null
wait "$FAKE" 2>/dev/null
printf '#!/bin/sh\nwhile :; do :; done\n' > "$W/bin/retroarch"
"$W/bin/retroarch" &
FAKE=$!
KICKED_PID=$FAKE PREV_PID=$FAKE PREV_TICKS=0
sleep 1
trace_sample
check "kick: a kicked process that uses CPU again is no longer watched" '[ -z "$KICKED_PID" ] && kill -0 $FAKE 2>/dev/null && ! grep -q " hung" $LOGS_DIR/events.log'
kill -9 "$FAKE" 2>/dev/null
wait "$FAKE" 2>/dev/null

# interrupts already enabled (the healthy 0xc8000200): nothing is written, the old recovery runs
frozen_tcon 0xc8000200 4000
trace_sample; trace_sample; trace_sample
wait "$FAKE" 2>/dev/null
check "kick: enabled interrupts are left alone and the hang falls back to the kill" '! grep -qE "^0x1c0c004 0x" $W/devmem.log && grep -q " hung: blocked" $LOGS_DIR/events.log && ! kill -0 $FAKE 2>/dev/null'

# masked, but the write does not bring the display back: falls back to the kill
frozen_tcon 0x00000a00 ""
trace_sample; trace_sample; trace_sample
wait "$FAKE" 2>/dev/null
check "kick: an ineffective write falls back to the kill" 'grep -qx "0x1c0c004 0xc8000a00" $W/devmem.log && grep -q " hung: blocked" $LOGS_DIR/events.log && ! kill -0 $FAKE 2>/dev/null && [ "$KICK_N" = 1 ]'

# no tool installed (the VM, other consoles): the old behaviour
DEVMEM_BIN="$W/bin/does-not-exist"
frozen_tcon 0x00000a00 4000
trace_sample; trace_sample; trace_sample
wait "$FAKE" 2>/dev/null
check "kick: without the tool the hang is recovered by the kill" 'grep -q " hung: blocked" $LOGS_DIR/events.log && ! kill -0 $FAKE 2>/dev/null && [ ! -s $W/devmem.log ]'

# kick limit reached: no more attempts
DEVMEM_BIN="$W/bin/fakedevmem"
KICK_MAX=0
frozen_tcon 0x00000a00 4000
trace_sample; trace_sample; trace_sample
wait "$FAKE" 2>/dev/null
check "kick: KICK_MAX=0 never touches the register" '[ ! -s $W/devmem.log ] && grep -q " hung: blocked" $LOGS_DIR/events.log'
KICK_MAX=5
DEVMEM_BIN=r36os-devmem
INTERRUPTS_FILE=/proc/interrupts
FE_STATE=stopped

### persist: the build language only seeds new cards; the menu choice always wins
export PERSIST_LIB=1 PERSIST_LIBSH="$PWD/rootfs/overlay/usr/libexec/r36os/lib.sh" PERSIST_MOUNT=/
export PERSIST_RAM=$W/p/ram PERSIST_SYS=$W/p/sys PERSIST_FACTORY=$W/p/factory
mkdir -p "$PERSIST_RAM" "$PERSIST_SYS" "$PERSIST_FACTORY"
. rootfs/overlay/usr/libexec/r36os/persist
echo 'user_language = "7"' > "$PERSIST_FACTORY/retroarch.cfg"
restore >/dev/null 2>&1
check "language: a new card gets the factory (build) language" 'grep -q "^user_language = \"7\"$" $PERSIST_SYS/retroarch/retroarch.cfg && grep -q "^user_language = \"7\"$" $PERSIST_RAM/retroarch.cfg'
printf 'menu_scale_factor = "2.000000"\nuser_language = "3"\n' > "$PERSIST_SYS/retroarch/retroarch.cfg"
echo 'user_language = "0"' > "$PERSIST_FACTORY/retroarch.cfg"
rm -rf "$PERSIST_RAM"
restore >/dev/null 2>&1
check "language: a build with another language keeps the menu choice" 'grep -q "^user_language = \"3\"$" $PERSIST_RAM/retroarch.cfg && grep -q "^user_language = \"3\"$" $PERSIST_SYS/retroarch/retroarch.cfg'
check "language: persist no longer rewrites user_language" '! grep -q "lang_sync\|user_language" rootfs/overlay/usr/libexec/r36os/persist'

### Single card (r36s-single-card, task 7.1): boots on the GA36, the R36S and the GA36
### again share ROMS/logs/ with one boot sequence, and each boot names its console
rm -f "$LOGS_RAM"/*.pending "$LOGS_DIR"/events*.log "$LOGS_DIR/.boot"
for console in ga36 r36s ga36; do
	echo "$console" > "$W/board"
	BOARD_FILE=$W/board cmd_start >/dev/null 2>&1
done
starts=$(sed -n 's/^[^ ]* \([0-9]*\) boot OK started: \([a-z0-9]*\) .*/\1 \2/p' "$LOGS_DIR/events.log" | tr '\n' ' ')
check "single card: three boots in one sequence, each with its console" '[ "$starts" = "1 ga36 2 r36s 3 ga36 " ]'
check "single card: the counter is shared on ROMS" '[ "$(cat "$LOGS_DIR/.boot")" = 3 ]'
check "single card: the boot log header names the console" \
	'grep -q "echo \"== console: \$(board)\"" rootfs/overlay/usr/libexec/r36os/bootlog'
check "single card: the hardware snapshot names the board" \
	'grep -q "^kv board " rootfs/overlay/usr/libexec/r36os/hwinfo'

rm -rf "$W"
echo "falhas: $FAILS"
[ $FAILS -eq 0 ]
