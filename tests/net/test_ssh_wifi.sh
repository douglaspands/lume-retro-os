#!/bin/sh
# lume-launcher 12.5 (D18): SSH over Wi-Fi with the code on the screen, only when turned on,
# only on the Wi-Fi address. Runs in busybox (builder container) with fake ip, dropbear,
# dropbearkey and chpasswd.
set -u
cd "$(dirname "$0")/../.."
SSH_WIFI="busybox sh aports/lume-net/files/usr/libexec/lume/ssh-wifi"
W=$(mktemp -d)
FAILS=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; FAILS=$((FAILS + 1)); fi; }

mkdir -p "$W/bin" "$W/net/eth0" "$W/net/wlan0/wireless" "$W/net/p2p-wlan0-0/wireless" "$W/card/lume" "$W/card/ssh"
LOG="$W/cmd.log"
# ip: the address of $W/addr.<dev> (none when the file is missing)
cat > "$W/bin/ip" <<EOF
#!/bin/sh
for a; do dev=\$a; done
[ -f "$W/addr.\$dev" ] && echo "3: \$dev    inet \$(cat "$W/addr.\$dev")/24 brd 192.168.1.255 scope global wlan0"
exit 0
EOF
# dropbear: logs its arguments, serves until killed
cat > "$W/bin/dropbear" <<EOF
#!/bin/sh
echo "dropbear \$*" >> "$LOG"
while :; do sleep 1; done
EOF
cat > "$W/bin/dropbearkey" <<EOF
#!/bin/sh
echo "dropbearkey \$*" >> "$LOG"
for a; do f=\$a; done
echo hostkey > "\$f"
EOF
# chpasswd: the shadow line it was given ("user:password", -e for an encrypted one)
cat > "$W/bin/chpasswd" <<EOF
#!/bin/sh
read -r line
echo "chpasswd \$* \$line" >> "$LOG"
echo "\$line" > "$W/shadow.console"
EOF
chmod +x "$W/bin/"*

export SETTINGS="$W/card/lume/settings.toml" CODE="$W/card/ssh/wifi-code" \
	KEYS="$W/card/ssh/authorized_keys" HOSTKEY="$W/card/ssh/dropbear_ed25519_host_key" \
	NET_CLASS="$W/net" IP="$W/bin/ip" DROPBEAR="$W/bin/dropbear" DROPBEARKEY="$W/bin/dropbearkey" \
	CHPASSWD="$W/bin/chpasswd" ROOT_SSH="$W/root/.ssh" RUN="$W/run"
running() { [ -f "$W/run/ssh-wifi.pid" ] && kill -0 "$(cat "$W/run/ssh-wifi.pid")" 2>/dev/null; }
last() { grep '^dropbear ' "$LOG" 2>/dev/null | tail -n 1; }
code() { cat "$CODE"; }

# off from the factory: nothing, not even a code
echo 192.168.1.20 > "$W/addr.wlan0"
echo 'language = "pt"' > "$SETTINGS"
$SSH_WIFI apply > /dev/null
check "off: nothing listens" '! running && [ ! -s "$LOG" ] && [ ! -f "$CODE" ]'

# on: a code made on the card, applied to "console", dropbear on the Wi-Fi address only
echo 'ssh_wifi = true' >> "$SETTINGS"
$SSH_WIFI apply > /dev/null
check "on: listening" 'running'
check "code made on the card" 'code | grep -Eq "^[2-9A-HJKMNP-Z]{4}-[2-9A-HJKMNP-Z]{4}$"'
check "code is the password of console" '[ "$(cat "$W/shadow.console")" = "console:$(code)" ]'
check "only on the Wi-Fi address" 'last | grep -q -- "-p 192.168.1.20:22"'
check "root has no empty password here (no -B)" '! last | grep -q -- " -B"'
check "passwords allowed (no -s, no -g)" '! last | grep -Eq -- " -s | -g "'
check "never on every interface" '! last | grep -q "0.0.0.0"'
check "host key made once on the card" '[ -s "$HOSTKEY" ] && [ "$(grep -c "^dropbearkey" "$LOG")" = 1 ]'
check "no keys on the card: none installed" '[ ! -f "$W/root/.ssh/authorized_keys" ]'

