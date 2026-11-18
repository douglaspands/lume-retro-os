/*
 * lume-input: the input daemon of Lume Retro OS (lume-launcher D8; it grew out of
 * lume-padmerge, r36s-single-card D8).
 *
 * One process per console, as root, before the frontend:
 *  - reads the board profile (/usr/share/lume/input/<board>.conf): the source devices by
 *    name, the code map and the mixer control;
 *  - grabs every source device (EVIOCGRAB), so programs only see the virtual one;
 *  - publishes through uinput the virtual gamepad with the same name as before ("GA36-MB
 *    Gamepad", "R36S Gamepad"), so the RetroArch autoconfig does not change;
 *  - the Fn key is the system button (lume-hud-actions D1, D13) and never goes out: alone it
 *    is a gesture, "fn_tap" (let go before fn_hold_ms) or "fn_hold <table>" then
 *    "fn_release" (held); Fn with a key of the profile's chord table sends that action's
 *    name and swallows the key; Fn with any other key swallows it and sends nothing
 *    (reserved chords). A Fn that made a chord never gives a gesture;
 *  - volume keys change the ALSA mixer in fixed steps and are not forwarded; "volume" then
 *    goes to the clients of the socket (the launcher shows the level);
 *  - Fn+volume keys change the screen backlight in steps of 5% instead (never below 5%), and
 *    "brightness" goes to the clients;
 *  - after either, "LUME_LEVEL" asks RetroArch (127.0.0.1:55355, patch 0011) to draw the
 *    launcher's level line over a running game;
 *  - a client may send "tap KEY_<name>" (a press and, 50 ms later, a release on the virtual
 *    device, which declares those keys) and "capture on" / "capture off" (D11: the held keys
 *    are released, nothing is forwarded and the client gets "nav up|down|left|right|a|b";
 *    "capture off", the end of that client's connection or 2 s without a message from it
 *    end the capture). The Fn gestures and chords keep working during a capture;
 *  - the power button (device-fixes D11, task 8.2; the protocol is frozen in
 *    lume_core::sleep and docs/LAUNCHER.md, "Protocolo do sono") is read from the profile's
 *    "power" source and never goes out: let go before 1 s it creates the request
 *    <sleep dir>/suspend (O_EXCL) and sends "power_tap"; held 2 s it creates
 *    <sleep dir>/poweroff and sends "power_hold", once per hold; let go between 1 s and 2 s
 *    it does nothing. Without the folder (lume-sleep not up) a request is one kernel log line
 *    and no notice;
 *  - the sleep folder is watched (inotify) for "phase", written by lume-sleep: on
 *    "suspend <seq>" the clients connected then get "suspend <seq>" and their
 *    "suspend_ok <seq>" are collected for 2 s, then "clients" is written by rename
 *    ("suspend <seq> ok <n>/<n>" or "suspend <seq> timeout <a>/<n>"); until "resume <seq>"
 *    nothing is forwarded (no key, no axis, no gesture, no request, no client tap). On
 *    "resume <seq>" the queued input of every source is read and dropped, the keys held on
 *    the virtual device are released, the sticks are read again, the power button is ignored
 *    until it is seen let go (a press within 1 s of the resume is still the waking one, and a
 *    tap begun within that 1 s makes no request; a hold still powers off), and then the
 *    clients get "resume <seq>". With no "resume" within 60 s of awake time, the input comes back on
 *    its own (a stuck or dead lume-sleep must not leave the console without controls).
 *
 * The socket protocol (SOCK_SEQPACKET, one message per packet, lume_core::input mirrors it):
 *   daemon -> client: quit | app_menu | save_state | load_state | screenshot | hud |
 *                     fn_tap | fn_hold <button>=<action>... | fn_release |
 *                     volume | brightness | nav up|down|left|right|a|b |
 *                     power_tap | power_hold | suspend <seq> | resume <seq>
 *   client -> daemon: tap KEY_<name> | capture on | capture off | suspend_ok <seq>
 *
 * Profile lines of the chords: "fn <code>", "fn_hold_ms <ms>" (default 500) and
 * "chord <code> <action>" in output codes; the older "quit <code>" reads as "chord <code> quit".
 * "power <device name>": the optional source of the power button (only its KEY_POWER is
 * read); a KEY_POWER of any other source is the power button too and never goes out.
 *
 * usage: lume-input --profile FILE [--socket PATH] [--timeout SECONDS]
 *        lume-input --profile FILE --test OUT --source NAME=PATH... [--socket PATH]
 *        lume-input --list
 *
 * --test runs the same loop with files or FIFOs as sources and a file as the output, with no
 * input device and no uinput (the host tests use it). LUME_INPUT_AMIXER replaces amixer,
 * LUME_INPUT_BACKLIGHT replaces /sys/class/backlight and LUME_SLEEP_DIR replaces the sleep
 * folder /run/lume/sleep.
 */
#define _GNU_SOURCE
#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <grp.h>
#include <linux/input.h>
#include <linux/uinput.h>
#include <netinet/in.h>
#include <poll.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/inotify.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define PROG "lume-input"
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define MAX_SOURCES 6
#define MAX_KEYS 64
#define MAX_AXES 8
#define MAX_CLIENTS 8
#define MAX_CHORDS 16
#define DEFAULT_SOCKET "/run/lume/input.sock"
#define DEFAULT_SLEEP_DIR "/run/lume/sleep"
#define FN_HOLD_MS 500		/* default of fn_hold_ms */
#define TAP_MS 50		/* press to release of a client's "tap" */
#define CAPTURE_IDLE_MS 2000	/* a capture ends after this long without a message */
/* the sleep protocol (lume_core::sleep: TAP_MAX, HOLD, CLIENT_REPLY, WAKE_GUARD) */
#define POWER_TAP_MS 1000	/* a power press let go before this is a tap */
#define POWER_HOLD_MS 2000	/* held this long it is the shutdown */
#define CLIENT_REPLY_MS 2000	/* the wait for "suspend_ok <seq>" */
#define WAKE_GUARD_MS 1000	/* a press this soon after the resume is the waking one */
#define SLEEP_STUCK_MS 60000	/* awake time without "resume": the input comes back */
#define WATCH_RETRY_MS 1000	/* no folder to watch yet: try again */

struct code_name {
	const char *name;
	unsigned short code;
};

/* the names a profile may use (numbers are accepted too: 0x13c) */
static const struct code_name NAMES[] = {
	{ "BTN_A", BTN_A },           { "BTN_B", BTN_B },           { "BTN_X", BTN_X },
	{ "BTN_Y", BTN_Y },           { "BTN_SOUTH", BTN_SOUTH },   { "BTN_EAST", BTN_EAST },
	{ "BTN_NORTH", BTN_NORTH },   { "BTN_WEST", BTN_WEST },     { "BTN_TL", BTN_TL },
	{ "BTN_TR", BTN_TR },         { "BTN_TL2", BTN_TL2 },       { "BTN_TR2", BTN_TR2 },
	{ "BTN_SELECT", BTN_SELECT }, { "BTN_START", BTN_START },   { "BTN_MODE", BTN_MODE },
	{ "BTN_THUMBL", BTN_THUMBL }, { "BTN_THUMBR", BTN_THUMBR },
	{ "BTN_DPAD_UP", BTN_DPAD_UP },       { "BTN_DPAD_DOWN", BTN_DPAD_DOWN },
	{ "BTN_DPAD_LEFT", BTN_DPAD_LEFT },   { "BTN_DPAD_RIGHT", BTN_DPAD_RIGHT },
	{ "BTN_TRIGGER_HAPPY1", BTN_TRIGGER_HAPPY1 }, { "BTN_TRIGGER_HAPPY2", BTN_TRIGGER_HAPPY2 },
	{ "BTN_TRIGGER_HAPPY3", BTN_TRIGGER_HAPPY3 }, { "BTN_TRIGGER_HAPPY4", BTN_TRIGGER_HAPPY4 },
	{ "BTN_TRIGGER_HAPPY5", BTN_TRIGGER_HAPPY5 },
	{ "KEY_VOLUMEUP", KEY_VOLUMEUP }, { "KEY_VOLUMEDOWN", KEY_VOLUMEDOWN },
	/* keyboard keys: the VM profile, and the keys a client may "tap" (the virtual device
	 * declares every KEY_ of this table, the volume keys aside) */
	{ "KEY_ESC", KEY_ESC },       { "KEY_ENTER", KEY_ENTER },   { "KEY_SPACE", KEY_SPACE },
	{ "KEY_TAB", KEY_TAB },       { "KEY_BACKSPACE", KEY_BACKSPACE },
	{ "KEY_LEFTSHIFT", KEY_LEFTSHIFT }, { "KEY_RIGHTSHIFT", KEY_RIGHTSHIFT },
	{ "KEY_LEFTCTRL", KEY_LEFTCTRL },   { "KEY_LEFTALT", KEY_LEFTALT },
	{ "KEY_UP", KEY_UP },         { "KEY_DOWN", KEY_DOWN },     { "KEY_LEFT", KEY_LEFT },
	{ "KEY_RIGHT", KEY_RIGHT },   { "KEY_MINUS", KEY_MINUS },   { "KEY_EQUAL", KEY_EQUAL },
	{ "KEY_F1", KEY_F1 },   { "KEY_F2", KEY_F2 },   { "KEY_F3", KEY_F3 },   { "KEY_F4", KEY_F4 },
	{ "KEY_F5", KEY_F5 },   { "KEY_F6", KEY_F6 },   { "KEY_F7", KEY_F7 },   { "KEY_F8", KEY_F8 },
	{ "KEY_F9", KEY_F9 },   { "KEY_F10", KEY_F10 }, { "KEY_F11", KEY_F11 }, { "KEY_F12", KEY_F12 },
	{ "KEY_0", KEY_0 }, { "KEY_1", KEY_1 }, { "KEY_2", KEY_2 }, { "KEY_3", KEY_3 },
	{ "KEY_4", KEY_4 }, { "KEY_5", KEY_5 }, { "KEY_6", KEY_6 }, { "KEY_7", KEY_7 },
	{ "KEY_8", KEY_8 }, { "KEY_9", KEY_9 },
	{ "KEY_A", KEY_A }, { "KEY_B", KEY_B }, { "KEY_C", KEY_C }, { "KEY_D", KEY_D },
	{ "KEY_E", KEY_E }, { "KEY_F", KEY_F }, { "KEY_G", KEY_G }, { "KEY_H", KEY_H },
	{ "KEY_I", KEY_I }, { "KEY_J", KEY_J }, { "KEY_K", KEY_K }, { "KEY_L", KEY_L },
	{ "KEY_M", KEY_M }, { "KEY_N", KEY_N }, { "KEY_O", KEY_O }, { "KEY_P", KEY_P },
	{ "KEY_Q", KEY_Q }, { "KEY_R", KEY_R }, { "KEY_S", KEY_S }, { "KEY_T", KEY_T },
	{ "KEY_U", KEY_U }, { "KEY_V", KEY_V }, { "KEY_W", KEY_W }, { "KEY_X", KEY_X },
	{ "KEY_Y", KEY_Y }, { "KEY_Z", KEY_Z },
	{ "ABS_X", ABS_X },           { "ABS_Y", ABS_Y },           { "ABS_RX", ABS_RX },
	{ "ABS_RY", ABS_RY },         { "ABS_Z", ABS_Z },           { "ABS_RZ", ABS_RZ },
};

