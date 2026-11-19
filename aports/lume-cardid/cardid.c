/*
 * lume-cardid (openspec game-experience-tuning D11, task 9.3): the fingerprint of the ROMS
 * card as it is on the card, read past every cache of the running kernel.
 *
 *   lume-cardid <device> [<path>]   one line: boot=<counter> at=<cluster>:<size>:<mtime>
 *                                   bitmap=<hash>
 *   lume-cardid --shutdown <dir>    the exFAT of <dir> refuses every write from now on
 *                                   (EXFAT_IOC_SHUTDOWN, no sync)
 *
 * Why: one card serves two consoles. A console that sleeps keeps the exFAT allocation state
 * of the card in RAM; when the card boots on the other console meanwhile and comes back, the
 * first writes after the wake land on clusters the other console gave to other files. The
 * kernel cannot tell (same card, same CID), and a read through the file system can return
 * the old directory entry from the dentry, inode or buffer cache. So lume-sleep takes this
 * fingerprint right before the suspension (ROMS already read-only, so it is final) and again
 * at the wake, and compares the two lines.
 *
 * The fingerprint is read from the block device with O_DIRECT (no page cache, no buffer
 * cache): the boot sector, the root directory, the directories of <path> (default
 * logs/.boot, the boot counter every Lume boot rewrites, lume-logd) and the first sector of
 * the file, plus a hash of the allocation bitmap, which any write that allocates or frees a
 * cluster changes (a PC copying files, a boot of another system). A normal wake reads a few
 * sectors and the bitmap (clusters / 8 bytes, 128 KiB on a 128 GB card with 128 KiB
 * clusters).
 *
 * Exit status: 0 the line was printed (boot=- when <path> is missing), 1 the device could
 * not be read or is not exFAT (the reason on stderr), 2 usage.
 */
#define _GNU_SOURCE
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

/* include/uapi/linux/exfat.h (kernel 6.18), copied: the musl headers do not carry it */
#define LUME_EXFAT_IOC_SHUTDOWN _IOR('X', 125, uint32_t)
#define LUME_EXFAT_GOING_DOWN_NOSYNC 0x2

#define ALIGN 4096
/* caps: a directory or a bitmap larger than this is not one of a Lume card */
#define DIR_MAX (16u << 20)
#define BITMAP_MAX (8u << 20)
#define CLUSTER_EOC 0xFFFFFFFFu

static int fd = -1;
static unsigned sect_bits, clus_bits;
static uint64_t fat_off, heap_off; /* in sectors */
static uint32_t clu_count, root_clu;

static int fail(const char *what)
{
	fprintf(stderr, "lume-cardid: %s\n", what);
	return 1;
}

static void *abuf(size_t n)
{
	void *p = NULL;
	if (posix_memalign(&p, ALIGN, n ? n : ALIGN))
		return NULL;
	return p;
}

/* len bytes at off; both are multiples of the sector size (512 or 4096) */
static int rd(uint64_t off, void *buf, size_t len)
{
	size_t done = 0;
	while (done < len) {
		ssize_t r = pread(fd, (char *)buf + done, len - done, (off_t)(off + done));
		if (r < 0 && errno == EINTR)
			continue;
		if (r <= 0)
			return -1;
		done += (size_t)r;
	}
	return 0;
}

