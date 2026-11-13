// SPDX-License-Identifier: GPL-2.0-or-later
/*
 * lume-bootsel: device tree selection in the initramfs of Lume Retro OS
 * (openspec change boot-dtb-select, design D1 to D7).
 *
 * The factory bootloader always starts the kernel with the default device tree of the SoC.
 * This tool looks at BOOT/dtbs/<soc>/, decides which device tree describes the hardware
 * and, when it is not the running one, prepares it and loads the same kernel with it
 * through kexec_load (kexec -l); the init then unmounts everything and runs kexec -e.
 *
 * Decision order: BOOT/dtbs/force; the list on the screen (selection key held at power
 * on); back to the last device tree that reached the frontend; the choice saved from the
 * list; the rules of the candidates (read-only probes); the default.
 *
 * Exit status: 0 keep booting with the running device tree; 10 a kernel is loaded, the
 * init must run kexec -e; 2 bad usage.
 *
 * --root DIR prefixes every path (/proc/device-tree, /sys, /dev, /etc, BOOT and ROMS), so
 * the tests run it on the PC against a fake tree; there a device node that is a regular
 * file is read as a description of the device (see the tests).
 */

#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#include <linux/gpio.h>
#include <linux/i2c-dev.h>
#include <linux/input.h>

#include <libfdt.h>

#define EXIT_KEXEC 10
#define MAX_CAND 32
#define MAX_ROWS 8
#define ID_LEN 64
#define LIST_LEN 512
#define MENU_IDLE_MS 60000
#define KEY_WAIT_MS 1000

/* --- options and paths ------------------------------------------------------------- */

static const char *opt_root = "";
static const char *opt_boot = "/boot";
static const char *opt_roms;
static const char *opt_kernel;
static const char *opt_kexec = "/bin/kexec";
static const char *opt_out;
static int opt_dry_run;

/* path under --root; returns a static buffer from a small ring */
static const char *rp(const char *fmt, ...)
{
	static char ring[8][PATH_MAX];
	static int next;
	char *out = ring[next++ % 8];
	char rel[PATH_MAX];
	va_list ap;

	va_start(ap, fmt);
	vsnprintf(rel, sizeof(rel), fmt, ap);
	va_end(ap);
	snprintf(out, PATH_MAX, "%s%s", opt_root, rel);
	return out;
}

/* --- log ----------------------------------------------------------------------------- */

static char logbuf[12288];
static size_t loglen;
static int kmsg = -1;

static void lg(const char *fmt, ...)
{
	char line[512];
	va_list ap;
	size_t n;

	va_start(ap, fmt);
	vsnprintf(line, sizeof(line), fmt, ap);
	va_end(ap);
	fprintf(stderr, "lume-bootsel: %s\n", line);
	if (kmsg >= 0)
		dprintf(kmsg, "lume-bootsel: %s\n", line);
	n = strlen(line);
	if (loglen + n + 2 < sizeof(logbuf)) {
		memcpy(logbuf + loglen, line, n);
		loglen += n;
		logbuf[loglen++] = '\n';
		logbuf[loglen] = 0;
	}
}

/* --- small helpers ------------------------------------------------------------------- */

static char *read_file(const char *path, size_t *len)
{
	FILE *f = fopen(path, "rb");
	char *buf = NULL;
	size_t cap = 0, n = 0, r;

	if (!f)
		return NULL;
	do {
		if (n + 4096 + 1 > cap) {
			cap = (n + 4096 + 1) * 2;
			buf = realloc(buf, cap);
			if (!buf) {
				fclose(f);
				return NULL;
			}
		}
		r = fread(buf + n, 1, cap - n - 1, f);
		n += r;
	} while (r > 0);
	fclose(f);
	buf[n] = 0;
	if (len)
		*len = n;
	return buf;
}

static void trim(char *s)
{
	char *p = s, *e;

	if ((unsigned char)p[0] == 0xef && (unsigned char)p[1] == 0xbb && (unsigned char)p[2] == 0xbf)
		p += 3; /* UTF-8 BOM of Windows editors */
	while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n')
		p++;
	memmove(s, p, strlen(p) + 1);
	e = s + strlen(s);
	while (e > s && (e[-1] == ' ' || e[-1] == '\t' || e[-1] == '\r' || e[-1] == '\n'))
		*--e = 0;
}

static int is_dir(const char *path)
{
	struct stat st;

	return stat(path, &st) == 0 && S_ISDIR(st.st_mode);
}

static int is_chr(const char *path)
{
	struct stat st;

	return stat(path, &st) == 0 && S_ISCHR(st.st_mode);
}

static void copy_str(char *dst, size_t size, const char *src)
{
	snprintf(dst, size, "%s", src ? src : "");
}

static long now_ms(void)
{
	struct timespec ts;

	clock_gettime(CLOCK_MONOTONIC, &ts);
	return ts.tv_sec * 1000L + ts.tv_nsec / 1000000L;
}

/* comma separated lists of ids (bad=) */
static int list_has(const char *list, const char *id)
{
	size_t n = strlen(id);
	const char *p = list;

	while (*id && (p = strstr(p, id))) {
		if ((p == list || p[-1] == ',') && (p[n] == 0 || p[n] == ','))
			return 1;
		p += n;
	}
	return 0;
}

static void list_add(char *list, size_t size, const char *id)
{
	if (!*id || list_has(list, id))
		return;
	if (*list)
		strncat(list, ",", size - strlen(list) - 1);
	strncat(list, id, size - strlen(list) - 1);
}

