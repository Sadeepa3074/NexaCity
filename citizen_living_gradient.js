/* NexaCity Living Gradient — subtle citizen-workspace atmosphere.
 * Lightweight 2D simplex-noise canvas; no external libraries or network assets.
 * Respects reduced-motion preferences and pauses when the page is hidden.
 */
(() => {
  'use strict';

  const canvas = document.getElementById('citizen-living-gradient');
  if (!(canvas instanceof HTMLCanvasElement)) return;

  const ctx = canvas.getContext('2d', { alpha: false });
  if (!ctx) return;

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const permutation = new Uint8Array(512);
  const seed = 0x4e657861;
  let randomState = seed >>> 0;
  const random = () => {
    randomState = (Math.imul(randomState, 1664525) + 1013904223) >>> 0;
    return randomState / 4294967296;
  };
  const basePermutation = Array.from({ length: 256 }, (_, index) => index);
  for (let i = basePermutation.length - 1; i > 0; i -= 1) {
    const j = Math.floor(random() * (i + 1));
    [basePermutation[i], basePermutation[j]] = [basePermutation[j], basePermutation[i]];
  }
  for (let i = 0; i < 512; i += 1) permutation[i] = basePermutation[i & 255];

  const gradients = [
    [1, 1], [-1, 1], [1, -1], [-1, -1],
    [1, 0], [-1, 0], [0, 1], [0, -1],
  ];
  const F2 = 0.3660254037844386;
  const G2 = 0.21132486540518713;
  const clamp = (value, min = 0, max = 1) => Math.max(min, Math.min(max, value));

  function simplex2D(x, y) {
    const skew = (x + y) * F2;
    const i = Math.floor(x + skew);
    const j = Math.floor(y + skew);
    const unskew = (i + j) * G2;
    const x0 = x - (i - unskew);
    const y0 = y - (j - unskew);
    const i1 = x0 > y0 ? 1 : 0;
    const j1 = x0 > y0 ? 0 : 1;
    const x1 = x0 - i1 + G2;
    const y1 = y0 - j1 + G2;
    const x2 = x0 - 1 + 2 * G2;
    const y2 = y0 - 1 + 2 * G2;
    const ii = i & 255;
    const jj = j & 255;

    const contribution = (px, py, hash) => {
      let attenuation = 0.5 - px * px - py * py;
      if (attenuation <= 0) return 0;
      attenuation *= attenuation;
      const gradient = gradients[hash & 7];
      return attenuation * attenuation * (gradient[0] * px + gradient[1] * py);
    };

    const h0 = permutation[ii + permutation[jj]];
    const h1 = permutation[ii + i1 + permutation[jj + j1]];
    const h2 = permutation[ii + 1 + permutation[jj + 1]];
    return 70 * (
      contribution(x0, y0, h0) +
      contribution(x1, y1, h1) +
      contribution(x2, y2, h2)
    );
  }

  const mix = (a, b, amount) => a + (b - a) * amount;
  const ivory = [245, 248, 241];
  const sage = [139, 177, 147];
  const paleLeaf = [205, 226, 207];
  const forest = [23, 76, 60];
  let width = 1;
  let height = 1;
  let frameId = 0;
  let lastFrame = 0;
  let elapsed = 0;
  let disposed = false;
  let imageData;

  function resize() {
    // Render at a small internal resolution; the browser smoothly scales it up.
    width = Math.max(120, Math.min(230, Math.round(window.innerWidth / 6)));
    height = Math.max(76, Math.min(150, Math.round(window.innerHeight / 7)));
    canvas.width = width;
    canvas.height = height;
    imageData = ctx.createImageData(width, height);
    render(0);
    lastFrame = 0;
    if (!reducedMotion.matches && !document.hidden) requestFrame();
  }

  function render(time) {
    if (!imageData) return;
    const pixels = imageData.data;
    const t = time * 0.000018;

    for (let y = 0; y < height; y += 1) {
      const v = y / Math.max(1, height - 1);
      for (let x = 0; x < width; x += 1) {
        const u = x / Math.max(1, width - 1);
        const broad = simplex2D(u * 2.8 + t, v * 2.2 - t * 0.48);
        const detail = simplex2D(u * 6.4 - t * 0.8 + 8.3, v * 5.2 + t * 0.58 - 3.1);
        const drift = simplex2D(u * 1.55 + 2.7, v * 1.35 - t * 0.25 + 6.1);
        const cloud = clamp(0.48 + broad * 0.26 + detail * 0.13 + drift * 0.12);
        // Keep the green clearly visible through the page whitespace while
        // preserving a light enough field for dark text and white cards.
        const leafMix = clamp(0.16 + cloud * 0.35, 0.16, 0.48);
        const forestMix = clamp((cloud - 0.57) * 0.22, 0, 0.095);

        // Soft upper-right glow with a restrained edge vignette.
        const gx = (u - 0.74) / 0.72;
        const gy = (v - 0.22) / 0.62;
        const glow = Math.exp(-(gx * gx + gy * gy) * 2.15) * 0.12;
        const edge = Math.pow(Math.max(Math.abs(u - 0.5) * 1.55, Math.abs(v - 0.5) * 1.6), 2.1);
        const vignette = 1 - clamp(edge * 0.06, 0, 0.06);

        const tint = [
          mix(paleLeaf[0], sage[0], cloud),
          mix(paleLeaf[1], sage[1], cloud),
          mix(paleLeaf[2], sage[2], cloud),
        ];
        let r = mix(ivory[0], tint[0], leafMix + glow * 0.30);
        let g = mix(ivory[1], tint[1], leafMix + glow * 0.42);
        let b = mix(ivory[2], tint[2], leafMix + glow * 0.24);
        r = mix(r, forest[0], forestMix);
        g = mix(g, forest[1], forestMix);
        b = mix(b, forest[2], forestMix);

        // Fine, stable film grain: visible only as a soft texture, not flicker.
        let hash = Math.imul(x + 1, 374761393) ^ Math.imul(y + 7, 668265263);
        hash = Math.imul(hash ^ (hash >>> 13), 1274126177);
        const grain = (((hash ^ (hash >>> 16)) >>> 0) / 4294967295 - 0.5) * 3.2;
        const offset = (y * width + x) * 4;
        pixels[offset] = clamp((r * vignette + grain) / 255, 0, 1) * 255;
        pixels[offset + 1] = clamp((g * vignette + grain) / 255, 0, 1) * 255;
        pixels[offset + 2] = clamp((b * vignette + grain) / 255, 0, 1) * 255;
        pixels[offset + 3] = 255;
      }
    }
    ctx.putImageData(imageData, 0, 0);
  }

  function requestFrame() {
    if (disposed || frameId || reducedMotion.matches || document.hidden) return;
    frameId = window.requestAnimationFrame(animate);
  }

  function animate(timestamp) {
    frameId = 0;
    if (disposed || reducedMotion.matches || document.hidden) return;
    if (timestamp - lastFrame >= 48) {
      elapsed += Math.min(64, timestamp - (lastFrame || timestamp));
      lastFrame = timestamp;
      render(elapsed);
    }
    requestFrame();
  }

  function handleVisibility() {
    if (document.hidden) {
      if (frameId) window.cancelAnimationFrame(frameId);
      frameId = 0;
      return;
    }
    if (reducedMotion.matches) render(0);
    else requestFrame();
  }

  function handleMotionPreference() {
    if (frameId) window.cancelAnimationFrame(frameId);
    frameId = 0;
    if (reducedMotion.matches) render(0);
    else requestFrame();
  }

  const onMotionChange = handleMotionPreference;
  if (typeof reducedMotion.addEventListener === 'function') reducedMotion.addEventListener('change', onMotionChange);
  else if (typeof reducedMotion.addListener === 'function') reducedMotion.addListener(onMotionChange);
  document.addEventListener('visibilitychange', handleVisibility);
  window.addEventListener('resize', resize, { passive: true });

  resize();

  window.addEventListener('pagehide', () => {
    disposed = true;
    if (frameId) window.cancelAnimationFrame(frameId);
  }, { once: true });
})();
