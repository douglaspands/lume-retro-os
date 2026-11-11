/*
 * Teste de host do protocolo do controle do GA36 (tarefa 9.2): ga36mb-gamepad-proto.h,
 * extraído da kernel/patches/0006, compilado e executado por
 * tests/integration/test_kernel_drivers.py no container de cross.
 */
#include <stdio.h>
#include <string.h>
#include "ga36mb-gamepad-proto.h"

static int failures;

#define CHECK(cond) do { if (!(cond)) { printf("FAIL line %d: %s\n", __LINE__, #cond); failures++; } } while (0)

/* Alimenta um buffer inteiro; devolve quantos pacotes válidos saíram e guarda os últimos eixos. */
static int feed(struct gp_parser *p, const u8 *buf, int n, struct gp_axes *axes)
{
	int packets = 0;

	for (int i = 0; i < n; i++)
		packets += gp_feed(p, buf[i], axes);
	return packets;
}

int main(void)
{
	struct gp_parser p = { 0 };
	struct gp_axes axes = { 0 };

	/* pacote válido: centro e extremos; o analógico esquerdo é invertido */
	const u8 centre[8] = { 0xA7, 0x10, 0x00, 128, 128, 128, 128, 0x00 };
	CHECK(feed(&p, centre, 8, &axes) == 1);
	CHECK(axes.lx == 127 && axes.ly == 127 && axes.rx == 128 && axes.ry == 128);

	const u8 low[8] = { 0xA7, 0x10, 0x00, 0, 0, 0, 0, 0x00 };
	CHECK(feed(&p, low, 8, &axes) == 1);
	CHECK(axes.lx == 255 && axes.ly == 255 && axes.rx == 0 && axes.ry == 0);

	const u8 high[8] = { 0xA7, 0x10, 0x00, 255, 255, 255, 255, 0x00 };
	CHECK(feed(&p, high, 8, &axes) == 1);
	CHECK(axes.lx == 0 && axes.ly == 0 && axes.rx == 255 && axes.ry == 255);

	/* cabeçalho errado: nada sai, e o pacote bom seguinte é lido */
	const u8 bad_header[8] = { 0xA7, 0x11, 0, 1, 2, 3, 4, 0 };
	CHECK(feed(&p, bad_header, 8, &axes) == 0);
	CHECK(feed(&p, centre, 8, &axes) == 1);

	/* último byte errado */
	const u8 bad_tail[8] = { 0xA7, 0x10, 0, 1, 2, 3, 4, 0x55 };
	CHECK(feed(&p, bad_tail, 8, &axes) == 0);

	/* pacote truncado, lixo e um bom: ressincroniza no próximo A7 */
	const u8 truncated[5] = { 0xA7, 0x10, 0x00, 9, 9 };
	CHECK(feed(&p, truncated, 5, &axes) == 0);
	gp_reset(&p);
	const u8 noise[3] = { 0x01, 0x02, 0x03 };
	CHECK(feed(&p, noise, 3, &axes) == 0);
	CHECK(feed(&p, centre, 8, &axes) == 1);

	/* um A7 solto antes do cabeçalho não engole o pacote */
	const u8 stray[9] = { 0xA7, 0xA7, 0x10, 0x00, 128, 128, 128, 128, 0x00 };
	gp_reset(&p);
	CHECK(feed(&p, stray, 9, &axes) == 1);

	/* dois pacotes seguidos */
	u8 two[16];
	memcpy(two, centre, 8);
	memcpy(two + 8, high, 8);
	gp_reset(&p);
	CHECK(feed(&p, two, 16, &axes) == 2);

	/* handshake: A6 01 00 e os três bytes aleatórios; keepalive A6 01 01 01 01 01 */
	u8 hs[GP_HANDSHAKE_LEN];
	const u8 random[3] = { 0x11, 0x22, 0x33 };
	gp_make_handshake(hs, random);
	CHECK(hs[0] == 0xA6 && hs[1] == 0x01 && hs[2] == 0x00 && hs[3] == 0x11 && hs[4] == 0x22 && hs[5] == 0x33);
	CHECK(gp_keepalive[0] == 0xA6 && gp_keepalive[1] == 0x01 && gp_keepalive[2] == 0x01 && gp_keepalive[5] == 0x01);

	/* resposta: escolhe k e codifica o desafio como o microcontrolador */
	u8 answer[8] = { 0xA7, 0x10, 0x00, 0, 0, 0, 0x40, 0x00 };
	answer[3] = (u8)((hs[3] + 1) ^ answer[6] ^ 0x5A);
	answer[4] = (u8)((hs[4] + 2) ^ answer[6] ^ 0x5A);
	answer[5] = (u8)((hs[5] + 3) ^ answer[6] ^ 0x5A);
	CHECK(gp_answer_matches(answer, hs));
	answer[4] ^= 0x01;
	CHECK(!gp_answer_matches(answer, hs));

	CHECK(GP_BAUD == 9600 && GP_PACKET_LEN == 8);
	if (failures)
		return 1;
	puts("ok");
	return 0;
}