# the same code on every apply and after a restart of the service (fixed until asked)
first=$(code)
pid=$(cat "$W/run/ssh-wifi.pid")
$SSH_WIFI apply > /dev/null
check "unchanged: same server, same code" '[ "$(cat "$W/run/ssh-wifi.pid")" = "$pid" ] && [ "$(code)" = "$first" ]'
check "the code is applied once" '[ "$(grep -c "^chpasswd  console:" "$LOG")" = 1 ]'

# the launcher writes a new code ("Generate a new code"): applied without a restart
echo "ABCD-2345" > "$CODE"
$SSH_WIFI apply > /dev/null
check "new code applied" '[ "$(cat "$W/shadow.console")" = "console:ABCD-2345" ] && [ "$(cat "$W/run/ssh-wifi.pid")" = "$pid" ]'

# a broken code file is replaced by a fresh code, never used as a password
echo "x; rm -rf /" > "$CODE"
$SSH_WIFI apply > /dev/null
check "broken code replaced" 'code | grep -Eq "^[2-9A-HJKMNP-Z]{4}-[2-9A-HJKMNP-Z]{4}$" && ! grep -q "rm -rf" "$W/shadow.console"'

# a key on the card (advanced): installed 600 under a 700 dir, without a restart
echo "ssh-ed25519 AAAA test" > "$KEYS"
$SSH_WIFI apply > /dev/null
check "key installed for root" 'cmp -s "$KEYS" "$W/root/.ssh/authorized_keys"'
check "keys file mode 600, dir 700" '[ "$(stat -c %a "$W/root/.ssh/authorized_keys")" = 600 ] && [ "$(stat -c %a "$W/root/.ssh")" = 700 ]'

# the router gives another address: moved, same code
code_now=$(code)
echo 192.168.1.33 > "$W/addr.wlan0"
$SSH_WIFI apply > /dev/null
check "new address, same code" 'running && last | grep -q -- "-p 192.168.1.33:22" && ! kill -0 "$pid" 2>/dev/null && [ "$(code)" = "$code_now" ]'

# Wi-Fi down: stopped, keys removed, "console" locked again; the code stays on the card
rm -f "$W/addr.wlan0"
$SSH_WIFI apply > /dev/null
check "Wi-Fi down: stopped" '! running && [ ! -f "$W/root/.ssh/authorized_keys" ]'
check "console locked again" '[ "$(cat "$W/shadow.console")" = "console:!" ]'
check "the code stays on the card" '[ "$(code)" = "$code_now" ]'

# only a Wi-Fi Direct group up: never there
echo 10.0.0.1 > "$W/addr.p2p-wlan0-0"
$SSH_WIFI apply > /dev/null
check "never on Wi-Fi Direct" '! running'

# back on: the same code again
echo 192.168.1.20 > "$W/addr.wlan0"
$SSH_WIFI apply > /dev/null
check "back on with the same code" 'running && [ "$(cat "$W/shadow.console")" = "console:$code_now" ]'

# turned off in the launcher: stopped
echo 'ssh_wifi = false' > "$SETTINGS"
$SSH_WIFI apply > /dev/null
check "turned off: stopped" '! running'

# the service loop: picks the option up, and stops the server on TERM
echo 'ssh_wifi = true' > "$SETTINGS"
INTERVAL=0.2 $SSH_WIFI watch > /dev/null &
svc=$!
sleep 1
check "watch starts it" 'running'
kill "$svc"
sleep 0.5
check "TERM stops it" '! running'

rm -rf "$W"
[ "$FAILS" = 0 ] && echo "ssh-wifi: all passed"
exit "$FAILS"
