/*
 * lume-logd: the sampling loop of lume-logd in C (openspec game-governor 1.2, D8, P-60).
 *
 *   lume-logd run    every `interval` s (ROMS/system/etc/logs.conf): one metrics line, the
 *                    frontend trace line, the usb trace line and the events of the sample;
 *                    the kernel messages are traced as they arrive, during the wait; every
 *                    `flush` s the batch goes to the card through `logd flush`.
 *
 * It replaces the shell loop of /usr/libexec/lume/logd (`logd run` execs it after the
 * hardware snapshot) and writes exactly the same files and lines (docs/LOGS.md), so the
 * card format, `lume power report` and the tests do not change. The rare and heavy work
 * stays in the shell, run as a child only when it happens: the batch flush
 * (`logd flush`), the detailed snapshot of a frozen RetroArch (`logd snapshot <pid> <state>`)
 * and the re-enabling of a masked display interrupt (`logd kick`).
 *
 * Why C: a shell sample costs ~36 ms of the A33 at 1008 MHz and much more at the 120 MHz the
 * idle launcher runs at: 1.8% of a core with the default interval (measured on the GA36,
 * 2026-11-18). The budget is 1%.
 *
 * Environment (the tests set them; defaults are the console paths): PROC_ROOT (/proc, for
 * uptime, stat and meminfo), SYS_ROOT (/sys), LOGS_RAM (/run/lume/logs), LOGS_CONF,
 * LUME_STATUS, FRONTEND_LOG, INTERRUPTS_FILE, IRQ_SYS, DRI_DIR, ASOUND_DIR, GPU_DEVFREQ_DIR,
 * KMSG_DEV, RA_PORT (55355), LOGD_CMD (the shell logd), LOGD_SAMPLES (stop after N samples,
 * tests), LOGD_NOWAIT (no wait between samples, tests), RECOVER_MAX (3), KICK_MAX (5),
 * HANG_LIMIT (2), LUME_FRONTENDS (/usr/libexec/lume/frontends/), TIMEZONE_FILE
 * (/etc/timezone), ZONEINFO_DIR (/usr/share/zoneinfo).
 * Processes (retroarch, lume-run...) are always looked up in the real /proc.
 */
#define _GNU_SOURCE
/* every text goes into a fixed buffer and a longer one is cut on purpose (a log line, a
 * sysfs value): the truncation warning would flag each of them */
#pragma GCC diagnostic ignored "-Wformat-truncation"
#include <arpa/inet.h>
#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <glob.h>
#include <netinet/in.h>
#include <poll.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define PROG "lume-logd"
#define TRACE_MAX_BYTES 2097152L
#define FRONTEND_RAM_MAX_BYTES 8388608L
#define FRONTEND_RAM_KEEP_BYTES 1048576L
#define DEEP_MAX 6
#define NOANS_LIMIT 3
#define FPS_SLOW_PCT 95
#define MAXZ 16
#define MAXP 8
#define MAXC 16
#define LINE 8192

static volatile sig_atomic_t stop_sig;
static void on_term(int s) { (void)s; stop_sig = 1; }

/* ---------------------------------------------------------------- configuration */

static const char *proc_root, *sys_root, *logs_ram, *logs_conf_path, *lume_status, *frontend_log,
	*interrupts_file, *irq_sys, *dri_dir, *asound_dir, *devfreq_dir, *kmsg_dev, *logd_cmd,
	*frontends_dir;
static int ra_port = 55355, recover_max = 3, kick_max = 5, hang_limit = 2;
static int log_enable = 1, log_interval = 5, log_flush = 60;
static long samples_max = -1;
static int nowait;

static const char *env(const char *k, const char *def)
{
	const char *v = getenv(k);

	return v && *v ? v : def;
}

static int envi(const char *k, int def)
{
	const char *v = getenv(k);

	return v && *v ? atoi(v) : def;
}

/* ---------------------------------------------------------------- small helpers */

static void path(char *out, size_t n, const char *fmt, ...)
{
	va_list ap;

	va_start(ap, fmt);
	vsnprintf(out, n, fmt, ap);
	va_end(ap);
}

/* whole small file into buf (NUL-terminated); -1 when unreadable */
static int slurp(const char *p, char *buf, size_t n)
{
	int fd = open(p, O_RDONLY | O_CLOEXEC);
	ssize_t r, got = 0;

	if (fd < 0)
		return -1;
	while ((size_t)got < n - 1 && (r = read(fd, buf + got, n - 1 - got)) > 0)
		got += r;
	close(fd);
	buf[got] = 0;
	return (int)got;
}

/* first line of a file without the newline; empty string when unreadable */
static char *first_line(const char *p, char *buf, size_t n)
{
	char *nl;

	if (slurp(p, buf, n) < 0) {
		buf[0] = 0;
		return buf;
	}
	if ((nl = strchr(buf, '\n')))
		*nl = 0;
	return buf;
}

static int readable(const char *p) { return access(p, R_OK) == 0; }

/* A process that still runs: it exists and is not a zombie (a zombie holds nothing). The
 * real /proc, not proc_root: the pid is the one the kernel was just asked to kill. */
static int still_running(pid_t pid)
{
	char p[64], b[256], *r;

	if (kill(pid, 0) != 0)
		return 0;
	snprintf(p, sizeof(p), "/proc/%d/stat", (int)pid);
	if (slurp(p, b, sizeof(b)) <= 0 || !(r = strrchr(b, ')')))
		return 1;
	return r[1] != ' ' || r[2] != 'Z';
}

static long file_size(const char *p)
{
	struct stat st;

	return stat(p, &st) ? -1 : (long)st.st_size;
}

static void append(const char *p, const char *s, mode_t mode)
{
	int fd = open(p, O_WRONLY | O_APPEND | O_CREAT | O_CLOEXEC, mode);

	if (fd < 0)
		return;
	if (write(fd, s, strlen(s)) < 0) {
		/* nothing to do: a full tmpfs drops the line, as the shell did */
	}
	close(fd);
}

/* ---------------------------------------------------------------- clock */

/* uptime: the first field of /proc/uptime as text and in centiseconds */
static char up_txt[32];
static long up_cs;

static long text_cs(const char *t)
{
	long i = strtol(t, NULL, 10);
	const char *d = strchr(t, '.');
	int f = 0;

	if (d) {
		if (isdigit((unsigned char)d[1]))
			f = (d[1] - '0') * 10;
		if (isdigit((unsigned char)d[1]) && isdigit((unsigned char)d[2]))
			f += d[2] - '0';
	}
	return i * 100 + f;
}

static void read_uptime(void)
{
	char p[512], b[128], *sp;

	path(p, sizeof(p), "%s/uptime", proc_root);
	first_line(p, b, sizeof(b));
	if ((sp = strchr(b, ' ')))
		*sp = 0;
	snprintf(up_txt, sizeof(up_txt), "%s", b);
	up_cs = text_cs(b);
}

/* The time zone: lume-persist sets /etc/timezone at boot, after lume-logd started (which then
 * wrote in UTC until the next boot, game-governor D20). Read every round; when it changes, TZ
 * points at its zoneinfo file and tzset() loads it (musl reloads when TZ changes). The shell
 * logd children inherit the new TZ. A name that is not a zone, or has no file, is ignored. */
static const char *tz_file, *zoneinfo_dir;
static char tz_cur[128];

static void tz_follow(void)
{
	char z[128], p[512], tz[600];
	size_t i;

	first_line(tz_file, z, sizeof(z));
	if (!*z || !strcmp(z, tz_cur) || strstr(z, ".."))
		return;
	for (i = 0; z[i]; i++)
		if (!isalnum((unsigned char)z[i]) && !strchr("/_+-", z[i]))
			return;
	path(p, sizeof(p), "%s/%s", zoneinfo_dir, z);
	if (!readable(p))
		return;
	snprintf(tz_cur, sizeof(tz_cur), "%s", z);
	snprintf(tz, sizeof(tz), ":%s", p);
	setenv("TZ", tz, 1);
	tzset();
}

