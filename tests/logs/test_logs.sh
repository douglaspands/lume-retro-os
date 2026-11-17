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
. aports/lume-core/files/usr/libexec/r36os/lib.sh
. aports/lume-core/files/usr/libexec/r36os/logs.sh
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
check "evento: descarregado com data, boot, categoria e resultado" 'grep -qE "^[0-9-]{10}T[0-9:]{8} 7 test FAIL second, with spaces$" $LOGS_DIR/events.log && [ ! -s $LOGS_RAM/events.pending ]'
check "event: the buffer is back, empty and writable by the launcher" '[ "$(stat -c %a $LOGS_RAM/events.pending)" = 666 ]'
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
export LOGD_LIB=1 LOGD_LIBDIR="$PWD/aports/lume-core/files/usr/libexec/r36os"
. aports/lume-core/files/usr/libexec/r36os/logd
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
wait "$FAKE" 2>/dev/null   # reaped: a zombie still has the name retroarch
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

### logd: OTG port sample (usb-device-access 1.1), on a fake /sys shaped like the GA36
SYS_ROOT="$W/sys"
rm -rf "$SYS_ROOT"
rm -f "$LOGS_RAM"/events.pending "$LOGS_RAM"/trace.pending "$LOGS_DIR"/events*.log
check "usb: a console without OTG sysfs (the vm) is none" '[ "$(usb_state)" = none ]'
usb_watch
check "usb: the vm logs a trace line and no event" 'grep -q " usb: none$" $LOGS_RAM/trace.pending && ! grep -q " usb " $LOGS_RAM/events.pending 2>/dev/null'
mkdir -p "$SYS_ROOT/class/extcon/extcon0" "$SYS_ROOT/bus/platform/devices/musb-hdrc.1.auto" \
	"$SYS_ROOT/class/udc/musb-hdrc.1.auto" "$SYS_ROOT/class/power_supply/axp20x-usb" \
	"$SYS_ROOT/class/power_supply/axp20x-battery" "$SYS_ROOT/bus/usb/devices/usb1" \
	"$SYS_ROOT/bus/usb/devices/1-0:1.0"
