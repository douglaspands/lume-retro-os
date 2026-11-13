/*
 * r36os-padmerge: join the built-in buttons (gpio-keys) and sticks (adc-joystick) of the
 * R36S into one Linux gamepad, "R36S Gamepad", through uinput (design D8 of
 * r36s-single-card). Both source devices are grabbed, so only the merged one is seen.
 *
 * The merged gamepad uses the same button codes as the GA36 one (kernel driver
 * ga36mb-gamepad), so both consoles get the same RetroArch button indices.
 *
 * usage: r36os-padmerge [--keys NAME] [--sticks NAME] [--timeout SECONDS] [--list]
 */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <linux/uinput.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define GAMEPAD_NAME "R36S Gamepad"
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))

struct keymap {
	unsigned short from;	/* code of the gpio-keys button (board DTS) */
	unsigned short to;	/* code of the merged gamepad */
};

/*
 * The face buttons follow the printed labels as on the GA36: A (right) is BTN_A, B
 * (bottom) is BTN_B. F1-F5 have no fixed meaning in the DTS; their order on the case is
 * confirmed on the device (open question of the design).
 */
static const struct keymap KEYS[] = {
	{ BTN_EAST, BTN_A },  { BTN_SOUTH, BTN_B }, { BTN_NORTH, BTN_X }, { BTN_WEST, BTN_Y },
	{ BTN_TL, BTN_TL },   { BTN_TR, BTN_TR },   { BTN_TL2, BTN_TL2 }, { BTN_TR2, BTN_TR2 },
	{ BTN_DPAD_UP, BTN_DPAD_UP },     { BTN_DPAD_DOWN, BTN_DPAD_DOWN },
	{ BTN_DPAD_LEFT, BTN_DPAD_LEFT }, { BTN_DPAD_RIGHT, BTN_DPAD_RIGHT },
	{ BTN_TRIGGER_HAPPY1, BTN_SELECT }, { BTN_TRIGGER_HAPPY2, BTN_START },
	{ BTN_TRIGGER_HAPPY3, BTN_THUMBL }, { BTN_TRIGGER_HAPPY4, BTN_THUMBR },
	{ BTN_TRIGGER_HAPPY5, BTN_MODE },
};

static const unsigned short AXES[] = { ABS_X, ABS_Y, ABS_RX, ABS_RY };

static volatile sig_atomic_t stop;

static void on_signal(int sig)
{
	(void)sig;
	stop = 1;
}

static int map_key(unsigned short code)
{
	for (size_t i = 0; i < ARRAY_SIZE(KEYS); i++)
		if (KEYS[i].from == code)
			return KEYS[i].to;
	return -1;
}

static int is_axis(unsigned short code)
{
	for (size_t i = 0; i < ARRAY_SIZE(AXES); i++)
		if (AXES[i] == code)
			return 1;
	return 0;
}

/* Open the event device whose name is `name`; -1 if there is none. */
static int open_by_name(const char *name)
{
	DIR *dir = opendir("/dev/input");
	struct dirent *e;
	int found = -1;

	if (!dir)
		return -1;
	while (found < 0 && (e = readdir(dir))) {
		char path[300], dev_name[256] = "";
		int fd;

		if (strncmp(e->d_name, "event", 5))
			continue;
		snprintf(path, sizeof(path), "/dev/input/%s", e->d_name);
		fd = open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
		if (fd < 0)
			continue;
		if (ioctl(fd, EVIOCGNAME(sizeof(dev_name) - 1), dev_name) >= 0 &&
		    !strcmp(dev_name, name))
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
		int fd;

		if (strncmp(e->d_name, "event", 5))
			continue;
		snprintf(path, sizeof(path), "/dev/input/%s", e->d_name);
		fd = open(path, O_RDONLY | O_CLOEXEC);
		if (fd < 0)
			continue;
		ioctl(fd, EVIOCGNAME(sizeof(dev_name) - 1), dev_name);
		printf("%s\t%s\n", path, dev_name);
		close(fd);
	}
	closedir(dir);
}

static int create_gamepad(int sticks)
{
	struct uinput_setup setup;
	int fd = open("/dev/uinput", O_WRONLY | O_NONBLOCK | O_CLOEXEC);

	if (fd < 0) {
		perror("r36os-padmerge: /dev/uinput");
		return -1;
	}
	ioctl(fd, UI_SET_EVBIT, EV_SYN);
	ioctl(fd, UI_SET_EVBIT, EV_KEY);
	for (size_t i = 0; i < ARRAY_SIZE(KEYS); i++)
		ioctl(fd, UI_SET_KEYBIT, KEYS[i].to);
	if (sticks >= 0) {
		ioctl(fd, UI_SET_EVBIT, EV_ABS);
		for (size_t i = 0; i < ARRAY_SIZE(AXES); i++) {
			struct uinput_abs_setup abs = { .code = AXES[i] };

			/* the ranges of the board DTS (adc-joystick abs-range, already inverted) */
			if (ioctl(sticks, EVIOCGABS(AXES[i]), &abs.absinfo) < 0)
				abs.absinfo = (struct input_absinfo){ .minimum = 0, .maximum = 1023 };
			ioctl(fd, UI_ABS_SETUP, &abs);
		}
	}
	memset(&setup, 0, sizeof(setup));
	setup.id.bustype = BUS_VIRTUAL;
	setup.id.vendor = 0x1209;	/* pid.codes */
	setup.id.product = 0x3653;	/* "6S" */
	setup.id.version = 1;
	snprintf(setup.name, sizeof(setup.name), "%s", GAMEPAD_NAME);
	if (ioctl(fd, UI_DEV_SETUP, &setup) < 0 || ioctl(fd, UI_DEV_CREATE) < 0) {
		perror("r36os-padmerge: uinput setup");
		close(fd);
		return -1;
	}
	return fd;
}