struct source {
	char name[128];
	int optional;
	int power;	/* the power button: only its KEY_POWER is read */
	int fd;
};

struct keymap {
	unsigned short from, to;
};

/* Fn + code (an output code) gives the action's name to the clients */
struct chord_entry {
	unsigned short code;
	char action[24];
};

struct profile {
	char name[UINPUT_MAX_NAME_SIZE];
	unsigned short vendor, product;
	struct source src[MAX_SOURCES];
	int nsrc;
	struct keymap keys[MAX_KEYS];
	int nkeys;
	unsigned short axes[MAX_AXES];
	int naxes;
	int passthrough;
	int fn;		/* output code, -1 if none */
	int fn_hold_ms;
	struct chord_entry chords[MAX_CHORDS];
	int nchords;
	char hold_msg[320];	/* "fn_hold B=app_menu ... Vol=brightness" */
	char mixer_card[64], mixer_ctl[64];
	int mixer_step;
	int mixer_max;	/* raw ceiling of the control (0: none), e.g. 0 dB of a digital DAC */
	int backlight_max;	/* raw ceiling of the backlight (0: none): 100% of the launcher */
};

static volatile sig_atomic_t stop;
static int clients[MAX_CLIENTS];
static int nclients;
/* D11: the client that holds the capture (-1: none) and when it last spoke */
static int capture_fd = -1;
static long long capture_seen;
/* a client's "tap": the release still to send (-1: none) and when */
static int tap_code = -1;
static long long tap_at;
/* D11: between "phase suspend" and "phase resume" nothing is forwarded */
static int asleep;
static void reply_gone(int fd);

