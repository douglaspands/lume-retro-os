/*
 * lume-shot: a PNG of what the console screen shows (lume-launcher D12, the remote part
 * of P-57). Reads the framebuffer of the primary plane through DRM, so it captures the
 * launcher, the RetroArch menu or a game alike. Run as root, usually over the USB cable:
 *
 *   lume-shot [OUT.png]                       (default /tmp/lume-shot.png)
 *   lume-shot --raw FILE --size WxH --pitch N --format FOURCC OUT.png   (tests on the PC)
 *
 * No libdrm: the ioctls of the kernel uapi headers only. GETFB2 hands out the buffer
 * handle to CAP_SYS_ADMIN; the buffer is read through a PRIME dma-buf mmap, or through
 * MAP_DUMB when the driver cannot export it. Formats: XRGB8888, ARGB8888, XBGR8888,
 * ABGR8888 and RGB565, linear only; anything else is refused by name, never written wrong.
 * The image keeps the framebuffer orientation (a rotated panel shows rotated).
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>
#include <zlib.h>

#include <drm/drm.h>
#include <drm/drm_fourcc.h>
#include <drm/drm_mode.h>
#include <linux/dma-buf.h>

#define PROG "lume-shot"
#define MAX_PLANES 32

static int fail(const char *what)
{
	fprintf(stderr, PROG ": %s\n", what);
	return 1;
}

static void fourcc_name(uint32_t f, char out[5])
{
	for (int i = 0; i < 4; i++) {
		char c = (char)((f >> (8 * i)) & 0xff);
		out[i] = (c >= 32 && c < 127) ? c : '?';
	}
	out[4] = 0;
}

/* One row of the framebuffer to 8-bit RGB; 0 when the format is not supported. */
static int to_rgb(uint32_t format, const uint8_t *src, uint8_t *dst, uint32_t width)
{
	switch (format) {
	case DRM_FORMAT_XRGB8888:
	case DRM_FORMAT_ARGB8888:	/* little endian: B G R X */
		for (uint32_t x = 0; x < width; x++, src += 4, dst += 3) {
			dst[0] = src[2];
			dst[1] = src[1];
			dst[2] = src[0];
		}
		return 1;
	case DRM_FORMAT_XBGR8888:
	case DRM_FORMAT_ABGR8888:	/* R G B X */
		for (uint32_t x = 0; x < width; x++, src += 4, dst += 3) {
			dst[0] = src[0];
			dst[1] = src[1];
			dst[2] = src[2];
		}
		return 1;
	case DRM_FORMAT_RGB565:
		for (uint32_t x = 0; x < width; x++, src += 2, dst += 3) {
			uint16_t p = (uint16_t)(src[0] | (src[1] << 8));
			uint8_t r = (p >> 11) & 0x1f, g = (p >> 5) & 0x3f, b = p & 0x1f;

			dst[0] = (uint8_t)((r << 3) | (r >> 2));
			dst[1] = (uint8_t)((g << 2) | (g >> 4));
			dst[2] = (uint8_t)((b << 3) | (b >> 2));
		}
		return 1;
	}
	return 0;
}

static int bytes_per_pixel(uint32_t format)
{
	return format == DRM_FORMAT_RGB565 ? 2 : 4;
}

static void put32(uint8_t *p, uint32_t v)
{
	p[0] = v >> 24;
	p[1] = v >> 16;
	p[2] = v >> 8;
	p[3] = v;
}

static int chunk(FILE *f, const char *type, const uint8_t *data, uint32_t len)
{
	uint8_t hdr[8], crc[4];
	uLong c = crc32(0, (const Bytef *)type, 4);

	put32(hdr, len);
	memcpy(hdr + 4, type, 4);
	if (len)
		c = crc32(c, data, len);
	put32(crc, (uint32_t)c);
	return fwrite(hdr, 1, 8, f) == 8 && (!len || fwrite(data, 1, len, f) == len) &&
	       fwrite(crc, 1, 4, f) == 4;
}

