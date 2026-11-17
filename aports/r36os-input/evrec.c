/*
 * r36os-evrec: record and replay the virtual gamepad of the console (change virtual-gamepad,
 * D2). The virtual pad is the one r36os-input publishes through uinput ("GA36-MB Gamepad" or
 * "R36S Gamepad" on BUS_VIRTUAL), the same events the launcher and the games read.
 *
 *   r36os-evrec record <out>                       read the virtual pad (no EVIOCGRAB) until
 *                                                  SIGTERM/SIGINT and write a recording
 *   r36os-evrec play <file> [--pad virtual|kernel] replay a recording on the pad node
 *
 * Recording format (version 1, src/r36os/evrec.py, docs/BUILD.md):
 *
 *   # r36os-evrec 1 <ga36|r36s>
 *   <ms> <type> <code> <value>
 *   # end <ms>
 *
 * record writes every event it reads, SYN_REPORT included (one closes each group), except
 * SYN_DROPPED; each line is flushed. Times are the event timestamps (CLOCK_MONOTONIC through
 * EVIOCSCLOCKID) relative to the start, never decreasing.
 *
 * play refuses a recording of another console and a node it cannot write (only root writes
 * the event nodes), both before sending anything. It writes each group of events with the
 * same ms in one write at the absolute time start + ms (clock_nanosleep TIMER_ABSTIME on
 * CLOCK_MONOTONIC), with one SYN_REPORT after it (recorded SYN_DROPPED or empty reports are
 * not sent), waits until the end marker, then releases every key still pressed (EV_KEY value
 * 0 and SYN_REPORT). It also releases on SIGTERM, SIGINT, SIGHUP and on a write error. Last
 * line on stdout: `delay max=<ms> mean=<ms> events=<n>`, the lateness of each written event
 * (SYN not counted) against its recorded time. The timestamp written in each input_event is
 * the time since the start (the kernel replaces it on a real node; the tests read it).
 *
 * Exit status: 0 done, 1 error, 2 usage, 3 refused (another console, no permission),
 * 128+signal when play was interrupted (keys released). record ends with 0 on a signal.
 *
 * For the host tests: R36OS_EVREC_DEVICES replaces /proc/bus/input/devices,
 * R36OS_EVREC_INPUT_DIR replaces /dev/input, and R36OS_EVREC_CLOCK=fake[:<lag_us>] uses a
 * clock that starts at 0 and jumps to each wake-up time plus <lag_us> instead of sleeping
 * (in record, the event timestamps are then taken as relative to 0). On a regular file,
 * record follows the end of the file like `tail -f`.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/input.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define EXIT_ERROR 1
#define EXIT_USAGE 2
#define EXIT_REFUSED 3
#define NS_PER_MS 1000000LL
#define NS_PER_S 1000000000LL
#define SLICE_NS (100 * NS_PER_MS) /* longest sleep between two looks at the stop flag */
#define MAX_DEVICES 128

static const struct {
	const char *console, *virtual_name, *kernel_name;
} BOARDS[] = {
	{ "ga36", "GA36-MB Gamepad", "GA36-MB Gamepad" },
	{ "r36s", "R36S Gamepad", "gpio-keys" },
};

static volatile sig_atomic_t stop_signal;

static void on_signal(int sig)
{
	stop_signal = sig;
}

/* `hup`: also stop on SIGHUP (play: the ssh session of `r36os dev play` dropped). record
 * leaves SIGHUP as inherited: `r36os dev record` starts it under nohup, detached. */
static void install_signals(int hup)
{
	struct sigaction sa = { .sa_handler = on_signal }; /* no SA_RESTART: sleeps wake up */
	struct sigaction ign = { .sa_handler = SIG_IGN };

	sigemptyset(&sa.sa_mask);
	sigaction(SIGTERM, &sa, NULL);
	sigaction(SIGINT, &sa, NULL);
	if (hup)
		sigaction(SIGHUP, &sa, NULL);
	sigaction(SIGPIPE, &ign, NULL); /* a write error is handled, not fatal */
}

/* ---- clock ---- */

static int fake_clock;
static int64_t fake_ns, fake_lag_ns;

