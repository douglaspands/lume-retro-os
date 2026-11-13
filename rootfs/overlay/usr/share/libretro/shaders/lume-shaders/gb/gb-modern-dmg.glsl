/*
   GB Modern DMG Shader
   Single-pass High-Clarity DMG-01 palette, sharp-bilinear scaling and reflective dot-matrix
   grid for the original Game Boy. Optimized for the Mali-400 of the R36S (GLSL ES, mediump,
   one texture read, no pow, no loops).

   - Works on luma, so a core that sends gray or a tinted palette lands on the same 4 tones.
   - S-curve on luma (pivot 0.35, as in gba-modern-remaster), then a piecewise map onto four
     olive anchors spaced at least 0.20 apart in Rec. 709 luma; TONE SEPARATION pulls values
     near a Game Boy level onto that level (smoothstep inside each segment).
   - Olive warmth shifts red up and blue down in proportion to green, keeping G > R > B.
   - Transition width follows the output scale: one output pixel at 2x and at 3.33x.
   - Dot-matrix grid: the one-output-pixel gap at the trailing edge of every game pixel is
     pulled toward the reflective olive substrate (T3 * 0.55), not toward black: dark dots get
     a lighter seam and the light background only a faint texture.
*/

#pragma parameter TONE_SEP "TONE SEPARATION" 0.50 0.0 1.0 0.05
#pragma parameter CONTRAST "S-CURVE Contrast" 0.20 0.0 1.0 0.05
#pragma parameter WARMTH "OLIVE WARMTH" 0.50 0.0 1.0 0.05
#pragma parameter SOFTNESS "PIXEL SOFTNESS" 0.05 0.0 1.0 0.05
#pragma parameter LCD_GRID "DOT MATRIX GRID (0=Off)" 0.22 0.0 1.0 0.05
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
uniform COMPAT_PRECISION float TONE_SEP;
uniform COMPAT_PRECISION float CONTRAST;
uniform COMPAT_PRECISION float WARMTH;
uniform COMPAT_PRECISION float SOFTNESS;
uniform COMPAT_PRECISION float LCD_GRID;
uniform COMPAT_PRECISION float BRIGHTNESS;
#else
#define TONE_SEP 0.50
#define CONTRAST 0.20
#define WARMTH 0.50
#define SOFTNESS 0.05
#define LCD_GRID 0.22
#define BRIGHTNESS 0.0
#endif

// High-Clarity DMG-01 palette: rgb(20,36,12), rgb(56,104,44), rgb(136,176,68), rgb(216,234,148)
const vec3 T0 = vec3(0.078431, 0.141176, 0.047059);   // ink, fully on (luma 0.12)
const vec3 T1 = vec3(0.219608, 0.407843, 0.172549);   // dark gray (luma 0.35)
const vec3 T2 = vec3(0.533333, 0.690196, 0.266667);   // light gray (luma 0.63)
const vec3 T3 = vec3(0.847059, 0.917647, 0.580392);   // background, pixel off (luma 0.88)

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

	// 2. Luma (Rec. 709) and S-curve, pivot 0.35
	COMPAT_PRECISION float L = dot(c, vec3(0.2126, 0.7152, 0.0722));
	L = clamp(L + CONTRAST * 2.0 * L * (1.0 - L) * (L - 0.35), 0.0, 1.0);

	// 3. Four tones: one weight per segment (0-1/3, 1/3-2/3, 2/3-1), each pulled toward its
	// ends by TONE_SEP, so a level near 1/3 or 2/3 lands on the anchor
	COMPAT_PRECISION vec3 w = clamp(vec3(L * 3.0) - vec3(0.0, 1.0, 2.0), 0.0, 1.0);
	w = mix(w, w * w * (3.0 - 2.0 * w), TONE_SEP);
	c = T0 + (T1 - T0) * w.x + (T2 - T1) * w.y + (T3 - T2) * w.z;
	c += (WARMTH - 0.5) * vec3(0.10, 0.0, -0.10) * c.g;

	// 4. Dot-matrix grid: the gap is the last output pixel of each game pixel (1 px, at most
	// 0.3 game pixel), box-filtered over the output pixel so it holds at 3.33x. The gap shows
	// the olive substrate: lighter than a dark dot, a little darker than the background.
	COMPAT_PRECISION float gap = min(px, 0.3);
	COMPAT_PRECISION vec2 pos = fract(TEX0.xy * TextureSize);
	COMPAT_PRECISION vec2 lo = pos - 0.5 * px;
	COMPAT_PRECISION vec2 hi = pos + 0.5 * px;
	COMPAT_PRECISION vec2 cover = clamp(min(hi, 1.0) - max(lo, 1.0 - gap), 0.0, gap)
		+ clamp(min(hi, 0.0) - max(lo, -gap), 0.0, gap);
	cover = min(cover / px, 1.0);
	COMPAT_PRECISION float g = 1.0 - (1.0 - cover.x) * (1.0 - cover.y);
	c = mix(c, T3 * 0.55, LCD_GRID * g);

	FragColor = vec4(clamp(c * (1.0 + BRIGHTNESS), 0.0, 1.0), texel.a);
}

#endif
