/*
 * r36os-powerctl: CPU frequency by the load of the game (openspec game-governor D12) and, with
 * --mode auto, CPU and GPU by the bottleneck of the game (D17, see run_auto below).
 *
 * Started by the r36os-power service when a game profile has controller=load|auto, stopped with
 * SIGTERM at the end of the game. It puts cpu0's policy in the `userspace` governor and picks
 * the frequency itself through scaling_setspeed:
 *
 * - every 250 ms it reads utime+stime of every thread of every process of the game cgroup
 *   (/proc/<pid>/task/<tid>/stat) and takes the busiest thread: the load is that thread's CPU
 *   time over the interval, in percent of one core. The "main process" of the game is thus the
 *   process that owns the busiest thread; lume-run execs the runner directly in the cgroup, so
 *   it is the runner (RetroArch or a standalone emulator), and a helper process that sleeps
 *   never wins;
 * - one step of the frequency table up after the load stayed above 85% for 1 s, one step down
 *   after it stayed below 50% for 3 s; any sample outside the band restarts that timer, and a
 *   step restarts both;
 * - always inside the profile [min, max] and never above the current scaling_max_freq, which
 *   the kernel's thermal cooling lowers (read on every tick);
 * - it starts at the highest allowed step (the game is loading) and stays there until the game
 *   cgroup has a process;
 * - it runs at nice -10, above the game (nice -5, D13), so a game that fills every core does
 *   not starve the sampling.
 *
 * The game cgroup is the newest <cgroup>/game-* directory (mtime, then the higher number);
 * lume-run creates it before it sends `game` to the service. The controller ends with the game:
 * when that cgroup is gone or empty. At the end it prints one line on stdout with the time
 * spent at each step, the number of steps up and down and why it ended:
 *
 *   1008000=12.5s 912000=3.0s up=2 down=3 end=game
 *
 * end= game (the cgroup emptied), stop (SIGTERM/SIGINT), no-game (no process in the cgroup in
 * --wait ms), owner (the --owner process is gone), governor (someone else changed the
 * governor: exit 4). Refusal at start (no userspace governor, no frequency table, no step in
 * [min, max]): a message on stderr and exit 3, nothing changed. Usage error: exit 2.
 *
 * usage: r36os-powerctl [--min KHZ] [--max KHZ] [--sys DIR] [--proc DIR] [--cgroup DIR]
 *                       [--owner PID] [--interval MS] [--up PCT] [--up-time MS]
 *                       [--down PCT] [--down-time MS] [--wait MS] [--fake-clock]
 *
 * Defaults: min = scaling_min_freq (the service already wrote the profile min, game floor
 * included), max = cpuinfo_max_freq, --sys /sys (or $PP_SYS), --proc /proc, --cgroup
 * /sys/fs/cgroup/lume (or $LUME_CGROUP), 250 ms, 85% for 1000 ms, 50% for 3000 ms, wait
 * 10000 ms.
 *
 * --fake-clock (tests): instead of sleeping, each tick reads one line "<ms>" from stdin (the
 * time that passed) and prints "tick <now_ms> <load%|-> <khz>" after it; end of stdin = stop.
 */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define PROG "r36os-powerctl"
#define MAX_STEPS 64
#define MAX_THREADS 1024
#define MAX_PIDS 256

static volatile sig_atomic_t stop_sig;

static void on_signal(int s)
{
	(void)s;
	stop_sig = 1;
}

/* ---- small file helpers ---- */

/* a path in a fixed buffer; a path too long is cut and then simply fails to open */
static void mkpath(char *out, size_t len, const char *fmt, ...)
{
	va_list ap;

	va_start(ap, fmt);
	vsnprintf(out, len, fmt, ap);
	va_end(ap);
}

static int read_text(const char *path, char *buf, size_t len)
{
	int fd = open(path, O_RDONLY | O_CLOEXEC);
	ssize_t n;

	if (fd < 0)
		return -1;
	n = read(fd, buf, len - 1);
	close(fd);
	if (n < 0)
		return -1;
	buf[n] = 0;
	return (int)n;
}

static long read_long(const char *path)
{
	char buf[64];

	if (read_text(path, buf, sizeof(buf)) <= 0)
		return -1;
	return strtol(buf, NULL, 10);
}

static int write_text(const char *path, const char *val)
{
	int fd = open(path, O_WRONLY | O_TRUNC | O_CLOEXEC);
	size_t len = strlen(val);
	ssize_t n;

	if (fd < 0)
		return -1;
	n = write(fd, val, len);
	close(fd);
	return n == (ssize_t)len ? 0 : -1;
}

/* ---- configuration ---- */

static const char *sys_root = "/sys";
static const char *proc_root = "/proc";
static const char *cg_root = "/sys/fs/cgroup/lume";
static long opt_min = -1, opt_max = -1, owner = -1;
static long interval_ms = 250, up_pct = 85, up_time = 1000, down_pct = 50, down_time = 3000;
static long wait_ms = 10000;
static int fake_clock;

static char cf[512]; /* cpu0 cpufreq directory */

static void cf_path(char *out, size_t len, const char *name)
{
	mkpath(out, len, "%s/%s", cf, name);
}

static long cf_long(const char *name)
{
	char p[600];

	cf_path(p, sizeof(p), name);
	return read_long(p);
}

/* ---- clock ---- */

static long long now_ms;