static char log_ts[32], log_hms[16];

static void log_clock(void)
{
	time_t t = time(NULL);
	struct tm tm;

	localtime_r(&t, &tm);
	strftime(log_ts, sizeof(log_ts), "%Y-%m-%dT%H:%M:%S", &tm);
	strftime(log_hms, sizeof(log_hms), "%H:%M:%S", &tm);
}

static long mono_ms(void)
{
	struct timespec ts;

	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

/* ---------------------------------------------------------------- events and trace */

static void event(const char *cat, const char *res, const char *fmt, ...)
{
	char p[512], d[2048], line[2300], bn[32];
	va_list ap;

	va_start(ap, fmt);
	vsnprintf(d, sizeof(d), fmt, ap);
	va_end(ap);
	log_clock();
	path(p, sizeof(p), "%s/boot-n", logs_ram);
	first_line(p, bn, sizeof(bn));
	snprintf(line, sizeof(line), "%s %s %s %s %s\n", log_ts, *bn ? bn : "0", cat, res, d);
	path(p, sizeof(p), "%s/events.pending", logs_ram);
	if (access(p, F_OK)) {
		append(p, "", 0666);
		chmod(p, 0666);  /* shared with lume-run (logs.sh events_file) */
	}
	append(p, line, 0666);
}

static long trace_bytes = -1;

static void trace(const char *fmt, ...)
{
	char p[512], l[LINE], line[LINE + 16];
	va_list ap;

	va_start(ap, fmt);
	vsnprintf(l, sizeof(l), fmt, ap);
	va_end(ap);
	log_clock();
	path(p, sizeof(p), "%s/trace.pending", logs_ram);
	if (trace_bytes < 0) {
		trace_bytes = file_size(p);
		if (trace_bytes < 0)
			trace_bytes = 0;
	}
	if (trace_bytes >= TRACE_MAX_BYTES)
		return;
	snprintf(line, sizeof(line), "%s %s\n", log_hms, l);
	append(p, line, 0644);
	trace_bytes += (long)strlen(l) + 10;
}

/* the shell logd for the rare work: flush, snapshot, kick. Returns the exit code. */
static int shell(const char *a1, const char *a2, const char *a3)
{
	pid_t pid = fork();
	int st;

	if (pid < 0)
		return -1;
	if (pid == 0) {
		execl("/bin/sh", "sh", logd_cmd, a1, a2, a3, (char *)NULL);
		_exit(127);
	}
	while (waitpid(pid, &st, 0) < 0 && errno == EINTR)
		;
	trace_bytes = -1;  /* other writers: measure the buffer again */
	return WIFEXITED(st) ? WEXITSTATUS(st) : -1;
}

static void logs_flush(void) { shell("flush", NULL, NULL); }

/* ---------------------------------------------------------------- discover (header) */

static char zone[MAXZ][256], ztype[MAXZ][64];
static int ztrip[MAXZ], zhot[MAXZ], nzones;
static char policy[MAXP][256];
static int npolicies;
static char bat[256];

static int cmp_str(const void *a, const void *b) { return strcmp(*(char *const *)a, *(char *const *)b); }

/* glob sorted as the shell expands it */
static int sorted_glob(const char *pat, glob_t *g) { return glob(pat, 0, NULL, g); }

static void discover(void)
{
	char p[512], b[256], hdr[4096], q[600];
	glob_t g;
	size_t i;
	int k;
	FILE *f;

	nzones = 0;
	path(p, sizeof(p), "%s/class/thermal/thermal_zone*", sys_root);
	if (!sorted_glob(p, &g)) {
		for (i = 0; i < g.gl_pathc && nzones < MAXZ; i++) {
			glob_t t;
			size_t j;

			path(q, sizeof(q), "%s/temp", g.gl_pathv[i]);
			if (!readable(q))
				continue;
			snprintf(zone[nzones], sizeof(zone[0]), "%s", g.gl_pathv[i]);
			path(q, sizeof(q), "%s/type", g.gl_pathv[i]);
			first_line(q, ztype[nzones], sizeof(ztype[0]));
			ztrip[nzones] = -1;
			zhot[nzones] = 0;
			path(q, sizeof(q), "%s/trip_point_*_type", g.gl_pathv[i]);
			if (!sorted_glob(q, &t)) {
				for (j = 0; j < t.gl_pathc; j++) {
					char tp[600], v[64];

					if (strcmp(first_line(t.gl_pathv[j], v, sizeof(v)), "passive"))
						continue;
					snprintf(tp, sizeof(tp), "%.*s_temp",
						 (int)(strlen(t.gl_pathv[j]) - strlen("_type")), t.gl_pathv[j]);
					ztrip[nzones] = atoi(first_line(tp, v, sizeof(v))) / 1000;
					break;
				}
				globfree(&t);
			}
			nzones++;
		}
		globfree(&g);
	}
	npolicies = 0;
	path(p, sizeof(p), "%s/devices/system/cpu/cpufreq/policy*", sys_root);
	if (!sorted_glob(p, &g)) {
		for (i = 0; i < g.gl_pathc && npolicies < MAXP; i++) {
			path(q, sizeof(q), "%s/scaling_cur_freq", g.gl_pathv[i]);
			if (readable(q))
				snprintf(policy[npolicies++], sizeof(policy[0]), "%s", g.gl_pathv[i]);
		}
		globfree(&g);
	}
	bat[0] = 0;
	path(p, sizeof(p), "%s/class/power_supply/*", sys_root);
	if (!sorted_glob(p, &g)) {
		for (i = 0; i < g.gl_pathc; i++) {
			path(q, sizeof(q), "%s/type", g.gl_pathv[i]);
			if (!strcmp(first_line(q, b, sizeof(b)), "Battery")) {
				snprintf(bat, sizeof(bat), "%s", g.gl_pathv[i]);
				break;
			}
		}
		globfree(&g);
	}
	/* header */
	snprintf(hdr, sizeof(hdr), "time,uptime_s");
	for (k = 0; k < nzones; k++) {
		char t[64];
		size_t j;

		snprintf(t, sizeof(t), "%s", ztype[k]);
		for (j = 0; t[j]; j++)
			if (!isalnum((unsigned char)t[j]) && t[j] != '_')
				t[j] = '_';
		snprintf(hdr + strlen(hdr), sizeof(hdr) - strlen(hdr), ",temp_%s_c", t);
	}
	for (k = 0; k < npolicies; k++)
		snprintf(hdr + strlen(hdr), sizeof(hdr) - strlen(hdr), ",freq_%s_mhz", strrchr(policy[k], '/') + 1);
	path(p, sizeof(p), "%s/stat", proc_root);
	if ((f = fopen(p, "re"))) {
		char l[1024];

		while (fgets(l, sizeof(l), f)) {
			if (!strncmp(l, "cpu ", 4))
				continue;
			if (strncmp(l, "cpu", 3) || !isdigit((unsigned char)l[3]))
				break;
			snprintf(hdr + strlen(hdr), sizeof(hdr) - strlen(hdr), ",cpu%d_pct", atoi(l + 3));
		}
		fclose(f);
	}
	snprintf(hdr + strlen(hdr), sizeof(hdr) - strlen(hdr),
		 ",mem_avail_mb,swap_used_mb,bat_pct,bat_mv,bat_ma,bat_status,frontend,core,content,fps,fps_nominal"
		 ",lume_ui_rss_kb,lume_ui_cpu_pct,lume_run_rss_kb,lume_run_cpu_pct,input_rss_kb,input_cpu_pct\n");
	path(p, sizeof(p), "%s/metrics.header", logs_ram);
	{
		int fd = open(p, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);

		if (fd >= 0) {
			if (write(fd, hdr, strlen(hdr)) < 0) {
				/* tmpfs full: no header, as the shell */
			}
			close(fd);
		}
	}
	(void)cmp_str;
}

/* ---------------------------------------------------------------- processes */

/* pid of a process by its comm, kept between samples and checked by comm (the shell
 * proc_pid): the scan of /proc runs only when the kept one no longer has the name */
struct watched {
	const char *name;
	pid_t pid;
	unsigned long long ticks;
	long cs;
	int have;
};

static int comm_is(pid_t pid, const char *name)
{
	char p[64], b[64];

	path(p, sizeof(p), "/proc/%d/comm", (int)pid);
	return !strcmp(first_line(p, b, sizeof(b)), name);
}

static pid_t find_pid(const char *name)
{
	DIR *d = opendir("/proc");
	struct dirent *e;
	pid_t best = 0;

	if (!d)
		return 0;
	while ((e = readdir(d))) {
		pid_t p;

		if (!isdigit((unsigned char)e->d_name[0]))
			continue;
		p = (pid_t)atoi(e->d_name);
		/* the newest one, as busybox pidof lists it first: RetroArch runs under a wrapper
		 * of the same name (the frontend script), and the emulator is the child */
		if (comm_is(p, name) && p > best)
			best = p;
	}
	closedir(d);
	return best;
}

static long sample_n;

static pid_t proc_pid(struct watched *w)
{
	if (w->pid && comm_is(w->pid, w->name))
		return w->pid;
	w->pid = find_pid(w->name);
	return w->pid;
}

/* fields after "(comm) " of /proc/<pid>/stat into f[0..n): f[0] is the state */
static int stat_fields(const char *p, char f[][24], int n)
{
	char b[1024], *s, *tok, *save = NULL;
	int i = 0;

	if (slurp(p, b, sizeof(b)) <= 0 || !(s = strrchr(b, ')')))
		return 0;
	for (tok = strtok_r(s + 1, " \n", &save); tok && i < n; tok = strtok_r(NULL, " \n", &save))
		snprintf(f[i++], 24, "%s", tok);
	return i;
}

/* "rss,cpu" of a watched process (the shell proc_usage) */
static void proc_usage(struct watched *w, char *out, size_t n)
{
	char p[64], f[20][24], st[2048], *r;
	pid_t old = w->pid, pid = proc_pid(w);
	unsigned long long ticks;
	char rss[32] = "", pct[32] = "";

	path(p, sizeof(p), "/proc/%d/stat", (int)pid);
	if (!pid || stat_fields(p, f, 20) < 13) {
		w->pid = 0;
		w->have = 0;
		snprintf(out, n, ",");
		return;
	}
	if (pid != old)
		w->have = 0;
	ticks = strtoull(f[11], NULL, 10) + strtoull(f[12], NULL, 10);
	path(p, sizeof(p), "/proc/%d/status", (int)pid);
	if (slurp(p, st, sizeof(st)) > 0 && (r = strstr(st, "VmRSS:")))
		snprintf(rss, sizeof(rss), "%ld", strtol(r + 6, NULL, 10));
	if (w->have && ticks >= w->ticks && up_cs > w->cs) {
		long x = (long)((ticks - w->ticks) * 1000 / (unsigned long long)(up_cs - w->cs));

		snprintf(pct, sizeof(pct), "%ld.%ld", x / 10, x % 10);
	}
	w->ticks = ticks;
	w->cs = up_cs;
	w->have = 1;
	snprintf(out, n, "%s,%s", rss, pct);
}

static struct watched w_ra = { "retroarch", 0, 0, 0, 0 }, w_ui = { "lume-ui", 0, 0, 0, 0 },
	w_run = { "lume-run", 0, 0, 0, 0 }, w_in = { "lume-input", 0, 0, 0, 0 };

/* retroarch: looked up again once per sample (only while no launcher is on screen). The
 * frontend script that starts it has the same name and lives as long as the game: a pid kept
 * from the first moments of a game would stay on the script and never reach the emulator. */
static long ra_seen = -1;

static pid_t ra_pid(void)
{
	if (ra_seen != sample_n) {
		ra_seen = sample_n;
		w_ra.pid = 0;
	}
	return proc_pid(&w_ra);
}

/* any process whose command line contains s (the shell's pgrep -f) */
static int pgrep_f(const char *s)
{
	DIR *d = opendir("/proc");
	struct dirent *e;
	int found = 0;

	if (!d)
		return 0;
	while (!found && (e = readdir(d))) {
		char p[64], b[4096];
		int n, i;

		if (!isdigit((unsigned char)e->d_name[0]) || atoi(e->d_name) == getpid())
			continue;
		path(p, sizeof(p), "/proc/%s/cmdline", e->d_name);
		if ((n = slurp(p, b, sizeof(b))) <= 0)
			continue;
		for (i = 0; i < n; i++)
			if (!b[i])
				b[i] = ' ';
		found = strstr(b, s) != NULL;
	}
	closedir(d);
	return found;
}

/* ---------------------------------------------------------------- frontend */

static char fe_state[16], fe_core[256], fe_content[512], fe_frames[32];
static int lume;

/* GET_STATUS over UDP with a 1 s answer timeout (nc -u -w1) */
static int get_status(char *out, size_t n)
{
	int s = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC, 0);
	struct sockaddr_in a;
	struct pollfd pfd;
	ssize_t r;

	out[0] = 0;
	if (s < 0)
		return -1;
	memset(&a, 0, sizeof(a));
	a.sin_family = AF_INET;
	a.sin_port = htons((unsigned short)ra_port);
	a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
	if (sendto(s, "GET_STATUS", 10, 0, (struct sockaddr *)&a, sizeof(a)) < 0) {
		close(s);
		return -1;
	}
	pfd.fd = s;
	pfd.events = POLLIN;
	if (poll(&pfd, 1, 1000) == 1 && (r = recv(s, out, n - 1, 0)) > 0)
		out[r] = 0;
	close(s);
	return 0;
}