static void clock_setup(void)
{
	const char *c = getenv("R36OS_EVREC_CLOCK");

	if (!c || !*c)
		return;
	if (strncmp(c, "fake", 4) != 0 || (c[4] && c[4] != ':')) {
		fprintf(stderr, "evrec: bad R36OS_EVREC_CLOCK `%s` (want fake[:<lag_us>])\n", c);
		exit(EXIT_USAGE);
	}
	fake_clock = 1;
	if (c[4] == ':')
		fake_lag_ns = strtoll(c + 5, NULL, 10) * 1000;
}

static int64_t now_ns(void)
{
	struct timespec ts;

	if (fake_clock)
		return fake_ns;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (int64_t)ts.tv_sec * NS_PER_S + ts.tv_nsec;
}

/* Sleep until the absolute time t. Slices of at most SLICE_NS bound the wait for a signal
 * that lands between the flag check and the sleep; the last slice ends exactly at t.
 * Returns 0 at t, -1 when a stop signal arrived first. */
static int sleep_until(int64_t t)
{
	if (fake_clock) {
		if (stop_signal)
			return -1;
		if (fake_ns < t)
			fake_ns = t;
		fake_ns += fake_lag_ns;
		return 0;
	}
	for (;;) {
		int64_t n, wake;
		struct timespec ts;

		if (stop_signal)
			return -1;
		n = now_ns();
		if (n >= t)
			return 0;
		wake = t - n > SLICE_NS ? n + SLICE_NS : t;
		ts.tv_sec = wake / NS_PER_S;
		ts.tv_nsec = wake % NS_PER_S;
		clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &ts, NULL);
	}
}

/* ---- the pads in /proc/bus/input/devices ---- */

struct device {
	char name[128];
	int bus;
	int event;
};

static int read_devices(struct device *dev, int max)
{
	const char *path = getenv("R36OS_EVREC_DEVICES");
	char line[1024];
	int n = 0, open_block = 0;
	FILE *f;

	if (!path || !*path)
		path = "/proc/bus/input/devices";
	f = fopen(path, "re");
	if (!f) {
		fprintf(stderr, "evrec: cannot read %s: %s\n", path, strerror(errno));
		return -1;
	}
	while (fgets(line, sizeof(line), f)) {
		if (line[0] == '\n' || line[0] == '\r') {
			if (open_block && n < max)
				n++;
			open_block = 0;
			continue;
		}
		if (!open_block) {
			if (n >= max)
				continue;
			memset(&dev[n], 0, sizeof(dev[n]));
			dev[n].bus = -1;
			dev[n].event = -1;
			open_block = 1;
		}
		if (strncmp(line, "I: Bus=", 7) == 0) {
			dev[n].bus = (int)strtol(line + 7, NULL, 16);
		} else if (strncmp(line, "N: Name=\"", 9) == 0) {
			char *end = strrchr(line + 9, '"');
			size_t len = end ? (size_t)(end - (line + 9)) : 0;

			if (len >= sizeof(dev[n].name))
				len = sizeof(dev[n].name) - 1;
			memcpy(dev[n].name, line + 9, len);
			dev[n].name[len] = 0;
		} else if (strncmp(line, "H: Handlers=", 12) == 0) {
			char *tok = strtok(line + 12, " \t\n");

			for (; tok; tok = strtok(NULL, " \t\n")) {
				char *end;
				long e;

				if (strncmp(tok, "event", 5) != 0 || !tok[5])
					continue;
				e = strtol(tok + 5, &end, 10);
				if (!*end && e >= 0 && e < INT_MAX)
					dev[n].event = (int)e;
			}
		}
	}
	if (open_block && n < max)
		n++;
	fclose(f);
	return n;
}

/* The console (index in BOARDS) and the event number of the virtual pad, or with `kernel`
 * of the kernel pad (same rule as find_pads in src/r36os/dev.py). */