static int emit(int out, unsigned short type, unsigned short code, int value)
{
	struct input_event ev = { .type = type, .code = code, .value = value };

	return write(out, &ev, sizeof(ev)) == (ssize_t)sizeof(ev) ? 0 : -1;
}

/* Forward the events of one source; -1 when the device is gone (or a file ended). */
static int forward(int src, int out)
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
			code = map_key(ev[i].code);
			if (code >= 0)
				emit(out, EV_KEY, code, ev[i].value);
			break;
		case EV_ABS:
			if (is_axis(ev[i].code))
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
	fprintf(stderr, "usage: r36os-padmerge [--keys NAME] [--sticks NAME] "
		"[--timeout SECONDS] [--list]\n"
		"       r36os-padmerge --replay KEYS_FILE STICKS_FILE OUT_FILE\n");
}

/*
 * --replay: the same translation, from files of recorded input events to a file, with
 * no input device and no uinput (the host tests use it; it needs no privileges).
 */
static int replay(const char *keys_path, const char *sticks_path, const char *out_path)
{
	const char *paths[2] = { keys_path, sticks_path };
	int out = open(out_path, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);

	if (out < 0) {
		perror(out_path);
		return 1;
	}
	for (int i = 0; i < 2; i++) {
		int src = open(paths[i], O_RDONLY | O_CLOEXEC);

		if (src < 0) {
			perror(paths[i]);
			close(out);
			return 1;
		}
		while (forward(src, out) == 0)
			;
		close(src);
	}
	close(out);
	return 0;
}

int main(int argc, char **argv)
{
	const char *keys_name = "gpio-keys", *sticks_name = "adc-joystick";
	int timeout_s = 10, keys, sticks, out, rc = 0;
	struct sigaction sa = { .sa_handler = on_signal };

	for (int i = 1; i < argc; i++) {
		if (!strcmp(argv[i], "--list")) {
			list_devices();
			return 0;
		} else if (!strcmp(argv[i], "--replay") && i + 3 < argc) {
			return replay(argv[i + 1], argv[i + 2], argv[i + 3]);
		} else if (i + 1 < argc && !strcmp(argv[i], "--keys")) {
			keys_name = argv[++i];
		} else if (i + 1 < argc && !strcmp(argv[i], "--sticks")) {
			sticks_name = argv[++i];
		} else if (i + 1 < argc && !strcmp(argv[i], "--timeout")) {
			timeout_s = atoi(argv[++i]);
		} else {
			usage();
			return 2;
		}
	}
	sigaction(SIGTERM, &sa, NULL);
	sigaction(SIGINT, &sa, NULL);

	keys = wait_for(keys_name, timeout_s);
	if (keys < 0) {
		fprintf(stderr, "r36os-padmerge: no input device named \"%s\"\n", keys_name);
		return 1;
	}
	/* the sticks are optional: without them the buttons still work */
	sticks = wait_for(sticks_name, 1);
	if (sticks < 0)
		fprintf(stderr, "r36os-padmerge: no input device named \"%s\"; buttons only\n",
			sticks_name);
	out = create_gamepad(sticks);
	if (out < 0)
		return 1;
	ioctl(keys, EVIOCGRAB, 1);
	if (sticks >= 0)
		ioctl(sticks, EVIOCGRAB, 1);
	fprintf(stderr, "r36os-padmerge: \"%s\" + \"%s\" -> \"%s\"\n", keys_name,
		sticks >= 0 ? sticks_name : "(none)", GAMEPAD_NAME);

	while (!stop) {
		struct pollfd fds[2] = { { .fd = keys, .events = POLLIN },
					 { .fd = sticks, .events = POLLIN } };
		int nfds = sticks >= 0 ? 2 : 1;

		if (poll(fds, nfds, -1) < 0) {
			if (errno == EINTR)
				continue;
			rc = 1;
			break;
		}
		for (int i = 0; i < nfds; i++) {
			if (fds[i].revents & (POLLERR | POLLHUP | POLLNVAL)) {
				fprintf(stderr, "r36os-padmerge: source device gone\n");
				rc = 1;
				stop = 1;
			} else if ((fds[i].revents & POLLIN) && forward(fds[i].fd, out) < 0) {
				rc = 1;
				stop = 1;
			}
		}
	}
	ioctl(out, UI_DEV_DESTROY);
	close(out);
	close(keys);
	if (sticks >= 0)
		close(sticks);
	return rc;
}