/* PNG, 8-bit RGB, no filter, from the framebuffer rows. */
static int write_png(const char *out, const uint8_t *fb, uint32_t width, uint32_t height,
		     uint32_t pitch, uint32_t format)
{
	size_t row = (size_t)width * 3 + 1, raw_len = row * height;
	uint8_t *raw = malloc(raw_len), ihdr[13];
	uLongf z_len = compressBound(raw_len);
	uint8_t *z = malloc(z_len);
	char tmp[4096];
	FILE *f;
	int ok;

	if (!raw || !z)
		return fail("out of memory");
	for (uint32_t y = 0; y < height; y++) {
		raw[y * row] = 0;
		if (!to_rgb(format, fb + (size_t)y * pitch, raw + y * row + 1, width)) {
			char n[5];

			fourcc_name(format, n);
			fprintf(stderr, PROG ": pixel format %s not supported\n", n);
			return 1;
		}
	}
	if (compress2(z, &z_len, raw, raw_len, 6) != Z_OK)
		return fail("zlib compression failed");
	put32(ihdr, width);
	put32(ihdr + 4, height);
	ihdr[8] = 8;	/* bit depth */
	ihdr[9] = 2;	/* RGB */
	ihdr[10] = ihdr[11] = ihdr[12] = 0;
	snprintf(tmp, sizeof(tmp), "%s.tmp", out);
	f = fopen(tmp, "wb");
	if (!f)
		return fail("cannot write the image");
	ok = fwrite("\x89PNG\r\n\x1a\n", 1, 8, f) == 8 && chunk(f, "IHDR", ihdr, 13) &&
	     chunk(f, "IDAT", z, (uint32_t)z_len) && chunk(f, "IEND", NULL, 0);
	ok = (fclose(f) == 0) && ok;
	free(raw);
	free(z);
	if (!ok || rename(tmp, out) != 0) {
		unlink(tmp);
		return fail("cannot write the image");
	}
	return 0;
}

/* ---- the screen through DRM ---- */

struct shot {
	uint32_t fb_id, width, height, pitch, offset, format, handle;
	uint64_t modifier;
	int has_modifier;
};

/* The framebuffer on screen: the biggest one among the planes that scan out (the primary;
 * a cursor plane is small). 0 when this card shows nothing. */
static int find_fb(int fd, struct shot *s)
{
	uint32_t ids[MAX_PLANES];
	struct drm_mode_get_plane_res res = { .plane_id_ptr = (uintptr_t)ids,
					      .count_planes = MAX_PLANES };
	struct drm_set_client_cap cap = { .capability = DRM_CLIENT_CAP_UNIVERSAL_PLANES, .value = 1 };
	uint64_t best = 0;

	ioctl(fd, DRM_IOCTL_SET_CLIENT_CAP, &cap);
	if (ioctl(fd, DRM_IOCTL_MODE_GETPLANERESOURCES, &res) != 0)
		return 0;
	if (res.count_planes > MAX_PLANES)
		res.count_planes = MAX_PLANES;
	for (uint32_t i = 0; i < res.count_planes; i++) {
		struct drm_mode_get_plane p = { .plane_id = ids[i] };
		struct drm_mode_fb_cmd2 fb = { 0 };

		if (ioctl(fd, DRM_IOCTL_MODE_GETPLANE, &p) != 0 || !p.fb_id || !p.crtc_id)
			continue;
		fb.fb_id = p.fb_id;
		if (ioctl(fd, DRM_IOCTL_MODE_GETFB2, &fb) != 0)
			continue;
		if ((uint64_t)fb.width * fb.height <= best) {
			if (fb.handles[0]) {
				struct drm_gem_close c = { .handle = fb.handles[0] };

				ioctl(fd, DRM_IOCTL_GEM_CLOSE, &c);
			}
			continue;
		}
		if (best && s->handle) {
			struct drm_gem_close c = { .handle = s->handle };

			ioctl(fd, DRM_IOCTL_GEM_CLOSE, &c);
		}
		best = (uint64_t)fb.width * fb.height;
		s->fb_id = fb.fb_id;
		s->width = fb.width;
		s->height = fb.height;
		s->pitch = fb.pitches[0];
		s->offset = fb.offsets[0];
		s->format = fb.pixel_format;
		s->handle = fb.handles[0];
		s->has_modifier = !!(fb.flags & DRM_MODE_FB_MODIFIERS);
		s->modifier = fb.modifier[0];
	}
	return best > 0;
}

/* Maps the buffer for reading: PRIME dma-buf first, then MAP_DUMB. */
static uint8_t *map_fb(int fd, const struct shot *s, size_t len, int *dmabuf)
{
	struct drm_prime_handle prime = { .handle = s->handle, .flags = DRM_CLOEXEC | DRM_RDWR };
	struct drm_mode_map_dumb dumb = { .handle = s->handle };
	void *p;

	*dmabuf = -1;
	if (ioctl(fd, DRM_IOCTL_PRIME_HANDLE_TO_FD, &prime) == 0 ||
	    (prime.flags = DRM_CLOEXEC, ioctl(fd, DRM_IOCTL_PRIME_HANDLE_TO_FD, &prime) == 0)) {
		p = mmap(NULL, len, PROT_READ, MAP_SHARED, prime.fd, 0);
		if (p != MAP_FAILED) {
			struct dma_buf_sync sync = { .flags = DMA_BUF_SYNC_START | DMA_BUF_SYNC_READ };

			ioctl(prime.fd, DMA_BUF_IOCTL_SYNC, &sync);
			*dmabuf = prime.fd;
			return p;
		}
		close(prime.fd);
	}
	if (ioctl(fd, DRM_IOCTL_MODE_MAP_DUMB, &dumb) == 0) {
		p = mmap(NULL, len, PROT_READ, MAP_SHARED, fd, (off_t)dumb.offset);
		if (p != MAP_FAILED)
			return p;
	}
	return NULL;
}