static long long now_ms(void)
{
	struct timespec ts;

	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (long long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

static void on_signal(int sig)
{
	(void)sig;
	stop = 1;
}

/* One line on stderr and in the kernel log (the boot log keeps it); English only. */
static void logline(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
static void logline(const char *fmt, ...)
{
	char msg[300];
	va_list ap;
	int k;

	va_start(ap, fmt);
	vsnprintf(msg, sizeof(msg), fmt, ap);
	va_end(ap);
	fprintf(stderr, PROG ": %s\n", msg);
	k = open("/dev/kmsg", O_WRONLY | O_CLOEXEC);
	if (k >= 0) {
		dprintf(k, "<5>" PROG ": %s\n", msg);
		close(k);
	}
}

static int parse_code(const char *s)
{
	char *end;
	long v;

	for (size_t i = 0; i < ARRAY_SIZE(NAMES); i++)
		if (!strcmp(NAMES[i].name, s))
			return NAMES[i].code;
	v = strtol(s, &end, 0);
	if (*s && !*end && v >= 0 && v <= KEY_MAX)
		return (int)v;
	return -1;
}

static const char *code_name(int code)
{
	for (size_t i = 0; i < ARRAY_SIZE(NAMES); i++)
		if (NAMES[i].code == code)
			return NAMES[i].name;
	return NULL;
}

/* A key a client may "tap": a keyboard key of the table, not a volume key, and none of
 * KEY_UP..KEY_DOWN: RetroArch's udev joypad driver numbers that range before BTN_MISC, so
 * declaring it would shift every button index of the autoconfig. */
static int tappable(int code)
{
	const char *n = code_name(code);

	return n && !strncmp(n, "KEY_", 4) && code != KEY_VOLUMEUP && code != KEY_VOLUMEDOWN &&
	       (code < KEY_UP || code > KEY_DOWN);
}

/* The short name of a button for the chord hint (the glyph on the screen): the gamepad
 * buttons, and the VM keyboard keys that play them (lume-ui's input.rs layout). */
static const char *button_label(int code, char *buf, size_t size)
{
	static const struct code_name LABELS[] = {
		{ "A", BTN_A }, { "A", KEY_X }, { "B", BTN_B }, { "B", KEY_Z },
		{ "X", BTN_X }, { "X", KEY_S }, { "Y", BTN_Y }, { "Y", KEY_A },
		{ "L1", BTN_TL }, { "L1", KEY_Q }, { "R1", BTN_TR }, { "R1", KEY_W },
		{ "L2", BTN_TL2 }, { "R2", BTN_TR2 }, { "L3", BTN_THUMBL }, { "R3", BTN_THUMBR },
		{ "Select", BTN_SELECT }, { "Select", KEY_RIGHTSHIFT },
		{ "Start", BTN_START }, { "Start", KEY_ENTER },
		{ "Up", BTN_DPAD_UP }, { "Down", BTN_DPAD_DOWN },
		{ "Left", BTN_DPAD_LEFT }, { "Right", BTN_DPAD_RIGHT },
	};
	const char *n;

	for (size_t i = 0; i < ARRAY_SIZE(LABELS); i++)
		if (LABELS[i].code == code)
			return LABELS[i].name;
	n = code_name(code);
	if (n && strchr(n, '_'))
		return strchr(n, '_') + 1;
	snprintf(buf, size, "0x%x", code);
	return buf;
}

static int valid_action(const char *s)
{
	size_t n = strlen(s);

	if (!n || n >= sizeof(((struct chord_entry *)0)->action))
		return 0;
	return strspn(s, "abcdefghijklmnopqrstuvwxyz_") == n;
}

static int add_chord(struct profile *p, int code, const char *action)
{
	for (int i = 0; i < p->nchords; i++)
		if (p->chords[i].code == code) {
			snprintf(p->chords[i].action, sizeof(p->chords[i].action), "%s", action);
			return 0;
		}
	if (p->nchords == MAX_CHORDS || !valid_action(action))
		return -1;
	p->chords[p->nchords].code = (unsigned short)code;
	snprintf(p->chords[p->nchords++].action, sizeof(p->chords[0].action), "%s", action);
	return 0;
}

static const char *chord_action(const struct profile *p, int code)
{
	for (int i = 0; i < p->nchords; i++)
		if (p->chords[i].code == code)
			return p->chords[i].action;
	return NULL;
}

/* "fn_hold B=app_menu R1=save_state ... Vol=brightness": the chord table, so the hint on
 * the screen never keeps a second copy of it (D13). */
static void build_hold_msg(struct profile *p)
{
	size_t len = (size_t)snprintf(p->hold_msg, sizeof(p->hold_msg), "fn_hold");

	for (int i = 0; i < p->nchords && len < sizeof(p->hold_msg); i++) {
		char buf[16];

		len += (size_t)snprintf(p->hold_msg + len, sizeof(p->hold_msg) - len, " %s=%s",
					button_label(p->chords[i].code, buf, sizeof(buf)), p->chords[i].action);
	}
	if (len < sizeof(p->hold_msg))
		snprintf(p->hold_msg + len, sizeof(p->hold_msg) - len, " Vol=brightness");
}

static char *trim(char *s)
{
	char *e;

	while (isspace((unsigned char)*s))
		s++;
	e = s + strlen(s);
	while (e > s && isspace((unsigned char)e[-1]))
		*--e = 0;
	return s;
}

/* Reads a profile; prints the offending line and returns -1 on error. */
static int load_profile(const char *path, struct profile *p)
{
	FILE *f = fopen(path, "r");
	char line[256];
	int n = 0;

	memset(p, 0, sizeof(*p));
	p->fn = -1;
	p->fn_hold_ms = FN_HOLD_MS;
	p->vendor = 0x1209;	/* pid.codes */
	if (!f) {
		perror(path);
		return -1;
	}
	while (fgets(line, sizeof(line), f)) {
		char *s, *arg, *hash;
		int a, b;

		n++;
		hash = strchr(line, '#');
		if (hash)
			*hash = 0;
		s = trim(line);
		if (!*s)
			continue;
		arg = s;
		while (*arg && !isspace((unsigned char)*arg))
			arg++;
		if (*arg)
			*arg++ = 0;
		arg = trim(arg);
		if (!strcmp(s, "name") && *arg) {
			snprintf(p->name, sizeof(p->name), "%s", arg);
		} else if (!strcmp(s, "id") && sscanf(arg, "%i %i", &a, &b) == 2) {
			p->vendor = (unsigned short)a;
			p->product = (unsigned short)b;
		} else if ((!strcmp(s, "source") || !strcmp(s, "source-optional")) && *arg &&
			   p->nsrc < MAX_SOURCES) {
			snprintf(p->src[p->nsrc].name, sizeof(p->src[0].name), "%s", arg);
			p->src[p->nsrc].optional = !strcmp(s, "source-optional");
			p->src[p->nsrc++].fd = -1;
		} else if (!strcmp(s, "power") && *arg && p->nsrc < MAX_SOURCES) {
			/* optional: without it the console still plays, only the button is gone */
			snprintf(p->src[p->nsrc].name, sizeof(p->src[0].name), "%s", arg);
			p->src[p->nsrc].optional = 1;
			p->src[p->nsrc].power = 1;
			p->src[p->nsrc++].fd = -1;
		} else if (!strcmp(s, "key") && p->nkeys < MAX_KEYS) {
			char from[64], to[64];

			if (sscanf(arg, "%63s %63s", from, to) != 2 || (a = parse_code(from)) < 0 ||
			    (b = parse_code(to)) < 0)
				goto bad;
			p->keys[p->nkeys].from = (unsigned short)a;
			p->keys[p->nkeys++].to = (unsigned short)b;
		} else if (!strcmp(s, "axis") && p->naxes < MAX_AXES && (a = parse_code(arg)) >= 0) {
			p->axes[p->naxes++] = (unsigned short)a;
		} else if (!strcmp(s, "passthrough") && !*arg) {
			p->passthrough = 1;
		} else if (!strcmp(s, "fn") && (a = parse_code(arg)) >= 0) {
			p->fn = a;
		} else if (!strcmp(s, "quit") && (a = parse_code(arg)) >= 0) {
			/* the line of older profiles on the card */
			if (add_chord(p, a, "quit") < 0)
				goto bad;
		} else if (!strcmp(s, "chord")) {
			char code[64], action[64];

			if (sscanf(arg, "%63s %63s", code, action) != 2 || (a = parse_code(code)) < 0 ||
			    add_chord(p, a, action) < 0)
				goto bad;
		} else if (!strcmp(s, "fn_hold_ms") && sscanf(arg, "%d", &a) == 1) {
			if (a < 100 || a > 5000)
				goto bad;
			p->fn_hold_ms = a;
		} else if (!strcmp(s, "mixer") &&
			   sscanf(arg, "%63s %63[^0-9] %d %d", p->mixer_card, p->mixer_ctl, &p->mixer_step,
				  &p->mixer_max) >= 3) {
			char *c = trim(p->mixer_ctl);

			memmove(p->mixer_ctl, c, strlen(c) + 1);
			if (p->mixer_step < 1 || p->mixer_step > 25 || p->mixer_max < 0)
				goto bad;
		} else if (!strcmp(s, "backlight_max") && sscanf(arg, "%d", &p->backlight_max) == 1) {
			if (p->backlight_max < 1)
				goto bad;
		} else {
			goto bad;
		}
	}
	fclose(f);
	if (!*p->name || !p->nsrc || (!p->nkeys && !p->passthrough)) {
		fprintf(stderr, PROG ": %s: needs name, a source and keys (or passthrough)\n", path);
		return -1;
	}
	build_hold_msg(p);
	return 0;
bad:
	fprintf(stderr, PROG ": %s:%d: bad line\n", path, n);
	fclose(f);
	return -1;
}

static int map_key(const struct profile *p, unsigned short code)
{
	if (code == KEY_VOLUMEUP || code == KEY_VOLUMEDOWN || code == KEY_POWER)
		return code;	/* handled by the daemon, never forwarded */
	for (int i = 0; i < p->nkeys; i++)
		if (p->keys[i].from == code)
			return p->keys[i].to;
	return p->passthrough ? code : -1;
}

static int is_axis(const struct profile *p, unsigned short code)
{
	for (int i = 0; i < p->naxes; i++)
		if (p->axes[i] == code)
			return 1;
	return 0;
}

/* Open the event device named `name`, skipping virtual ones (our own output has the same
 * name as the GA36 source); -1 if there is none. */
static int open_by_name(const char *name)
{
	DIR *dir = opendir("/dev/input");
	struct dirent *e;
	int found = -1;

	if (!dir)
		return -1;
	while (found < 0 && (e = readdir(dir))) {
		char path[300], dev_name[256] = "";
		struct input_id id;
		int fd;

		if (strncmp(e->d_name, "event", 5))
			continue;
		snprintf(path, sizeof(path), "/dev/input/%s", e->d_name);
		fd = open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
		if (fd < 0)
			continue;
		if (ioctl(fd, EVIOCGNAME(sizeof(dev_name) - 1), dev_name) >= 0 &&
		    !strcmp(dev_name, name) && ioctl(fd, EVIOCGID, &id) >= 0 &&
		    id.bustype != BUS_VIRTUAL)
			found = fd;
		else
			close(fd);
	}
	closedir(dir);
	return found;
}

static int wait_for(const char *name, int timeout_s)
{
	for (int i = 0; i <= timeout_s * 10; i++) {
		int fd = open_by_name(name);

		if (fd >= 0 || stop)
			return fd;
		usleep(100000);
	}
	return -1;
}

static void list_devices(void)
{
	DIR *dir = opendir("/dev/input");
	struct dirent *e;

	if (!dir)
		return;
	while ((e = readdir(dir))) {
		char path[300], dev_name[256] = "";
		struct input_id id = { 0 };
		int fd;

		if (strncmp(e->d_name, "event", 5))
			continue;
		snprintf(path, sizeof(path), "/dev/input/%s", e->d_name);
		fd = open(path, O_RDONLY | O_CLOEXEC);
		if (fd < 0)
			continue;
		ioctl(fd, EVIOCGNAME(sizeof(dev_name) - 1), dev_name);
		ioctl(fd, EVIOCGID, &id);
		printf("%s\t%s\tbus=0x%x\n", path, dev_name, id.bustype);
		close(fd);
	}
	closedir(dir);
}

static int create_device(const struct profile *p)
{
	struct uinput_setup setup;
	int fd = open("/dev/uinput", O_WRONLY | O_NONBLOCK | O_CLOEXEC);

	if (fd < 0) {
		perror(PROG ": /dev/uinput");
		return -1;
	}
	ioctl(fd, UI_SET_EVBIT, EV_SYN);
	ioctl(fd, UI_SET_EVBIT, EV_KEY);
	if (p->passthrough)
		for (int c = 1; c < 256; c++)
			if (c != KEY_VOLUMEUP && c != KEY_VOLUMEDOWN && c != KEY_POWER)
				ioctl(fd, UI_SET_KEYBIT, c);
	for (int i = 0; i < p->nkeys; i++)
		ioctl(fd, UI_SET_KEYBIT, p->keys[i].to);
	/* the keys a client may tap (a runner action "key:KEY_F2", D3) */
	for (size_t i = 0; i < ARRAY_SIZE(NAMES); i++)
		if (tappable(NAMES[i].code))
			ioctl(fd, UI_SET_KEYBIT, NAMES[i].code);
	if (p->naxes)
		ioctl(fd, UI_SET_EVBIT, EV_ABS);
	for (int i = 0; i < p->naxes; i++) {
		struct uinput_abs_setup abs = { .code = p->axes[i] };
		int got = 0;

		/* the ranges of the source (the board DTS or the kernel driver) */
		for (int s = 0; s < p->nsrc && !got; s++)
			got = p->src[s].fd >= 0 &&
			      ioctl(p->src[s].fd, EVIOCGABS(p->axes[i]), &abs.absinfo) >= 0 &&
			      abs.absinfo.maximum > abs.absinfo.minimum;
		if (!got)
			abs.absinfo = (struct input_absinfo){ .minimum = 0, .maximum = 1023 };
		ioctl(fd, UI_ABS_SETUP, &abs);
	}
	memset(&setup, 0, sizeof(setup));
	setup.id.bustype = BUS_VIRTUAL;
	setup.id.vendor = p->vendor;
	setup.id.product = p->product;
	setup.id.version = 1;
	snprintf(setup.name, sizeof(setup.name), "%s", p->name);
	if (ioctl(fd, UI_DEV_SETUP, &setup) < 0 || ioctl(fd, UI_DEV_CREATE) < 0) {
		perror(PROG ": uinput setup");
		close(fd);
		return -1;
	}
	return fd;
}

/* the keys the virtual device shows as held (a capture releases them) */
static unsigned char out_down[KEY_MAX + 1];

static void emit(int out, unsigned short type, unsigned short code, int value)
{
	struct input_event ev = { .type = type, .code = code, .value = value };

	if (type == EV_KEY && code <= KEY_MAX)
		out_down[code] = value != 0;
	if (write(out, &ev, sizeof(ev)) != (ssize_t)sizeof(ev))
		return;	/* a full uinput queue drops the event, like the kernel would */
}

static void emit_key(int out, unsigned short code, int value)
{
	emit(out, EV_KEY, code, value);
	emit(out, EV_SYN, SYN_REPORT, 0);
}

/* ---- the input socket (lume-run is the client) ---- */

static int open_socket(const char *path)
{
	struct sockaddr_un addr = { .sun_family = AF_UNIX };
	struct group *g;
	int fd;

	if (strlen(path) >= sizeof(addr.sun_path))
		return -1;
	strcpy(addr.sun_path, path);
	fd = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
	if (fd < 0)
		return -1;
	unlink(path);
	if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0 || listen(fd, 4) < 0) {
		perror(PROG ": socket");
		close(fd);
		return -1;
	}
	/* the frontend runs as game */
	g = getgrnam("game");
	if (g && chown(path, 0, g->gr_gid) == 0)
		chmod(path, 0660);
	return fd;
}

static void accept_client(int lfd)
{
	int c = accept4(lfd, NULL, NULL, SOCK_NONBLOCK | SOCK_CLOEXEC);

	if (c < 0)
		return;
	if (nclients == MAX_CLIENTS) {
		close(c);
		return;
	}
	clients[nclients++] = c;
}

static void capture_end(const char *why)
{
	if (capture_fd < 0)
		return;
	capture_fd = -1;
	logline("capture off (%s)", why);
}

static void drop_client(int i)
{
	if (clients[i] == capture_fd)
		capture_end("client gone");
	reply_gone(clients[i]);
	close(clients[i]);
	clients[i] = clients[--nclients];
}

/* A message to every client: an action of a chord ("quit" for Fn+Start; with no client the
 * chord does nothing), a Fn gesture, "volume" after a volume key. Clients ignore what they
 * do not know. A client that cannot take it is dropped (only in the main process: a child
 * just skips it). */
static void send_all(const char *msg, int drop)
{
	size_t len = strlen(msg);

	for (int i = 0; i < nclients;) {
		if (send(clients[i], msg, len, MSG_NOSIGNAL | MSG_DONTWAIT) != (ssize_t)len && drop)
			drop_client(i);
		else
			i++;
	}
}

/* ---- the level line over a game ---- */

/* Asks RetroArch for the launcher's level line (patch 0011, "LUME_LEVEL"): the right edge
 * for the volume, the left one for the brightness, in the colors of the launcher's theme
 * (written by lume-ui to level-colors on the card: "volume=rrggbb" and
 * "brightness=rrggbb"). A datagram to 127.0.0.1: with no game of RetroArch open, nobody
 * reads it. LUME_INPUT_RA_PORT and LUME_INPUT_LEVEL_COLORS change for the tests. */
static void ra_level(int left, long pct)
{
	const char *port = getenv("LUME_INPUT_RA_PORT");
	const char *colors = getenv("LUME_INPUT_LEVEL_COLORS");
	const char *key = left ? "brightness=" : "volume=";
	char rgb[7], line[64], msg[64];
	struct sockaddr_in to = { .sin_family = AF_INET };
	FILE *f;
	int fd;

	strcpy(rgb, left ? "ffffff" : "4db3ff");
	if (!colors)
		colors = "/storage/system/lume/level-colors";
	f = fopen(colors, "re");
	if (f) {
		while (fgets(line, sizeof(line), f)) {
			size_t k = strlen(key);

			if (!strncmp(line, key, k) && strspn(line + k, "0123456789abcdefABCDEF") >= 6) {
				memcpy(rgb, line + k, 6);
				rgb[6] = 0;
			}
		}
		fclose(f);
	}
	if (pct < 0)
		pct = 0;
	if (pct > 100)
		pct = 100;
	to.sin_port = htons(port ? (unsigned short)atoi(port) : 55355);
	to.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
	snprintf(msg, sizeof(msg), "LUME_LEVEL %s %ld %s", left ? "left" : "right", pct, rgb);
	fd = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC, 0);
	if (fd < 0)
		return;
	sendto(fd, msg, strlen(msg), MSG_DONTWAIT, (struct sockaddr *)&to, sizeof(to));
	close(fd);
}

/* ---- volume ---- */

/* "amixer sget" of the control: the raw limits and the first channel's raw value. 0 if read. */
static int mixer_get(const char *amixer, const struct profile *p, int *lo, int *hi, int *cur)
{
	char buf[4096], *l;
	size_t n = 0;
	ssize_t r;
	int fds[2], have_lim = 0, have_cur = 0;
	pid_t pid;

	if (pipe(fds) < 0)
		return -1;
	pid = fork();
	if (pid == 0) {
		dup2(fds[1], 1);
		close(fds[0]);
		close(fds[1]);
		execlp(amixer, "amixer", "-c", p->mixer_card, "sget", p->mixer_ctl, (char *)NULL);
		_exit(127);
	}
	close(fds[1]);
	while (pid > 0 && n < sizeof(buf) - 1 && (r = read(fds[0], buf + n, sizeof(buf) - 1 - n)) > 0)
		n += (size_t)r;
	close(fds[0]);
	buf[n] = 0;
	if (pid > 0)
		waitpid(pid, NULL, 0);
	/* "  Limits: Playback 0 - 192" and "  Front Left: Playback 160 [83%] [0.00dB] [on]" */
	for (l = strtok(buf, "\n"); l; l = strtok(NULL, "\n")) {
		char *pb = strstr(l, "Playback ");

		if (!pb)
			continue;
		if (strstr(l, "Limits:"))
			have_lim = sscanf(pb, "Playback %d - %d", lo, hi) == 2;
		else if (!have_cur && strchr(pb, '['))
			have_cur = sscanf(pb, "Playback %d", cur) == 1;
	}
	return have_lim && have_cur && *hi > *lo ? 0 : -1;
}

/* "amixer sset" of the control to `value`, waited for. */
static void mixer_set(const char *amixer, const struct profile *p, const char *value)
{
	pid_t pid = fork();

	if (pid == 0) {
		int null = open("/dev/null", O_RDWR);

		if (null >= 0)
			dup2(null, 1);
		execlp(amixer, "amixer", "-c", p->mixer_card, "-q", "sset", p->mixer_ctl, value,
		       (char *)NULL);
		_exit(127);
	}
	if (pid > 0)
		waitpid(pid, NULL, 0);
}

/* One volume step. With a ceiling (mixer_max) the new raw value is computed here and set as
 * a number, so the control never goes above it, not even for a moment (GA36: DAC 160 is
 * 0 dB, above it the digital gain clips). Then "volume" goes to the clients (the launcher
 * shows the level), also when the level was already at a limit. Runs in a child: the input
 * loop never waits. */
static void volume(const struct profile *p, int up)
{
	const char *amixer = getenv("LUME_INPUT_AMIXER");
	char step[16];
	pid_t pid;

	if (!p->mixer_step)
		return;
	if (!amixer)
		amixer = "amixer";
	pid = fork();
	if (pid == 0) {
		int null = open("/dev/null", O_RDWR);

		signal(SIGCHLD, SIG_DFL);	/* this child waits for its own amixer */
		if (null >= 0)
			dup2(null, 2);
		snprintf(step, sizeof(step), "%d%%%c", p->mixer_step, up ? '+' : '-');
		if (p->mixer_max > 0) {
			int lo, hi, cur, d, v, top;

			if (mixer_get(amixer, p, &lo, &hi, &cur) < 0)
				_exit(1);
			d = (p->mixer_step * (hi - lo) + 50) / 100;
			if (d < 1)
				d = 1;
			top = p->mixer_max < hi ? p->mixer_max : hi;
			v = up ? cur + d : cur - d;
			if (v > top)
				v = top;
			if (v < lo)
				v = lo;
			snprintf(step, sizeof(step), "%d", v);
			if (v != cur)
				mixer_set(amixer, p, step);
			/* the level is a share of the ceiling, as the launcher shows it */
			ra_level(0, top > lo ? ((long)(v - lo) * 100 + (top - lo) / 2) / (top - lo) : 0);
		} else {
			int lo, hi, cur;

			mixer_set(amixer, p, step);
			if (mixer_get(amixer, p, &lo, &hi, &cur) == 0)
				ra_level(0, ((long)(cur - lo) * 100 + (hi - lo) / 2) / (hi - lo));
		}
		send_all("volume", 0);
		_exit(0);
	}
}

/* ---- brightness ---- */

/* A number from a sysfs file; -1 when it cannot be read. */
static long read_long(const char *dir, const char *name)
{
	char path[512], buf[32];
	long v = -1;
	ssize_t n;
	int fd;

	snprintf(path, sizeof(path), "%s/%s", dir, name);
	fd = open(path, O_RDONLY | O_CLOEXEC);
	if (fd < 0)
		return -1;
	n = read(fd, buf, sizeof(buf) - 1);
	close(fd);
	if (n > 0) {
		buf[n] = 0;
		v = strtol(buf, NULL, 10);
	}
	return v;
}

/* The folder of the first backlight in dir; 0 when found. */
static int find_backlight(char *dir, size_t size)
{
	const char *root = getenv("LUME_INPUT_BACKLIGHT");
	struct dirent *e;
	DIR *d;

	if (!root)
		root = "/sys/class/backlight";
	d = opendir(root);
	if (!d)
		return -1;
	dir[0] = 0;
	while ((e = readdir(d))) {
		if (e->d_name[0] != '.') {
			snprintf(dir, size, "%s/%s", root, e->d_name);
			break;
		}
	}
	closedir(d);
	return dir[0] ? 0 : -1;
}

static void write_backlight(const char *dir, long v)
{
	char path[420], value[24];
	int fd, len;

	snprintf(path, sizeof(path), "%s/brightness", dir);
	fd = open(path, O_WRONLY | O_TRUNC | O_CLOEXEC);
	if (fd < 0)
		return;
	len = snprintf(value, sizeof(value), "%ld", v);
	if (write(fd, value, (size_t)len) != len)
		logline("backlight not written: %s", strerror(errno));
	close(fd);
}

/* At start: a backlight above the profile's ceiling comes down to it (the kernel starts the
 * GA36 at level 8 from its device tree; above 7 the panel flickers). */
static void clamp_backlight(const struct profile *p)
{
	char dir[400];
	long cur;

	if (p->backlight_max <= 0 || find_backlight(dir, sizeof(dir)) < 0)
		return;
	cur = read_long(dir, "brightness");
	if (cur > p->backlight_max) {
		write_backlight(dir, p->backlight_max);
		logline("backlight %ld above the ceiling, set to %d", cur, p->backlight_max);
	}
}

/* One brightness step of 5% on the first backlight (the launcher's Settings use the same
 * steps and floor: never fully dark, the screen would look off). With a ceiling in the
 * profile (backlight_max) that level is 100% and nothing goes above it (GA36: above level 7
 * the panel flickers and shows broken parts, seen 2026-11-15). Then "brightness" goes to the
 * clients, also at a limit. A sysfs write is quick: done in the main process. */
static void brightness(const struct profile *p, int up)
{
	char dir[400];
	long max, cur, pct, v, floor_v;

	if (find_backlight(dir, sizeof(dir)) < 0)
		return;
	max = read_long(dir, "max_brightness");
	cur = read_long(dir, "brightness");
	if (max <= 0 || cur < 0)
		return;
	if (p->backlight_max > 0 && p->backlight_max < max)
		max = p->backlight_max;	/* the ceiling is 100% from here on */
	pct = (cur * 100 + max / 2) / max + (up ? 5 : -5);
	if (pct > 100)
		pct = 100;
	if (pct < 5)
		pct = 5;
	v = (max * pct + 50) / 100;
	/* a coarse backlight (GA36: 0-10) can round 5% back to the same level: then one level */
	if (v == cur)
		v = up ? cur + 1 : cur - 1;
	if (v > max)
		v = max;
	floor_v = (max * 5 + 50) / 100;
	if (floor_v < 1)
		floor_v = 1;
	if (v < floor_v)
		v = floor_v;
	if (v != cur)
		write_backlight(dir, v);
	ra_level(1, (v * 100 + max / 2) / max);
	send_all("brightness", 1);
}

/* ---- the Fn key: gestures and chords (D1, D13) ---- */

struct chord {
	int fn_down;		/* Fn held */
	int fn_used;		/* a chord or Fn+volume happened: no gesture on release */
	int fn_held;		/* "fn_hold" went out: "fn_release" is due */
	long long fn_since;	/* when Fn went down */
	unsigned char swallow[KEY_MAX + 1];	/* keys whose repeats and release are dropped */
};

/* Milliseconds until "fn_hold" is due; -1 when no gesture is pending. */
static long long hold_due(const struct profile *p, const struct chord *c, long long now)
{
	long long left;

	if (!c->fn_down || c->fn_used || c->fn_held)
		return -1;
	left = c->fn_since + p->fn_hold_ms - now;
	return left > 0 ? left : 0;
}

/* Fn held long enough without another key: the hint of the chords. */
static void hold_check(const struct profile *p, struct chord *c, long long now)
{
	if (hold_due(p, c, now) == 0) {
		c->fn_held = 1;
		send_all(p->hold_msg, 1);
	}
}

/* Fn was used in a chord: the hint goes away first, and no gesture follows. */
static void fn_used(struct chord *c)
{
	c->fn_used = 1;
	if (c->fn_held) {
		c->fn_held = 0;
		send_all("fn_release", 1);
	}
}

/* The "nav" word of a key during a capture (the gamepad codes and the VM keyboard of
 * lume-ui's input.rs); NULL for a key that navigates nothing. */
static const char *nav_word(int code)
{
	switch (code) {
	case BTN_DPAD_UP: case KEY_UP: return "nav up";
	case BTN_DPAD_DOWN: case KEY_DOWN: return "nav down";
	case BTN_DPAD_LEFT: case KEY_LEFT: return "nav left";
	case BTN_DPAD_RIGHT: case KEY_RIGHT: return "nav right";
	case BTN_A: case KEY_X: return "nav a";
	case BTN_B: case KEY_Z: case KEY_ESC: case KEY_BACKSPACE: return "nav b";
	}
	return NULL;
}

static void capture_send(const char *msg)
{
	size_t len = strlen(msg);

	if (capture_fd >= 0 && send(capture_fd, msg, len, MSG_NOSIGNAL | MSG_DONTWAIT) != (ssize_t)len)
		logline("nav not delivered: %s", strerror(errno));
}

/* ---- the power button and the sleep protocol (device-fixes D11, lume_core::sleep) ---- */

static const char *sleep_dir = DEFAULT_SLEEP_DIR;
static unsigned int asleep_seq;
static long long asleep_since;

/* the power button: down since, the hold already sent, ignored until let go (after a resume) */
static struct {
	int down, held, ignore;
	long long since;
} pw;
static long long resumed_at = -WAKE_GUARD_MS;	/* no resume yet: no guard */

/* the wait for the answers to "suspend <seq>" (wait_seq 0: none); the clients awaited are
 * the ones connected when the notice went out */
static unsigned int wait_seq;
static long long wait_deadline;
static int waiting[MAX_CLIENTS], nwaiting, wait_answered, wait_total;

/* inotify on the sleep folder, and on its parent until the folder appears (lume-sleep
 * starts after the frontend, this daemon before it) */
static int ino_fd = -1, ino_dir_wd = -1, ino_parent_wd = -1;
static long long ino_retry_at;
static char last_phase[32];

/* A sequence number: a positive decimal integer that fits in 32 bits; 0 if it is not one. */
static unsigned int parse_seq(const char *s)
{
	size_t n = strlen(s);
	unsigned long long v;

	if (!n || n > 10 || strspn(s, "0123456789") != n)
		return 0;
	v = strtoull(s, NULL, 10);
	return v > 0xffffffffULL ? 0 : (unsigned int)v;
}

/* Text of a file as it may go in a log line: printable ASCII, the rest as '?'. */
static void log_safe(char *s)
{
	for (; *s; s++)
		if ((unsigned char)*s < 0x20 || (unsigned char)*s > 0x7e)
			*s = '?';
}

/* Creates the request `name` in the sleep folder, never twice (O_EXCL); 1 when made. */
static int sleep_request(const char *name)
{
	char path[512];
	int fd;

	snprintf(path, sizeof(path), "%s/%s", sleep_dir, name);
	fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
	if (fd >= 0) {
		close(fd);
		return 1;
	}
	if (errno == EEXIST)
		logline("%s request already pending", name);
	else if (errno == ENOENT)
		logline("no sleep service (%s missing): power button request dropped", sleep_dir);
	else
		logline("power button request %s not made: %s", name, strerror(errno));
	return 0;
}

/* A gesture of the power button: the request, then the notice (only for a new request). */
static void power_gesture(const char *request, const char *notice)
{
	if (sleep_request(request))
		send_all(notice, 1);
}

/* Milliseconds until the hold is due; -1 when none is pending. */
static long long power_hold_due(long long now)
{
	long long left;

	if (!pw.down || pw.held || asleep)
		return -1;
	left = pw.since + POWER_HOLD_MS - now;
	return left > 0 ? left : 0;
}

static void power_check(long long now)
{
	if (power_hold_due(now) == 0) {
		pw.held = 1;
		power_gesture("poweroff", "power_hold");
	}
}

/* A KEY_POWER event: the tap and the hold; the button never goes out. */
static void power_key(int value)
{
	long long now = now_ms();

	if (asleep || value == 2)
		return;
	if (pw.ignore) {
		/* the press that woke the console: wait for its release; a press within the
		 * guard is that one too, a later one is new (its release was dropped asleep) */
		if (value == 0)
			pw.ignore = 0;
		if (value == 0 || now - resumed_at < WAKE_GUARD_MS)
			return;
		pw.ignore = 0;
	}
	if (value == 1) {
		pw.down = 1;
		pw.held = 0;
		pw.since = now;
		return;
	}
	if (!pw.down)
		return;
	power_check(now);	/* a release read late must not turn a hold into nothing */
	if (!pw.held && now - pw.since < POWER_TAP_MS) {
		/* a tap begun within the guard is the waking press bouncing: no request (lume-sleep
		 * drops it too); a hold still powers off */
		if (pw.since - resumed_at < WAKE_GUARD_MS)
			logline("power tap within 1 s of the resume dropped: the press that woke the console");
		else
			power_gesture("suspend", "power_tap");
	}
	pw.down = pw.held = 0;
}

/* "clients", written by rename: how the clients answered "suspend <seq>". */
static void write_clients(void)
{
	char tmp[512], path[512], line[64];
	int fd, len, ok, err = 0;

	len = snprintf(line, sizeof(line), "suspend %u %s %d/%d\n", wait_seq,
		       nwaiting ? "timeout" : "ok", wait_answered, wait_total);
	snprintf(tmp, sizeof(tmp), "%s/.clients.tmp", sleep_dir);
	snprintf(path, sizeof(path), "%s/clients", sleep_dir);
	unlink(tmp);
	fd = open(tmp, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0644);
	ok = fd >= 0 && write(fd, line, (size_t)len) == len;
	if (!ok)
		err = errno;
	if (fd >= 0)
		close(fd);
	if (ok && rename(tmp, path) < 0) {
		ok = 0;
		err = errno;
	}
	if (!ok) {
		logline("clients not written: %s", strerror(err));
		unlink(tmp);
	}
}

/* The wait is over (everyone answered, the deadline, or a newer phase): "clients" goes out. */
static void reply_finish(void)
{
	if (!wait_seq)
		return;
	if (nwaiting)
		logline("suspend %u: %d of %d client(s) answered within 2 s", wait_seq, wait_answered,
			wait_total);
	write_clients();
	wait_seq = 0;
	nwaiting = 0;
}

/* `fd` is no longer awaited: it answered, or it hung up (then it does not count at all). */
static void reply_take(int fd, int answered)
{
	for (int i = 0; i < nwaiting; i++)
		if (waiting[i] == fd) {
			waiting[i] = waiting[--nwaiting];
			if (answered)
				wait_answered++;
			else
				wait_total--;
			if (!nwaiting)
				reply_finish();
			return;
		}
}

static void reply_gone(int fd)
{
	if (wait_seq)
		reply_take(fd, 0);
}

/* "suspend_ok <seq>": another sequence, a second answer or a client not asked is ignored. */
static void reply_answer(int fd, unsigned int seq)
{
	if (wait_seq && seq == wait_seq)
		reply_take(fd, 1);
}

static void reply_start(unsigned int seq)
{
	char msg[32];

	reply_finish();	/* an older wait still open answers now */
	snprintf(msg, sizeof(msg), "suspend %u", seq);
	send_all(msg, 1);
	nwaiting = 0;
	for (int i = 0; i < nclients; i++)
		waiting[nwaiting++] = clients[i];
	wait_total = nwaiting;
	wait_answered = 0;
	wait_deadline = now_ms() + CLIENT_REPLY_MS;
	wait_seq = seq;
	if (!nwaiting)
		reply_finish();
}

/* Releases every key the virtual device shows as held; the number released. */
static int release_held(int out)
{
	int released = 0;

	for (int k = 0; k <= KEY_MAX; k++)
		if (out_down[k]) {
			emit(out, EV_KEY, (unsigned short)k, 0);
			released++;
		}
	if (released)
		emit(out, EV_SYN, SYN_REPORT, 0);
	return released;
}

/* Fn back to rest; a hint on the screen goes away first. */
static void chord_reset(struct chord *c)
{
	if (c->fn_held)
		send_all("fn_release", 1);
	c->fn_down = c->fn_used = c->fn_held = 0;
	memset(c->swallow, 0, sizeof(c->swallow));
}

/* Reads and drops everything queued on the sources; the number of events dropped. */
static int drain(const struct profile *p)
{
	struct input_event ev[64];
	int dropped = 0;

	for (int s = 0; s < p->nsrc; s++) {
		ssize_t n;

		if (p->src[s].fd < 0)
			continue;
		for (int k = 0; k < 256 && (n = read(p->src[s].fd, ev, sizeof(ev))) > 0; k++)
			dropped += (int)((size_t)n / sizeof(ev[0]));
	}
	return dropped;
}

/* The sticks as they are now (the moves made asleep were dropped, and the kernel only
 * reports changes); a source that cannot tell (a test FIFO) is skipped. */
static void sync_axes(const struct profile *p, int out)
{
	int sent = 0;

	for (int i = 0; i < p->naxes; i++)
		for (int s = 0; s < p->nsrc; s++) {
			struct input_absinfo abs;

			if (p->src[s].fd < 0 || p->src[s].power ||
			    ioctl(p->src[s].fd, EVIOCGABS(p->axes[i]), &abs) < 0 || abs.maximum <= abs.minimum)
				continue;
			emit(out, EV_ABS, p->axes[i], abs.value);
			sent = 1;
			break;
		}
	if (sent)
		emit(out, EV_SYN, SYN_REPORT, 0);
}

/* May the power button be down right now? The key state of each power source; one that
 * cannot tell (a test FIFO) counts as down. */
static int power_maybe_down(const struct profile *p)
{
	for (int s = 0; s < p->nsrc; s++) {
		unsigned char bits[KEY_MAX / 8 + 1];

		if (!p->src[s].power || p->src[s].fd < 0)
			continue;
		memset(bits, 0, sizeof(bits));
		if (ioctl(p->src[s].fd, EVIOCGKEY(sizeof(bits)), bits) < 0 ||
		    (bits[KEY_POWER / 8] & (1 << (KEY_POWER % 8))))
			return 1;
	}
	return 0;
}

/* "phase suspend <seq>": tell the clients and stop forwarding. */
static void sleep_begin(unsigned int seq, struct chord *c)
{
	chord_reset(c);
	pw.down = pw.held = pw.ignore = 0;
	asleep = 1;
	asleep_seq = seq;
	asleep_since = now_ms();
	reply_start(seq);
}

/* "phase resume <seq>" (or the input coming back on its own): drop the queued input,
 * release the held keys, then tell the clients. */
static void sleep_end(unsigned int seq, const struct profile *p, struct chord *c, int out)
{
	char msg[32];
	int dropped, released;

	reply_finish();
	dropped = drain(p);
	released = release_held(out);
	tap_code = -1;	/* released above */
	sync_axes(p, out);
	chord_reset(c);
	pw.down = pw.held = 0;
	pw.ignore = power_maybe_down(p);
	resumed_at = now_ms();
	if (capture_fd >= 0)
		capture_seen = resumed_at;	/* the menu could not renew it asleep */
	asleep = 0;
	logline("resume %u: %d queued event(s) dropped, %d key(s) released", seq, dropped, released);
	snprintf(msg, sizeof(msg), "resume %u", seq);
	send_all(msg, 1);
}

/* Reads "phase" (root's only; the owner of the daemon in the tests). */
static void read_phase(const struct profile *p, struct chord *c, int out)
{
	char path[512], buf[32], *word, *rest;
	struct stat st = { 0 };
	unsigned int seq = 0;
	ssize_t n;
	int fd;

	snprintf(path, sizeof(path), "%s/phase", sleep_dir);
	fd = open(path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC);
	if (fd < 0)
		return;
	if (fstat(fd, &st) < 0 || !S_ISREG(st.st_mode) || (st.st_uid != 0 && st.st_uid != geteuid())) {
		close(fd);
		logline("phase not trusted (owner %u)", (unsigned int)st.st_uid);
		return;
	}
	n = read(fd, buf, sizeof(buf) - 1);
	close(fd);
	if (n <= 0)
		return;
	buf[n] = 0;
	word = trim(buf);
	if (!strcmp(word, last_phase))
		return;	/* the same phase seen twice (written, then renamed) */
	snprintf(last_phase, sizeof(last_phase), "%s", word);
	rest = strchr(word, ' ');
	if (rest) {
		*rest++ = 0;
		seq = parse_seq(trim(rest));
	}
	if (seq && !strcmp(word, "suspend")) {
		sleep_begin(seq, c);
	} else if (seq && !strcmp(word, "resume")) {
		sleep_end(seq, p, c, out);
	} else {
		char shown[32];

		snprintf(shown, sizeof(shown), "%s", last_phase);
		log_safe(shown);
		logline("bad phase \"%s\"", shown);
	}
}

/* Watches the sleep folder (or its parent until the folder appears). */
static void sleep_watch(void)
{
	char parent[512], *slash;

	if (ino_fd < 0)
		ino_fd = inotify_init1(IN_NONBLOCK | IN_CLOEXEC);
	if (ino_fd < 0)
		return;
	if (ino_parent_wd < 0) {
		snprintf(parent, sizeof(parent), "%s", sleep_dir);
		slash = strrchr(parent, '/');
		if (!slash)
			snprintf(parent, sizeof(parent), ".");
		else if (slash == parent)
			slash[1] = 0;
		else
			*slash = 0;
		ino_parent_wd = inotify_add_watch(ino_fd, parent, IN_CREATE | IN_MOVED_TO | IN_ONLYDIR);
	}
	if (ino_dir_wd < 0) {
		ino_dir_wd = inotify_add_watch(ino_fd, sleep_dir, IN_CLOSE_WRITE | IN_MOVED_TO |
					       IN_DELETE_SELF | IN_MOVE_SELF | IN_ONLYDIR);
		if (ino_dir_wd >= 0)
			last_phase[0] = 0;	/* a phase left there before is not acted on */
	}
	if (ino_dir_wd < 0 && ino_parent_wd < 0)
		ino_retry_at = now_ms() + WATCH_RETRY_MS;
}

static void sleep_events(const struct profile *p, struct chord *c, int out)
{
	char buf[4096] __attribute__((aligned(__alignof__(struct inotify_event))));
	const char *base = strrchr(sleep_dir, '/');
	int phase = 0, appeared = 0, gone = 0;
	ssize_t n;

	base = base ? base + 1 : sleep_dir;
	while ((n = read(ino_fd, buf, sizeof(buf))) > 0) {
		for (char *at = buf; at < buf + n;) {
			const struct inotify_event *ev = (const struct inotify_event *)(void *)at;

			at += sizeof(*ev) + ev->len;
			if (ino_dir_wd >= 0 && ev->wd == ino_dir_wd) {
				if (ev->mask & (IN_DELETE_SELF | IN_MOVE_SELF | IN_IGNORED))
					gone = 1;
				else if (ev->len && !strcmp(ev->name, "phase"))
					phase = 1;
			} else if (ino_parent_wd >= 0 && ev->wd == ino_parent_wd && ev->len &&
				   !strcmp(ev->name, base)) {
				appeared = 1;
			}
		}
	}
	if (gone) {
		inotify_rm_watch(ino_fd, ino_dir_wd);
		ino_dir_wd = -1;
		phase = 0;
		appeared = 1;	/* it may be there again already */
		if (asleep) {
			logline("sleep folder gone while asleep: input back");
			sleep_end(asleep_seq, p, c, out);
		}
	}
	if (appeared)
		sleep_watch();
	if (phase)
		read_phase(p, c, out);
}

static void key_event(const struct profile *p, struct chord *c, int out, int code, int value)
{
	const char *action;

	if (code == KEY_POWER) {
		power_key(value);
		return;
	}
	if (code == KEY_VOLUMEUP || code == KEY_VOLUMEDOWN) {
		if (value != 1)
			return;
		if (c->fn_down) {
			/* Fn+volume: the backlight */
			fn_used(c);
			brightness(p, code == KEY_VOLUMEUP);
		} else {
			volume(p, code == KEY_VOLUMEUP);
		}
		return;
	}
	if (p->fn >= 0 && code == p->fn) {
		/* the Fn key never goes out; repeats are dropped */
		if (value == 1) {
			c->fn_down = 1;
			c->fn_used = c->fn_held = 0;
			c->fn_since = now_ms();
		} else if (value == 0 && c->fn_down) {
			if (c->fn_held)
				send_all("fn_release", 1);
			else if (!c->fn_used)
				send_all("fn_tap", 1);
			c->fn_down = c->fn_used = c->fn_held = 0;
		}
		return;
	}
	if (value != 1 && c->swallow[code]) {
		/* the repeats and the release of a chord's key */
		if (value == 0)
			c->swallow[code] = 0;
		return;
	}
	if (c->fn_down && value == 1) {
		/* hold_check runs first: a Fn held past fn_hold_ms shows the hint, then the
		 * chord takes it away */
		hold_check(p, c, now_ms());
		fn_used(c);
		c->swallow[code] = 1;
		action = chord_action(p, code);
		if (action)
			send_all(action, 1);
		return;	/* a chord out of the table is reserved: nothing */
	}
	if (capture_fd >= 0) {
		/* D11: nothing reaches the game; the menu gets the navigation */
		const char *nav = nav_word(code);

		if (nav && value != 0)
			capture_send(nav);
		return;
	}
	if (value != 1 && code <= KEY_MAX && !out_down[code])
		return;	/* the repeat or release of a press the game never got (asleep, a capture) */
	emit(out, EV_KEY, code, value);
}

/* ---- the client messages: tap and capture (D2, D11) ---- */

static void capture_start(int fd, int out)
{
	int released;

	capture_seen = now_ms();
	if (capture_fd == fd)
		return;	/* the renewal of every second */
	/* nothing stays held in the game */
	released = release_held(out);
	capture_fd = fd;
	logline("capture on (%d key(s) released)", released);
}

static void client_message(int fd, char *msg, int out)
{
	char *m = trim(msg);
	int code;

	if (fd == capture_fd)
		capture_seen = now_ms();
	if (!strcmp(m, "capture on")) {
		capture_start(fd, out);
	} else if (!strcmp(m, "capture off")) {
		if (fd == capture_fd)
			capture_end("asked");
	} else if (!strncmp(m, "suspend_ok ", 11)) {
		reply_answer(fd, parse_seq(trim(m + 11)));
	} else if (!strncmp(m, "tap ", 4)) {
		if (asleep)
			return;	/* D11: nothing reaches the game until the resume */
		code = parse_code(trim(m + 4));
		if (strncmp(trim(m + 4), "KEY_", 4) || code < 0 || !tappable(code)) {
			logline("tap refused: \"%s\"", m + 4);
			return;
		}
		if (tap_code >= 0)
			emit_key(out, (unsigned short)tap_code, 0);
		emit_key(out, (unsigned short)code, 1);
		tap_code = code;
		tap_at = now_ms() + TAP_MS;
	}
	/* anything else: a newer client, ignored */
}

/* The timers of the loop: fn_hold, the power hold, the release of a tap, the idle end of a
 * capture, the deadline of the clients' answers, a suspension without resume, the watch of
 * the sleep folder. */
static void timers(const struct profile *p, struct chord *c, int out)
{
	long long now = now_ms();

	hold_check(p, c, now);
	power_check(now);
	if (wait_seq && now >= wait_deadline)
		reply_finish();
	if (asleep && now - asleep_since >= SLEEP_STUCK_MS) {
		logline("no resume within %d s of suspend %u: input back", SLEEP_STUCK_MS / 1000, asleep_seq);
		sleep_end(asleep_seq, p, c, out);
	}
	if (ino_dir_wd < 0 && ino_parent_wd < 0 && now >= ino_retry_at)
		sleep_watch();
	if (tap_code >= 0 && now >= tap_at) {
		emit_key(out, (unsigned short)tap_code, 0);
		tap_code = -1;
	}
	if (capture_fd >= 0 && now - capture_seen >= CAPTURE_IDLE_MS)
		capture_end("no message in 2 s");
}

/* The poll timeout in ms (-1: none) for the next timer. */
static int next_timer(const struct profile *p, const struct chord *c, int base)
{
	long long now = now_ms(), t = base, d;

	d = hold_due(p, c, now);
	if (d >= 0 && (t < 0 || d < t))
		t = d;
	if (tap_code >= 0) {
		d = tap_at > now ? tap_at - now : 0;
		if (t < 0 || d < t)
			t = d;
	}
	if (capture_fd >= 0) {
		d = capture_seen + CAPTURE_IDLE_MS - now;
		d = d > 0 ? d : 0;
		if (t < 0 || d < t)
			t = d;
	}
	d = power_hold_due(now);
	if (d >= 0 && (t < 0 || d < t))
		t = d;
	if (wait_seq) {
		d = wait_deadline > now ? wait_deadline - now : 0;
		if (t < 0 || d < t)
			t = d;
	}
	if (asleep) {
		d = asleep_since + SLEEP_STUCK_MS - now;
		d = d > 0 ? d : 0;
		if (t < 0 || d < t)
			t = d;
	}
	if (ino_dir_wd < 0 && ino_parent_wd < 0) {
		d = ino_retry_at > now ? ino_retry_at - now : 0;
		if (t < 0 || d < t)
			t = d;
	}
	return (int)t;
}

/* Forward the events of one source; -1 when the device is gone (or a file ended). */
static int forward(const struct profile *p, struct chord *c, const struct source *src, int out)
{
	struct input_event ev[64];
	ssize_t n = read(src->fd, ev, sizeof(ev));

	if (n < 0)
		return errno == EAGAIN || errno == EINTR ? 0 : -1;
	if (n == 0)
		return -1;
	if (asleep)
		return 0;	/* D11: read and dropped until the resume */
	for (size_t i = 0; i < (size_t)n / sizeof(ev[0]); i++) {
		int code;

		if (src->power) {
			/* only the button: its SYN and anything else never reach the game */
			if (ev[i].type == EV_KEY && ev[i].code == KEY_POWER)
				key_event(p, c, out, KEY_POWER, ev[i].value);
			continue;
		}
		switch (ev[i].type) {
		case EV_KEY:
			code = map_key(p, ev[i].code);
			if (code >= 0)
				key_event(p, c, out, code, ev[i].value);
			break;
		case EV_ABS:
			if (is_axis(p, ev[i].code) && capture_fd < 0)
				emit(out, EV_ABS, ev[i].code, ev[i].value);
			break;
		case EV_SYN:
			if (ev[i].code == SYN_REPORT)
				emit(out, EV_SYN, SYN_REPORT, 0);
			break;
		}
	}
	return 0;
}

static void usage(void)
{
	fprintf(stderr,
		"usage: " PROG " --profile FILE [--socket PATH] [--timeout SECONDS]\n"
		"       " PROG " --profile FILE --test OUT --source NAME=PATH... [--socket PATH]\n"
		"       " PROG " --list\n");
}

int main(int argc, char **argv)
{
	const char *profile_path = NULL, *sock_path = DEFAULT_SOCKET, *test_out = NULL;
	const char *test_src[MAX_SOURCES * 2];
	int ntest_src = 0, timeout_s = 10, out, lfd, rc = 0;
	struct sigaction sa = { .sa_handler = on_signal };
	struct sigaction chld = { .sa_handler = SIG_IGN, .sa_flags = SA_NOCLDWAIT };
	struct profile p;
	static struct chord chord;

	for (int i = 1; i < argc; i++) {
		if (!strcmp(argv[i], "--list")) {
			list_devices();
			return 0;
		} else if (i + 1 < argc && !strcmp(argv[i], "--profile")) {
			profile_path = argv[++i];
		} else if (i + 1 < argc && !strcmp(argv[i], "--socket")) {
			sock_path = argv[++i];
		} else if (i + 1 < argc && !strcmp(argv[i], "--timeout")) {
			timeout_s = atoi(argv[++i]);
		} else if (i + 1 < argc && !strcmp(argv[i], "--test")) {
			test_out = argv[++i];
		} else if (i + 1 < argc && !strcmp(argv[i], "--source") &&
			   ntest_src < (int)ARRAY_SIZE(test_src)) {
			test_src[ntest_src++] = argv[++i];
		} else {
			usage();
			return 2;
		}
	}
	if (!profile_path) {
		usage();
		return 2;
	}
	if (load_profile(profile_path, &p) < 0)
		return 1;
	sigaction(SIGTERM, &sa, NULL);
	sigaction(SIGINT, &sa, NULL);
	sigaction(SIGCHLD, &chld, NULL);
	signal(SIGPIPE, SIG_IGN);

	for (int s = 0; s < p.nsrc; s++) {
		if (test_out) {
			/* --source NAME=PATH: a file or FIFO instead of the device NAME */
			for (int t = 0; t < ntest_src; t++) {
				size_t len = strlen(p.src[s].name);

				if (!strncmp(test_src[t], p.src[s].name, len) && test_src[t][len] == '=')
					p.src[s].fd = open(test_src[t] + len + 1, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
			}
		} else {
			p.src[s].fd = wait_for(p.src[s].name, p.src[s].optional ? 1 : timeout_s);
		}
		if (p.src[s].fd < 0) {
			logline("no input device named \"%s\"%s", p.src[s].name,
				p.src[s].optional ? " (optional)" : "");
			if (!p.src[s].optional)
				return 1;
		}
	}
	out = test_out ? open(test_out, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644)
		       : create_device(&p);
	if (out < 0)
		return 1;
	for (int s = 0; s < p.nsrc; s++)
		if (p.src[s].fd >= 0 && !test_out)
			ioctl(p.src[s].fd, EVIOCGRAB, 1);
	lfd = open_socket(sock_path);
	if (lfd < 0)
		logline("no socket at %s: the Fn chords do nothing", sock_path);
	if (getenv("LUME_SLEEP_DIR") && *getenv("LUME_SLEEP_DIR"))
		sleep_dir = getenv("LUME_SLEEP_DIR");
	sleep_watch();
	clamp_backlight(&p);
	{
		int found = 0;

		for (int s = 0; s < p.nsrc; s++)
			found += p.src[s].fd >= 0;
		logline("\"%s\" from %d of %d source(s), socket %s, volume %s", p.name, found, p.nsrc,
			sock_path, p.mixer_step ? p.mixer_ctl : "off");
	}

	while (!stop) {
		struct pollfd fds[MAX_SOURCES + 2 + MAX_CLIENTS];
		int src_idx[MAX_SOURCES], n = 0, live = 0;

		for (int s = 0; s < p.nsrc; s++) {
			if (p.src[s].fd < 0)
				continue;
			src_idx[n] = s;
			fds[n++] = (struct pollfd){ .fd = p.src[s].fd, .events = POLLIN };
			live++;
		}
		if (!live)
			break;
		fds[n++] = (struct pollfd){ .fd = lfd, .events = POLLIN };
		fds[n++] = (struct pollfd){ .fd = ino_fd, .events = POLLIN };
		for (int i = 0; i < nclients; i++)
			fds[n++] = (struct pollfd){ .fd = clients[i], .events = POLLIN };
		/* a timeout only while a timer runs (Fn held, a tap, a capture) */
		if (poll(fds, n, next_timer(&p, &chord, test_out ? 50 : -1)) < 0) {
			if (errno == EINTR)
				continue;
			rc = 1;
			break;
		}
		timers(&p, &chord, out);
		for (int i = 0; i < live; i++) {
			struct source *src = &p.src[src_idx[i]];

			if ((fds[i].revents & POLLIN) && forward(&p, &chord, src, out) == 0)
				continue;
			if (!(fds[i].revents & (POLLIN | POLLERR | POLLHUP | POLLNVAL)))
				continue;
			if (test_out) {
				/* a test FIFO between two writers: wait for the next one */
				usleep(20000);
				continue;
			}
			logline("source device \"%s\" gone", src->name);
			rc = 1;
			stop = 1;
		}
		/* the phases of lume-sleep */
		if (ino_fd >= 0 && (fds[live + 1].revents & POLLIN))
			sleep_events(&p, &chord, out);
		/* the clients' messages; a client that hung up (lume-run between two games). A
		 * message above may have dropped a client and moved the others: each polled slot
		 * is looked up again by its descriptor */
		for (int at = live + 2; at < n; at++) {
			char buf[128];
			ssize_t got;
			int i;

			if (!(fds[at].revents & (POLLHUP | POLLERR | POLLIN)))
				continue;
			for (i = 0; i < nclients && clients[i] != fds[at].fd; i++)
				;
			if (i == nclients)
				continue;
			got = recv(clients[i], buf, sizeof(buf) - 1, MSG_DONTWAIT);
			if (got < 0 && (errno == EAGAIN || errno == EINTR))
				continue;
			if (got <= 0) {
				drop_client(i);
				continue;
			}
			buf[got] = 0;
			client_message(clients[i], buf, out);
		}
		/* new clients last: the ones polled above keep their slots */
		if (lfd >= 0 && (fds[live].revents & POLLIN))
			accept_client(lfd);
	}
	if (!test_out)
		ioctl(out, UI_DEV_DESTROY);
	close(out);
	if (lfd >= 0) {
		close(lfd);
		unlink(sock_path);
	}
	for (int s = 0; s < p.nsrc; s++)
		if (p.src[s].fd >= 0)
			close(p.src[s].fd);
	return rc;
}