static void frontend_state(void)
{
	char s[256] = "", r[2048], *st, *rest, *c, *fr;

	fe_core[0] = fe_content[0] = fe_frames[0] = 0;
	lume = 0;
	if (readable(lume_status) && proc_pid(&w_run))
		lume = 1;
	if (lume) {
		first_line(lume_status, s, sizeof(s));
		if (strncmp(s, "game:", 5)) {
			snprintf(fe_state, sizeof(fe_state), "launcher");
			return;
		}
	}
	if (!ra_pid()) {
		if (lume) {
			snprintf(fe_state, sizeof(fe_state), "game");
			snprintf(fe_core, sizeof(fe_core), "%s", s + 5);
			return;
		}
		snprintf(fe_state, sizeof(fe_state), pgrep_f(frontends_dir) ? "other" : "stopped");
		return;
	}
	get_status(r, sizeof(r));
	/* "GET_STATUS <state> <core>,<content>,crc32=<x>[,frames=<n>]" */
	st = strchr(r, ' ');
	if (st) {
		st++;
		rest = strchr(st, ' ');
		if (rest)
			*rest++ = 0;
	}
	if (st && (!strcmp(st, "PLAYING") || !strcmp(st, "PAUSED"))) {
		char *nl;

		snprintf(fe_state, sizeof(fe_state), "%s", !strcmp(st, "PAUSED") ? "paused" : "game");
		if (!rest)
			rest = st + strlen(st);
		if ((nl = strchr(rest, '\n')))
			*nl = 0;
		if ((fr = strstr(rest, ",frames="))) {
			char *last = fr, *x;

			while ((x = strstr(last + 1, ",frames=")))
				last = x;
			snprintf(fe_frames, sizeof(fe_frames), "%ld", strtol(last + 8, NULL, 10));
			if (!isdigit((unsigned char)last[8]))
				fe_frames[0] = 0;
		}
		c = strchr(rest, ',');
		snprintf(fe_core, sizeof(fe_core), "%.*s", c ? (int)(c - rest) : (int)strlen(rest), rest);
		if (c) {
			char *crc = NULL, *x = c;

			/* the content ends at the last ",crc32=" (the shell's ${rest%,crc32=*}) */
			while ((x = strstr(x, ",crc32=")))
				crc = x++;
			snprintf(fe_content, sizeof(fe_content), "%.*s",
				 crc && crc > c ? (int)(crc - c - 1) : (int)strlen(c + 1), c + 1);
		}
		if (lume)
			fe_content[0] = 0;
	} else if (st && !strncmp(st, "CONTENTLESS", 11)) {
		snprintf(fe_state, sizeof(fe_state), "menu");
	} else {
		snprintf(fe_state, sizeof(fe_state), "no_answer");
	}
}

