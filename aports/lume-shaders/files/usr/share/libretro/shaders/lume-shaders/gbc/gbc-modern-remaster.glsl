/*
   GBC Modern Remaster Shader
   Single-pass vivid color, sharp-bilinear scaling and LCD pixel grid for Game Boy Color.
   Optimized for the Mali-400 of the R36S (GLSL ES, mediump, one texture read).
   Same pipeline as gba-modern-remaster, measured at 533x480 (3.33x, the GBC area of the
   640x480 screen) on raw RGB555 (Gambatte color correction off): PIXEL SOFTNESS 0.05 keeps
   1-pixel dithering sharp at 2x, and the ceiling is the top channel + 0.035, so nothing
   under 245 reaches 255.

   - Vibrance only pushes up what is under-saturated, so saturated reds stay put.
   - Highlight roll-off: the extra chroma fades as luma rises (filmic, like an HDR tone
     map), so bright colors stop glowing without ever dropping below their own chroma.
   - S-curve on luma (pivot 0.35) plus a highlight shoulder, hue preserved; saturated
     colors (blues) are not darkened and colors already at the top are not brightened.
   - Clip protection reduces chroma instead of cutting a channel.
   - Transition width follows the output scale: sharp at 2x and at 3.33x.
   - LCD grid: a one-output-pixel dark gap at the trailing edge of every game pixel,
     box-filtered over the output pixel so it holds at integer and fractional scales.
*/

#pragma parameter VIBRANCE "VIBRANCE" 0.45 0.0 1.0 0.05
#pragma parameter SATURATION "SATURATION" 1.10 0.5 1.3 0.01
#pragma parameter ROLLOFF "HIGHLIGHT ROLLOFF" 0.35 0.0 1.0 0.05
#pragma parameter CONTRAST "S-CURVE Contrast" 0.28 0.0 1.0 0.05
#pragma parameter HIGHLIGHT "HIGHLIGHT SHOULDER" 0.05 0.0 1.0 0.05
#pragma parameter SOFTNESS "PIXEL SOFTNESS" 0.05 0.0 1.0 0.05
#pragma parameter LCD_GRID "LCD GRID (0=Off)" 0.10 0.0 1.0 0.05
#pragma parameter BRIGHTNESS "BRIGHTNESS" 0.0 -0.30 0.30 0.01

#if defined(VERTEX)

#if __VERSION__ >= 130
#define COMPAT_VARYING out
#define COMPAT_ATTRIBUTE in
#define COMPAT_TEXTURE texture
#else
#define COMPAT_VARYING varying
#define COMPAT_ATTRIBUTE attribute
#define COMPAT_TEXTURE texture2D
#endif

COMPAT_ATTRIBUTE vec4 VertexCoord;
COMPAT_ATTRIBUTE vec4 COLOR;
COMPAT_ATTRIBUTE vec4 TexCoord;
COMPAT_VARYING vec4 COL0;
COMPAT_VARYING vec4 TEX0;

uniform mat4 MVPMatrix;
uniform int FrameDirection;
uniform int FrameCount;
uniform vec2 OutputSize;
uniform vec2 TextureSize;
uniform vec2 InputSize;

void main()
{
   gl_Position = MVPMatrix * VertexCoord;
   COL0 = COLOR;
   TEX0.xy = TexCoord.xy;
}

#elif defined(FRAGMENT)

#if __VERSION__ >= 130
#define COMPAT_VARYING in
#define COMPAT_TEXTURE texture
out vec4 FragColor;
#else
#define COMPAT_VARYING varying
#define COMPAT_TEXTURE texture2D
#define FragColor gl_FragColor
#endif

#ifdef GL_ES
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
#define COMPAT_PRECISION mediump
#else
#define COMPAT_PRECISION
#endif

COMPAT_VARYING vec4 COL0;
COMPAT_VARYING vec4 TEX0;

uniform sampler2D Texture;
uniform COMPAT_PRECISION vec2 OutputSize;
uniform COMPAT_PRECISION vec2 TextureSize;
uniform COMPAT_PRECISION vec2 InputSize;
uniform int FrameDirection;
uniform int FrameCount;

#ifdef PARAMETER_UNIFORM
uniform COMPAT_PRECISION float VIBRANCE;
uniform COMPAT_PRECISION float SATURATION;
uniform COMPAT_PRECISION float ROLLOFF;
uniform COMPAT_PRECISION float CONTRAST;
uniform COMPAT_PRECISION float HIGHLIGHT;
uniform COMPAT_PRECISION float SOFTNESS;
uniform COMPAT_PRECISION float LCD_GRID;
uniform COMPAT_PRECISION float BRIGHTNESS;
#else
#define VIBRANCE 0.45
#define SATURATION 1.10
#define ROLLOFF 0.35
#define CONTRAST 0.28
#define HIGHLIGHT 0.05
#define SOFTNESS 0.05
#define LCD_GRID 0.10
#define BRIGHTNESS 0.0
#endif

