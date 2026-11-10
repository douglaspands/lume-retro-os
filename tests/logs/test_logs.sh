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

rm -rf "$W"
echo "falhas: $FAILS"
[ $FAILS -eq 0 ]