static int capture(const char *out)
{
	char path[32], name[5];
	struct shot s = { 0 };
	int fd = -1;

	for (int n = 0; n < 8; n++) {
		snprintf(path, sizeof(path), "/dev/dri/card%d", n);
		fd = open(path, O_RDWR | O_CLOEXEC);
		if (fd < 0)
			continue;
		memset(&s, 0, sizeof(s));
		if (find_fb(fd, &s))
			break;
		close(fd);
		fd = -1;
	}
	if (fd < 0)
		return fail("no DRM device shows an image");
	fourcc_name(s.format, name);
	if (!s.handle) {
		close(fd);
		return fail("no access to the framebuffer (run as root)");
	}
	if (s.has_modifier && s.modifier != DRM_FORMAT_MOD_LINEAR) {
		fprintf(stderr, PROG ": framebuffer %ux%u %s is tiled or compressed (modifier 0x%llx)\n",
			s.width, s.height, name, (unsigned long long)s.modifier);
		close(fd);
		return 1;
	}
	{
		size_t len = (size_t)s.offset + (size_t)s.pitch * s.height;
		int dmabuf, rc;
		uint8_t *map = map_fb(fd, &s, len, &dmabuf);
		struct drm_gem_close c = { .handle = s.handle };

		if (!map) {
			ioctl(fd, DRM_IOCTL_GEM_CLOSE, &c);
			close(fd);
			return fail("the framebuffer cannot be mapped for reading");
		}
		rc = write_png(out, map + s.offset, s.width, s.height, s.pitch, s.format);
		if (dmabuf >= 0) {
			struct dma_buf_sync sync = { .flags = DMA_BUF_SYNC_END | DMA_BUF_SYNC_READ };

			ioctl(dmabuf, DMA_BUF_IOCTL_SYNC, &sync);
			close(dmabuf);
		}
		munmap(map, len);
		ioctl(fd, DRM_IOCTL_GEM_CLOSE, &c);
		close(fd);
		if (rc == 0)
			printf("%s: %ux%u %s from %s\n", out, s.width, s.height, name, path);
		return rc;
	}
}

/* --raw: a framebuffer from a file (tests on the PC) */
static int raw(int argc, char **argv)
{
	const char *file = NULL, *out = NULL, *fmt = NULL;
	uint32_t w = 0, h = 0, pitch = 0, format;
	uint8_t *buf;
	size_t len;
	FILE *f;
	int rc;

	for (int i = 1; i < argc; i++) {
		if (!strcmp(argv[i], "--raw") && i + 1 < argc)
			file = argv[++i];
		else if (!strcmp(argv[i], "--size") && i + 1 < argc)
			sscanf(argv[++i], "%ux%u", &w, &h);
		else if (!strcmp(argv[i], "--pitch") && i + 1 < argc)
			pitch = (uint32_t)strtoul(argv[++i], NULL, 10);
		else if (!strcmp(argv[i], "--format") && i + 1 < argc)
			fmt = argv[++i];
		else
			out = argv[i];
	}
	if (!file || !out || !fmt || strlen(fmt) != 4 || !w || !h)
		return fail("usage: --raw FILE --size WxH --format FOURCC [--pitch N] OUT.png");
	format = fourcc_code(fmt[0], fmt[1], fmt[2], fmt[3]);
	if (!pitch)
		pitch = w * (uint32_t)bytes_per_pixel(format);
	len = (size_t)pitch * h;
	buf = malloc(len);
	f = fopen(file, "rb");
	if (!buf || !f || fread(buf, 1, len, f) != len) {
		if (f)
			fclose(f);
		return fail("raw framebuffer too short");
	}
	fclose(f);
	rc = write_png(out, buf, w, h, pitch, format);
	free(buf);
	return rc;
}

int main(int argc, char **argv)
{
	for (int i = 1; i < argc; i++)
		if (!strcmp(argv[i], "--raw"))
			return raw(argc, argv);
	if (argc > 2 || (argc == 2 && argv[1][0] == '-'))
		return fail("usage: lume-shot [OUT.png]");
	return capture(argc == 2 ? argv[1] : "/tmp/lume-shot.png");
}
