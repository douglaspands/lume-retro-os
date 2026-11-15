/*
 * r36os-input: the input daemon of Lume Retro OS (lume-launcher D8; it grew out of
 * r36os-padmerge, r36s-single-card D8).
 *
 * One process per console, as root, before the frontend:
 *  - reads the board profile (/usr/share/r36os/input/<board>.conf): the source devices by
 *    name, the code map and the mixer control;
 *  - grabs every source device (EVIOCGRAB), so programs only see the virtual one;
 *  - publishes through uinput the virtual gamepad with the same name as before ("GA36-MB
 *    Gamepad", "R36S Gamepad"), so the RetroArch autoconfig does not change;
 *  - Fn chord: Fn alone gives a Fn press and release when it is let go (the RetroArch menu);
 *    Fn+Start sends "quit" to the clients of /run/r36os/input.sock and neither key goes
 *    out; Fn with any other key gives both keys;
 *  - volume keys change the ALSA mixer in fixed steps and are not forwarded; "volume" then
 *    goes to the clients of the socket (the launcher shows the level);
 *  - Fn+volume keys change the screen backlight in steps of 5% instead (never below 5%), and
 *    "brightness" goes to the clients; Fn then gives no tap on release;
 *  - after either, "LUME_LEVEL" asks RetroArch (127.0.0.1:55355, patch 0011) to draw the
 *    launcher's level line over a running game.
 *
 * usage: r36os-input --profile FILE [--socket PATH] [--timeout SECONDS]
 *        r36os-input --profile FILE --test OUT --source NAME=PATH... [--socket PATH]
 *        r36os-input --list
 *
 * --test runs the same loop with files or FIFOs as sources and a file as the output, with no
 * input device and no uinput (the host tests use it). R36OS_INPUT_AMIXER replaces amixer and
 * R36OS_INPUT_BACKLIGHT replaces /sys/class/backlight.
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
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <unistd.h>

#define PROG "r36os-input"
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define MAX_SOURCES 4
#define MAX_KEYS 64
#define MAX_AXES 8
#define MAX_CLIENTS 8
#define DEFAULT_SOCKET "/run/r36os/input.sock"

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
	{ "KEY_F1", KEY_F1 },         { "KEY_ENTER", KEY_ENTER },
	{ "KEY_VOLUMEUP", KEY_VOLUMEUP }, { "KEY_VOLUMEDOWN", KEY_VOLUMEDOWN },
	{ "ABS_X", ABS_X },           { "ABS_Y", ABS_Y },           { "ABS_RX", ABS_RX },
	{ "ABS_RY", ABS_RY },         { "ABS_Z", ABS_Z },           { "ABS_RZ", ABS_RZ },
};

struct source {
	char name[128];
	int optional;
	int fd;
};

struct keymap {
	unsigned short from, to;
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
	int fn, quit;	/* output codes, -1 if none */
	char mixer_card[64], mixer_ctl[64];
	int mixer_step;
	int mixer_max;	/* raw ceiling of the control (0: none), e.g. 0 dB of a digital DAC */
	int backlight_max;	/* raw ceiling of the backlight (0: none): 100% of the launcher */
};

static volatile sig_atomic_t stop;
static int clients[MAX_CLIENTS];
static int nclients;

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
	p->fn = p->quit = -1;
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
			p->quit = a;
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
	return 0;
bad:
	fprintf(stderr, PROG ": %s:%d: bad line\n", path, n);
	fclose(f);
	return -1;
}