static int find_pad(int kernel, int *board, int *event)
{
	struct device dev[MAX_DEVICES];
	int n = read_devices(dev, MAX_DEVICES);

	if (n < 0)
		return -1;
	for (int i = 0; i < n; i++) {
		for (int b = 0; b < (int)(sizeof(BOARDS) / sizeof(BOARDS[0])); b++) {
			if (strcmp(dev[i].name, BOARDS[b].virtual_name) != 0 ||
			    dev[i].bus != BUS_VIRTUAL || dev[i].event < 0)
				continue;
			*board = b;
			if (!kernel) {
				*event = dev[i].event;
				return 0;
			}
			for (int k = 0; k < n; k++) {
				if (strcmp(dev[k].name, BOARDS[b].kernel_name) == 0 &&
				    dev[k].bus != BUS_VIRTUAL && dev[k].event >= 0) {
					*event = dev[k].event;
					return 0;
				}
			}
			fprintf(stderr, "evrec: no kernel pad `%s` on the console\n",
				BOARDS[b].kernel_name);
			return -1;
		}
	}
	fprintf(stderr, "evrec: no virtual gamepad on the console (is r36os-input running?)\n");
	return -1;
}

static void node_path(char *buf, size_t len, int event)
{
	const char *dir = getenv("R36OS_EVREC_INPUT_DIR");

	if (!dir || !*dir)
		dir = "/dev/input";
	snprintf(buf, len, "%s/event%d", dir, event);
}

/* ---- the recording file ---- */

struct rec_event {
	int64_t ms;
	uint16_t type, code;
	int32_t value;
};

struct recording {
	int board;
	struct rec_event *ev;
	size_t n;
	int64_t end_ms;
};

/* A decimal integer like the Python reader: an optional '-' and digits, nothing else. */
static int parse_int(const char *s, int64_t lo, int64_t hi, int64_t *out)
{
	const char *p = s;
	char *end;
	long long v;

	if (*p == '-')
		p++;
	if (!*p || strspn(p, "0123456789") != strlen(p) || strlen(p) > 18)
		return -1;
	errno = 0;
	v = strtoll(s, &end, 10);
	if (errno || *end || v < lo || v > hi)
		return -1;
	*out = v;
	return 0;
}

static int load_error(const char *path, size_t lineno, const char *msg)
{
	fprintf(stderr, "evrec: %s: line %zu: %s\n", path, lineno, msg);
	return -1;
}

static int load_recording(const char *path, struct recording *r)
{
	FILE *f = fopen(path, "re");
	char *text = NULL, *line, *next;
	size_t size = 0, cap = 0, lineno = 1, got;
	int64_t last = 0;
	int ended = 0;

	if (!f) {
		fprintf(stderr, "evrec: cannot read %s: %s\n", path, strerror(errno));
		return -1;
	}
	for (;;) {
		if (size + 4096 + 1 > cap) {
			cap = cap ? cap * 2 : 65536;
			text = realloc(text, cap);
			if (!text) {
				fclose(f);
				return load_error(path, 0, "out of memory");
			}
		}
		got = fread(text + size, 1, cap - size - 1, f);
		size += got;
		if (got == 0)
			break;
	}
	fclose(f);
	text[size] = 0;
	if (strlen(text) != size)
		return load_error(path, 1, "not a text file");
	if (size && text[size - 1] == '\n')
		text[--size] = 0; /* one final newline is optional */
	if (!size)
		return load_error(path, 1, "empty recording");

	memset(r, 0, sizeof(*r));
	r->board = -1;
	for (line = text; line; line = next, lineno++) {
		next = strchr(line, '\n');
		if (next)
			*next++ = 0;
		if (lineno == 1) {
			for (int b = 0; b < (int)(sizeof(BOARDS) / sizeof(BOARDS[0])); b++) {
				char want[64];

				snprintf(want, sizeof(want), "# r36os-evrec 1 %s", BOARDS[b].console);
				if (strcmp(line, want) == 0)
					r->board = b;
			}
			if (r->board < 0)
				return load_error(path, 1, "bad header (want `# r36os-evrec 1 <ga36|r36s>`)");
			continue;
		}
		if (ended)
			return load_error(path, lineno, "data after the end marker");
		if (strncmp(line, "# end ", 6) == 0) {
			if (parse_int(line + 6, 0, INT64_MAX / NS_PER_MS, &r->end_ms) || r->end_ms < last)
				return load_error(path, lineno, "bad end time or end before the last event");
			ended = 1;
			continue;
		}
		{
			char *field[4], *p = line;
			int64_t v[4];
			int nf = 0;

			while (nf < 4) {
				field[nf++] = p;
				p = strchr(p, ' ');
				if (!p)
					break;
				*p++ = 0;
			}
			if (nf != 4 || p)
				return load_error(path, lineno, "want `<ms> <type> <code> <value>`");
			if (parse_int(field[0], 0, INT64_MAX / NS_PER_MS, &v[0]) ||
			    parse_int(field[1], 0, 0xffff, &v[1]) ||
			    parse_int(field[2], 0, 0xffff, &v[2]) ||
			    parse_int(field[3], INT32_MIN, INT32_MAX, &v[3]))
				return load_error(path, lineno, "bad number (or negative time, type or code)");
			if (v[0] < last)
				return load_error(path, lineno, "time goes backwards");
			last = v[0];
			if (r->n % 1024 == 0) {
				struct rec_event *ev = realloc(r->ev, (r->n + 1024) * sizeof(*ev));

				if (!ev)
					return load_error(path, lineno, "out of memory");
				r->ev = ev;
			}
			r->ev[r->n++] = (struct rec_event){ v[0], (uint16_t)v[1], (uint16_t)v[2],
							     (int32_t)v[3] };
		}
	}
	free(text);
	if (!ended)
		return load_error(path, lineno, "missing end marker (`# end <ms>`)");
	return 0;
}