static void csv(char *dst, size_t n, const char *s)
{
	size_t i;

	snprintf(dst, n, "%s", s);
	for (i = 0; dst[i]; i++)
		if (dst[i] == ',' || dst[i] == '\n')
			dst[i] = ';';
}

/* ---------------------------------------------------------------- game FPS */

static char game_key[800], game_core[256], game_content[512], game_nominal[32], fps[32];
static long game_t0, fps_prev_frames = -1, fps_prev_cs;
static int slow_n, slow;
static time_t fps_mark;

/* the nominal FPS of the core: the last "Geometry: ... FPS: <n>," of the frontend log */
static void core_nominal_fps(void)
{
	FILE *f = fopen(frontend_log, "re");
	char l[LINE], *g, *p;

	game_nominal[0] = 0;
	if (!f)
		return;
	while (fgets(l, sizeof(l), f)) {
		if (!(g = strstr(l, "Geometry: ")) || !(p = strstr(g, " FPS: ")))
			continue;
		p += 6;
		{
			size_t k = strspn(p, "0123456789.");

			snprintf(game_nominal, sizeof(game_nominal), "%.*s", (int)k, p);
		}
	}
	fclose(f);
}

/* did the frontend log change since the last look (mtime, one second resolution as the
 * shell's -nt test: a write in the same second counts as a change) */
static int changed(time_t *mark)
{
	struct stat st;

	if (stat(frontend_log, &st))
		return 0;
	if (*mark && st.st_mtime < *mark)
		return 0;
	*mark = time(NULL);
	return 1;
}

static void game_track(void)
{
	char key[800] = "";
	long upi = up_cs / 100;

	if (!strcmp(fe_state, "game") || !strcmp(fe_state, "paused"))
		snprintf(key, sizeof(key), "%s|%s", fe_core, fe_content);
	if (strcmp(key, game_key)) {
		if (*game_key && !lume)
			event("game", "OK", "closed: core=%s content=%s duration=%lds", game_core, game_content,
			      upi - game_t0);
		if (*key) {
			snprintf(game_core, sizeof(game_core), "%s", fe_core);
			snprintf(game_content, sizeof(game_content), "%s", fe_content);
			game_t0 = upi;
			if (!lume)
				event("game", "OK", "opened: core=%s content=%s", fe_core, fe_content);
		}
		snprintf(game_key, sizeof(game_key), "%s", key);
		game_nominal[0] = 0;
		fps_prev_frames = -1;
		slow_n = slow = 0;
	}
	fps[0] = 0;
	if (*game_key && !*game_nominal && changed(&fps_mark))
		core_nominal_fps();
	if (strcmp(fe_state, "game") || !*fe_frames) {
		fps_prev_frames = -1;
		return;
	}
	{
		long fr = strtol(fe_frames, NULL, 10);

		if (fps_prev_frames >= 0 && fr >= fps_prev_frames && up_cs > fps_prev_cs) {
			long x = ((fr - fps_prev_frames) * 2000 + up_cs - fps_prev_cs) / (2 * (up_cs - fps_prev_cs));

			snprintf(fps, sizeof(fps), "%ld.%ld", x / 10, x % 10);
		}
		fps_prev_frames = fr;
		fps_prev_cs = up_cs;
	}
	if (!*fps || !*game_nominal)
		return;
	if (text_cs(fps) * 100 < text_cs(game_nominal) * FPS_SLOW_PCT) {
		slow_n++;
		if (slow_n >= 2 && !slow) {
			slow = 1;
			if (*game_content)
				event("game", "FAIL", "slow: core=%s %s fps (nominal %s) content=%s", game_core, fps,
				      game_nominal, game_content);
			else
				event("game", "FAIL", "slow: core=%s %s fps (nominal %s)", game_core, fps, game_nominal);
		}
	} else {
		slow_n = 0;
		if (slow) {
			slow = 0;
			event("game", "OK", "full speed again: core=%s %s fps (nominal %s)", game_core, fps,
			      game_nominal);
		}
	}
}

/* ---------------------------------------------------------------- display, audio, usb */

static char vb_files[8][512];
static int nvb = -1;  /* -1: not looked yet */

/* sum of the display controller interrupts; "" when there is none */
static void vblank_scan(char *out, size_t n)
{
	long vb = 0;
	int found = 0, i;
	char p[600], b[4096];

	out[0] = 0;
	if (!strcmp(interrupts_file, "/proc/interrupts") && nvb < 0) {
		glob_t g;
		size_t k;

		nvb = 0;
		path(p, sizeof(p), "%s/*/actions", irq_sys);
		if (!glob(p, 0, NULL, &g)) {
			for (k = 0; k < g.gl_pathc && nvb < 8; k++) {
				first_line(g.gl_pathv[k], b, sizeof(b));
				if (strstr(b, "lcd-controller") || strstr(b, "tcon"))
					snprintf(vb_files[nvb++], sizeof(vb_files[0]), "%.*s/per_cpu_count",
						 (int)(strlen(g.gl_pathv[k]) - strlen("/actions")), g.gl_pathv[k]);
			}
			globfree(&g);
		} else {
			nvb = -2;  /* no irq directory: the table */
		}
	}
	if (!strcmp(interrupts_file, "/proc/interrupts") && nvb >= 0) {
		for (i = 0; i < nvb; i++) {
			char *s = first_line(vb_files[i], b, sizeof(b)), *e;

			found = 1;
			while (*s) {
				long v = strtol(s, &e, 10);

				if (e == s)
					break;
				vb += v;
				s = *e == ',' ? e + 1 : e;
				if (*e != ',')
					break;
			}
		}
		if (found || nvb == 0) {
			if (found)
				snprintf(out, n, "%ld", vb);
			return;
		}
	}
	{
		FILE *f = fopen(interrupts_file, "re");
		char l[1024];

		if (!f)
			return;
		while (fgets(l, sizeof(l), f)) {
			char *s, *e;

			if (!strstr(l, "lcd-controller") && !strstr(l, "tcon"))
				continue;
			found = 1;
			s = strchr(l, ':');
			s = s ? s + 1 : l;
			for (;;) {
				long v;

				while (*s == ' ')
					s++;
				v = strtol(s, &e, 10);
				if (e == s || (*e != ' ' && *e != '\n' && *e))
					break;
				vb += v;
				s = e;
			}
		}
		fclose(f);
		if (found)
			snprintf(out, n, "%ld", vb);
	}
}

static void gpu_mhz(char *out, size_t n)
{
	char p[600], b[64];
	glob_t g;

	out[0] = 0;
	path(p, sizeof(p), "%s/*gpu*/cur_freq", devfreq_dir);
	if (glob(p, 0, NULL, &g))
		return;
	if (g.gl_pathc && readable(g.gl_pathv[0]))
		snprintf(out, n, "%ld", strtol(first_line(g.gl_pathv[0], b, sizeof(b)), NULL, 10) / 1000000);
	globfree(&g);
}