echo 1c19400.phy > "$SYS_ROOT/class/extcon/extcon0/name"
echo USB > "$SYS_ROOT/class/power_supply/axp20x-usb/type"
echo Battery > "$SYS_ROOT/class/power_supply/axp20x-battery/type"
echo 1 > "$SYS_ROOT/class/power_supply/axp20x-battery/online"
usb_fake() {  # USB USB-HOST musb-mode udc-state vbus-online host-devices
	printf 'USB=%s\nUSB-HOST=%s\n' "$1" "$2" > "$SYS_ROOT/class/extcon/extcon0/state"
	echo "$3" > "$SYS_ROOT/bus/platform/devices/musb-hdrc.1.auto/mode"
	echo "$4" > "$SYS_ROOT/class/udc/musb-hdrc.1.auto/state"
	echo "$5" > "$SYS_ROOT/class/power_supply/axp20x-usb/online"
	rm -rf "$SYS_ROOT/bus/usb/devices/1-1" "$SYS_ROOT/bus/usb/devices/1-1:1.0"
	[ "$6" = 0 ] || mkdir -p "$SYS_ROOT/bus/usb/devices/1-1" "$SYS_ROOT/bus/usb/devices/1-1:1.0"
}
usb_fake 0 0 b_idle "not attached" 0 0
check "usb: nothing plugged" '[ "$(usb_state)" = "extcon=1c19400.phy:USB=0,USB-HOST=0 musb=b_idle udc=musb-hdrc.1.auto:not_attached vbus=axp20x-usb:0 host_devs=0" ]'
usb_fake 0 0 b_idle "not attached" 1 0
check "usb: charger on the DC port (only the PMIC input)" '[ "$(usb_state)" = "extcon=1c19400.phy:USB=0,USB-HOST=0 musb=b_idle udc=musb-hdrc.1.auto:not_attached vbus=axp20x-usb:1 host_devs=0" ]'
usb_fake 1 0 b_peripheral configured 1 0
check "usb: PC cable on the OTG port" '[ "$(usb_state)" = "extcon=1c19400.phy:USB=1,USB-HOST=0 musb=b_peripheral udc=musb-hdrc.1.auto:configured vbus=axp20x-usb:1 host_devs=0" ]'
usb_fake 0 1 a_host "not attached" 0 1
check "usb: OTG adapter with a pendrive (interfaces not counted)" '[ "$(usb_state)" = "extcon=1c19400.phy:USB=0,USB-HOST=1 musb=a_host udc=musb-hdrc.1.auto:not_attached vbus=axp20x-usb:0 host_devs=1" ]'
mkdir -p "$SYS_ROOT/class/usb_role/ff300000.usb-role-switch" "$SYS_ROOT/class/extcon/extcon1"
echo device > "$SYS_ROOT/class/usb_role/ff300000.usb-role-switch/role"
printf 'HDMI=0\n' > "$SYS_ROOT/class/extcon/extcon1/state"
check "usb: a role switch is listed, an extcon without USB cables is not" 'usb_state | grep -q " role=ff300000.usb-role-switch:device " && ! usb_state | grep -q HDMI'
rm -rf "$SYS_ROOT/class/usb_role" "$SYS_ROOT/class/extcon/extcon1"
rm -f "$LOGS_RAM"/events.pending "$LOGS_RAM"/trace.pending
USB_LAST=none
usb_fake 0 0 b_idle "not attached" 0 0
usb_watch; usb_watch
usb_fake 1 0 b_peripheral configured 1 0
usb_watch; usb_watch
check "usb: one trace line per sample" '[ "$(grep -c " usb: " $LOGS_RAM/trace.pending)" = 4 ]'
check "usb: one event per change only" '[ "$(grep -c " usb OK otg: " $LOGS_RAM/events.pending)" = 2 ] && grep " usb OK otg: " $LOGS_RAM/events.pending | tail -n 1 | grep -q "usb OK otg: extcon=1c19400.phy:USB=1,USB-HOST=0 musb=b_peripheral"'
check "usb: a PC that configures the gadget is connected" 'grep -q " usb OK device: connected$" $LOGS_RAM/events.pending'
usb_fake 1 0 b_peripheral configured 1 0
usb_watch
usb_fake 0 0 b_idle "not attached" 0 0
usb_watch
check "usb: unplugging the PC is disconnected, each once" '[ "$(grep -c " usb OK device: connected$" $LOGS_RAM/events.pending)" = 1 ] && [ "$(grep -c " usb OK device: disconnected$" $LOGS_RAM/events.pending)" = 1 ]'
rm -f "$LOGS_RAM"/events.pending "$LOGS_RAM"/trace.pending
rm -rf "$SYS_ROOT"
SYS_ROOT=/sys USB_LAST=none USB_CONNECTED=0

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