static int map_key(const struct profile *p, unsigned short code)
{
	if (code == KEY_VOLUMEUP || code == KEY_VOLUMEDOWN)
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
			if (c != KEY_VOLUMEUP && c != KEY_VOLUMEDOWN)
				ioctl(fd, UI_SET_KEYBIT, c);
	for (int i = 0; i < p->nkeys; i++)
		ioctl(fd, UI_SET_KEYBIT, p->keys[i].to);
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

static void emit(int out, unsigned short type, unsigned short code, int value)
{
	struct input_event ev = { .type = type, .code = code, .value = value };

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

static void drop_client(int i)
{
	close(clients[i]);
	clients[i] = clients[--nclients];
}

/* A message to every client: "quit" for Fn+Start (with no client the combo does nothing),
 * "volume" after a volume key. Clients ignore what they do not know. A client that cannot
 * take it is dropped (only in the main process: a child just skips it). */
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
 * reads it. R36OS_INPUT_RA_PORT and R36OS_INPUT_LEVEL_COLORS change for the tests. */
static void ra_level(int left, long pct)
{
	const char *port = getenv("R36OS_INPUT_RA_PORT");
	const char *colors = getenv("R36OS_INPUT_LEVEL_COLORS");
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
	const char *amixer = getenv("R36OS_INPUT_AMIXER");
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

/* One brightness step of 5% on the first backlight (the launcher's Settings use the same
 * steps and floor: never fully dark, the screen would look off). With a ceiling in the
 * profile (backlight_max) that level is 100% and nothing goes above it (GA36: above level 8
 * the panel flickers and shows broken parts, seen 2026-11-15). Then "brightness" goes to the
 * clients, also at a limit. A sysfs write is quick: done in the main process. */
static void brightness(const struct profile *p, int up)
{
	const char *root = getenv("R36OS_INPUT_BACKLIGHT");
	char dir[400], value[24];
	struct dirent *e;
	long max, cur, pct, v, floor_v;
	DIR *d;
	int fd;

	if (!root)
		root = "/sys/class/backlight";
	d = opendir(root);
	if (!d)
		return;
	dir[0] = 0;
	while ((e = readdir(d))) {
		if (e->d_name[0] != '.') {
			snprintf(dir, sizeof(dir), "%s/%s", root, e->d_name);
			break;
		}
	}
	closedir(d);
	if (!dir[0])
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
	if (v != cur) {
		char path[420];

		snprintf(path, sizeof(path), "%s/brightness", dir);
		fd = open(path, O_WRONLY | O_TRUNC | O_CLOEXEC);
		if (fd >= 0) {
			int len = snprintf(value, sizeof(value), "%ld", v);

			if (write(fd, value, (size_t)len) != len)
				logline("backlight not written: %s", strerror(errno));
			close(fd);
		}
	}
	ra_level(1, (v * 100 + max / 2) / max);
	send_all("brightness", 1);
}

/* ---- the Fn chord ---- */

struct chord {
	int fn_down;		/* Fn held, not forwarded yet */
	int fn_forwarded;	/* Fn went out (another key came with it) */
	int fn_used;		/* something happened while Fn was held */
	unsigned char swallow[KEY_MAX + 1];	/* releases to drop */
};

static void key_event(const struct profile *p, struct chord *c, int out, int code, int value)
{
	if (code == KEY_VOLUMEUP || code == KEY_VOLUMEDOWN) {
		if (value != 1)
			return;
		if (c->fn_down) {
			/* Fn+volume: the backlight; Fn was used, so no tap on its release */
			c->fn_used = 1;
			brightness(p, code == KEY_VOLUMEUP);
		} else {
			volume(p, code == KEY_VOLUMEUP);
		}
		return;
	}
	if (p->fn >= 0 && code == p->fn) {
		if (value == 1) {
			c->fn_down = 1;
			c->fn_forwarded = c->fn_used = 0;
		} else if (value == 0) {
			if (c->fn_forwarded)
				emit_key(out, code, 0);
			else if (!c->fn_used) {
				/* Fn alone: a tap on release (the RetroArch menu) */
				emit_key(out, code, 1);
				emit_key(out, code, 0);
			}
			c->fn_down = c->fn_forwarded = c->fn_used = 0;
		}
		return;	/* repeats of Fn are dropped */
	}
	if (value == 0 && c->swallow[code]) {
		c->swallow[code] = 0;
		return;
	}
	if (c->fn_down && value == 1) {
		c->fn_used = 1;
		if (code == p->quit && !c->fn_forwarded) {
			send_all("quit", 1);
			c->swallow[code] = 1;
			return;
		}
		if (!c->fn_forwarded) {
			emit_key(out, p->fn, 1);
			c->fn_forwarded = 1;
		}
	}
	if (value == 2 && c->swallow[code])
		return;
	emit(out, EV_KEY, code, value);
}

/* Forward the events of one source; -1 when the device is gone (or a file ended). */
static int forward(const struct profile *p, struct chord *c, int src, int out)
{
	struct input_event ev[64];
	ssize_t n = read(src, ev, sizeof(ev));

	if (n < 0)
		return errno == EAGAIN || errno == EINTR ? 0 : -1;
	if (n == 0)
		return -1;
	for (size_t i = 0; i < (size_t)n / sizeof(ev[0]); i++) {
		int code;

		switch (ev[i].type) {
		case EV_KEY:
			code = map_key(p, ev[i].code);
			if (code >= 0)
				key_event(p, c, out, code, ev[i].value);
			break;
		case EV_ABS:
			if (is_axis(p, ev[i].code))
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
		logline("no socket at %s: Fn+Start does nothing", sock_path);
	{
		int found = 0;

		for (int s = 0; s < p.nsrc; s++)
			found += p.src[s].fd >= 0;
		logline("\"%s\" from %d of %d source(s), socket %s, volume %s", p.name, found, p.nsrc,
			sock_path, p.mixer_step ? p.mixer_ctl : "off");
	}

	while (!stop) {
		struct pollfd fds[MAX_SOURCES + 1 + MAX_CLIENTS];
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
		for (int i = 0; i < nclients; i++)
			fds[n++] = (struct pollfd){ .fd = clients[i], .events = POLLIN };
		if (poll(fds, n, test_out ? 50 : -1) < 0) {
			if (errno == EINTR)
				continue;
			rc = 1;
			break;
		}
		for (int i = 0; i < live; i++) {
			struct source *src = &p.src[src_idx[i]];

			if ((fds[i].revents & POLLIN) && forward(&p, &chord, src->fd, out) == 0)
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
		if (lfd >= 0 && (fds[live].revents & POLLIN))
			accept_client(lfd);
		/* a client that hung up (lume-run between two games) */
		for (int i = nclients - 1; i >= 0; i--) {
			int at = live + 1 + i;

			if (at < n && (fds[at].revents & (POLLHUP | POLLERR | POLLIN))) {
				char buf[16];

				if (recv(clients[i], buf, sizeof(buf), MSG_DONTWAIT) <= 0)
					drop_client(i);
			}
		}
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