/* the value of "<key> : value" in a /proc/asound file */
static int kv(const char *buf, const char *key, char *out, size_t n)
{
	const char *l = buf;
	size_t kl = strlen(key);

	while (l && *l) {
		const char *c = strchr(l, ':'), *nl = strchr(l, '\n');

		if (c && (!nl || c < nl) && !strncmp(l, key, kl)) {
			const char *k = l + kl;

			while (k < c && *k == ' ')
				k++;
			if (k == c) {
				c++;
				while (*c == ' ')
					c++;
				snprintf(out, n, "%.*s", nl ? (int)(nl - c) : (int)strlen(c), c);
				return 1;
			}
		}
		l = nl ? nl + 1 : NULL;
	}
	out[0] = 0;
	return 0;
}

static void pcm_scan(char *out, size_t n)
{
	char p[600], b[2048], h[2048], st[64], rate[64], ptr[64], up[32];
	glob_t g;
	size_t i;

	snprintf(out, n, "-");
	path(p, sizeof(p), "%s/card*/pcm*p/sub*/status", asound_dir);
	if (glob(p, 0, NULL, &g))
		return;
	for (i = 0; i < g.gl_pathc; i++) {
		char hp[600], *x;

		if (slurp(g.gl_pathv[i], b, sizeof(b)) < 0 || !kv(b, "state", st, sizeof(st)) || !*st)
			continue;
		snprintf(hp, sizeof(hp), "%.*s/hw_params", (int)(strlen(g.gl_pathv[i]) - strlen("/status")),
			 g.gl_pathv[i]);
		h[0] = 0;
		slurp(hp, h, sizeof(h));
		kv(h, "rate", rate, sizeof(rate));
		for (x = rate; isdigit((unsigned char)*x); x++)
			;
		*x = 0;
		{
			char up_p[512], ub[128], *sp;

			path(up_p, sizeof(up_p), "%s/uptime", proc_root);
			first_line(up_p, ub, sizeof(ub));
			if ((sp = strchr(ub, ' ')))
				*sp = 0;
			snprintf(up, sizeof(up), "%s", ub);
		}
		slurp(g.gl_pathv[i], b, sizeof(b));
		kv(b, "hw_ptr", ptr, sizeof(ptr));
		snprintf(out, n, "%s/%s/%s/%s", st, rate, up, ptr);
		break;
	}
	globfree(&g);
}

static void glob_each(const char *pat, void (*cb)(const char *, void *), void *ctx)
{
	glob_t g;
	size_t i;

	if (glob(pat, 0, NULL, &g))
		return;
	for (i = 0; i < g.gl_pathc; i++)
		cb(g.gl_pathv[i], ctx);
	globfree(&g);
}

struct sbuf {
	char s[2048];
};

static void sb_add(struct sbuf *b, const char *fmt, ...)
{
	size_t l = strlen(b->s);
	va_list ap;

	va_start(ap, fmt);
	vsnprintf(b->s + l, sizeof(b->s) - l, fmt, ap);
	va_end(ap);
}

static void cb_extcon(const char *f, void *ctx)
{
	char b[1024], s[1024] = "", d[600], name[256], *l, *save = NULL;

	if (slurp(f, b, sizeof(b)) < 0)
		return;
	for (l = strtok_r(b, "\n", &save); l; l = strtok_r(NULL, "\n", &save))
		snprintf(s + strlen(s), sizeof(s) - strlen(s), ",%s", l);
	if (!strstr(s, "USB"))
		return;
	snprintf(d, sizeof(d), "%.*s", (int)(strlen(f) - strlen("/state")), f);
	path(name, sizeof(name), "%s/name", d);
	first_line(name, b, sizeof(b));
	sb_add(ctx, " extcon=%s:%s", *b ? b : strrchr(d, '/') + 1, s + 1);
}

static void cb_musb(const char *f, void *ctx)
{
	char b[128];

	if (readable(f))
		sb_add(ctx, " musb=%s", first_line(f, b, sizeof(b)));
}

static void cb_role(const char *f, void *ctx)
{
	char b[128], d[600];

	if (!readable(f))
		return;
	snprintf(d, sizeof(d), "%.*s", (int)(strlen(f) - strlen("/role")), f);
	sb_add(ctx, " role=%s:%s", strrchr(d, '/') + 1, first_line(f, b, sizeof(b)));
}

static void cb_udc(const char *f, void *ctx)
{
	char b[128], d[600];
	size_t i;

	if (!readable(f))
		return;
	snprintf(d, sizeof(d), "%.*s", (int)(strlen(f) - strlen("/state")), f);
	first_line(f, b, sizeof(b));
	for (i = 0; b[i]; i++)
		if (b[i] == ' ')
			b[i] = '_';
	sb_add(ctx, " udc=%s:%s", strrchr(d, '/') + 1, b);
}

static void cb_vbus(const char *d, void *ctx)
{
	char p[700], b[128];

	path(p, sizeof(p), "%s/type", d);
	if (strcmp(first_line(p, b, sizeof(b)), "USB"))
		return;
	path(p, sizeof(p), "%s/online", d);
	sb_add(ctx, " vbus=%s:%s", strrchr(d, '/') + 1, first_line(p, b, sizeof(b)));
}

static void cb_dev(const char *d, void *ctx)
{
	if (!strchr(strrchr(d, '/') + 1, ':'))
		(*(int *)ctx)++;
}

static void usb_scan(char *out, size_t n)
{
	struct sbuf b = { "" };
	char p[600];
	int devs = 0;

	path(p, sizeof(p), "%s/class/extcon/*/state", sys_root);
	glob_each(p, cb_extcon, &b);
	path(p, sizeof(p), "%s/bus/platform/devices/musb-hdrc.*/mode", sys_root);
	glob_each(p, cb_musb, &b);
	path(p, sizeof(p), "%s/class/usb_role/*/role", sys_root);
	glob_each(p, cb_role, &b);
	path(p, sizeof(p), "%s/class/udc/*/state", sys_root);
	glob_each(p, cb_udc, &b);
	path(p, sizeof(p), "%s/class/power_supply/*", sys_root);
	glob_each(p, cb_vbus, &b);
	path(p, sizeof(p), "%s/bus/usb/devices/[0-9]*-*", sys_root);
	glob_each(p, cb_dev, &devs);
	if (!*b.s && !devs)
		snprintf(out, n, "none");
	else
		snprintf(out, n, "%s host_devs=%d", *b.s ? b.s + 1 : "", devs);
}

static char usb_last[2048] = "none";
static int usb_connected;

static void usb_watch(void)
{
	char s[2048];

	usb_scan(s, sizeof(s));
	trace("usb: %s", s);
	if (!strcmp(s, usb_last))
		return;
	snprintf(usb_last, sizeof(usb_last), "%s", s);
	event("usb", "OK", "otg: %s", s);
	{
		char pad[2100];
		int conf;

		snprintf(pad, sizeof(pad), " %s ", s);
		conf = strstr(pad, " udc=") && strstr(pad, ":configured ");
		if (conf && !usb_connected) {
			usb_connected = 1;
			event("usb", "OK", "device: connected");
		} else if (!conf && usb_connected) {
			usb_connected = 0;
			event("usb", "OK", "device: disconnected");
		}
	}
}

/* audio stalls of RetroArch (patch 0003): the new part of the frontend log */
static long audio_pos;
static time_t audio_mark;

