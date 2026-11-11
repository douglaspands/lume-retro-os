/*
 * r36os-devmem: read or write one 32-bit hardware register through /dev/mem.
 *
 *   r36os-devmem [-f FILE] ADDR [VALUE]
 *
 * Prints the register value as 0x%08x (after the write, when VALUE is given). The access
 * is an aligned 32-bit load/store on an mmap()ed page, which is what a device register
 * needs (read()/write() on /dev/mem are not reliable for registers on ARM). The busybox
 * of the image has no devmem applet. Root only, like /dev/mem itself.
 *
 * -f FILE replaces /dev/mem by a regular file, so the tool can be tested without hardware.
 */
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

static int usage(void)
{
	fprintf(stderr, "usage: r36os-devmem [-f FILE] ADDR [VALUE]\n");
	return 2;
}

static int parse(const char *s, unsigned long long *out)
{
	char *end = NULL;

	errno = 0;
	*out = strtoull(s, &end, 0);
	return errno == 0 && end != s && *end == '\0';
}

int main(int argc, char **argv)
{
	const char *path = "/dev/mem";
	unsigned long long addr, value = 0;
	int write_it = 0, i = 1, fd;
	long page;
	off_t base;
	void *map;
	volatile uint32_t *reg;

	if (argc > 2 && strcmp(argv[1], "-f") == 0) {
		path = argv[2];
		i = 3;
	}
	if (i >= argc || argc - i > 2)
		return usage();
	if (!parse(argv[i], &addr) || (addr & 3))
		return usage();
	if (argc - i == 2) {
		if (!parse(argv[i + 1], &value) || value > 0xffffffffULL)
			return usage();
		write_it = 1;
	}

	page = sysconf(_SC_PAGESIZE);
	base = (off_t)(addr & ~((unsigned long long)page - 1));
	fd = open(path, (write_it ? O_RDWR : O_RDONLY) | O_SYNC);
	if (fd < 0) {
		perror(path);
		return 1;
	}
	map = mmap(NULL, (size_t)page, PROT_READ | (write_it ? PROT_WRITE : 0), MAP_SHARED, fd, base);
	if (map == MAP_FAILED) {
		perror("mmap");
		close(fd);
		return 1;
	}
	reg = (volatile uint32_t *)((char *)map + (addr - (unsigned long long)base));
	if (write_it)
		*reg = (uint32_t)value;
	printf("0x%08x\n", (unsigned)*reg);

	munmap(map, (size_t)page);
	close(fd);
	return 0;
}