static uint16_t le16(const uint8_t *p) { return (uint16_t)(p[0] | p[1] << 8); }
static uint32_t le32(const uint8_t *p)
{
	return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static uint64_t le64(const uint8_t *p) { return (uint64_t)le32(p) | (uint64_t)le32(p + 4) << 32; }

static int valid_cluster(uint32_t c) { return c >= 2 && c <= clu_count + 1; }

static uint64_t cluster_off(uint32_t c)
{
	return (heap_off + ((uint64_t)(c - 2) << (clus_bits - sect_bits))) << sect_bits;
}

/* the FAT entry of c: the next cluster of its chain (CLUSTER_EOC at the end), 0 on error */
static uint32_t next_cluster(uint32_t c)
{
	static uint8_t *sec;
	static uint64_t cached = UINT64_MAX;
	uint64_t byte = (fat_off << sect_bits) + (uint64_t)c * 4;
	uint64_t s = byte >> sect_bits;
	uint32_t n;
	if (!sec && !(sec = abuf((size_t)1 << sect_bits)))
		return 0;
	if (s != cached) {
		if (rd(s << sect_bits, sec, (size_t)1 << sect_bits))
			return 0;
		cached = s;
	}
	n = le32(sec + (byte & (((uint64_t)1 << sect_bits) - 1)));
	if (n == CLUSTER_EOC)
		return CLUSTER_EOC;
	return valid_cluster(n) ? n : 0;
}

/* a directory (or any chain) into memory: contiguous when nofat (len bytes), else by the
 * FAT until its end; *size gets the bytes read */
static uint8_t *load_chain(uint32_t first, int nofat, uint64_t len, size_t *size)
{
	size_t csize = (size_t)1 << clus_bits, cap = DIR_MAX, n = 0;
	uint8_t *buf = NULL, *cl, *grown;
	uint32_t c = first;
	if (!valid_cluster(first))
		return NULL;
	if (nofat) {
		uint64_t want = (len + csize - 1) / csize * csize;
		if (want == 0 || want > cap)
			return NULL;
		cap = (size_t)want;
	}
	/* one aligned cluster for the O_DIRECT read, copied into a buffer that grows */
	if (csize > cap || !(cl = abuf(csize)))
		return NULL;
	while (n + csize <= cap) {
		if (rd(cluster_off(c), cl, csize) || !(grown = realloc(buf, n + csize)))
			goto bad;
		buf = grown;
		memcpy(buf + n, cl, csize);
		n += csize;
		if (nofat) {
			c++;
			if (n >= cap || !valid_cluster(c))
				break;
			continue;
		}
		c = next_cluster(c);
		if (c == CLUSTER_EOC)
			break;
		if (c == 0)
			goto bad;
	}
	free(cl);
	*size = n;
	return buf;
bad:
	free(cl);
	free(buf);
	return NULL;
}

struct entry {
	uint32_t first;
	uint64_t len;
	int nofat, dir;
	uint32_t mtime;
	uint8_t mtime_cs;
};

/* the entry set named name (ASCII, compared without case as exFAT does for ASCII) in the
 * directory dir/size: 0 found, 1 not there */
static int find(const uint8_t *dir, size_t size, const char *name, struct entry *e)
{
	size_t nlen = strlen(name);
	for (size_t i = 0; i + 32 <= size; i += 32) {
		const uint8_t *f = dir + i, *s;
		unsigned sec, k, got = 0, nl;
		if (f[0] == 0x00)
			return 1; /* end of the directory */
		if (f[0] != 0x85)
			continue;
		sec = f[1];
		if (sec < 2 || i + 32 * (sec + 1) > size)
			continue;
		s = f + 32;
		if (s[0] != 0xC0)
			continue;
		nl = s[3];
		if (nl != nlen)
			continue;
		for (k = 2; k <= sec && got < nl; k++) {
			const uint8_t *n = f + 32 * k;
			if (n[0] != 0xC1)
				break;
			for (unsigned j = 0; j < 15 && got < nl; j++, got++) {
				uint16_t ch = le16(n + 2 + 2 * j);
				if (ch > 127 || tolower(ch) != tolower((unsigned char)name[got]))
					goto next;
			}
		}
		if (got != nl)
			continue;
		e->first = le32(s + 20);
		e->len = le64(s + 24);
		e->nofat = (s[1] & 0x02) != 0;
		e->dir = (le16(f + 4) & 0x10) != 0;
		e->mtime = le32(f + 12);
		e->mtime_cs = f[21];
		return 0;
next:;
	}
	return 1;
}

/* FNV-1a, 64 bits */
static uint64_t fnv(uint64_t h, const uint8_t *p, size_t n)
{
	while (n--) {
		h ^= *p++;
		h *= 0x100000001b3ull;
	}
	return h;
}

static int fingerprint(const char *dev, const char *path)
{
	uint8_t *boot, *dir, *bm = NULL, *data;
	size_t size = 0;
	char comp[256], counter[33] = "-", at[64] = "-", bitmap[24] = "-";
	const char *p = path;
	struct entry e = { 0 };
	int found = 1;
	uint64_t bm_len = 0;
	uint32_t bm_first = 0;

	fd = open(dev, O_RDONLY | O_DIRECT | O_CLOEXEC);
	if (fd < 0 && errno == EINVAL) /* a file system without O_DIRECT (the host tests) */
		fd = open(dev, O_RDONLY | O_CLOEXEC);
	if (fd < 0) {
		fprintf(stderr, "lume-cardid: %s: %s\n", dev, strerror(errno));
		return 1;
	}
	if (!(boot = abuf(ALIGN)) || rd(0, boot, ALIGN))
		return fail("cannot read the boot sector");
	if (memcmp(boot + 3, "EXFAT   ", 8) || le16(boot + 510) != 0xAA55)
		return fail("not an exFAT boot sector");
	sect_bits = boot[108];
	clus_bits = boot[108] + boot[109];
	fat_off = le32(boot + 80);
	heap_off = le32(boot + 88);
	clu_count = le32(boot + 92);
	root_clu = le32(boot + 96);
	if (sect_bits < 9 || sect_bits > 12 || clus_bits > 25 || !valid_cluster(root_clu))
		return fail("bad exFAT geometry");

	/* the root directory: the allocation bitmap, then the path */
	if (!(dir = load_chain(root_clu, 0, 0, &size)))
		return fail("cannot read the root directory");
	for (size_t i = 0; i + 32 <= size && dir[i]; i += 32) {
		if (dir[i] == 0x81 && !(dir[i + 1] & 1)) { /* the first bitmap */
			bm_first = le32(dir + i + 20);
			bm_len = le64(dir + i + 24);
			break;
		}
	}
	while (*p) {
		size_t n = strcspn(p, "/");
		uint8_t *sub;
		if (n == 0 || n >= sizeof comp) {
			p += n + (p[n] == '/');
			continue;
		}
		memcpy(comp, p, n);
		comp[n] = 0;
		p += n + (p[n] == '/');
		found = find(dir, size, comp, &e);
		if (found)
			break;
		if (!*p)
			break;
		if (!e.dir) {
			found = 1;
			break;
		}
		sub = load_chain(e.first, e.nofat, e.len, &size);
		free(dir);
		dir = sub;
		if (!dir)
			return fail("cannot read a directory of the path");
	}
	if (!found && !e.dir) {
		snprintf(at, sizeof at, "%" PRIu32 ":%" PRIu64 ":%08" PRIx32 ".%u", e.first, e.len,
			 e.mtime, e.mtime_cs);
		if (e.len && valid_cluster(e.first)) {
			size_t sl = (size_t)1 << sect_bits, k = 0;
			if (!(data = abuf(sl)) || rd(cluster_off(e.first), data, sl))
				return fail("cannot read the file");
			for (size_t j = 0; j < sl && j < e.len && k < sizeof counter - 1; j++)
				if (isdigit(data[j]))
					counter[k++] = (char)data[j];
			counter[k] = 0;
			if (!k)
				strcpy(counter, "?");
			free(data);
		}
	}
	if (bm_len && bm_len <= BITMAP_MAX && valid_cluster(bm_first)) {
		/* contiguous, as the kernel reads it (fs/exfat/balloc.c) */
		size_t sl = (size_t)1 << sect_bits;
		size_t n = (size_t)((bm_len + sl - 1) / sl * sl);
		if (!(bm = abuf(n)) || rd(cluster_off(bm_first), bm, n))
			return fail("cannot read the allocation bitmap");
		snprintf(bitmap, sizeof bitmap, "%016" PRIx64,
			 fnv(0xcbf29ce484222325ull, bm, (size_t)bm_len));
		free(bm);
	}
	printf("boot=%s at=%s bitmap=%s\n", counter, at, bitmap);
	free(dir);
	free(boot);
	close(fd);
	return 0;
}

static int shutdown_fs(const char *dir)
{
	uint32_t flags = LUME_EXFAT_GOING_DOWN_NOSYNC;
	int d = open(dir, O_RDONLY | O_DIRECTORY | O_CLOEXEC);
	if (d < 0 || ioctl(d, LUME_EXFAT_IOC_SHUTDOWN, &flags)) {
		fprintf(stderr, "lume-cardid: shutdown of %s: %s\n", dir, strerror(errno));
		return 1;
	}
	close(d);
	return 0;
}

int main(int argc, char **argv)
{
	if (argc == 3 && !strcmp(argv[1], "--shutdown"))
		return shutdown_fs(argv[2]);
	if ((argc == 2 || argc == 3) && argv[1][0] != '-')
		return fingerprint(argv[1], argc == 3 ? argv[2] : "logs/.boot");
	fprintf(stderr, "usage: lume-cardid <device> [<path>] | lume-cardid --shutdown <dir>\n");
	return 2;
}