### logd under the lume-launcher (lume-launcher 6.4): RetroArch absent is not a failure
LUME_STATUS="$W/lume-status"
# fake pidof: prints a pid, as the real one (logd keeps it and reads /proc/<pid>/comm)
pidof() { case "$1" in lume-run) echo $$ ;; *) return 1 ;; esac; }
echo ui > "$LUME_STATUS"
frontend_state
check "lume: no retroarch, interface on screen is launcher" '[ "$FE_STATE" = launcher ] && [ -n "$LUME" ]'
echo game:love > "$LUME_STATUS"
frontend_state
check "lume: a native game is game, with the runner as core" '[ "$FE_STATE" = game ] && [ "$FE_CORE" = love ] && [ -z "$FE_CONTENT" ]'
pidof() { echo $$; }
nc() { printf '%s' "$NC_REPLY"; }
NC_REPLY='GET_STATUS PLAYING super_nes,Secret Title (U),crc32=1a2b3c,frames=10
'
frontend_state
check "lume: RetroArch game under the launcher has no content name" '[ "$FE_STATE" = game ] && [ "$FE_CORE" = super_nes ] && [ -z "$FE_CONTENT" ]'
rm -f "$LOGS_RAM"/events.pending
game_track 5.00
FE_STATE=menu FE_CORE="" FE_FRAMES=""; game_track 9.00
check "lume: logd writes no opened/closed lines (lume-run does)" '! grep -q " game " $LOGS_RAM/events.pending 2>/dev/null'
unset -f pidof nc
rm -f "$LUME_STATUS"; LUME=""
frontend_state
check "lume: without the status file it is the old logic" '[ "$FE_STATE" != launcher ]'
### process usage columns: a busy loop stands in for lume-run
printf '#!/bin/sh\nwhile :; do :; done\n' > "$W/lumeprobe"
chmod +x "$W/lumeprobe"
"$W/lumeprobe" &
LR=$!
sleep 0.2
proc_usage lumeprobe 10.0; u1=$PU_OUT
sleep 0.5
proc_usage lumeprobe 10.5; u2=$PU_OUT
check "usage: rss, and cpu from the second sample on" 'echo "$u1" | grep -qE "^[0-9]+,$" && echo "$u2" | grep -qE "^[0-9]+,[0-9]+\.[0-9]$"'
proc_usage no-such-proc 1.0
check "usage: a missing process gives empty columns" '[ "$PU_OUT" = "," ]'
uptime_cs 116.58; a=$CS; uptime_cs 10.5; b=$CS; uptime_cs 7.08; c=$CS; uptime_cs 42; d=$CS
check "usage: uptime in centiseconds, no octal trap" '[ "$a" = 11658 ] && [ "$b" = 1050 ] && [ "$c" = 708 ] && [ "$d" = 4200 ]' "$a $b $c $d"
kill $LR 2>/dev/null; wait $LR 2>/dev/null
check "usage: the metrics header has the launcher columns" 'grep -q "lume_ui_rss_kb,lume_ui_cpu_pct,lume_run_rss_kb,lume_run_cpu_pct,input_rss_kb,input_cpu_pct" aports/lume-core/files/usr/libexec/r36os/logd'

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

