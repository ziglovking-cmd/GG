import * as THREE from 'three';

/** Procedural canvas texture — noisier materials without external assets. */
export function makeNoiseTexture({
  size = 256,
  base = [30, 36, 44],
  variance = 28,
  grain = 0.55,
  streaks = false,
} = {}) {
  const c = document.createElement('canvas');
  c.width = c.height = size;
  const ctx = c.getContext('2d');
  const img = ctx.createImageData(size, size);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const i = (y * size + x) * 4;
      const n =
        (Math.random() * 2 - 1) * variance * grain +
        (streaks ? Math.sin(x * 0.35 + y * 0.02) * 8 : 0) +
        Math.sin((x + y) * 0.07) * 6;
      img.data[i] = Math.max(0, Math.min(255, base[0] + n));
      img.data[i + 1] = Math.max(0, Math.min(255, base[1] + n * 0.9));
      img.data[i + 2] = Math.max(0, Math.min(255, base[2] + n * 0.75));
      img.data[i + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  return tex;
}

export function makeAsphaltTexture() {
  const tex = makeNoiseTexture({
    size: 512,
    base: [28, 30, 34],
    variance: 22,
    grain: 0.9,
    streaks: true,
  });
  tex.repeat.set(6, 14);
  return tex;
}

export function makeConcreteTexture() {
  const tex = makeNoiseTexture({
    size: 256,
    base: [72, 62, 54],
    variance: 18,
    grain: 0.7,
  });
  tex.repeat.set(3, 2);
  return tex;
}

export function makeFurTexture() {
  return makeNoiseTexture({
    size: 128,
    base: [180, 90, 42],
    variance: 35,
    grain: 1,
    streaks: true,
  });
}

export function makeGrassTexture() {
  const tex = makeNoiseTexture({
    size: 256,
    base: [42, 52, 28],
    variance: 24,
    grain: 0.85,
  });
  tex.repeat.set(4, 12);
  return tex;
}