static long long mono_ms(void)
{
	struct timespec ts;

	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (long long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

/* waits one interval; 0 when the controller must stop */
static int tick_wait(void)
{
	if (fake_clock) {
		char line[64] = "";

		if (stop_sig || !fgets(line, sizeof(line), stdin))
			return 0;
		now_ms += strtol(line, NULL, 10);
		return !stop_sig;
	}
	{
		struct timespec ts = { interval_ms / 1000, (interval_ms % 1000) * 1000000L };

		if (!stop_sig)
			nanosleep(&ts, NULL);
	}
	now_ms = mono_ms();
	return !stop_sig;
}

/* ---- the game cgroup ---- */

static char game_cg[512]; /* locked once it had a process */

/* newest <cg_root>/game-* by mtime, then by number; 0 when none */
static int newest_game(char *out, size_t len)
{
	DIR *d = opendir(cg_root);
	struct dirent *e;
	long long best_t = -1;
	long best_n = -1;
	char p[768];
	struct stat st;

	if (!d)
		return 0;
	while ((e = readdir(d))) {
		long n;
		long long t;
		char *end;

		if (strncmp(e->d_name, "game-", 5))
			continue;
		n = strtol(e->d_name + 5, &end, 10);
		if (*end || end == e->d_name + 5)
			continue;
		mkpath(p, sizeof(p), "%s/%s", cg_root, e->d_name);
		if (stat(p, &st) || !S_ISDIR(st.st_mode))
			continue;
		t = (long long)st.st_mtim.tv_sec * 1000000000LL + st.st_mtim.tv_nsec;
		if (t > best_t || (t == best_t && n > best_n)) {
			best_t = t;
			best_n = n;
			mkpath(out, len, "%s", p);
		}
	}
	closedir(d);
	return best_n >= 0;
}

/* pids of cgroup.procs of dir; -1 when unreadable (the cgroup is gone) */
static int cg_pids(const char *dir, long *pids, int max)
{
	char p[600], buf[4096], *s, *end;
	int n = 0;

	mkpath(p, sizeof(p), "%s/cgroup.procs", dir);
	if (read_text(p, buf, sizeof(buf)) < 0)
		return -1;
	for (s = buf; n < max; s = end) {
		long v = strtol(s, &end, 10);

		if (end == s)
			break;
		if (v > 0)
			pids[n++] = v;
	}
	return n;
}

/* ---- load of the busiest thread ---- */

struct thread {
	long tid;
	unsigned long long ticks;
};

static struct thread prev[MAX_THREADS], cur[MAX_THREADS];
static int nprev, ncur, have_prev;
static long long prev_ms;
static long clk_tck;

/* utime + stime of /proc/<pid>/task/<tid>/stat */
static int thread_ticks(long pid, const char *tid, unsigned long long *out)
{
	char p[600], buf[1024], *s;
	unsigned long long ut, st;
	int i;

	mkpath(p, sizeof(p), "%s/%ld/task/%s/stat", proc_root, pid, tid);
	if (read_text(p, buf, sizeof(buf)) <= 0)
		return -1;
	s = strrchr(buf, ')');
	if (!s)
		return -1;
	s++;
	/* after "(comm)": state is field 0, utime field 11, stime field 12 */
	for (i = 0; i < 11 && s; i++) {
		s = strchr(s + 1, ' ');
	}
	if (!s || sscanf(s, " %llu %llu", &ut, &st) != 2)
		return -1;
	*out = ut + st;
	return 0;
}

static void sample_pid(long pid)
{
	char p[600];
	DIR *d;
	struct dirent *e;

	mkpath(p, sizeof(p), "%s/%ld/task", proc_root, pid);
	d = opendir(p);
	if (!d)
		return;
	while ((e = readdir(d)) && ncur < MAX_THREADS) {
		unsigned long long t;

		if (e->d_name[0] < '0' || e->d_name[0] > '9')
			continue;
		if (thread_ticks(pid, e->d_name, &t))
			continue;
		cur[ncur].tid = strtol(e->d_name, NULL, 10);
		cur[ncur].ticks = t;
		ncur++;
	}
	closedir(d);
}

/* load in percent of one core of the busiest thread since the previous sample; -1 = none */
static long busiest_load(const long *pids, int npids)
{
	unsigned long long best = 0;
	long long dt = now_ms - prev_ms;
	int i, j, seen = 0;
	long load = -1;

	ncur = 0;
	for (i = 0; i < npids; i++)
		sample_pid(pids[i]);
	if (have_prev && dt > 0) {
		for (i = 0; i < ncur; i++) {
			for (j = 0; j < nprev; j++) {
				if (prev[j].tid != cur[i].tid)
					continue;
				if (cur[i].ticks >= prev[j].ticks && cur[i].ticks - prev[j].ticks > best)
					best = cur[i].ticks - prev[j].ticks;
				seen = 1;
				break;
			}
		}
		if (seen)
			load = (long)(best * 100000ULL / ((unsigned long long)clk_tck * (unsigned long long)dt));
	}
	memcpy(prev, cur, sizeof(cur[0]) * (size_t)ncur);
	nprev = ncur;
	have_prev = 1;
	prev_ms = now_ms;
	return load;
}

/* ---- frequency table ---- */

static long steps[MAX_STEPS];
static long long step_ms[MAX_STEPS];
static int nsteps;

static int cmp_long(const void *a, const void *b)
{
	long x = *(const long *)a, y = *(const long *)b;

	return (x > y) - (x < y);
}

static int load_steps(long lo, long hi)
{
	char p[600], buf[2048], *s, *end;
	long all[MAX_STEPS];
	int n = 0, i;

	cf_path(p, sizeof(p), "scaling_available_frequencies");
	if (read_text(p, buf, sizeof(buf)) <= 0)
		return 0;
	for (s = buf; n < MAX_STEPS; s = end) {
		long v = strtol(s, &end, 10);

		if (end == s)
			break;
		all[n++] = v;
	}
	qsort(all, (size_t)n, sizeof(all[0]), cmp_long);
	nsteps = 0;
	for (i = 0; i < n; i++)
		if (all[i] >= lo && all[i] <= hi && (nsteps == 0 || steps[nsteps - 1] != all[i]))
			steps[nsteps++] = all[i];
	return nsteps;
}

/* highest step <= cap (the lowest step when the cap is under all of them) */
static int cap_index(long cap)
{
	int i;

	if (cap <= 0)
		return nsteps - 1;
	for (i = nsteps - 1; i > 0; i--)
		if (steps[i] <= cap)
			return i;
	return 0;
}

static int has_word(const char *text, const char *word)
{
	size_t len = strlen(word);
	const char *s = text;

	while ((s = strstr(s, word))) {
		if ((s == text || s[-1] == ' ' || s[-1] == '\n') &&
		    (s[len] == 0 || s[len] == ' ' || s[len] == '\n'))
			return 1;
		s += len;
	}
	return 0;
}

static void usage(void)
{
	fprintf(stderr,
		"usage: " PROG " [--mode load|auto] [--min KHZ] [--max KHZ] [--sys DIR] [--proc DIR]\n"
		"                      [--cgroup DIR] [--owner PID] [--interval MS] [--up PCT]\n"
		"                      [--up-time MS] [--down PCT] [--down-time MS] [--wait MS]\n"
		"                      [--gpu DIR] [--gpu-min HZ] [--gpu-max HZ] [--state FILE]\n"
		"                      [--fake-clock]\n");
	exit(2);
}

/* ==== bottleneck controller (--mode auto, openspec game-governor D17) ====================
 *
 * One decision per window (--interval, 1000 ms by default in this mode). Signals:
 * - cpu: the busiest thread of the game cgroup, percent of one core (as in the load mode);
 * - gpu: for every DRM file the game has open (/proc/<pid>/fd -> /dev/dri/..., found again
 *   every 2 s), the drm-engine-<name> times of its fdinfo; one client opened twice counts
 *   once (drm-client-id). Busy = the busiest engine's time over the window, in percent;
 * - frames: the sum of drm-page-flips of those clients over the window (kernel patch 0036);
 *   the target is the highest rate of the last 30 windows; a drop is a window below 90% of
 *   it (only with a target of at least 20 fps and 5 windows of history);
 * - thermal: scaling_max_freq of the CPU and max_freq of the GPU devfreq (the kernel lowers
 *   them); never written above;
 * - memory: MemAvailable and CmaFree of /proc/meminfo, diagnosis only (D19).
 * Rules, one step per window and resource:
 *   1. a saturated resource (busy > --up) goes up;
 *   2. a frame drop with no saturated resource raises the busier one that can still rise
 *      (bottleneck "pacing");
 *   3. a resource below --down for --down-time, with no drop and no step up in the last 5 s,
 *      goes down;
 *   4. never above the thermal caps ("thermal" when a saturated or dropping game is held
 *      under a cap below the top of the range).
 * A resource whose range has a single step is not controlled: the CPU then keeps its governor
 * (the profile pinned it), the GPU keeps its min_freq. The CPU runs on the userspace governor
 * (scaling_setspeed); the GPU through the min_freq floor of its devfreq (simple_ondemand stays
 * free above it), given back at the end.
 */

#define MAX_FDS 32
#define MAX_CLIENTS 16
#define MAX_ENGINES 4
#define HIST 30

static int mode_auto;
static const char *gpu_dir_opt;
static long opt_gmin = -1, opt_gmax = -1;
static const char *state_file;

struct drmfd {
	long pid;
	int fd;
};

struct client {
	unsigned long long id, flips;
	int have_flips, nengines;
	char eng[MAX_ENGINES][24];
	unsigned long long ns[MAX_ENGINES];
};

static struct drmfd drmfds[MAX_FDS];
static int ndrmfds;
static long long drm_scan_ms = -1000000;
static struct client cl_prev[MAX_CLIENTS], cl_cur[MAX_CLIENTS];
static int ncl_prev, ncl_cur, have_cl_prev;

static void drm_scan(const long *pids, int npids)
{
	char p[600], link[256];
	int i;

	ndrmfds = 0;
	for (i = 0; i < npids && ndrmfds < MAX_FDS; i++) {
		DIR *d;
		struct dirent *e;

		mkpath(p, sizeof(p), "%s/%ld/fd", proc_root, pids[i]);
		d = opendir(p);
		if (!d)
			continue;
		while ((e = readdir(d)) && ndrmfds < MAX_FDS) {
			ssize_t n;
			char lp[700];

			if (e->d_name[0] < '0' || e->d_name[0] > '9')
				continue;
			mkpath(lp, sizeof(lp), "%s/%s", p, e->d_name);
			n = readlink(lp, link, sizeof(link) - 1);
			if (n <= 0)
				continue;
			link[n] = 0;
			if (strncmp(link, "/dev/dri/", 9))
				continue;
			drmfds[ndrmfds].pid = pids[i];
			drmfds[ndrmfds].fd = (int)strtol(e->d_name, NULL, 10);
			ndrmfds++;
		}
		closedir(d);
	}
}

/* fdinfo of every DRM fd -> cl_cur (one entry per drm-client-id) */
static void drm_sample(void)
{
	char p[600], buf[2048];
	int i;

	ncl_cur = 0;
	for (i = 0; i < ndrmfds; i++) {
		struct client c;
		char *line, *save = NULL;
		int have_id = 0, j, dup = 0;

		mkpath(p, sizeof(p), "%s/%ld/fdinfo/%d", proc_root, drmfds[i].pid, drmfds[i].fd);
		if (read_text(p, buf, sizeof(buf)) <= 0)
			continue;
		memset(&c, 0, sizeof(c));
		for (line = strtok_r(buf, "\n", &save); line; line = strtok_r(NULL, "\n", &save)) {
			char *v = strchr(line, ':');

			if (!v)
				continue;
			*v++ = 0;
			if (!strcmp(line, "drm-client-id")) {
				c.id = strtoull(v, NULL, 10);
				have_id = 1;
			} else if (!strcmp(line, "drm-page-flips")) {
				c.flips = strtoull(v, NULL, 10);
				c.have_flips = 1;
			} else if (!strncmp(line, "drm-engine-", 11) && c.nengines < MAX_ENGINES &&
				   strncmp(line + 11, "capacity", 8)) {
				snprintf(c.eng[c.nengines], sizeof(c.eng[0]), "%s", line + 11);
				c.ns[c.nengines] = strtoull(v, NULL, 10);
				c.nengines++;
			}
		}
		if (!have_id)
			c.id = 1000000000ULL + (unsigned long long)i; /* no id: never merged */
		for (j = 0; j < ncl_cur; j++)
			if (cl_cur[j].id == c.id)
				dup = 1;
		if (!dup && ncl_cur < MAX_CLIENTS)
			cl_cur[ncl_cur++] = c;
	}
}

static const struct client *cl_find(unsigned long long id)
{
	int i;

	for (i = 0; i < ncl_prev; i++)
		if (cl_prev[i].id == id)
			return &cl_prev[i];
	return NULL;
}

/* deltas since the previous sample: frames (-1 when no client reports page flips) and the
 * busiest engine's time in ns (-1 when no client reports engines) */
static void drm_deltas(long long *frames, long long *busy_ns)
{
	char names[MAX_CLIENTS * MAX_ENGINES][24];
	unsigned long long sums[MAX_CLIENTS * MAX_ENGINES];
	int nnames = 0, i, k, any_flips = 0, any_eng = 0;
	unsigned long long fl = 0, best = 0;

	for (i = 0; i < ncl_cur; i++) {
		const struct client *c = &cl_cur[i], *o = have_cl_prev ? cl_find(c->id) : NULL;

		if (!o)
			continue;
		if (c->have_flips && o->have_flips) {
			any_flips = 1;
			if (c->flips >= o->flips)
				fl += c->flips - o->flips;
		}
		for (k = 0; k < c->nengines; k++) {
			int m, n;
			unsigned long long d = 0;

			for (m = 0; m < o->nengines; m++)
				if (!strcmp(o->eng[m], c->eng[k]) && c->ns[k] >= o->ns[m])
					d = c->ns[k] - o->ns[m];
			any_eng = 1;
			for (n = 0; n < nnames; n++)
				if (!strcmp(names[n], c->eng[k]))
					break;
			if (n == nnames) {
				snprintf(names[n], sizeof(names[0]), "%s", c->eng[k]);
				sums[n] = 0;
				nnames++;
			}
			sums[n] += d;
		}
	}
	for (i = 0; i < nnames; i++)
		if (sums[i] > best)
			best = sums[i];
	*frames = any_flips ? (long long)fl : -1;
	*busy_ns = any_eng ? (long long)best : -1;
	memcpy(cl_prev, cl_cur, sizeof(cl_cur[0]) * (size_t)ncl_cur);
	ncl_prev = ncl_cur;
	have_cl_prev = 1;
}

/* MemAvailable and CmaFree in kB (-1 when missing) */
static void meminfo(long *avail, long *cma)
{
	char p[600], buf[4096], *s;

	*avail = *cma = -1;
	mkpath(p, sizeof(p), "%s/meminfo", proc_root);
	if (read_text(p, buf, sizeof(buf)) <= 0)
		return;
	if ((s = strstr(buf, "MemAvailable:")))
		*avail = strtol(s + 13, NULL, 10);
	if ((s = strstr(buf, "CmaFree:")))
		*cma = strtol(s + 8, NULL, 10);
}

/* GPU steps of the devfreq table inside [lo, hi] */
static long gsteps[MAX_STEPS];
static long long gstep_ms[MAX_STEPS];
static int ngsteps;
static char gdir[512];

static int load_gsteps(long lo, long hi)
{
	char p[600], buf[2048], *s, *end;
	long all[MAX_STEPS];
	int n = 0, i;

	ngsteps = 0;
	mkpath(p, sizeof(p), "%s/available_frequencies", gdir);
	if (read_text(p, buf, sizeof(buf)) <= 0)
		return 0;
	for (s = buf; n < MAX_STEPS; s = end) {
		long v = strtol(s, &end, 10);

		if (end == s)
			break;
		all[n++] = v;
	}
	qsort(all, (size_t)n, sizeof(all[0]), cmp_long);
	for (i = 0; i < n; i++)
		if ((lo < 0 || all[i] >= lo) && (hi < 0 || all[i] <= hi) &&
		    (ngsteps == 0 || gsteps[ngsteps - 1] != all[i]))
			gsteps[ngsteps++] = all[i];
	return ngsteps;
}

static int gcap_index(long cap)
{
	int i;

	if (cap <= 0)
		return ngsteps - 1;
	for (i = ngsteps - 1; i > 0; i--)
		if (gsteps[i] <= cap)
			return i;
	return 0;
}

static long gdir_long(const char *name)
{
	char p[600];

	mkpath(p, sizeof(p), "%s/%s", gdir, name);
	return read_long(p);
}

/* first devfreq device with a frequency table (the GPU on both consoles) */
static int find_gpu_dir(void)
{
	char p[600];
	DIR *d;
	struct dirent *e;
	struct stat st;

	if (gpu_dir_opt) {
		mkpath(gdir, sizeof(gdir), "%s", gpu_dir_opt);
		mkpath(p, sizeof(p), "%s/available_frequencies", gdir);
		return !stat(p, &st);
	}
	mkpath(p, sizeof(p), "%s/class/devfreq", sys_root);
	d = opendir(p);
	if (!d)
		return 0;
	while ((e = readdir(d))) {
		char q[800];

		if (e->d_name[0] == '.')
			continue;
		mkpath(q, sizeof(q), "%s/%s/available_frequencies", p, e->d_name);
		if (!stat(q, &st)) {
			mkpath(gdir, sizeof(gdir), "%s/%s", p, e->d_name);
			closedir(d);
			return 1;
		}
	}
	closedir(d);
	return 0;
}

enum { B_NONE, B_CPU, B_GPU, B_PACING, B_THERMAL, B_MEMORY, B_SYNC, B_N };
static const char *bname[B_N] = { "none", "cpu", "gpu", "pacing", "thermal", "memory", "sync" };

static void write_state(long ckhz, long load, long ghz, long gbusy, long fps10, long target10,
			int b, long avail)
{
	char tmp[600], text[512];
	int fd, n;

	if (!state_file)
		return;
	n = snprintf(text, sizeof(text),
		     "mode auto\ncpu_khz %ld\ncpu_load %ld\ngpu_hz %ld\ngpu_busy %ld\n"
		     "fps %ld.%ld\nfps_target %ld.%ld\nbottleneck %s\nmem_avail_kb %ld\n",
		     ckhz, load, ghz, gbusy, fps10 < 0 ? -1 : fps10 / 10, fps10 < 0 ? 0 : fps10 % 10,
		     target10 / 10, target10 % 10, bname[b], avail);
	mkpath(tmp, sizeof(tmp), "%s.tmp", state_file);
	fd = open(tmp, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
	if (fd < 0)
		return;
	if (write(fd, text, (size_t)n) != n) {
		close(fd);
		unlink(tmp);
		return;
	}
	close(fd);
	rename(tmp, state_file);
}

static void auto_summary(int ups, int downs, const int *bcount, long mem_min, const char *end)
{
	int i;

	printf("cpu:");
	for (i = nsteps - 1; i >= 0; i--)
		if (step_ms[i] > 0)
			printf(" %ld=%lld.%llds", steps[i], step_ms[i] / 1000, step_ms[i] % 1000 / 100);
	printf(" gpu:");
	for (i = ngsteps - 1; i >= 0; i--)
		if (gstep_ms[i] > 0)
			printf(" %ld=%lld.%llds", gsteps[i], gstep_ms[i] / 1000, gstep_ms[i] % 1000 / 100);
	printf(" up=%d down=%d bottleneck", ups, downs);
	for (i = B_CPU; i < B_N; i++)
		printf(" %s=%d", bname[i], bcount[i]);
	if (mem_min >= 0)
		printf(" mem_min=%ldk", mem_min);
	printf(" end=%s\n", end);
	fflush(stdout);
}

static int run_auto(void)
{
	char p[600], buf[1024], val[32];
	long pids[MAX_PIDS], cwritten = -1, gwritten = -1, orig_gmin = -1, mem_min = -1;
	long hist[HIST];
	long long start_ms, last_ms, dt = 0, last_up_ms = -1000000;
	long long cslack = 0, gslack = 0;
	int nhist = 0, hpos = 0, cidx, gidx = 0, ups = 0, downs = 0, rc = 0, i, drops = 0;
	int cpu_ctl, gpu_ctl, have_gpu, bcount[B_N];
	const char *end = "stop";

	memset(bcount, 0, sizeof(bcount));
	/* CPU: controlled when the range has more than one step */
	cpu_ctl = nsteps > 1;
	if (cpu_ctl) {
		cf_path(p, sizeof(p), "scaling_available_governors");
		if (read_text(p, buf, sizeof(buf)) <= 0 || !has_word(buf, "userspace")) {
			fprintf(stderr, PROG ": refused: userspace governor not available\n");
			return 3;
		}
	}
	/* GPU */
	have_gpu = find_gpu_dir();
	if (have_gpu) {
		orig_gmin = gdir_long("min_freq");
		if (opt_gmin < 0)
			opt_gmin = orig_gmin;
		if (opt_gmax < 0)
			opt_gmax = gdir_long("max_freq");
		have_gpu = load_gsteps(opt_gmin, opt_gmax) > 0;
	}
	gpu_ctl = have_gpu && ngsteps > 1;

	if (setpriority(PRIO_PROCESS, 0, -10))
		errno = 0;
	if (cpu_ctl) {
		cf_path(p, sizeof(p), "scaling_governor");
		if (write_text(p, "userspace")) {
			fprintf(stderr, PROG ": refused: cannot select the userspace governor\n");
			return 3;
		}
	}
	now_ms = fake_clock ? 0 : mono_ms();
	start_ms = last_ms = now_ms;
	/* the game is loading: start at the top of each range under the caps */
	cidx = cap_index(cf_long("scaling_max_freq"));
	if (have_gpu)
		gidx = gcap_index(gdir_long("max_freq"));

	for (;;) {
		long load = -1, gbusy = -1, fps10 = -1, target10 = 0, avail, cma, ccap_khz, gcap_hz;
		long long frames = -1, busy_ns = -1;
		int npids = -1, capi, gcapi = 0, drop = 0, csat, gsat, b = B_NONE, raised = 0, sync = 0;

		if (owner > 0 && kill((pid_t)owner, 0) && errno == ESRCH) {
			end = "owner";
			break;
		}
		if (cpu_ctl && cwritten >= 0) {
			cf_path(p, sizeof(p), "scaling_governor");
			if (read_text(p, buf, sizeof(buf)) <= 0 || strncmp(buf, "userspace", 9)) {
				end = "governor";
				rc = 4;
				break;
			}
		}
		if (!game_cg[0]) {
			char cand[512];

			if (newest_game(cand, sizeof(cand)) && cg_pids(cand, pids, MAX_PIDS) > 0)
				mkpath(game_cg, sizeof(game_cg), "%s", cand);
			else if (now_ms - start_ms >= wait_ms) {
				end = "no-game";
				break;
			}
		}
		if (game_cg[0]) {
			npids = cg_pids(game_cg, pids, MAX_PIDS);
			if (npids <= 0) {
				end = "game";
				break;
			}
			load = busiest_load(pids, npids);
			if (now_ms - drm_scan_ms >= 2000) {
				drm_scan(pids, npids);
				drm_scan_ms = now_ms;
			}
			drm_sample();
			drm_deltas(&frames, &busy_ns);
		}
		if (dt > 0 && busy_ns >= 0)
			gbusy = (long)(busy_ns / 10000LL / dt); /* ns / (dt ms * 1e6) * 100 */
		if (dt > 0 && frames >= 0) {
			fps10 = (long)(frames * 10000LL / dt);
			hist[hpos] = fps10;
			hpos = (hpos + 1) % HIST;
			if (nhist < HIST)
				nhist++;
		}
		for (i = 0; i < nhist; i++)
			if (hist[i] > target10)
				target10 = hist[i];
		if (fps10 >= 0 && nhist >= 5 && target10 >= 200 && fps10 * 100 < target10 * 90)
			drop = 1;
		/* pacing needs two lost windows in a row: a 60 fps core on a 55.7 Hz panel beats
		 * between 53 and 55 frames a second on its own (GA36, threaded video) */
		drops = drop ? drops + 1 : 0;
		meminfo(&avail, &cma);
		if (avail >= 0 && (mem_min < 0 || avail < mem_min))
			mem_min = avail;

		/* caps */
		ccap_khz = cf_long("scaling_max_freq");
		capi = cap_index(ccap_khz);
		if (have_gpu) {
			gcap_hz = gdir_long("max_freq");
			gcapi = gcap_index(gcap_hz);
		}
		csat = cpu_ctl && load > up_pct;
		gsat = gpu_ctl && gbusy > up_pct;

		if (load >= 0 || gbusy >= 0) {
			/* rule 1: the saturated resource(s) */
			if (csat && cidx < capi) {
				cidx++;
				raised = 1;
			}
			if (gsat && gidx < gcapi) {
				gidx++;
				raised = 1;
			}
			if (csat || gsat)
				b = (csat && (!gsat || load >= gbusy)) ? B_CPU : B_GPU;
			/* rule 2: frames lost, nothing saturated, the busier one at least half busy: it
			 * rises (pacing). Frames lost with both resources mostly idle are not a clock
			 * problem (vsync, audio pacing, a panel slower than the core): "sync", no step
			 * up, and the slack rule may still lower what is left over. */
			sync = drop && !csat && !gsat && load < down_pct && gbusy < down_pct;
			if (sync)
				b = B_SYNC;
			if (drop && !csat && !gsat && !sync && drops >= 2) {
				int c_can = cpu_ctl && cidx < capi, g_can = gpu_ctl && gidx < gcapi;

				b = B_PACING;
				if (c_can && (!g_can || load >= gbusy)) {
					cidx++;
					raised = 1;
				} else if (g_can) {
					gidx++;
					raised = 1;
				}
			}
			/* rule 4: held under a thermal cap below the top of the range */
			if ((csat || gsat || drop) && !raised &&
			    ((cpu_ctl && capi < nsteps - 1 && cidx >= capi) ||
			     (gpu_ctl && gcapi < ngsteps - 1 && gidx >= gcapi)))
				b = B_THERMAL;
			if (raised) {
				ups++;
				last_up_ms = now_ms;
				cslack = gslack = 0;
			}
			/* rule 3: slack, never right after a step up or with frames lost to a clock */
			cslack = (!raised && (!drop || sync) && cpu_ctl && load >= 0 && load < down_pct) ? cslack + dt : 0;
			gslack = (!raised && (!drop || sync) && gpu_ctl && gbusy >= 0 && gbusy < down_pct) ? gslack + dt : 0;
			if (now_ms - last_up_ms >= 5000) {
				if (cslack >= down_time && cidx > 0) {
					cidx--;
					downs++;
					cslack = 0;
				}
				if (gslack >= down_time && gidx > 0) {
					gidx--;
					downs++;
					gslack = 0;
				}
			}
		}
		if (b == B_NONE && avail >= 0 && avail < 32 * 1024)
			b = B_MEMORY;
		if (b != B_NONE)
			bcount[b]++;
		if (cidx > capi)
			cidx = capi;
		if (have_gpu && gidx > gcapi)
			gidx = gcapi;

		if (cpu_ctl && steps[cidx] != cwritten) {
			snprintf(val, sizeof(val), "%ld", steps[cidx]);
			cf_path(p, sizeof(p), "scaling_setspeed");
			if (write_text(p, val))
				fprintf(stderr, PROG ": write scaling_setspeed %s failed\n", val);
			cwritten = steps[cidx];
		}
		if (gpu_ctl && gsteps[gidx] != gwritten) {
			snprintf(val, sizeof(val), "%ld", gsteps[gidx]);
			mkpath(p, sizeof(p), "%s/min_freq", gdir);
			if (write_text(p, val))
				fprintf(stderr, PROG ": write gpu min_freq %s failed\n", val);
			gwritten = gsteps[gidx];
		}
		write_state(cpu_ctl ? steps[cidx] : cf_long("scaling_cur_freq"), load,
			    have_gpu ? (gpu_ctl ? gsteps[gidx] : gdir_long("cur_freq")) : -1, gbusy, fps10,
			    target10, b, avail);
		if (fake_clock) {
			printf("tick %lld cpu=%ld gpu=%ld fps=%ld -> %ld %ld %s\n", now_ms, load, gbusy,
			       fps10 < 0 ? -1 : fps10 / 10, cpu_ctl ? steps[cidx] : -1L,
			       gpu_ctl ? gsteps[gidx] : -1L, bname[b]);
			fflush(stdout);
		}

		if (!tick_wait()) {
			if (cpu_ctl)
				step_ms[cidx] += now_ms - last_ms;
			if (gpu_ctl)
				gstep_ms[gidx] += now_ms - last_ms;
			end = "stop";
			break;
		}
		dt = now_ms - last_ms;
		if (cpu_ctl)
			step_ms[cidx] += dt;
		if (gpu_ctl)
			gstep_ms[gidx] += dt;
		last_ms = now_ms;
	}
	/* the GPU floor goes back to what the profile set */
	if (gpu_ctl && orig_gmin > 0) {
		snprintf(val, sizeof(val), "%ld", orig_gmin);
		mkpath(p, sizeof(p), "%s/min_freq", gdir);
		write_text(p, val);
	}
	if (state_file)
		unlink(state_file);
	auto_summary(ups, downs, bcount, mem_min, end);
	return rc;
}

static long num_arg(const char *s)
{
	char *end;
	long v = strtol(s, &end, 10);

	if (end == s || *end || v < 0)
		usage();
	return v;
}

static void summary(int ups, int downs, const char *end)
{
	int i;

	for (i = nsteps - 1; i >= 0; i--)
		if (step_ms[i] > 0)
			printf("%ld=%lld.%llds ", steps[i], step_ms[i] / 1000, step_ms[i] % 1000 / 100);
	printf("up=%d down=%d end=%s\n", ups, downs, end);
	fflush(stdout);
}

int main(int argc, char **argv)
{
	const char *env;
	char p[600], buf[1024], val[32];
	struct sigaction sa;
	long pids[MAX_PIDS], written = -1;
	long long up_acc = 0, down_acc = 0, start_ms, last_ms, dt = 0;
	int i, idx, ups = 0, downs = 0, rc = 0, interval_set = 0;
	const char *end = "stop";

	if ((env = getenv("PP_SYS")) && *env)
		sys_root = env;
	if ((env = getenv("LUME_CGROUP")) && *env)
		cg_root = env;
	for (i = 1; i < argc; i++) {
		const char *a = argv[i];

		if (!strcmp(a, "--fake-clock")) {
			fake_clock = 1;
			continue;
		}
		if (i + 1 >= argc)
			usage();
		if (!strcmp(a, "--mode")) {
			const char *m = argv[++i];

			if (!strcmp(m, "auto"))
				mode_auto = 1;
			else if (strcmp(m, "load"))
				usage();
		} else if (!strcmp(a, "--gpu"))
			gpu_dir_opt = argv[++i];
		else if (!strcmp(a, "--gpu-min"))
			opt_gmin = num_arg(argv[++i]);
		else if (!strcmp(a, "--gpu-max"))
			opt_gmax = num_arg(argv[++i]);
		else if (!strcmp(a, "--state"))
			state_file = argv[++i];
		else if (!strcmp(a, "--min"))
			opt_min = num_arg(argv[++i]);
		else if (!strcmp(a, "--max"))
			opt_max = num_arg(argv[++i]);
		else if (!strcmp(a, "--sys"))
			sys_root = argv[++i];
		else if (!strcmp(a, "--proc"))
			proc_root = argv[++i];
		else if (!strcmp(a, "--cgroup"))
			cg_root = argv[++i];
		else if (!strcmp(a, "--owner"))
			owner = num_arg(argv[++i]);
		else if (!strcmp(a, "--interval")) {
			interval_ms = num_arg(argv[++i]);
			interval_set = 1;
		}
		else if (!strcmp(a, "--up"))
			up_pct = num_arg(argv[++i]);
		else if (!strcmp(a, "--up-time"))
			up_time = num_arg(argv[++i]);
		else if (!strcmp(a, "--down"))
			down_pct = num_arg(argv[++i]);
		else if (!strcmp(a, "--down-time"))
			down_time = num_arg(argv[++i]);
		else if (!strcmp(a, "--wait"))
			wait_ms = num_arg(argv[++i]);
		else
			usage();
	}
	if (mode_auto && !interval_set)
		interval_ms = 1000;
	if (interval_ms < 10)
		usage();
	clk_tck = sysconf(_SC_CLK_TCK);
	if (clk_tck <= 0)
		clk_tck = 100;
	mkpath(cf, sizeof(cf), "%s/devices/system/cpu/cpu0/cpufreq", sys_root);

	if (mode_auto) {
		/* the CPU range; an empty one only means the CPU is not controlled */
		if (opt_min < 0)
			opt_min = cf_long("scaling_min_freq");
		if (opt_max < 0)
			opt_max = cf_long("cpuinfo_max_freq");
		if (opt_min >= 0 && opt_max >= 0)
			load_steps(opt_min, opt_max);
		memset(&sa, 0, sizeof(sa));
		sa.sa_handler = on_signal;
		sigaction(SIGTERM, &sa, NULL);
		sigaction(SIGINT, &sa, NULL);
		sigaction(SIGHUP, &sa, NULL);
		return run_auto();
	}

	/* refusals: nothing is changed */
	cf_path(p, sizeof(p), "scaling_available_governors");
	if (read_text(p, buf, sizeof(buf)) <= 0 || !has_word(buf, "userspace")) {
		fprintf(stderr, PROG ": refused: userspace governor not available\n");
		return 3;
	}
	if (opt_min < 0)
		opt_min = cf_long("scaling_min_freq");
	if (opt_max < 0)
		opt_max = cf_long("cpuinfo_max_freq");
	if (opt_min < 0 || opt_max < 0) {
		fprintf(stderr, PROG ": refused: no cpufreq limits\n");
		return 3;
	}
	if (!load_steps(opt_min, opt_max)) {
		fprintf(stderr, PROG ": refused: no frequency step in %ld..%ld kHz\n", opt_min, opt_max);
		return 3;
	}

	memset(&sa, 0, sizeof(sa));
	sa.sa_handler = on_signal; /* no SA_RESTART: a signal ends the sleep or the read */
	sigaction(SIGTERM, &sa, NULL);
	sigaction(SIGINT, &sa, NULL);
	sigaction(SIGHUP, &sa, NULL);

	/* above the game (nice -5, D13), like r36os-input; not allowed in the tests: ignored */
	if (setpriority(PRIO_PROCESS, 0, -10))
		errno = 0;
	cf_path(p, sizeof(p), "scaling_governor");
	if (write_text(p, "userspace")) {
		fprintf(stderr, PROG ": refused: cannot select the userspace governor\n");
		return 3;
	}
	now_ms = fake_clock ? 0 : mono_ms();
	start_ms = last_ms = now_ms;
	idx = cap_index(cf_long("scaling_max_freq"));

	for (;;) {
		long load = -1;
		int npids = -1, capi;

		if (owner > 0 && kill((pid_t)owner, 0) && errno == ESRCH) {
			end = "owner";
			break;
		}
		cf_path(p, sizeof(p), "scaling_governor");
		if (written >= 0 && (read_text(p, buf, sizeof(buf)) <= 0 || strncmp(buf, "userspace", 9))) {
			end = "governor";
			rc = 4;
			break;
		}

		/* the game */
		if (!game_cg[0]) {
			char cand[512];

			if (newest_game(cand, sizeof(cand)) && cg_pids(cand, pids, MAX_PIDS) > 0)
				mkpath(game_cg, sizeof(game_cg), "%s", cand);
			else if (now_ms - start_ms >= wait_ms) {
				end = "no-game";
				break;
			}
		}
		if (game_cg[0]) {
			npids = cg_pids(game_cg, pids, MAX_PIDS);
			if (npids <= 0) {
				end = "game";
				break;
			}
			load = busiest_load(pids, npids);
		}

		/* the decision: one step at a time, never above the thermal cap */
		capi = cap_index(cf_long("scaling_max_freq"));
		if (load >= 0) {
			/* no credit for going up while already at the top or under the cap */
			up_acc = load > up_pct && idx < capi && idx < nsteps - 1 ? up_acc + dt : 0;
			down_acc = load < down_pct ? down_acc + dt : 0;
			if (up_acc >= up_time && idx < capi && idx < nsteps - 1) {
				idx++;
				ups++;
				up_acc = down_acc = 0;
			} else if (down_acc >= down_time && idx > 0) {
				idx--;
				downs++;
				up_acc = down_acc = 0;
			}
		}
		if (idx > capi)
			idx = capi;
		if (steps[idx] != written) {
			snprintf(val, sizeof(val), "%ld", steps[idx]);
			cf_path(p, sizeof(p), "scaling_setspeed");
			if (write_text(p, val))
				fprintf(stderr, PROG ": write scaling_setspeed %s failed\n", val);
			written = steps[idx];
		}
		if (fake_clock) {
			if (load >= 0)
				printf("tick %lld %ld %ld\n", now_ms, load, written);
			else
				printf("tick %lld - %ld\n", now_ms, written);
			fflush(stdout);
		}

		/* the next interval, spent at steps[idx] */
		if (!tick_wait()) {
			step_ms[idx] += now_ms - last_ms;
			end = "stop";
			break;
		}
		dt = now_ms - last_ms;
		step_ms[idx] += dt;
		last_ms = now_ms;
	}
	summary(ups, downs, end);
	return rc;
}
