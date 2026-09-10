/**
 * HawaGuide - PEVI Color System
 *
 * Maps the Delhi NCR Base PEVI range (3.12 to 7.07) to a 4-stop hue rotation:
 *   Teal (#6EE7D8) → Lime-green (#86EFAC) → Amber (#F4A261) → Coral (#E76F51)
 *
 * Uses an ease-in-out power curve so that even a 0.1 PEVI difference in a
 * clustered range produces a visibly distinct shade — not just at the extremes.
 *
 * Used uniformly across the application for Canvas particle rendering AND
 * Location card ambient washes, exposure bars, and accent colors.
 */

interface RGB {
  r: number;
  g: number;
  b: number;
}

// 4-stop palette: clean → moderate-clean → moderate-high → highest risk
const STOPS: RGB[] = [
  { r: 110, g: 231, b: 216 }, // #6EE7D8 — Teal       (cleanest)
  { r: 134, g: 239, b: 172 }, // #86EFAC — Lime-green (low-moderate)
  { r: 244, g: 162, b: 97  }, // #F4A261 — Amber      (moderate-high)
  { r: 231, g: 111, b: 81  }, // #E76F51 — Coral      (highest risk)
];

const COLOR_NEUTRAL: RGB = { r: 71, g: 85, b: 105 }; // #475569 — Data unavailable

function lerp(a: number, b: number, t: number): number {
  return Math.round(a + (b - a) * t);
}

function interpolateRgb(c1: RGB, c2: RGB, t: number): RGB {
  return {
    r: lerp(c1.r, c2.r, t),
    g: lerp(c1.g, c2.g, t),
    b: lerp(c1.b, c2.b, t),
  };
}

/**
 * Ease-in-out power curve: exaggerates differences in the middle of the range,
 * making small PEVI deltas produce visually distinct hues in clustered data.
 * power=1.8 gives a noticeable but not extreme curve.
 */
function easeInOut(t: number, power = 1.8): number {
  if (t < 0.5) {
    return 0.5 * Math.pow(2 * t, power);
  }
  return 1 - 0.5 * Math.pow(2 * (1 - t), power);
}

/**
 * Returns raw RGB for a given PEVI value in [minPevi, maxPevi].
 * Applies an ease-in-out curve before mapping across the 4-stop palette.
 */
export function getPeviRgb(
  peviValue: number | null | undefined,
  minPevi = 3.12,
  maxPevi = 7.07
): RGB {
  if (peviValue === null || peviValue === undefined || isNaN(peviValue)) {
    return COLOR_NEUTRAL;
  }

  // Normalize to [0, 1], then apply ease curve for perceptual non-linearity
  const clamped = Math.max(minPevi, Math.min(maxPevi, peviValue));
  const linear = (clamped - minPevi) / (maxPevi - minPevi || 1);
  const t = easeInOut(linear);

  // Map eased t across 3 segments of the 4-stop palette
  const segCount = STOPS.length - 1; // 3
  const scaled = t * segCount;
  const segIndex = Math.min(Math.floor(scaled), segCount - 1);
  const segT = scaled - segIndex;

  return interpolateRgb(STOPS[segIndex], STOPS[segIndex + 1], segT);
}

/**
 * Returns a CSS rgb/rgba string for a given PEVI value.
 */
export function getPeviColor(
  peviValue: number | null | undefined,
  minPevi = 3.12,
  maxPevi = 7.07,
  alpha?: number
): string {
  const rgb = getPeviRgb(peviValue, minPevi, maxPevi);
  if (alpha !== undefined) {
    const safeAlpha = Math.max(0, Math.min(1, alpha));
    return `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${safeAlpha})`;
  }
  return `rgb(${rgb.r}, ${rgb.g}, ${rgb.b})`;
}

/**
 * Returns the normalized [0, 1] position of a PEVI value in the range.
 * Used to drive the exposure bar width.
 */
export function getPeviNormalized(
  peviValue: number | null | undefined,
  minPevi = 3.12,
  maxPevi = 7.07
): number {
  if (peviValue === null || peviValue === undefined || isNaN(peviValue)) return 0;
  const clamped = Math.max(minPevi, Math.min(maxPevi, peviValue));
  return (clamped - minPevi) / (maxPevi - minPevi || 1);
}