static void list_del(char *list, const char *id)
{
	char out[LIST_LEN] = "", copy[LIST_LEN], *tok, *save;

	copy_str(copy, sizeof(copy), list);
	for (tok = strtok_r(copy, ",", &save); tok; tok = strtok_r(NULL, ",", &save))
		if (strcmp(tok, id))
			list_add(out, sizeof(out), tok);
	strcpy(list, out);
}

/* --- the running device tree --------------------------------------------------------- */

static char soc[32];
static char soc_compat[128]; /* last string of /compatible: the SoC */
static char running_id[ID_LEN];

/* --- candidates (D3) ----------------------------------------------------------------- */

struct cand {
	char file[NAME_MAX + 1];
	char id[ID_LEN];
	uint32_t priority;
	int is_default;
	char *blob;
	size_t size;
	uint32_t *adc, *gpio, *i2c; /* rows of 4, 3 and 2 cells, host order */
	int nadc, ngpio, ni2c;
	int has_rules, matched;
};

static struct cand cands[MAX_CAND];
static int ncand;

static uint32_t *cells(const void *fdt, int node, const char *name, int width, int *rows)
{
	int len;
	const fdt32_t *p = fdt_getprop(fdt, node, name, &len);
	uint32_t *out;
	int i;

	*rows = 0;
	if (!p || len <= 0 || len % (4 * width))
		return NULL;
	out = malloc(len);
	for (i = 0; i < len / 4; i++)
		out[i] = fdt32_to_cpu(p[i]);
	*rows = len / (4 * width);
	return out;
}

static struct cand *find_cand(const char *name)
{
	int i;
	size_t n;

	for (i = 0; i < ncand; i++)
		if (!strcmp(cands[i].id, name) || !strcmp(cands[i].file, name))
			return &cands[i];
	/* the file name without .dtb */
	for (i = 0; i < ncand; i++) {
		n = strlen(cands[i].file);
		if (n > 4 && strlen(name) == n - 4 && !strncmp(cands[i].file, name, n - 4))
			return &cands[i];
	}
	return NULL;
}

static int dtb_filter(const struct dirent *d)
{
	size_t n = strlen(d->d_name);

	return n > 4 && !strcmp(d->d_name + n - 4, ".dtb");
}

static void load_candidates(void)
{
	const char *dir = rp("%s/dtbs/%s", opt_boot, soc);
	struct dirent **list;
	int n, i, node, len;

	n = scandir(dir, &list, dtb_filter, alphasort);
	if (n < 0) {
		lg("no folder dtbs/%s on BOOT", soc);
		return;
	}
	for (i = 0; i < n; i++) {
		struct cand *c = &cands[ncand];
		const char *name = list[i]->d_name;
		const char *id, *compat = NULL;
		char *blob;
		size_t size;

		blob = read_file(rp("%s/dtbs/%s/%s", opt_boot, soc, name), &size);
		if (blob && size >= sizeof(struct fdt_header) && !fdt_check_header(blob) &&
		    fdt_totalsize(blob) <= size)
			compat = fdt_getprop(blob, 0, "compatible", &len);
		if (!blob || size < sizeof(struct fdt_header) || fdt_check_header(blob) ||
		    fdt_totalsize(blob) > size) {
			lg("ignored %s: not a valid device tree", name);
			free(blob);
		} else if (!compat || fdt_stringlist_contains(compat, len, soc_compat) != 1) {
			lg("ignored %s: not compatible with %s", name, soc_compat);
			free(blob);
		} else if ((node = fdt_path_offset(blob, "/lume-select")) < 0 ||
			   !(id = fdt_getprop(blob, node, "lume,id", &len)) || len < 2 ||
			   strnlen(id, len) >= ID_LEN) {
			lg("ignored %s: no lume-select node with lume,id", name);
			free(blob);
		} else if (find_cand(id)) {
			lg("ignored %s: lume,id %s repeated", name, id);
			free(blob);
		} else if (ncand == MAX_CAND) {
			lg("ignored %s: more than %d candidates", name, MAX_CAND);
			free(blob);
		} else {
			const fdt32_t *prio = fdt_getprop(blob, node, "lume,priority", &len);

			memset(c, 0, sizeof(*c));
			copy_str(c->file, sizeof(c->file), name);
			copy_str(c->id, sizeof(c->id), id);
			c->priority = prio && len == 4 ? fdt32_to_cpu(*prio) : 0;
			c->is_default = fdt_getprop(blob, node, "lume,default", NULL) != NULL;
			c->adc = cells(blob, node, "lume,adc", 4, &c->nadc);
			c->gpio = cells(blob, node, "lume,gpio", 3, &c->ngpio);
			c->i2c = cells(blob, node, "lume,i2c-present", 2, &c->ni2c);
			c->has_rules = c->nadc + c->ngpio + c->ni2c > 0;
			c->blob = blob;
			c->size = size;
			ncand++;
			if (c->has_rules)
				lg("candidate %s (%s) priority %u, %d rule(s)%s", c->id, name,
				   c->priority, c->nadc + c->ngpio + c->ni2c,
				   c->is_default ? ", default" : "");
			else
				lg("candidate %s (%s) priority %u, no rules%s", c->id, name,
				   c->priority, c->is_default ? ", default" : "");
		}
		free(list[i]);
	}
	free(list);
}

static struct cand *default_cand(void)
{
	int i;

	for (i = 0; i < ncand; i++)
		if (cands[i].is_default)
			return &cands[i];
	return NULL;
}

/* --- probes (D4): read only ------------------------------------------------------------ */

/*
 * The device of a bus (iio:deviceN, gpiochipN, i2c-N) whose sysfs path goes through the
 * platform device at the MMIO address (".../1c22800.lradc/iio:device0").
 */