static void frontend_log_trim(void)
{
	long sz = file_size(frontend_log);
	char *buf, p[512];
	int fd;

	if (sz <= FRONTEND_RAM_MAX_BYTES)
		return;
	buf = malloc(FRONTEND_RAM_KEEP_BYTES);
	if (!buf)
		return;
	fd = open(frontend_log, O_RDWR | O_CLOEXEC);
	if (fd >= 0) {
		ssize_t r = pread(fd, buf, FRONTEND_RAM_KEEP_BYTES, sz - FRONTEND_RAM_KEEP_BYTES);

		if (r > 0 && ftruncate(fd, 0) == 0 && pwrite(fd, buf, (size_t)r, 0) < 0) {
			/* nothing more to do */
		}
		close(fd);
	}
	free(buf);
	path(p, sizeof(p), "%s/frontend.size", logs_ram);
	unlink(p);
}

static void audio_watch(void)
{
	long size = file_size(frontend_log);
	FILE *f;
	char l[LINE];

	if (size < 0)
		size = 0;
	if (size < audio_pos)
		audio_pos = 0;
	if (size <= audio_pos)
		return;
	f = fopen(frontend_log, "re");
	if (f) {
		char bp[512], bn[32];

		path(bp, sizeof(bp), "%s/boot-n", logs_ram);
		first_line(bp, bn, sizeof(bn));
		fseek(f, audio_pos, SEEK_SET);
		while (fgets(l, sizeof(l), f)) {
			if (strstr(l, "[ALSA] Playback stalled"))
				event("audio", "FAIL",
				      "playback stalled: the sound device stopped consuming, the game keeps running without sound; see frontend/boot-%s.log",
				      *bn ? bn : "0");
			else if (strstr(l, "[ALSA] Playback consuming again"))
				event("audio", "OK", "playback consuming again, sound resumed");
		}
		fclose(f);
	}
	audio_pos = size;
}

/* ---------------------------------------------------------------- frontend trace and hang */

static int noans, deep_n, hang, recover_n, kick_n;
static pid_t prev_pid, kicked_pid;
static long long prev_ticks = -1;
static char prev_vb[32], prev_state[16];
static int snapped;

static void snapshot(pid_t pid)
{
	char a[16];

	snprintf(a, sizeof(a), "%d", (int)pid);
	shell("snapshot", a, fe_state);
}

static int dri_fds(pid_t pid)
{
	char p[64], q[600];
	DIR *d, *dd;
	struct dirent *e, *de;
	int n = 0;

	path(p, sizeof(p), "/proc/%d/fd", (int)pid);
	if (!(d = opendir(p)))
		return 0;
	while ((e = readdir(d))) {
		struct stat fs;

		if (e->d_name[0] == '.')
			continue;
		path(q, sizeof(q), "%s/%s", p, e->d_name);
		if (stat(q, &fs))
			continue;
		if (!(dd = opendir(dri_dir)))
			break;
		while ((de = readdir(dd))) {
			char r[600];
			struct stat ds;

			if (de->d_name[0] == '.')
				continue;
			path(r, sizeof(r), "%s/%s", dri_dir, de->d_name);
			if (stat(r, &ds) || !S_ISCHR(ds.st_mode))
				continue;
			if (ds.st_dev == fs.st_dev && ds.st_ino == fs.st_ino) {
				n++;
				break;
			}
		}
		closedir(dd);
	}
	closedir(d);
	return n;
}

static void trace_sample(void)
{
	char vb[32], gpu[32], bn[32], pb[512];
	pid_t pid = 0;

	if (changed(&audio_mark)) {
		audio_watch();
		if (audio_pos > FRONTEND_RAM_MAX_BYTES) {
			frontend_log_trim();
			audio_pos = file_size(frontend_log);
			if (audio_pos < 0)
				audio_pos = 0;
		}
	}
	vblank_scan(vb, sizeof(vb));
	gpu_mhz(gpu, sizeof(gpu));
	path(pb, sizeof(pb), "%s/boot-n", logs_ram);
	first_line(pb, bn, sizeof(bn));
	if (strcmp(fe_state, "launcher"))
		pid = ra_pid();
	if (!pid) {
		trace("fe=%s pid=- gpu_mhz=%s vblank=%s", fe_state, gpu, vb);
		noans = hang = 0;
		prev_pid = 0;
		prev_ticks = -1;
	} else {
		char p[64], f[20][24], pcm[256], tasks[4096] = "", tp[64];
		long long ticks;
		DIR *d;
		struct dirent *e;

		path(p, sizeof(p), "/proc/%d/stat", (int)pid);
		memset(f, 0, sizeof(f));
		if (stat_fields(p, f, 20) < 1)
			snprintf(f[0], 24, "?");
		if (!*f[11])
			snprintf(f[11], 24, "0");
		if (!*f[12])
			snprintf(f[12], 24, "0");
		if (!*f[17])
			snprintf(f[17], 24, "0");
		ticks = atoll(f[11]) + atoll(f[12]);
		path(tp, sizeof(tp), "/proc/%d/task", (int)pid);
		if ((d = opendir(tp))) {
			while ((e = readdir(d))) {
				char sp[128], wp[128], tf[3][24], w[128];

				if (!isdigit((unsigned char)e->d_name[0]))
					continue;
				path(sp, sizeof(sp), "%s/%s/stat", tp, e->d_name);
				path(wp, sizeof(wp), "%s/%s/wchan", tp, e->d_name);
				tf[0][0] = 0;
				stat_fields(sp, tf, 1);
				w[0] = 0;
				slurp(wp, w, sizeof(w));
				snprintf(tasks + strlen(tasks), sizeof(tasks) - strlen(tasks), " %s:%s:%s", e->d_name,
					 tf[0], w);
			}
			closedir(d);
		}
		pcm_scan(pcm, sizeof(pcm));
		trace("fe=%s pid=%d st=%s utime=%s stime=%s threads=%s dri_fds=%d gpu_mhz=%s vblank=%s pcm=%s tasks=%s",
		      fe_state, (int)pid, f[0], f[11], f[12], f[17], dri_fds(pid), gpu, vb, pcm, tasks);
		/* hung: same process, (almost) no CPU, the vblank counter not moving (after a kick
		 * only the CPU counts) */
		if (pid == prev_pid && prev_ticks >= 0 && ticks <= prev_ticks + 2 &&
		    (!*vb || !strcmp(vb, prev_vb) || pid == kicked_pid)) {
			hang++;
		} else {
			hang = 0;
			if (pid == kicked_pid && prev_ticks >= 0)
				kicked_pid = 0;
		}
		prev_pid = pid;
		prev_ticks = ticks;
		snprintf(prev_vb, sizeof(prev_vb), "%s", vb);
		if (!hang)
			snapped = 0;
		if (hang == 1 && *vb) {
			if (deep_n < DEEP_MAX) {
				deep_n++;
				snapshot(pid);
				snapped = 1;
			}
			if (kick_n < kick_max) {
				/* logd kick: 0 the vblank runs again, 1 written but no effect, 2 nothing written */
				int r = shell("kick", NULL, NULL);

				if (r == 0) {
					kick_n++;
					event("frontend", "OK",
					      "recovery: re-enabled the masked display vblank interrupt; the display runs again, watching retroarch pid %d (kick %d of %d)",
					      (int)pid, kick_n, kick_max);
					hang = 0;
					kicked_pid = pid;
					vblank_scan(prev_vb, sizeof(prev_vb));
					logs_flush();
				} else if (r == 1) {
					kick_n++;
				}
			}
		}
		if (hang == hang_limit) {
			if (pid == kicked_pid)
				event("frontend", "FAIL",
				      "retroarch pid %d hung: blocked with no CPU for %ds although the display vblank runs again (state %s); see trace/boot-%s.log",
				      (int)pid, hang * log_interval, fe_state, bn);
			else
				event("frontend", "FAIL",
				      "retroarch pid %d hung: blocked with no CPU and no display vblank for %ds (state %s); see trace/boot-%s.log",
				      (int)pid, hang * log_interval, fe_state, bn);
			if (!snapped && deep_n < DEEP_MAX) {
				deep_n++;
				snapshot(pid);
			}
			if (recover_n < recover_max) {
				recover_n++;
				logs_flush();
				/* the whole group (lume-hud-actions 3.5: "retroarch" is also the name of a
				 * wrapper, and a stopped group survived the kill of one pid); SIGCONT first,
				 * then SIGKILL, and the death checked */
				{
					pid_t pg = getpgid(pid);

					/* never our own group (a test runs the fake game in it) */
					if (pg > 1 && pg != getpgrp()) {
						kill(-pg, SIGCONT);
						kill(-pg, SIGKILL);
					} else {
						kill(pid, SIGCONT);
						kill(pid, SIGKILL);
					}
					usleep(500000);
					int alive = still_running(pid);

					event("frontend", alive ? "FAIL" : "OK",
					      "recovery %d of %d: killed the hung retroarch pid %d (group %d)%s; the session restarts the frontend",
					      recover_n, recover_max, (int)pid, (int)pg,
					      alive ? " but it is still alive" : "");
				}
				prev_pid = 0;
			}
		}
		if (!strcmp(fe_state, "no_answer")) {
			noans++;
			if (noans == NOANS_LIMIT)
				event("frontend", "FAIL", "retroarch pid %d alive but no answer for %ds; see trace/boot-%s.log",
				      (int)pid, noans * log_interval, bn);
			if (noans >= NOANS_LIMIT && (noans - NOANS_LIMIT) % 6 == 0 && deep_n < DEEP_MAX) {
				deep_n++;
				snapshot(pid);
			}
		} else {
			if (noans >= NOANS_LIMIT)
				event("frontend", "OK", "retroarch answering again after %ds", noans * log_interval);
			noans = 0;
		}
	}
	if (strcmp(fe_state, prev_state) || noans > 0)
		logs_flush();
	snprintf(prev_state, sizeof(prev_state), "%s", fe_state);
}

