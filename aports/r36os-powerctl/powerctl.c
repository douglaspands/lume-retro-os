/*
 * r36os-powerctl: CPU frequency by the load of the game (openspec game-governor D12).
 *
 * Started by the r36os-power service when a game profile has controller=load, stopped with
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
		char line[64];

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
		"usage: " PROG " [--min KHZ] [--max KHZ] [--sys DIR] [--proc DIR] [--cgroup DIR]\n"
		"                      [--owner PID] [--interval MS] [--up PCT] [--up-time MS]\n"
		"                      [--down PCT] [--down-time MS] [--wait MS] [--fake-clock]\n");
	exit(2);
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
	int i, idx, ups = 0, downs = 0, rc = 0;
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
		if (!strcmp(a, "--min"))
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
		else if (!strcmp(a, "--interval"))
			interval_ms = num_arg(argv[++i]);
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
	if (interval_ms < 10)
		usage();
	clk_tck = sysconf(_SC_CLK_TCK);
	if (clk_tck <= 0)
		clk_tck = 100;
	mkpath(cf, sizeof(cf), "%s/devices/system/cpu/cpu0/cpufreq", sys_root);

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
