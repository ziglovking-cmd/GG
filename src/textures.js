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

/** Экран телефона с перепиской — «извини / я не напишу» */
export function makeChatTexture() {
  const c = document.createElement('canvas');
  c.width = 256;
  c.height = 512;
  const ctx = c.getContext('2d');
  ctx.fillStyle = '#0b0f16';
  ctx.fillRect(0, 0, 256, 512);
  // status bar
  ctx.fillStyle = '#121820';
  ctx.fillRect(0, 0, 256, 36);
  ctx.fillStyle = '#9ec7ff';
  ctx.font = '12px sans-serif';
  ctx.fillText('сегодня', 100, 24);

  const bubbles = [
    { me: false, y: 60, text: 'ты где?' },
    { me: true, y: 110, text: 'извини' },
    { me: false, y: 160, text: 'напиши' },
    { me: true, y: 210, text: 'я не напишу' },
    { me: false, y: 270, text: 'а чё так?' },
    { me: true, y: 330, text: '…' },
  ];
  ctx.font = 'bold 16px sans-serif';
  for (const b of bubbles) {
    const w = ctx.measureText(b.text).width + 28;
    const x = b.me ? 256 - w - 16 : 16;
    ctx.fillStyle = b.me ? '#1a4a7a' : '#1e2430';
    roundRect(ctx, x, b.y, w, 36, 12);
    ctx.fill();
    ctx.fillStyle = '#f2f6fc';
    ctx.fillText(b.text, x + 14, b.y + 24);
  }
  // input bar
  ctx.fillStyle = '#151a22';
  ctx.fillRect(0, 460, 256, 52);
  ctx.strokeStyle = '#2a3344';
  ctx.strokeRect(12, 472, 180, 28);
  ctx.fillStyle = '#556070';
  ctx.font = '12px sans-serif';
  ctx.fillText('сообщение', 20, 490);

  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.needsUpdate = true;
  return tex;
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

export function makeClockFaceTexture() {
  const c = document.createElement('canvas');
  c.width = c.height = 256;
  const ctx = c.getContext('2d');
  ctx.fillStyle = '#0e1420';
  ctx.beginPath();
  ctx.arc(128, 128, 120, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = '#9ec7ff';
  ctx.lineWidth = 4;
  ctx.stroke();
  ctx.fillStyle = '#f2f6fc';
  ctx.font = 'bold 22px sans-serif';
  ctx.textAlign = 'center';
  for (let i = 1; i <= 12; i++) {
    const a = (i / 12) * Math.PI * 2 - Math.PI / 2;
    ctx.fillText(String(i), 128 + Math.cos(a) * 90, 128 + Math.sin(a) * 90 + 8);
  }
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}