static int find_dev(const char *bus, const char *prefix, uint32_t addr, char *name, size_t size)
{
	const char *dir = rp("/sys/bus/%s/devices", bus);
	char want[24], real[PATH_MAX];
	struct dirent *d;
	DIR *dp = opendir(dir);
	int found = 0;

	if (!dp)
		return 0;
	snprintf(want, sizeof(want), "/%x.", addr);
	while (!found && (d = readdir(dp))) {
		if (strncmp(d->d_name, prefix, strlen(prefix)))
			continue;
		if (!realpath(rp("/sys/bus/%s/devices/%s", bus, d->d_name), real))
			continue;
		if (strstr(real, want)) {
			copy_str(name, size, d->d_name);
			found = 1;
		}
	}
	closedir(dp);
	return found;
}

static int probe_adc(const uint32_t *r)
{
	char dev[NAME_MAX + 1], *text;
	long v;

	if (!find_dev("iio", "iio:device", r[0], dev, sizeof(dev))) {
		lg("probe adc %#x channel %u: failed (no IIO device at that address)", r[0], r[1]);
		return 0;
	}
	text = read_file(rp("/sys/bus/iio/devices/%s/in_voltage%u_raw", dev, r[1]), NULL);
	if (!text) {
		lg("probe adc %#x channel %u: failed (no channel %u on %s)", r[0], r[1], r[1], dev);
		return 0;
	}
	v = strtol(text, NULL, 10);
	free(text);
	lg("probe adc %#x channel %u: %ld (rule %u-%u) %s", r[0], r[1], v, r[2], r[3],
	   v >= (long)r[2] && v <= (long)r[3] ? "match" : "no match");
	return v >= (long)r[2] && v <= (long)r[3];
}

/* level of a line the kernel already has as an input and nobody holds; -1 on failure */
static int gpio_level(const char *path, uint32_t line, char *why, size_t size)
{
	int fd, v = -1;

	if (!is_chr(path)) {
		/* test description: lines of "<offset> in|out free|used <level>" */
		char *text = read_file(path, NULL), *l, *save;
		unsigned off;
		char dir[8], use[8];
		int level;

		snprintf(why, size, "line %u not described", line);
		for (l = text ? strtok_r(text, "\n", &save) : NULL; l; l = strtok_r(NULL, "\n", &save)) {
			if (sscanf(l, "%u %7s %7s %d", &off, dir, use, &level) != 4 || off != line)
				continue;
			if (strcmp(use, "free"))
				snprintf(why, size, "line %u held by a driver", line);
			else if (strcmp(dir, "in"))
				snprintf(why, size, "line %u is not an input", line);
			else
				v = level;
		}
		free(text);
		return v;
	}
	fd = open(path, O_RDONLY | O_CLOEXEC);
	if (fd < 0) {
		snprintf(why, size, "%s", strerror(errno));
		return -1;
	}
	{
		struct gpio_v2_line_info info;
		struct gpio_v2_line_request req;
		struct gpio_v2_line_values vals;

		memset(&info, 0, sizeof(info));
		info.offset = line;
		if (ioctl(fd, GPIO_V2_GET_LINEINFO_IOCTL, &info) < 0) {
			snprintf(why, size, "line info: %s", strerror(errno));
		} else if (info.flags & GPIO_V2_LINE_FLAG_USED) {
			snprintf(why, size, "line %u held by %s", line,
				 info.consumer[0] ? info.consumer : "a driver");
		} else if (!(info.flags & GPIO_V2_LINE_FLAG_INPUT)) {
			snprintf(why, size, "line %u is not an input", line);
		} else {
			/* already an input: the request keeps the direction and the bias */
			memset(&req, 0, sizeof(req));
			req.offsets[0] = line;
			req.num_lines = 1;
			req.config.flags = GPIO_V2_LINE_FLAG_INPUT;
			copy_str(req.consumer, sizeof(req.consumer), "lume-bootsel");
			if (ioctl(fd, GPIO_V2_GET_LINE_IOCTL, &req) < 0) {
				snprintf(why, size, "request: %s", strerror(errno));
			} else {
				memset(&vals, 0, sizeof(vals));
				vals.mask = 1;
				if (ioctl(req.fd, GPIO_V2_LINE_GET_VALUES_IOCTL, &vals) < 0)
					snprintf(why, size, "read: %s", strerror(errno));
				else
					v = vals.bits & 1;
				close(req.fd);
			}
		}
	}
	close(fd);
	return v;
}

static int probe_gpio(const uint32_t *r)
{
	char dev[NAME_MAX + 1], why[128];
	int v;

	if (!find_dev("gpio", "gpiochip", r[0], dev, sizeof(dev))) {
		lg("probe gpio %#x line %u: failed (no GPIO controller at that address)", r[0], r[1]);
		return 0;
	}
	v = gpio_level(rp("/dev/%s", dev), r[1], why, sizeof(why));
	if (v < 0) {
		lg("probe gpio %#x line %u: failed (%s)", r[0], r[1], why);
		return 0;
	}
	lg("probe gpio %#x line %u: %d (rule %u) %s", r[0], r[1], v, r[2],
	   (uint32_t)v == r[2] ? "match" : "no match");
	return (uint32_t)v == r[2];
}