### Frozen format (game-governor 1.2, D8): the metrics columns, the per-column value format
### and the trace lines, pinned before the sampler was rewritten without external processes.
### It runs on the /proc and /sys of the machine running the test, without ROMS (the buffers
### stay in RAM to be read).
rm -f "$LOGS_RAM"/*.pending "$LOGS_DIR"/events*.log
LOGS_MOUNT=$W/not-mounted
METRICS_COLS='time,uptime_s(,temp_[A-Za-z0-9_]+_c)*(,freq_policy[0-9]+_mhz)*(,cpu[0-9]+_pct)+,mem_avail_mb,swap_used_mb,bat_pct,bat_mv,bat_ma,bat_status,frontend,core,content,fps,fps_nominal,lume_ui_rss_kb,lume_ui_cpu_pct,lume_run_rss_kb,lume_run_cpu_pct,input_rss_kb,input_cpu_pct'
# metrics_ok <header file> <line>: one value per column, each in the format of its column
metrics_ok() {
	printf '%s\n' "$2" | awk -F, -v hf="$1" '
		BEGIN { getline h < hf; n = split(h, col, ",") }
		{ if (NF != n) { print "fields " NF " != columns " n; exit 1 }
		  for (i = 1; i <= n; i++) { c = col[i]; v = $i; re = ""
			if (c == "time") re = "^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]$"
			else if (c == "uptime_s") re = "^[0-9]+\\.[0-9]+$"
			else if (c ~ /^temp_/) re = "^-?[0-9]+\\.[0-9]$"
			else if (c ~ /^freq_|^cpu[0-9]|_mb$/) re = "^-?[0-9]+$"
			else if (c == "bat_mv" || c == "bat_ma") re = "^(-?[0-9]+)?$"
			else if (c == "bat_pct") re = "^[0-9]*$"
			else if (c == "frontend") re = "^(stopped|other|launcher|game|paused|menu|no_answer)$"
			else if (c == "fps" || c == "fps_nominal") re = "^([0-9]+(\\.[0-9]+)?)?$"
			else if (c ~ /_rss_kb$/) re = "^[0-9]*$"
			else if (c ~ /_cpu_pct$/) re = "^([0-9]+\\.[0-9])?$"
			if (re != "" && v !~ re) { print "column " c " value [" v "]"; exit 1 }
		  } }'
}
# no frontend, whatever runs on the machine of the test (a PC may run its own retroarch)
pidof() { return 1; }
pgrep() { return 1; }
discover
: > "$LOGS_RAM/stat.prev"
check "frozen: the metrics header has the documented columns, in order" \
	'grep -qE "^$METRICS_COLS\$" "$LOGS_RAM/metrics.header"'
sample
sample
check "frozen: two samples give two metrics lines" '[ "$(grep -c "" "$LOGS_RAM/metrics.pending")" = 2 ]'
check "frozen: each metrics value has the format of its column" \
	'metrics_ok "$LOGS_RAM/metrics.header" "$(tail -n 1 "$LOGS_RAM/metrics.pending")"'
check "frozen: the cpu columns of the second sample are 0-100" \
	'tail -n 1 "$LOGS_RAM/metrics.pending" | awk -F, -v hf="$LOGS_RAM/metrics.header" "BEGIN { getline h < hf; n = split(h, c, \",\") } { for (i = 1; i <= n; i++) if (c[i] ~ /^cpu/ && (\$i < 0 || \$i > 100)) exit 1 }"'
check "frozen: the frontend trace line of a sample without retroarch" \
	'grep -qE "^[0-9]{2}:[0-9]{2}:[0-9]{2} fe=stopped pid=- gpu_mhz=[0-9]* vblank=[0-9]*$" "$LOGS_RAM/trace.pending"'
check "frozen: the usb trace line of each sample" \
	'[ "$(grep -cE "^[0-9]{2}:[0-9]{2}:[0-9]{2} usb: " "$LOGS_RAM/trace.pending")" = 2 ]'
unset -f pidof pgrep
check "frozen: no event from two quiet samples but the first usb state" \
	'! grep -v " usb OK otg: " "$LOGS_RAM/events.pending" 2>/dev/null | grep -q .'
# the trace of new kernel messages: one "k" line per message, with the dmesg time stamp
rm -f "$LOGS_RAM"/*.pending
printf '[    1.000000] old message\n' > "$W/dmesg"
dmesg() { cat "$W/dmesg"; }
KMSG_SEEN=1
printf '[   12.345678] lume: hello kernel\n[  123.000001] second line\n' >> "$W/dmesg"
trace_kernel
unset -f dmesg
check "frozen: new kernel messages become k lines with the dmesg time stamp" \
	'[ "$(grep -c " k " "$LOGS_RAM/trace.pending")" = 2 ] && grep -qE "^[0-9]{2}:[0-9]{2}:[0-9]{2} k \[   12\.345678\] lume: hello kernel$" "$LOGS_RAM/trace.pending" && grep -qE "^[0-9:]{8} k \[  123\.000001\] second line$" "$LOGS_RAM/trace.pending"'
check "frozen: kernel messages already seen are not traced again" '! grep -q "old message" "$LOGS_RAM/trace.pending"'
rm -f "$LOGS_RAM"/*.pending "$W/dmesg"
LOGS_MOUNT=/

### persist: the build language only seeds new cards; the menu choice always wins
export PERSIST_LIB=1 PERSIST_LIBSH="$PWD/aports/lume-core/files/usr/libexec/r36os/lib.sh" PERSIST_MOUNT=/
export PERSIST_RAM=$W/p/ram PERSIST_SYS=$W/p/sys PERSIST_FACTORY=$W/p/factory
mkdir -p "$PERSIST_RAM" "$PERSIST_SYS" "$PERSIST_FACTORY"
. aports/lume-saves/files/usr/libexec/r36os/persist
echo 'user_language = "7"' > "$PERSIST_FACTORY/retroarch.cfg"
restore >/dev/null 2>&1
check "language: a new card gets the factory (build) language" 'grep -q "^user_language = \"7\"$" $PERSIST_SYS/retroarch/retroarch.cfg && grep -q "^user_language = \"7\"$" $PERSIST_RAM/retroarch.cfg'
printf 'menu_scale_factor = "2.000000"\nuser_language = "3"\n' > "$PERSIST_SYS/retroarch/retroarch.cfg"
echo 'user_language = "0"' > "$PERSIST_FACTORY/retroarch.cfg"
rm -rf "$PERSIST_RAM"
restore >/dev/null 2>&1
check "language: a build with another language keeps the menu choice" 'grep -q "^user_language = \"3\"$" $PERSIST_RAM/retroarch.cfg && grep -q "^user_language = \"3\"$" $PERSIST_SYS/retroarch/retroarch.cfg'
check "language: persist no longer rewrites user_language" '! grep -q "lang_sync\|user_language" aports/lume-saves/files/usr/libexec/r36os/persist'

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
	'grep -q "echo \"== console: \$(board)\"" aports/lume-core/files/usr/libexec/r36os/bootlog'
check "single card: the hardware snapshot names the board" \
	'grep -q "^kv board " aports/lume-diag/files/usr/libexec/r36os/hwinfo'
### Fragment versions in the hardware snapshot (build-speed 8.2): the function of hwinfo run
### against a fake apk database
printf 'P:zlib\nV:1.3-r0\n\nP:lume-core\nV:1.0-r5\nS:10\n\nP:r36os-logd\nV:1.0-r1\n\nP:lume-diag\nV:1.0-r2\n\nP:busybox\nV:1.36-r0\n' > "$W/apk-installed"
eval "$(sed -n '/^fragment_versions() {/,/^}/p' aports/lume-diag/files/usr/libexec/r36os/hwinfo)"
APK_DB=$W/apk-installed
check "hwinfo: fragment versions list only lume-* and r36os-*, sorted" \
	'[ "$(fragment_versions | tr "\n" ";")" = "lume-core 1.0-r5;lume-diag 1.0-r2;r36os-logd 1.0-r1;" ]'
APK_DB=$W/none
check "hwinfo: a missing apk database lists nothing" '[ -z "$(fragment_versions)" ]'
check "hwinfo: the snapshot has the fragments section" \
	'grep -q "^sec fragments" aports/lume-diag/files/usr/libexec/r36os/hwinfo'
### DRAM clock in the hardware snapshot (game-governor 4.1): the function of hwinfo run
### against a fake r36os-devmem (N = 46 -> 1104 MHz, M = 3, sigma-delta on, source pll-ddr1)
cat > "$W/fake-devmem" <<'EOF'
#!/bin/sh
case "$1" in
0x01C2004C) echo 0x80002e00 ;;
0x01C202AC) echo 0xd1303333 ;;
0x01C202B0) echo 0x00000000 ;;
0x01C200F4) echo 0x00000003 ;;
0x01C200F8) echo 0x00010000 ;;
*) exit 1 ;;
esac
EOF
chmod +x "$W/fake-devmem"
eval "$(sed -n '/^dram_clock() {/,/^}/p' aports/lume-diag/files/usr/libexec/r36os/hwinfo)"
has() { command -v "$1" >/dev/null 2>&1; }
kv() { printf '%-26s %s\n' "$1:" "$2"; }
R36OS_DEVMEM=$W/fake-devmem
echo ga36 > "$W/board"
BOARD_FILE=$W/board
dram_out=$(dram_clock)
check "hwinfo: DRAM clock is computed from the registers (1104 MHz PLL -> 552 / 276)" \
	'printf "%s\n" "$dram_out" | grep -q "dram effective: *memory 552 MHz, controller 276 MHz (pll-ddr1 24 MHz x N=46 = 1104 MHz, M+1=4"'
check "hwinfo: DRAM clock records the raw registers next to the clock" \
	'printf "%s\n" "$dram_out" | grep -q "0x01c2004c = 0x80002e00" && printf "%s\n" "$dram_out" | grep -q "0x01c202ac = 0xd1303333 (sigma-delta on)" && printf "%s\n" "$dram_out" | grep -q "0x01c200f4 = 0x00000003"'
echo r36s > "$W/board"
check "hwinfo: DRAM clock is skipped silently on another board" '[ -z "$(dram_clock)" ]'
echo ga36 > "$W/board"
R36OS_DEVMEM=$W/absent-devmem
check "hwinfo: DRAM clock is skipped silently without r36os-devmem" '[ -z "$(dram_clock)" ]'
check "hwinfo: the snapshot has the DRAM clock block" \
	'grep -q "^drams=\$(dram_clock)" aports/lume-diag/files/usr/libexec/r36os/hwinfo'
unset BOARD_FILE R36OS_DEVMEM

### Device tree choice (boot-dtb-select, task 5.2): the running DTB, its confirmation when
### the frontend starts and the events of the choice made in the initramfs
DT_ROOT=$W/dt
DTB_CONF_DIR=$W/storage/system/etc
mkdir -p "$DT_ROOT/lume-select" "$DTB_CONF_DIR"
printf 'ga36mb,ga36-mb-v1.2\000allwinner,sun8i-a33\000' > "$DT_ROOT/compatible"
printf 'ga36-panel2\000' > "$DT_ROOT/lume-select/lume,id"
dmesg() { cat "$W/dmesg" 2>/dev/null; }
printf '[    1.2] lume-bootsel: rules of ga36-panel2: match\n[    1.3] lume-bootsel: selected ga36-panel2 (reason: rule)\n' > "$W/dmesg"
check "dtb: id and SoC folder of the running tree" '[ "$(dtb_id) $(dtb_soc)" = "ga36-panel2 a33" ]'
check "dtb: in use, with the reason from the boot log" '[ "$(dtb_in_use)" = "ga36-panel2 (rule)" ]'
mkdir -p "$DT_ROOT/chosen"
printf 'ga36-panel2\000forced\000' > "$DT_ROOT/chosen/lume,dtb-selected"
check "dtb: in use after a kexec, with the reason from /chosen" '[ "$(dtb_in_use)" = "ga36-panel2 (forced, after kexec)" ]'
rm -f "$DT_ROOT/chosen/lume,dtb-selected"

### Task 5.3: the state file is per device (SoC serial number) and the frontend confirms
### only the pending device tree that the screen could not confirm
SOC0_DIR=$W/soc0
mkdir -p "$SOC0_DIR"
check "dtb: without a serial number the state file is per SoC" '[ "$(dtb_conf_name)" = dtb-a33.conf ]'
printf '0000000000000000\n' > "$SOC0_DIR/serial_number"
check "dtb: an all-zero serial number counts as none" '[ "$(dtb_conf_name)" = dtb-a33.conf ]'
printf 'c3d9b8674f4b94f6\000' > "$DT_ROOT/serial-number"
check "dtb: without soc0 the serial number of the bootloader names the file (D6)" '[ "$(dtb_conf_name)" = dtb-a33-c3d9b8674f4b94f6.conf ]'
printf '02c00042:a1b2c3d4\n' > "$SOC0_DIR/serial_number"
check "dtb: the SoC serial number wins over the bootloader one" '[ "$(dtb_conf_name)" = dtb-a33-02c00042a1b2c3d4.conf ]'
rm -f "$DT_ROOT/serial-number"
check "dtb: with a serial number the state file is per device" '[ "$(dtb_conf_name)" = dtb-a33-02c00042a1b2c3d4.conf ]'
DEV1=$DTB_CONF_DIR/dtb-a33-02c00042a1b2c3d4.conf
rm -f "$LOGS_RAM"/*.pending "$LOGS_DIR"/events*.log
printf 'manual=ga36-panel2\ngood=ga36-panel1\npending=ga36-panel2\nbad=old\n' > "$DEV1"
printf 'manual=\ngood=\npending=ga36-panel2\nbad=\n' > "$DTB_CONF_DIR/dtb-a33.conf"
dtb_confirm; logs_flush
check "dtb: the frontend confirms the pending one (good, no pending, manual and bad kept)" \
	'grep -qx good=ga36-panel2 $DEV1 && grep -qx pending= $DEV1 && grep -qx manual=ga36-panel2 $DEV1 && grep -qx bad=old $DEV1'
check "dtb: only the file of this device is touched" 'grep -qx pending=ga36-panel2 $DTB_CONF_DIR/dtb-a33.conf'
check "dtb: confirmation event" 'grep -q " boot OK device tree ga36-panel2 confirmed: the frontend started (no question on the screen)" $LOGS_DIR/events.log'
dtb_confirm; logs_flush
check "dtb: confirmed once (no rewrite, no new event)" '[ "$(grep -c "confirmed: the frontend" $LOGS_DIR/events.log)" = 1 ] && [ ! -e $DEV1.tmp ]'
printf 'manual=\ngood=ga36-panel2\npending=\nbad=\n' > "$DEV1"
printf 'r36s,r36s-v5\000rockchip,rk3326\000' > "$DT_ROOT/compatible"
printf 'r36s-v5\000' > "$DT_ROOT/lume-select/lume,id"
dtb_confirm
check "dtb: nothing pending, nothing written (the default is never pending)" \
	'[ ! -e $DTB_CONF_DIR/dtb-rk3326-02c00042a1b2c3d4.conf ] && grep -qx good=ga36-panel2 $DEV1'
printf 'manual=\ngood=\npending=r36s-v6\nbad=\n' > "$DTB_CONF_DIR/dtb-rk3326-02c00042a1b2c3d4.conf"
dtb_confirm
check "dtb: a pending one that is not running is left to lume-bootsel" \
	'grep -qx pending=r36s-v6 $DTB_CONF_DIR/dtb-rk3326-02c00042a1b2c3d4.conf'
check "dtb: the hardware snapshot has the device tree in use and the state file" \
	'grep -q "^kv \"dt in use\" \"\$(dtb_in_use); state \$(dtb_conf_name)" aports/lume-diag/files/usr/libexec/r36os/hwinfo'
rm -rf "$DT_ROOT/lume-select"
dtb_confirm
check "dtb: without the node nothing is written" '[ "$(dtb_in_use)" = "no lume-select node" ]'
DT_ROOT=$W/none
check "dtb: the vm has no device tree" '[ "$(dtb_in_use)" = "none (no device tree)" ] && [ -z "$(dtb_conf_name)" ]'
printf '%s\n' "[    2.0] lume-bootsel: before kexec: fallback: ga36-panel2 was not confirmed in the previous boot; discarded" \
	"[    2.1] lume-bootsel: before kexec: selected other (reason: fallback)" \
	"[    2.2] lume-bootsel: ERROR: kexec -l failed (status 1); keeping the running device tree" > "$W/dmesg"
rm -f "$LOGS_RAM"/*.pending "$LOGS_DIR"/events*.log
BOARD_FILE=$W/board cmd_start >/dev/null 2>&1
check "dtb: the choice becomes an event" 'grep -q " boot OK device tree selected other (reason: fallback)" $LOGS_DIR/events.log'
check "dtb: fallback and errors become failure events" \
	'grep -q " boot FAIL device tree fallback: ga36-panel2 was not confirmed" $LOGS_DIR/events.log && grep -q " boot FAIL device tree ERROR: kexec -l failed" $LOGS_DIR/events.log'
# third start after a revert: the lines of the first start come with two prefixes
printf '%s\n' "[    1.0] lume-bootsel: before kexec: before kexec: selected ga36-panel2 (reason: forced)" \
	"[    1.1] lume-bootsel: before kexec: question shown: keep ga36-panel2? (15 s)" \
	"[    1.2] lume-bootsel: before kexec: not confirmed within 15 s: ga36-panel2 discarded on this device, going back to ga36-panel1" \
	"[    1.3] lume-bootsel: before kexec: selected ga36-panel1 (reason: reverted)" > "$W/dmesg"
rm -f "$LOGS_RAM"/*.pending "$LOGS_DIR"/events*.log
BOARD_FILE=$W/board cmd_start >/dev/null 2>&1
check "dtb: revert events (the choice, the missing answer and the way back)" \
	'grep -q " boot OK device tree selected ga36-panel2 (reason: forced)" $LOGS_DIR/events.log && grep -q " boot FAIL device tree not confirmed within 15 s: ga36-panel2 discarded" $LOGS_DIR/events.log && grep -q " boot OK device tree selected ga36-panel1 (reason: reverted)" $LOGS_DIR/events.log'
printf '%s\n' "[    1.0] lume-bootsel: before kexec: selected ga36-panel2 (reason: rule)" \
	"[    1.1] lume-bootsel: confirmed on screen: ga36-panel2 kept" > "$W/dmesg"
rm -f "$LOGS_RAM"/*.pending "$LOGS_DIR"/events*.log
BOARD_FILE=$W/board cmd_start >/dev/null 2>&1
check "dtb: confirmation on the screen becomes an event" 'grep -q " boot OK device tree confirmed on screen: ga36-panel2 kept" $LOGS_DIR/events.log'
unset -f dmesg

rm -rf "$W"
echo "falhas: $FAILS"
[ $FAILS -eq 0 ]