/* ---- play ---- */

static unsigned char pressed[KEY_CNT];
static int play_fd = -1;

static void set_time(struct input_event *e, int64_t t)
{
	if (t < 0)
		t = 0;
	e->input_event_sec = t / NS_PER_S;
	e->input_event_usec = (t % NS_PER_S) / 1000;
}

static int write_all(int fd, const void *buf, size_t len)
{
	const char *p = buf;

	while (len) {
		ssize_t w = write(fd, p, len);

		if (w < 0 && errno == EINTR)
			continue;
		if (w <= 0)
			return -1;
		p += w;
		len -= (size_t)w;
	}
	return 0;
}

/* Release every key still pressed, then one SYN_REPORT; errors are only reported. */
static void release_all(int64_t start)
{
	struct input_event e[64];
	int n = 0, released = 0;

	for (int code = 0; code < KEY_CNT; code++) {
		if (!pressed[code])
			continue;
		memset(&e[n], 0, sizeof(e[n]));
		set_time(&e[n], now_ns() - start);
		e[n].type = EV_KEY;
		e[n].code = (uint16_t)code;
		e[n].value = 0;
		pressed[code] = 0;
		released++;
		if (++n == 63 || code == KEY_CNT - 1) {
			if (write_all(play_fd, e, (size_t)n * sizeof(e[0])))
				fprintf(stderr, "evrec: release failed: %s\n", strerror(errno));
			n = 0;
		}
	}
	if (n && write_all(play_fd, e, (size_t)n * sizeof(e[0])))
		fprintf(stderr, "evrec: release failed: %s\n", strerror(errno));
	if (released) {
		memset(&e[0], 0, sizeof(e[0]));
		set_time(&e[0], now_ns() - start);
		e[0].type = EV_SYN;
		e[0].code = SYN_REPORT;
		if (write_all(play_fd, e, sizeof(e[0])))
			fprintf(stderr, "evrec: release failed: %s\n", strerror(errno));
		fprintf(stderr, "evrec: released %d key(s)\n", released);
	}
}