/* 1 present, 0 absent, -1 failure */
static int i2c_present(int bus, uint32_t addr, char *why, size_t size)
{
	const char *dev = rp("/dev/i2c-%d", bus);
	int fd, r = -1;
	unsigned char b;

	if (!is_chr(dev)) {
		/* test description: the addresses that answer, in hex */
		char *text = read_file(dev, NULL), *tok, *save;

		if (!text) {
			snprintf(why, size, "no /dev/i2c-%d", bus);
			return -1;
		}
		r = 0;
		for (tok = strtok_r(text, " \t\n", &save); tok; tok = strtok_r(NULL, " \t\n", &save))
			if (strtoul(tok, NULL, 16) == addr)
				r = 1;
		free(text);
		return r;
	}
	fd = open(dev, O_RDWR | O_CLOEXEC);
	if (fd < 0) {
		snprintf(why, size, "%s", strerror(errno));
		return -1;
	}
	if (ioctl(fd, I2C_SLAVE, (unsigned long)addr) < 0)
		snprintf(why, size, "address: %s", strerror(errno));
	else
		r = read(fd, &b, 1) == 1; /* one byte, like i2cdetect -r */
	close(fd);
	return r;
}

static int probe_i2c(const uint32_t *r)
{
	char dev[NAME_MAX + 1], why[128];
	int bus, v;

	if (!find_dev("i2c", "i2c-", r[0], dev, sizeof(dev))) {
		lg("probe i2c %#x address %#x: failed (no I2C controller at that address)", r[0], r[1]);
		return 0;
	}
	bus = atoi(dev + 4);
	if (is_dir(rp("/sys/bus/i2c/devices/%d-%04x/driver", bus, r[1]))) {
		/* a driver holds it, so it answered; the bus is not touched */
		lg("probe i2c %#x address %#x: present (bound to a driver) match", r[0], r[1]);
		return 1;
	}
	v = i2c_present(bus, r[1], why, sizeof(why));
	if (v < 0) {
		lg("probe i2c %#x address %#x: failed (%s)", r[0], r[1], why);
		return 0;
	}
	lg("probe i2c %#x address %#x: %s %s", r[0], r[1], v ? "present" : "absent",
	   v ? "match" : "no match");
	return v;
}

static int rules_match(struct cand *c)
{
	int i, ok = 1;

	for (i = 0; i < c->nadc; i++)
		ok &= probe_adc(c->adc + 4 * i);
	for (i = 0; i < c->ngpio; i++)
		ok &= probe_gpio(c->gpio + 3 * i);
	for (i = 0; i < c->ni2c; i++)
		ok &= probe_i2c(c->i2c + 2 * i);
	return ok;
}

/* --- state on ROMS (D6) ---------------------------------------------------------------- */

static struct {
	int persist;
	char manual[ID_LEN], good[ID_LEN], pending[ID_LEN], bad[LIST_LEN];
} st;

static const char *state_path(void)
{
	return rp("%s/system/etc/dtb-%s.conf", opt_roms, soc);
}

static void load_state(void)
{
	char *text, *l, *save;

	st.persist = opt_roms && is_dir(rp("%s", opt_roms));
	if (!st.persist) {
		lg("no ROMS: the choice is not saved");
		return;
	}
	text = read_file(state_path(), NULL);
	for (l = text ? strtok_r(text, "\n", &save) : NULL; l; l = strtok_r(NULL, "\n", &save)) {
		char *eq = strchr(l, '=');

		if (*l == '#' || !eq)
			continue;
		*eq++ = 0;
		trim(l);
		trim(eq);
		if (!strcmp(l, "manual"))
			copy_str(st.manual, sizeof(st.manual), eq);
		else if (!strcmp(l, "good"))
			copy_str(st.good, sizeof(st.good), eq);
		else if (!strcmp(l, "pending"))
			copy_str(st.pending, sizeof(st.pending), eq);
		else if (!strcmp(l, "bad"))
			copy_str(st.bad, sizeof(st.bad), eq);
	}
	free(text);
}

static void save_state(void)
{
	char tmp[PATH_MAX], dir[PATH_MAX];
	FILE *f;
	int fd;

	if (!st.persist)
		return;
	snprintf(dir, sizeof(dir), "%s", rp("%s/system", opt_roms));
	mkdir(dir, 0755);
	snprintf(dir, sizeof(dir), "%s", rp("%s/system/etc", opt_roms));
	mkdir(dir, 0755);
	snprintf(tmp, sizeof(tmp), "%s.tmp", state_path());
	f = fopen(tmp, "w");
	if (!f) {
		lg("ERROR: cannot write %s: %s", tmp, strerror(errno));
		return;
	}
	fprintf(f, "# Lume Retro OS: device tree choice of the %s SoC (lume-bootsel, r36os-logd)\n"
		   "manual=%s\ngood=%s\npending=%s\nbad=%s\n",
		soc, st.manual, st.good, st.pending, st.bad);
	fflush(f);
	fsync(fileno(f));
	fclose(f);
	if (rename(tmp, state_path()) < 0)
		lg("ERROR: cannot write %s: %s", state_path(), strerror(errno));
	fd = open(dir, O_RDONLY | O_DIRECTORY);
	if (fd >= 0) {
		fsync(fd);
		close(fd);
	}
}

/* --- keys and menu (D7) ---------------------------------------------------------------- */

enum { K_SELECT, K_UP, K_DOWN, K_OK, K_ROLES };
static const char *role_names[K_ROLES] = { "select", "up", "down", "ok" };
static int keys[K_ROLES][8], nkeys[K_ROLES];

