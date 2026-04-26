/**
 * Stable visual identity helpers for spatial surfaces.
 *
 * Keep this independent from tile components so layers, minimaps, clusters,
 * and backend-contract tests do not import presentation components just to
 * share channel colors.
 */

export function hashId(id: string): number {
  let h = 0;
  for (let i = 0; i < id.length; i++) {
    h = (h * 31 + id.charCodeAt(i)) >>> 0;
  }
  return h;
}

export function channelHue(id: string): number {
  return hashId(id) % 360;
}

export function dotColor(id: string): string {
  return `hsl(${channelHue(id)}, 55%, 58%)`;
}