static int cmd_play(int argc, char **argv)
{
	const char *file = NULL, *pad = "virtual";
	struct recording rec;
	struct input_event *buf;
	char node[PATH_MAX];
	int board, event, kernel, status = 0, need_syn = 0;
	int64_t start, max_delay = 0, sum_delay = 0;
	size_t count = 0, i = 0;

	for (int a = 0; a < argc; a++) {
		if (strcmp(argv[a], "--pad") == 0 && a + 1 < argc)
			pad = argv[++a];
		else if (!file && argv[a][0] != '-')
			file = argv[a];
		else
			file = NULL, a = argc;
	}
	if (!file || (strcmp(pad, "virtual") != 0 && strcmp(pad, "kernel") != 0)) {
		fprintf(stderr, "usage: r36os-evrec play <file> [--pad virtual|kernel]\n");
		return EXIT_USAGE;
	}
	kernel = strcmp(pad, "kernel") == 0;
	if (load_recording(file, &rec))
		return EXIT_ERROR;
	if (find_pad(kernel, &board, &event))
		return EXIT_ERROR;
	if (rec.board != board) {
		fprintf(stderr, "evrec: recording is for %s, not %s\n", BOARDS[rec.board].console,
			BOARDS[board].console);
		return EXIT_REFUSED;
	}
	if (kernel && strcmp(BOARDS[board].kernel_name, BOARDS[board].virtual_name) != 0) {
		/* R36S gpio-keys use other codes than the virtual pad (dev.py R36S_KERNEL_CODES) */
		fprintf(stderr, "evrec: the %s kernel pad uses other codes; play on the virtual pad\n",
			BOARDS[board].console);
		return EXIT_REFUSED;
	}
	node_path(node, sizeof(node), event);
	play_fd = open(node, O_WRONLY | O_CLOEXEC);
	if (play_fd < 0) {
		int e = errno;

		fprintf(stderr, "evrec: cannot write %s: %s%s\n", node, strerror(e),
			e == EACCES || e == EPERM ? " (play needs root)" : "");
		return e == EACCES || e == EPERM ? EXIT_REFUSED : EXIT_ERROR;
	}
	buf = calloc(rec.n + 1, sizeof(*buf));
	if (!buf) {
		fprintf(stderr, "evrec: out of memory\n");
		return EXIT_ERROR;
	}
	install_signals(1);

	start = now_ns();
	while (i < rec.n) {
		int64_t ms = rec.ev[i].ms, target = start + ms * NS_PER_MS, t, delay;
		size_t n = 0, keys = 0;

		if (sleep_until(target))
			break;
		t = now_ns() - start;
		for (; i < rec.n && rec.ev[i].ms == ms; i++) {
			const struct rec_event *r = &rec.ev[i];

			if (r->type == EV_SYN) {
				/* only a SYN_REPORT that closes events written since the last one */
				if (r->code != SYN_REPORT || !need_syn)
					continue;
				need_syn = 0;
			} else {
				need_syn = 1;
				keys++;
			}
			memset(&buf[n], 0, sizeof(buf[n]));
			set_time(&buf[n], t);
			buf[n].type = r->type;
			buf[n].code = r->code;
			buf[n].value = r->value;
			n++;
		}
		if (need_syn) {
			memset(&buf[n], 0, sizeof(buf[n]));
			set_time(&buf[n], t);
			buf[n].type = EV_SYN;
			buf[n].code = SYN_REPORT;
			n++;
			need_syn = 0;
		}
		if (!n)
			continue;
		if (write_all(play_fd, buf, n * sizeof(*buf))) {
			fprintf(stderr, "evrec: write to %s failed: %s\n", node, strerror(errno));
			status = EXIT_ERROR;
			/* the write may have been partial: release whatever this group pressed */
			for (size_t k = 0; k < n; k++)
				if (buf[k].type == EV_KEY && buf[k].code < KEY_CNT)
					pressed[buf[k].code] = 1;
			break;
		}
		delay = now_ns() - target;
		for (size_t k = 0; k < n; k++)
			if (buf[k].type == EV_KEY && buf[k].code < KEY_CNT)
				pressed[buf[k].code] = buf[k].value != 0;
		if (delay < 0)
			delay = 0;
		if (delay > max_delay)
			max_delay = delay;
		sum_delay += delay * (int64_t)keys;
		count += keys;
	}
	if (!status && !stop_signal)
		sleep_until(start + rec.end_ms * NS_PER_MS);
	release_all(start);
	printf("delay max=%.3f mean=%.3f events=%zu\n", (double)max_delay / NS_PER_MS,
	       count ? (double)sum_delay / (double)count / NS_PER_MS : 0.0, count);
	fflush(stdout);
	close(play_fd);
	free(buf);
	free(rec.ev);
	if (status)
		return status;
	if (stop_signal) {
		fprintf(stderr, "evrec: interrupted by signal %d\n", (int)stop_signal);
		return 128 + stop_signal;
	}
	return 0;
}

/* ---- record ---- */