static const struct { const char *name; int code; } key_names[] = {
	{ "KEY_VOLUMEDOWN", KEY_VOLUMEDOWN }, { "KEY_VOLUMEUP", KEY_VOLUMEUP },
	{ "KEY_POWER", KEY_POWER }, { "BTN_SOUTH", BTN_SOUTH }, { "BTN_EAST", BTN_EAST },
	{ "BTN_NORTH", BTN_NORTH }, { "BTN_WEST", BTN_WEST }, { "BTN_TL", BTN_TL },
	{ "BTN_TR", BTN_TR }, { "BTN_TL2", BTN_TL2 }, { "BTN_TR2", BTN_TR2 },
	{ "BTN_SELECT", BTN_SELECT }, { "BTN_START", BTN_START }, { "BTN_MODE", BTN_MODE },
	{ "BTN_DPAD_UP", BTN_DPAD_UP }, { "BTN_DPAD_DOWN", BTN_DPAD_DOWN },
	{ "BTN_DPAD_LEFT", BTN_DPAD_LEFT }, { "BTN_DPAD_RIGHT", BTN_DPAD_RIGHT },
};

static int key_code(const char *s)
{
	size_t i;
	char *end;
	long v;

	for (i = 0; i < sizeof(key_names) / sizeof(key_names[0]); i++)
		if (!strcmp(s, key_names[i].name))
			return key_names[i].code;
	v = strtol(s, &end, 0);
	return *s && !*end && v > 0 && v <= KEY_MAX ? (int)v : -1;
}

/* /etc/bootsel-keys: "<role>=<key>[,<key>...]" with role select, up, down or ok */
static int load_keys(void)
{
	char *text = read_file(rp("/etc/bootsel-keys"), NULL), *l, *save;
	int r;

	if (!text)
		return 0;
	for (l = strtok_r(text, "\n", &save); l; l = strtok_r(NULL, "\n", &save)) {
		char *eq, *hash = strchr(l, '#'), *tok, *s2;

		if (hash)
			*hash = 0;
		eq = strchr(l, '=');
		if (!eq)
			continue;
		*eq++ = 0;
		trim(l);
		for (r = 0; r < K_ROLES && strcmp(l, role_names[r]); r++)
			;
		if (r == K_ROLES)
			continue;
		for (tok = strtok_r(eq, ", \t", &s2); tok; tok = strtok_r(NULL, ", \t", &s2)) {
			int code = key_code(tok);

			if (code < 0)
				lg("bootsel-keys: unknown key %s", tok);
			else if (nkeys[r] < 8)
				keys[r][nkeys[r]++] = code;
		}
	}
	free(text);
	return nkeys[K_SELECT] && nkeys[K_UP] && nkeys[K_DOWN] && nkeys[K_OK];
}

static int role_of(int code)
{
	int r, i;

	for (r = K_UP; r < K_ROLES; r++)
		for (i = 0; i < nkeys[r]; i++)
			if (keys[r][i] == code)
				return r;
	return -1;
}

#define BITS_LEN (KEY_MAX / 8 + 1)
#define TEST_BIT(bits, n) ((bits)[(n) / 8] & (1 << ((n) % 8)))

static int event_filter(const struct dirent *d)
{
	return !strncmp(d->d_name, "event", 5) && !strchr(d->d_name, '.');
}

/* key capabilities of an input device; a test description (regular file) has them all */
static int has_any(const char *path, int role_first, int role_last)
{
	unsigned char bits[BITS_LEN];
	int fd, r, i, yes = 0;

	if (!is_chr(path))
		return 1;
	fd = open(path, O_RDONLY | O_CLOEXEC | O_NONBLOCK);
	if (fd < 0)
		return 0;
	memset(bits, 0, sizeof(bits));
	if (ioctl(fd, EVIOCGBIT(EV_KEY, sizeof(bits)), bits) >= 0)
		for (r = role_first; r <= role_last; r++)
			for (i = 0; i < nkeys[r]; i++)
				if (TEST_BIT(bits, keys[r][i]))
					yes = 1;
	close(fd);
	return yes;
}

static int held_now(const char *path)
{
	unsigned char bits[BITS_LEN];
	int fd, i, held = 0;

	if (!is_chr(path)) {
		/* test description: the codes held at power on, in <device>.held */
		char held_path[PATH_MAX], *text, *tok, *save;

		snprintf(held_path, sizeof(held_path), "%s.held", path);
		text = read_file(held_path, NULL);
		for (tok = text ? strtok_r(text, " \t\n", &save) : NULL; tok;
		     tok = strtok_r(NULL, " \t\n", &save))
			for (i = 0; i < nkeys[K_SELECT]; i++)
				if (key_code(tok) == keys[K_SELECT][i])
					held = 1;
		free(text);
		return held;
	}
	fd = open(path, O_RDONLY | O_CLOEXEC | O_NONBLOCK);
	if (fd < 0)
		return 0;
	memset(bits, 0, sizeof(bits));
	if (ioctl(fd, EVIOCGKEY(sizeof(bits)), bits) >= 0)
		for (i = 0; i < nkeys[K_SELECT]; i++)
			if (TEST_BIT(bits, keys[K_SELECT][i]))
				held = 1;
	close(fd);
	return held;
}

/* the selection key, read once as soon as a device with it shows up (at most 1 s) */
static int selection_key_held(void)
{
	long deadline = now_ms() + KEY_WAIT_MS;
	struct dirent **list;
	int n, i, found, held;

	for (;;) {
		found = held = 0;
		n = scandir(rp("/dev/input"), &list, event_filter, alphasort);
		for (i = 0; i < n; i++) {
			const char *path = rp("/dev/input/%s", list[i]->d_name);

			if (has_any(path, K_SELECT, K_SELECT)) {
				found = 1;
				held |= held_now(path);
			}
			free(list[i]);
		}
		if (n >= 0)
			free(list);
		if (found)
			return held;
		if (now_ms() >= deadline) {
			lg("no input device with the selection key within %d ms", KEY_WAIT_MS);
			return 0;
		}
		usleep(50000);
	}
}