/* ---------------------------------------------------------------- the sample */

static unsigned long long cp_t[MAXC], cp_i[MAXC];
static int bat_low;

static void milli_tenths(long t, char *out, size_t n)
{
	long x;

	if (t < 0) {
		x = (50 - t) / 100;
		snprintf(out, n, "-%ld.%ld", x / 10, x % 10);
	} else {
		x = (t + 50) / 100;
		snprintf(out, n, "%ld.%ld", x / 10, x % 10);
	}
}

static void sample(void)
{
	char line[LINE], p[600], b[4096], v[64];
	int k;

	sample_n++;
	read_uptime();
	log_clock();
	snprintf(line, sizeof(line), "%s,%s", log_ts, up_txt);
	for (k = 0; k < nzones; k++) {
		long t;
		int has;

		path(p, sizeof(p), "%s/temp", zone[k]);
		first_line(p, v, sizeof(v));
		has = *v != 0;
		t = strtol(v, NULL, 10);
		milli_tenths(t, b, sizeof(b));
		snprintf(line + strlen(line), sizeof(line) - strlen(line), ",%s", b);
		if (ztrip[k] >= 0 && has) {
			if (t / 1000 >= ztrip[k] && !zhot[k]) {
				zhot[k] = 1;
				event("temperature", "FAIL", "%s %ld \xc2\xb0" "C, above passive trip of %d \xc2\xb0" "C", ztype[k],
				      t / 1000, ztrip[k]);
			} else if (t / 1000 <= ztrip[k] - 5 && zhot[k]) {
				zhot[k] = 0;
				event("temperature", "OK", "%s back to %ld \xc2\xb0" "C", ztype[k], t / 1000);
			}
		}
	}
	for (k = 0; k < npolicies; k++) {
		path(p, sizeof(p), "%s/scaling_cur_freq", policy[k]);
		snprintf(line + strlen(line), sizeof(line) - strlen(line), ",%ld",
			 strtol(first_line(p, v, sizeof(v)), NULL, 10) / 1000);
	}
	/* per-core load since the previous sample (0 before the first one) */
	path(p, sizeof(p), "%s/stat", proc_root);
	if (slurp(p, b, sizeof(b)) > 0) {
		char *l = b, *nl;

		while (l && *l) {
			nl = strchr(l, '\n');
			if (nl)
				*nl = 0;
			if (!strncmp(l, "cpu", 3) && isdigit((unsigned char)l[3])) {
				int n = atoi(l + 3), i = 0;
				unsigned long long tot = 0, idle = 0, vv;
				char *s = strchr(l, ' '), *e;
				long long dt, di, x = 0;

				while (s && *s) {
					vv = strtoull(s, &e, 10);
					if (e == s)
						break;
					tot += vv;
					if (i == 3 || i == 4)
						idle += vv;
					i++;
					s = e;
				}
				if (n < MAXC) {
					dt = (long long)(tot - cp_t[n]);
					di = (long long)(idle - cp_i[n]);
					if (dt > 0) {
						x = 100 * (dt - di);
						x = x >= 0 ? (2 * x + dt) / (2 * dt) : -((dt - 2 * x) / (2 * dt));
					}
					cp_t[n] = tot;
					cp_i[n] = idle;
				}
				snprintf(line + strlen(line), sizeof(line) - strlen(line), ",%lld", x);
			} else if (strncmp(l, "cpu", 3)) {
				break;
			}
			l = nl ? nl + 1 : NULL;
		}
	}
	{
		long a = 0, st = 0, sf = 0;
		char *r;

		path(p, sizeof(p), "%s/meminfo", proc_root);
		if (slurp(p, b, sizeof(b)) > 0) {
			if ((r = strstr(b, "MemAvailable:")))
				a = strtol(r + 13, NULL, 10);
			if ((r = strstr(b, "SwapTotal:")))
				st = strtol(r + 10, NULL, 10);
			if ((r = strstr(b, "SwapFree:")))
				sf = strtol(r + 9, NULL, 10);
		}
		snprintf(line + strlen(line), sizeof(line) - strlen(line), ",%ld,%ld", a / 1024, (st - sf) / 1024);
	}
	{
		char pct[32] = "", mv[32] = "", ma[32] = "", bst[64] = "";

		if (*bat) {
			path(p, sizeof(p), "%s/capacity", bat);
			first_line(p, pct, sizeof(pct));
			/* the RK817 of the R36S has only voltage_avg and current_avg (R36S J1) */
			path(p, sizeof(p), "%s/voltage_now", bat);
			if (!readable(p))
				path(p, sizeof(p), "%s/voltage_avg", bat);
			snprintf(mv, sizeof(mv), "%ld", strtol(first_line(p, v, sizeof(v)), NULL, 10) / 1000);
			path(p, sizeof(p), "%s/current_now", bat);
			if (!readable(p))
				path(p, sizeof(p), "%s/current_avg", bat);
			snprintf(ma, sizeof(ma), "%ld", strtol(first_line(p, v, sizeof(v)), NULL, 10) / 1000);
			path(p, sizeof(p), "%s/status", bat);
			first_line(p, bst, sizeof(bst));
			if (*pct) {
				int c = atoi(pct);

				if (c < 10 && !bat_low) {
					bat_low = 1;
					event("battery", "FAIL", "below 10%% (%s%%, %s mV, %s)", pct, mv, bst);
				} else if (c > 15) {
					bat_low = 0;
				}
			}
		}
		snprintf(line + strlen(line), sizeof(line) - strlen(line), ",%s,%s,%s,%s", pct, mv, ma, bst);
	}
	frontend_state();
	game_track();
	{
		char c[300], t[600];

		csv(c, sizeof(c), fe_core);
		csv(t, sizeof(t), fe_content);
		snprintf(line + strlen(line), sizeof(line) - strlen(line), ",%s,%s,%s,%s,%s", fe_state, c, t, fps,
			 *game_key ? game_nominal : "");
	}
	{
		char u[64];

		if (!strcmp(fe_state, "launcher")) {
			proc_usage(&w_ui, u, sizeof(u));
			snprintf(line + strlen(line), sizeof(line) - strlen(line), ",%s", u);
		} else {
			snprintf(line + strlen(line), sizeof(line) - strlen(line), ",,");
		}
		if (lume) {
			proc_usage(&w_run, u, sizeof(u));
			snprintf(line + strlen(line), sizeof(line) - strlen(line), ",%s", u);
		} else {
			snprintf(line + strlen(line), sizeof(line) - strlen(line), ",,");
		}
		proc_usage(&w_in, u, sizeof(u));
		snprintf(line + strlen(line), sizeof(line) - strlen(line), ",%s\n", u);
	}
	path(p, sizeof(p), "%s/metrics.pending", logs_ram);
	append(p, line, 0644);
	trace_sample();
	usb_watch();
}