static int cmd_record(int argc, char **argv)
{
	char node[PATH_MAX], bytes[64 * sizeof(struct input_event)];
	size_t have = 0, count = 0;
	int board, event, fd, use_evtime, status = 0, clk = CLOCK_MONOTONIC;
	int64_t start, last = 0, end;
	FILE *out;

	if (argc != 1) {
		fprintf(stderr, "usage: r36os-evrec record <out>\n");
		return EXIT_USAGE;
	}
	if (find_pad(0, &board, &event))
		return EXIT_ERROR;
	node_path(node, sizeof(node), event);
	/* read only and no EVIOCGRAB: the launcher and the game keep getting every event */
	fd = open(node, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
	if (fd < 0) {
		fprintf(stderr, "evrec: cannot read %s: %s\n", node, strerror(errno));
		return errno == EACCES || errno == EPERM ? EXIT_REFUSED : EXIT_ERROR;
	}
	use_evtime = fake_clock || ioctl(fd, EVIOCSCLOCKID, &clk) == 0;
	out = fopen(argv[0], "we");
	if (!out) {
		fprintf(stderr, "evrec: cannot write %s: %s\n", argv[0], strerror(errno));
		return EXIT_ERROR;
	}
	install_signals(0);
	start = now_ns();
	if (fprintf(out, "# r36os-evrec 1 %s\n", BOARDS[board].console) < 0 || fflush(out)) {
		fprintf(stderr, "evrec: write to %s failed: %s\n", argv[0], strerror(errno));
		return EXIT_ERROR;
	}

	while (!stop_signal && !status) {
		struct pollfd p = { .fd = fd, .events = POLLIN };
		ssize_t got;
		size_t k;

		if (poll(&p, 1, (int)(SLICE_NS / NS_PER_MS)) <= 0)
			continue;
		got = read(fd, bytes + have, sizeof(bytes) - have);
		if (got < 0) {
			if (errno == EINTR || errno == EAGAIN)
				continue;
			fprintf(stderr, "evrec: read from %s failed: %s\n", node, strerror(errno));
			status = EXIT_ERROR;
			break;
		}
		if (got == 0) {
			/* end of a regular file (host tests): follow it */
			struct timespec ts = { 0, 20 * NS_PER_MS };

			nanosleep(&ts, NULL);
			continue;
		}
		have += (size_t)got;
		for (k = 0; k + sizeof(struct input_event) <= have; k += sizeof(struct input_event)) {
			struct input_event e;
			int64_t t, ms;

			memcpy(&e, bytes + k, sizeof(e));
			if (e.type == EV_SYN && e.code == SYN_DROPPED) {
				fprintf(stderr, "evrec: events dropped by the kernel buffer\n");
				continue;
			}
			t = use_evtime ? (int64_t)e.input_event_sec * NS_PER_S +
						 (int64_t)e.input_event_usec * 1000 - start
				       : now_ns() - start;
			ms = t < 0 ? 0 : t / NS_PER_MS;
			if (ms < last)
				ms = last;
			last = ms;
			if (fprintf(out, "%lld %u %u %d\n", (long long)ms, e.type, e.code, e.value) < 0 ||
			    fflush(out)) {
				fprintf(stderr, "evrec: write to %s failed: %s\n", argv[0], strerror(errno));
				status = EXIT_ERROR;
				break;
			}
			if (e.type != EV_SYN)
				count++;
		}
		memmove(bytes, bytes + k, have - k);
		have -= k;
	}
	/* close the recording even after an error, so what was read stays readable */
	end = (now_ns() - start) / NS_PER_MS;
	if (end < last)
		end = last;
	if (fprintf(out, "# end %lld\n", (long long)end) < 0 || fclose(out)) {
		fprintf(stderr, "evrec: write to %s failed: %s\n", argv[0], strerror(errno));
		status = EXIT_ERROR;
	}
	close(fd);
	printf("recorded events=%zu ms=%lld\n", count, (long long)end);
	return status;
}

int main(int argc, char **argv)
{
	clock_setup();
	if (argc >= 2 && strcmp(argv[1], "record") == 0)
		return cmd_record(argc - 2, argv + 2);
	if (argc >= 2 && strcmp(argv[1], "play") == 0)
		return cmd_play(argc - 2, argv + 2);
	fprintf(stderr, "usage: r36os-evrec record <out>\n"
			"       r36os-evrec play <file> [--pad virtual|kernel]\n");
	return EXIT_USAGE;
}