static void draw(FILE *tty, int cur, struct cand *autoc, struct cand *forced)
{
	int i;

	fprintf(tty, "\033[2J\033[H");
	fprintf(tty, "Lume Retro OS - device tree (%s)\n\n", soc);
	if (forced)
		fprintf(tty, "BOOT/dtbs/force selects %s: it is used while the file exists.\n"
			     "A choice here is saved for when the file is deleted.\n\n", forced->id);
	for (i = 0; i <= ncand; i++) {
		fprintf(tty, " %s ", i == cur ? ">" : " ");
		if (i == ncand) {
			fprintf(tty, "Automatic\n");
			continue;
		}
		fprintf(tty, "%s", cands[i].id);
		if (&cands[i] == autoc)
			fprintf(tty, " (auto)");
		if (!strcmp(cands[i].id, st.good))
			fprintf(tty, " (ok)");
		if (&cands[i] == forced)
			fprintf(tty, " (forced)");
		fprintf(tty, "\n");
	}
	fprintf(tty, "\nUp/Down: move   Confirm: choose\n");
	fflush(tty);
}

/* index of the chosen candidate, ncand for Automatic, -1 when nothing was chosen */
static int menu(struct cand *autoc, struct cand *forced)
{
	struct pollfd fds[16];
	struct dirent **list;
	FILE *tty;
	int n, i, nfd = 0, cur = ncand, open_fds;
	long idle;

	tty = fopen(rp("/dev/tty1"), "a");
	if (!tty) {
		lg("list: cannot open tty1: %s", strerror(errno));
		return -1;
	}
	for (i = 0; i < ncand; i++)
		if (!strcmp(cands[i].id, st.manual))
			cur = i;
	n = scandir(rp("/dev/input"), &list, event_filter, alphasort);
	for (i = 0; i < n; i++) {
		const char *path = rp("/dev/input/%s", list[i]->d_name);

		if (nfd < 16 && has_any(path, K_UP, K_OK)) {
			fds[nfd].fd = open(path, O_RDONLY | O_CLOEXEC);
			fds[nfd].events = POLLIN;
			if (fds[nfd].fd >= 0)
				nfd++;
		}
		free(list[i]);
	}
	if (n >= 0)
		free(list);
	lg("list shown (%d candidate(s))", ncand);
	draw(tty, cur, autoc, forced);
	open_fds = nfd;
	idle = now_ms() + MENU_IDLE_MS;
	while (open_fds > 0 && now_ms() < idle) {
		if (poll(fds, nfd, 200) <= 0)
			continue;
		for (i = 0; i < nfd; i++) {
			struct input_event ev;
			ssize_t r;
			int role;

			if (fds[i].fd < 0 || !(fds[i].revents & (POLLIN | POLLHUP | POLLERR)))
				continue;
			r = read(fds[i].fd, &ev, sizeof(ev));
			if (r != (ssize_t)sizeof(ev)) {
				/* end of a test description, or the device went away */
				close(fds[i].fd);
				fds[i].fd = -1;
				open_fds--;
				continue;
			}
			if (ev.type != EV_KEY || ev.value != 1)
				continue;
			idle = now_ms() + MENU_IDLE_MS;
			role = role_of(ev.code);
			if (role == K_UP)
				cur = cur > 0 ? cur - 1 : ncand;
			else if (role == K_DOWN)
				cur = cur < ncand ? cur + 1 : 0;
			else if (role == K_OK) {
				for (i = 0; i < nfd; i++)
					if (fds[i].fd >= 0)
						close(fds[i].fd);
				fprintf(tty, "\nSelected: %s\n", cur == ncand ? "Automatic" : cands[cur].id);
				fclose(tty);
				return cur;
			}
			draw(tty, cur, autoc, forced);
		}
	}
	for (i = 0; i < nfd; i++)
		if (fds[i].fd >= 0)
			close(fds[i].fd);
	fprintf(tty, "\nNothing chosen: booting with the automatic choice.\n");
	fclose(tty);
	lg("list closed without a choice");
	return -1;
}

/* --- preparing the device tree and kexec (D2) ------------------------------------------ */

static int is_memory_dir(const char *name)
{
	return !strcmp(name, "memory") || !strncmp(name, "memory@", 7);
}

static int copy_memory(void *fdt)
{
	DIR *dp = opendir(rp("/proc/device-tree")), *mp;
	struct dirent *d, *p;
	int off, copied = 0;

	if (!dp)
		return 0;
	/* drop the memory nodes of the file: the bootloader fixes the memory only in the
	 * tree it loads (on the GA36 it comes from the ATAGs) */
	for (off = fdt_first_subnode(fdt, 0); off >= 0;) {
		const char *type = fdt_getprop(fdt, off, "device_type", NULL);

		if (type && !strcmp(type, "memory")) {
			fdt_del_node(fdt, off);
			off = fdt_first_subnode(fdt, 0);
		} else {
			off = fdt_next_subnode(fdt, off);
		}
	}
	while ((d = readdir(dp))) {
		if (!is_memory_dir(d->d_name))
			continue;
		off = fdt_add_subnode(fdt, 0, d->d_name);
		if (off < 0)
			continue;
		mp = opendir(rp("/proc/device-tree/%s", d->d_name));
		while (mp && (p = readdir(mp))) {
			char *val;
			size_t len;

			if (p->d_name[0] == '.' || !strcmp(p->d_name, "name"))
				continue;
			val = read_file(rp("/proc/device-tree/%s/%s", d->d_name, p->d_name), &len);
			if (val)
				fdt_setprop(fdt, off, p->d_name, val, len);
			free(val);
		}
		if (mp)
			closedir(mp);
		copied++;
	}
	closedir(dp);
	return copied;
}