/* ---------------------------------------------------------------- kernel messages */

static int kmsg_fd = -1;
static long long kmsg_last = -1, kmsg_min;

static void kmsg_open(void)
{
	kmsg_fd = open(kmsg_dev, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
}

/* every record available now: "prio,seq,usec,flags;text" -> "k [  12.345678] text" */
static void kmsg_drain(void)
{
	char r[8192];

	if (kmsg_fd < 0)
		return;
	for (;;) {
		ssize_t n = read(kmsg_fd, r, sizeof(r) - 1);
		char *semi, *nl, *a, *b;
		long long seq, us;

		if (n < 0) {
			if (errno == EPIPE)
				continue;  /* records overwritten before we read them: go on */
			if (errno == EINVAL || errno == EAGAIN || errno == EINTR)
				return;
			return;
		}
		if (n == 0) {
			/* a regular file (tests): read it again from the start next time */
			lseek(kmsg_fd, 0, SEEK_SET);
			return;
		}
		r[n] = 0;
		/* a regular file may hold several records: one per line, continuation lines skipped */
		for (a = r; a && *a; a = nl ? nl + 1 : NULL) {
			nl = strchr(a, '\n');
			if (nl)
				*nl = 0;
			if (*a == ' ' || !*a)
				continue;
			if (!(semi = strchr(a, ';')))
				continue;
			b = strchr(a, ',');
			if (!b || b > semi)
				continue;
			seq = strtoll(b + 1, &b, 10);
			if (*b != ',')
				continue;
			us = strtoll(b + 1, NULL, 10);
			if (seq <= kmsg_last)
				continue;
			kmsg_last = seq;
			if (us < kmsg_min)
				continue;
			trace("k [%5lld.%06lld] %s", us / 1000000, us % 1000000, semi + 1);
		}
	}
}

/* ---------------------------------------------------------------- loop */

static void logs_conf(void)
{
	FILE *f = fopen(logs_conf_path, "re");
	char l[256];

	log_enable = 1;
	log_interval = 5;
	log_flush = 60;
	if (!f)
		return;
	while (fgets(l, sizeof(l), f)) {
		char k[64] = "", vs[64] = "", *e = strchr(l, '=');
		int v, i, j = 0;

		if (!e)
			continue;
		for (i = 0; l + i < e && j < 63; i++)
			if (l[i] != ' ' && l[i] != '\t')
				k[j++] = l[i];
		k[j] = 0;
		if (!*k || *k == '#')
			continue;
		for (j = 0, e++; *e && j < 63; e++)
			if (isdigit((unsigned char)*e))
				vs[j++] = *e;
		vs[j] = 0;
		if (!*vs)
			continue;
		v = atoi(vs);
		if (!strcmp(k, "enable"))
			log_enable = v != 0;
		else if (!strcmp(k, "interval") && v >= 1)
			log_interval = v;
		else if (!strcmp(k, "flush") && v >= 5)
			log_flush = v;
	}
	fclose(f);
}

static int cmd_run(void)
{
	struct sigaction sa;
	long next_ms, flush_at;
	long n = 0;

	memset(&sa, 0, sizeof(sa));
	sa.sa_handler = on_term;
	sigaction(SIGTERM, &sa, NULL);
	sigaction(SIGINT, &sa, NULL);
	signal(SIGPIPE, SIG_IGN);
	mkdir(logs_ram, 0755);
	logs_conf();
	if (log_enable) {
		discover();
		read_uptime();
		kmsg_min = (long long)up_cs * 10000;
		kmsg_open();
		kmsg_drain();
	}
	read_uptime();
	flush_at = up_cs / 100 + log_flush;
	next_ms = mono_ms();
	while (!stop_sig) {
		tz_follow();
		if (log_enable) {
			sample();
			kmsg_drain();
		}
		read_uptime();
		if (up_cs / 100 >= flush_at) {
			logs_flush();
			flush_at = up_cs / 100 + log_flush;
		}
		if (samples_max >= 0 && ++n >= samples_max)
			break;
		/* the wait: kernel messages as they arrive, a TERM ends it at once */
		next_ms += (long)log_interval * 1000;
		while (!stop_sig && !nowait) {
			long left = next_ms - mono_ms();
			struct pollfd pfd = { kmsg_fd, POLLIN, 0 };

			if (left <= 0)
				break;
			if (kmsg_fd >= 0 && poll(&pfd, 1, (int)left) > 0)
				kmsg_drain();
			else if (kmsg_fd < 0) {
				struct timespec ts = { left / 1000, (left % 1000) * 1000000L };

				nanosleep(&ts, NULL);
			}
		}
		if (mono_ms() - next_ms > (long)log_interval * 1000)
			next_ms = mono_ms();  /* a long stop (suspend): do not catch up */
	}
	kmsg_drain();
	logs_flush();
	return 0;
}

int main(int argc, char **argv)
{
	proc_root = env("PROC_ROOT", "/proc");
	sys_root = env("SYS_ROOT", "/sys");
	logs_ram = env("LOGS_RAM", "/run/lume/logs");
	logs_conf_path = env("LOGS_CONF", "/storage/system/etc/logs.conf");
	lume_status = env("LUME_STATUS", "/run/user/1000/lume/status");
	frontend_log = env("FRONTEND_LOG", "/var/log/frontend.log");
	interrupts_file = env("INTERRUPTS_FILE", "/proc/interrupts");
	irq_sys = env("IRQ_SYS", "/sys/kernel/irq");
	dri_dir = env("DRI_DIR", "/dev/dri");
	asound_dir = env("ASOUND_DIR", "/proc/asound");
	devfreq_dir = env("GPU_DEVFREQ_DIR", "/sys/class/devfreq");
	kmsg_dev = env("KMSG_DEV", "/dev/kmsg");
	logd_cmd = env("LOGD_CMD", "/usr/libexec/lume/logd");
	frontends_dir = env("LUME_FRONTENDS", "/usr/libexec/lume/frontends/");
	tz_file = env("TIMEZONE_FILE", "/etc/timezone");
	zoneinfo_dir = env("ZONEINFO_DIR", "/usr/share/zoneinfo");
	ra_port = envi("RA_PORT", 55355);
	recover_max = envi("RECOVER_MAX", 3);
	kick_max = envi("KICK_MAX", 5);
	hang_limit = envi("HANG_LIMIT", 2);
	samples_max = envi("LOGD_SAMPLES", -1);
	nowait = envi("LOGD_NOWAIT", 0);
	if (argc == 2 && !strcmp(argv[1], "run"))
		return cmd_run();
	fprintf(stderr, "usage: " PROG " run\n");
	return 2;
}