void main()
{
	// 1. Sharp-bilinear: the transition lasts about one output pixel at any scale
	COMPAT_PRECISION float px = InputSize.x / OutputSize.x;   // output pixel, in game pixels
	COMPAT_PRECISION float width = max(mix(px, 1.0, SOFTNESS), 0.0001);

	COMPAT_PRECISION vec2 p = TEX0.xy * TextureSize - 0.5;
	COMPAT_PRECISION vec2 i = floor(p);
	COMPAT_PRECISION vec2 f = clamp((fract(p) - 0.5) / width + 0.5, 0.0, 1.0);

	vec4 texel = COMPAT_TEXTURE(Texture, (i + 0.5 + f) / TextureSize);
	COMPAT_PRECISION vec3 c = texel.rgb;

	// 2. Luma (Rec. 709) and saturation of the pixel
	COMPAT_PRECISION float L = dot(c, vec3(0.2126, 0.7152, 0.0722));
	COMPAT_PRECISION float mx = max(c.r, max(c.g, c.b));
	COMPAT_PRECISION float mn = min(c.r, min(c.g, c.b));
	COMPAT_PRECISION float sat = (mx - mn) / max(mx, 0.001);

	// 3. Chroma gain: vibrance lifts what is muted, SATURATION is global, and the
	// roll-off takes back only the extra chroma as luma rises, so a bright yellow keeps
	// at least its own chroma (hs also feeds the shoulder below). The gain pivots on
	// luma in darks and mids and on the top channel in brights: pale skin and pastels
	// gain color by deepening the weaker channels, never by glowing, and hue holds.
	// Vibrance fades near gray, so whites and beige backgrounds are not tinted.
	COMPAT_PRECISION float hs = smoothstep(0.5, 1.0, L);
	COMPAT_PRECISION float gain = (1.0 + VIBRANCE * min(1.0 - sat, 4.0 * sat * (1.0 - sat))) * SATURATION;
	COMPAT_PRECISION float anchor = mix(L, mx, hs);
	c = max(vec3(anchor) + (c - anchor) * (1.0 + (gain - 1.0) * (1.0 - ROLLOFF * hs)), 0.0);

	// 4. S-curve and highlight shoulder on luma, scaling all channels by the same ratio.
	// The darkening fades with saturation (deep blues keep their strength), and a color
	// whose top channel already reaches the ceiling is not brightened (yellow stays yellow).
	COMPAT_PRECISION float k = (L
		+ CONTRAST * 2.0 * L * (1.0 - L) * (L - 0.35)
		+ HIGHLIGHT * hs * (1.0 - L) * 0.5) / max(L, 0.001);
	k = max(k, mix(k, 1.0, sat * sat));
	COMPAT_PRECISION float ceiling = min(1.0, mx + 0.035);
	k = min(k, max(ceiling / max(max(c.r, max(c.g, c.b)), 0.001), 1.0));
	c *= k;
	COMPAT_PRECISION float L2 = dot(c, vec3(0.2126, 0.7152, 0.0722));

	// 5. Clip protection: pull chroma toward luma until the top channel fits
	COMPAT_PRECISION float top = max(c.r, max(c.g, c.b));
	COMPAT_PRECISION float t = (top > ceiling) ? clamp((ceiling - L2) / max(top - L2, 0.0001), 0.0, 1.0) : 1.0;
	c = vec3(L2) + (c - L2) * t;

	// 6. LCD grid: the gap is the last output pixel of each game pixel (1 px, at most
	// 0.3 game pixel). Coverage is the overlap of this output pixel with the gap of its
	// own game pixel and with the gap of the previous one, so it stays correct when the
	// scale is not an integer.
	COMPAT_PRECISION float gap = min(px, 0.3);
	COMPAT_PRECISION vec2 pos = fract(TEX0.xy * TextureSize);
	COMPAT_PRECISION vec2 lo = pos - 0.5 * px;
	COMPAT_PRECISION vec2 hi = pos + 0.5 * px;
	COMPAT_PRECISION vec2 cover = clamp(min(hi, 1.0) - max(lo, 1.0 - gap), 0.0, gap)
		+ clamp(min(hi, 0.0) - max(lo, -gap), 0.0, gap);
	cover = min(cover / px, 1.0);
	COMPAT_PRECISION vec2 lit = 1.0 - LCD_GRID * cover;
	c *= lit.x * lit.y * (1.0 + BRIGHTNESS);

	FragColor = vec4(clamp(c, 0.0, 1.0), texel.a);
}

#endif