static const char *out_path(void)
{
	return opt_out ? opt_out : rp("/tmp/lume-bootsel.dtb");
}

static int prepare(struct cand *c, const char *reason)
{
	size_t size = c->size + 65536 + sizeof(logbuf);
	char *buf = malloc(size), sel[2 * ID_LEN];
	int chosen, err, mem, n;
	FILE *f;

	if (!buf || fdt_open_into(c->blob, buf, size)) {
		lg("ERROR: cannot open %s", c->file);
		free(buf);
		return -1;
	}
	mem = copy_memory(buf);
	chosen = fdt_path_offset(buf, "/chosen");
	if (chosen < 0)
		chosen = fdt_add_subnode(buf, 0, "chosen");
	/* "<id>\0<reason>\0": the restarted kernel sees it and does not choose again */
	n = snprintf(sel, sizeof(sel), "%s%c%s", c->id, 0, reason) + 1;
	lg("prepared %s: memory from the running tree (%d node(s))", c->file, mem);
	err = fdt_setprop(buf, chosen, "lume,dtb-selected", sel, n);
	if (!err)
		err = fdt_setprop_string(buf, chosen, "lume,dtb-log", logbuf);
	if (!err)
		err = fdt_pack(buf);
	if (err) {
		lg("ERROR: cannot prepare %s: %s", c->file, fdt_strerror(err));
		free(buf);
		return -1;
	}
	f = fopen(out_path(), "wb");
	if (!f || fwrite(buf, 1, fdt_totalsize(buf), f) != fdt_totalsize(buf)) {
		lg("ERROR: cannot write %s", out_path());
		if (f)
			fclose(f);
		free(buf);
		return -1;
	}
	fclose(f);
	free(buf);
	return 0;
}

static int kexec_load(const char *kernel)
{
	char dtb_arg[PATH_MAX + 8];
	pid_t pid;
	int status;

	snprintf(dtb_arg, sizeof(dtb_arg), "--dtb=%s", out_path());
	pid = fork();
	if (pid == 0) {
		execl(opt_kexec, "kexec", "-l", kernel, dtb_arg, (char *)NULL);
		_exit(127);
	}
	if (pid < 0 || waitpid(pid, &status, 0) < 0)
		return -1;
	return WIFEXITED(status) ? WEXITSTATUS(status) : -1;
}

/* --- second start, after the kexec ----------------------------------------------------- */

static int came_from_kexec(void)
{
	size_t len;
	char *sel = read_file(rp("/proc/device-tree/chosen/lume,dtb-selected"), &len);
	char *log, *l, *save;

	if (!sel)
		return 0;
	log = read_file(rp("/proc/device-tree/chosen/lume,dtb-log"), NULL);
	for (l = log ? strtok_r(log, "\n", &save) : NULL; l; l = strtok_r(NULL, "\n", &save))
		lg("before kexec: %s", l);
	free(log);
	lg("device tree from kexec: %s (reason: %s)", sel,
	   strlen(sel) + 1 < len ? sel + strlen(sel) + 1 : "?");
	free(sel);
	return 1;
}

/* --- main -------------------------------------------------------------------------------- */

static void usage(void)
{
	fprintf(stderr,
		"usage: lume-bootsel [--root DIR] [--boot DIR] [--roms DIR] [--kernel PATH]\n"
		"                    [--kexec PATH] [--out-dtb PATH] [--dry-run]\n"
		"  --boot    BOOT mount point (default /boot)\n"
		"  --roms    ROMS mount point; without it the choice is not saved\n"
		"  --kernel  kernel to reload, relative to BOOT (ga36/zImage, r36s/Image)\n"
		"  --dry-run decide, write the state and prepare the tree, but do not run kexec\n");
}

int main(int argc, char **argv)
{
	struct cand *forced = NULL, *autoc = NULL, *chosen = NULL, *def, *fallback = NULL;
	const char *reason, *target;
	char *text;
	int i, has_fallback = 0, choice = -1;

	for (i = 1; i < argc; i++) {
		const char *a = argv[i];

		if (!strcmp(a, "--dry-run"))
			opt_dry_run = 1;
		else if (i + 1 < argc && !strcmp(a, "--root"))
			opt_root = argv[++i];
		else if (i + 1 < argc && !strcmp(a, "--boot"))
			opt_boot = argv[++i];
		else if (i + 1 < argc && !strcmp(a, "--roms"))
			opt_roms = argv[++i];
		else if (i + 1 < argc && !strcmp(a, "--kernel"))
			opt_kernel = argv[++i];
		else if (i + 1 < argc && !strcmp(a, "--kexec"))
			opt_kexec = argv[++i];
		else if (i + 1 < argc && !strcmp(a, "--out-dtb"))
			opt_out = argv[++i];
		else {
			usage();
			return 2;
		}
	}
	if (!strcmp(opt_root, "/"))
		opt_root = "";
	if (!*opt_root)
		kmsg = open("/dev/kmsg", O_WRONLY | O_CLOEXEC);

	if (!is_dir(rp("/proc/device-tree"))) {
		lg("no device tree");
		return 0;
	}
	if (came_from_kexec())
		return 0;

	text = read_file(rp("/etc/soc"), NULL);
	copy_str(soc, sizeof(soc), text);
	free(text);
	trim(soc);
	{
		size_t len;
		char *compat = read_file(rp("/proc/device-tree/compatible"), &len);
		const char *last = compat;
		char *p;

		for (p = compat; p && p < compat + len; p += strlen(p) + 1)
			if (*p)
				last = p;
		copy_str(soc_compat, sizeof(soc_compat), last);
		free(compat);
		text = read_file(rp("/proc/device-tree/lume-select/lume,id"), NULL);
		copy_str(running_id, sizeof(running_id), text);
		free(text);
	}
	if (!*soc || !*soc_compat) {
		lg("ERROR: no /etc/soc or no compatible in the device tree; keeping the running one");
		return 0;
	}

	load_candidates();
	def = default_cand();
	if (!*running_id && def)
		copy_str(running_id, sizeof(running_id), def->id); /* no node: the default */
	lg("soc %s (%s), running device tree %s", soc, soc_compat,
	   *running_id ? running_id : "without lume-select node");
	load_state();

	/* a device tree that did not reach the frontend in the previous boot */
	if (*st.pending) {
		lg("fallback: %s did not reach the frontend in the previous boot; discarded",
		   st.pending);
		list_add(st.bad, sizeof(st.bad), st.pending);
		if (!strcmp(st.manual, st.pending))
			st.manual[0] = 0;
		st.pending[0] = 0;
		has_fallback = 1;
		fallback = find_cand(st.good);
		if (fallback && list_has(st.bad, fallback->id))
			fallback = NULL;
	}

	/* BOOT/dtbs/force (read only) */
	text = read_file(rp("%s/dtbs/force", opt_boot), NULL);
	if (text) {
		char *nl = strchr(text, '\n');

		if (nl)
			*nl = 0;
		trim(text);
		forced = *text ? find_cand(text) : NULL;
		if (forced)
			lg("force: BOOT/dtbs/force selects %s", forced->id);
		else
			lg("force ignored: '%s' in BOOT/dtbs/force is not a device tree of dtbs/%s",
			   text, soc);
		free(text);
	}

	/* automatic choice: highest priority whose rules all match, else the default */
	for (i = 0; i < ncand; i++) {
		struct cand *c = &cands[i];

		if (!c->has_rules)
			continue;
		if (list_has(st.bad, c->id)) {
			lg("rules of %s skipped: discarded before (bad)", c->id);
			continue;
		}
		c->matched = rules_match(c);
		lg("rules of %s: %s", c->id, c->matched ? "match" : "no match");
		if (c->matched && (!autoc || c->priority > autoc->priority))
			autoc = c;
	}
	if (!autoc) {
		lg("no rule matched");
		autoc = def;
	}

	/* the list, when the selection key is held */
	if (load_keys()) {
		if (ncand && selection_key_held())
			choice = menu(autoc, forced);
	} else {
		lg("no complete /etc/bootsel-keys: the list is off");
	}
	if (choice >= 0 && choice < ncand) {
		copy_str(st.manual, sizeof(st.manual), cands[choice].id);
		list_del(st.bad, cands[choice].id);
		lg("list: %s chosen and saved", cands[choice].id);
	} else if (choice == ncand) {
		st.manual[0] = 0;
		lg("list: automatic chosen, saved choice cleared");
	}

	if (forced) {
		chosen = forced;
		reason = "forced";
	} else if (choice >= 0 && choice < ncand) {
		chosen = &cands[choice];
		reason = "manual";
	} else if (has_fallback) {
		chosen = fallback ? fallback : def;
		reason = "fallback";
	} else if (*st.manual && find_cand(st.manual) && !list_has(st.bad, st.manual)) {
		chosen = find_cand(st.manual);
		reason = "manual";
	} else if (autoc && autoc != def) {
		chosen = autoc;
		reason = "rule";
	} else {
		chosen = def;
		reason = "default";
	}
	if (*st.manual && !find_cand(st.manual))
		lg("saved choice %s is not in dtbs/%s; ignored", st.manual, soc);

	target = chosen ? chosen->id : running_id;
	lg("selected %s (reason: %s)", *target ? target : "running device tree", reason);

	if (!chosen || !strcmp(chosen->id, running_id)) {
		lg("keeping the running device tree, no kexec");
		save_state();
		if (opt_dry_run)
			printf("selected=%s reason=%s kexec=no\n", target, reason);
		return 0;
	}

	/* switch: prepare the tree and load the same kernel with it */
	if (!opt_kernel || access(rp("%s/%s", opt_boot, opt_kernel), R_OK)) {
		lg("ERROR: kernel %s not found on BOOT; keeping the running device tree",
		   opt_kernel ? opt_kernel : "(none given)");
		save_state();
		return 0;
	}
	/* not yet confirmed by reaching the frontend: pending (never for the forced one) */
	if (strcmp(reason, "forced") && (!def || strcmp(chosen->id, def->id)) &&
	    strcmp(chosen->id, st.good))
		copy_str(st.pending, sizeof(st.pending), chosen->id);
	lg("switching to %s by kexec (%s/%s)", chosen->id, opt_boot, opt_kernel);
	if (prepare(chosen, reason)) {
		st.pending[0] = 0;
		save_state();
		return 0;
	}
	if (opt_dry_run) {
		save_state();
		printf("selected=%s reason=%s kexec=yes dtb=%s\n", chosen->id, reason, out_path());
		return 0;
	}
	i = kexec_load(rp("%s/%s", opt_boot, opt_kernel));
	if (i) {
		lg("ERROR: kexec -l failed (status %d); keeping the running device tree", i);
		st.pending[0] = 0;
		save_state();
		return 0;
	}
	save_state();
	return EXIT_KEXEC;
}
