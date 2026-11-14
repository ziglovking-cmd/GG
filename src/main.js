import * as THREE from 'three';
import { CUES, DURATION } from './lyrics.js';

const canvas = document.getElementById('stage');
const lyricNow = document.getElementById('lyric-now');
const lyricPrev = document.getElementById('lyric-prev');
const lyricHint = document.getElementById('lyric-hint');
const playBtn = document.getElementById('play-btn');
const progressEl = document.getElementById('progress');
const timeEl = document.getElementById('time');

const BPM = 168;
const BEAT = 60 / BPM;

let playing = false;
let startMs = 0;
let elapsed = 0;
let cueIndex = 0;
let prevLyric = '';

const renderer = new THREE.WebGLRenderer({
  canvas,
  antialias: true,
  alpha: false,
  powerPreference: 'high-performance',
});
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
renderer.setClearColor(0x06101c, 1);

const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(0x06101c, 0.045);

const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 120);
camera.position.set(0, 1.4, 8.5);

const ambient = new THREE.AmbientLight(0x6ea0d8, 0.55);
const key = new THREE.DirectionalLight(0xcfe4ff, 1.15);
key.position.set(4, 8, 6);
const rim = new THREE.PointLight(0xff4d3a, 1.4, 30);
rim.position.set(-4, 1, 2);
scene.add(ambient, key, rim);

// Wave floor
const waveGeo = new THREE.PlaneGeometry(40, 40, 96, 96);
const waveMat = new THREE.MeshStandardMaterial({
  color: 0x1d4f8c,
  emissive: 0x12325a,
  metalness: 0.45,
  roughness: 0.4,
  flatShading: true,
  wireframe: false,
});
const wave = new THREE.Mesh(waveGeo, waveMat);
wave.rotation.x = -Math.PI / 2;
wave.position.y = -1.35;
scene.add(wave);

const waveWire = new THREE.Mesh(
  waveGeo,
  new THREE.MeshBasicMaterial({
    color: 0x9ec7ff,
    wireframe: true,
    transparent: true,
    opacity: 0.12,
  })
);
waveWire.rotation.copy(wave.rotation);
waveWire.position.copy(wave.position);
waveWire.position.y += 0.02;
scene.add(waveWire);
const wavePos = waveGeo.attributes.position;

// Particle field
const COUNT = 500;
const pGeo = new THREE.BufferGeometry();
const pPos = new Float32Array(COUNT * 3);
for (let i = 0; i < COUNT; i++) {
  pPos[i * 3] = (Math.random() - 0.5) * 28;
  pPos[i * 3 + 1] = Math.random() * 12 - 1;
  pPos[i * 3 + 2] = (Math.random() - 0.5) * 28;
}
pGeo.setAttribute('position', new THREE.BufferAttribute(pPos, 3));
const particles = new THREE.Points(
  pGeo,
  new THREE.PointsMaterial({
    color: 0x9ec7ff,
    size: 0.045,
    transparent: true,
    opacity: 0.75,
    depthWrite: false,
  })
);
scene.add(particles);

const wordRoot = new THREE.Group();
scene.add(wordRoot);

/** @type {{ mesh: THREE.Mesh, born: number, life: number, vx: number, vy: number, vz: number, spin: number }[]} */
const liveWords = [];

function makeWordTexture(text, mode) {
  const canvasEl = document.createElement('canvas');
  const ctx = canvasEl.getContext('2d');
  const pad = 48;
  const fontSize = mode === 'chorus' || mode === 'stamp' ? 96 : mode === 'impact' ? 88 : 72;
  const family =
    mode === 'line' || mode === 'impact'
      ? '"Instrument Serif", Georgia, serif'
      : '"Bebas Neue", Impact, sans-serif';

  ctx.font = `${mode === 'line' ? 'italic ' : ''}700 ${fontSize}px ${family}`;
  const metrics = ctx.measureText(text);
  canvasEl.width = Math.ceil(metrics.width + pad * 2);
  canvasEl.height = Math.ceil(fontSize * 1.55 + pad);

  ctx.clearRect(0, 0, canvasEl.width, canvasEl.height);
  ctx.font = `${mode === 'line' ? 'italic ' : ''}700 ${fontSize}px ${family}`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillStyle =
    mode === 'glitch' ? '#ff4d3a' : mode === 'chorus' ? '#9ec7ff' : '#f2f6fc';
  ctx.shadowColor = mode === 'glitch' ? '#ff4d3a' : '#9ec7ff';
  ctx.shadowBlur = mode === 'impact' || mode === 'stamp' ? 28 : 14;
  ctx.fillText(text, canvasEl.width / 2, canvasEl.height / 2);

  const tex = new THREE.CanvasTexture(canvasEl);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.needsUpdate = true;
  return { tex, aspect: canvasEl.width / canvasEl.height };
}

function spawnWord(text, mode, t) {
  const { tex, aspect } = makeWordTexture(text, mode);
  const h = mode === 'stamp' ? 2.1 : mode === 'impact' ? 1.75 : mode === 'chorus' ? 1.45 : 1.05;
  const geo = new THREE.PlaneGeometry(h * aspect, h);
  const mat = new THREE.MeshBasicMaterial({
    map: tex,
    transparent: true,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
  const mesh = new THREE.Mesh(geo, mat);

  const angle = (Math.random() - 0.5) * Math.PI * 0.9;
  const radius = mode === 'chorus' ? 1.2 + Math.random() * 2.2 : 0.4 + Math.random() * 1.6;
  mesh.position.set(
    Math.sin(angle) * radius,
    mode === 'stamp' ? 1.8 : 0.6 + Math.random() * 1.8,
    -1.5 - Math.random() * 2.5
  );
  mesh.rotation.y = angle * 0.35;
  mesh.rotation.x = (Math.random() - 0.5) * 0.25;

  wordRoot.add(mesh);
  liveWords.push({
    mesh,
    born: t,
    life: mode === 'chorus' ? 2.2 : mode === 'stamp' ? 3.2 : 2.8,
    vx: Math.sin(angle) * (mode === 'chorus' ? 1.8 : 0.55),
    vy: mode === 'impact' ? 0.9 : 0.25 + Math.random() * 0.4,
    vz: mode === 'chorus' ? -1.4 : -0.55,
    spin: (Math.random() - 0.5) * 1.2,
  });

  // burst duplicates for chorus/impact
  if (mode === 'chorus' || mode === 'impact') {
    const parts = text.split(/\s+/).filter(Boolean);
    for (const part of parts.slice(0, 4)) {
      if (part === text && parts.length === 1) continue;
      const burst = makeWordTexture(part, mode);
      const bh = 0.55;
      const bmesh = new THREE.Mesh(
        new THREE.PlaneGeometry(bh * burst.aspect, bh),
        new THREE.MeshBasicMaterial({
          map: burst.tex,
          transparent: true,
          depthWrite: false,
          side: THREE.DoubleSide,
          opacity: 0.9,
        })
      );
      const a2 = Math.random() * Math.PI * 2;
      bmesh.position.set(Math.cos(a2) * 0.3, 1.2, -1);
      wordRoot.add(bmesh);
      liveWords.push({
        mesh: bmesh,
        born: t,
        life: 1.8,
        vx: Math.cos(a2) * 2.4,
        vy: 0.6 + Math.random(),
        vz: Math.sin(a2) * 2.4 - 0.5,
        spin: (Math.random() - 0.5) * 3,
      });
    }
  }
}

function setHudLyric(text, mode) {
  lyricPrev.textContent = prevLyric;
  prevLyric = text;
  lyricNow.textContent = text;
  lyricNow.className = `lyric-now is-${mode}`;
  // reflow animation
  void lyricNow.offsetWidth;
  lyricNow.className = `lyric-now is-${mode}`;
}

function formatTime(sec) {
  const s = Math.max(0, Math.min(DURATION, sec));
  const m = Math.floor(s / 60);
  const r = Math.floor(s % 60);
  return `${m}:${String(r).padStart(2, '0')}`;
}

function resize() {
  const w = window.innerWidth;
  const h = window.innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}

function updateWave(t, intensity) {
  for (let i = 0; i < wavePos.count; i++) {
    const x = wavePos.getX(i);
    const y = wavePos.getY(i);
    const z =
      Math.sin(x * 0.55 + t * 1.6) * 0.38 * intensity +
      Math.cos(y * 0.4 - t * 1.1) * 0.3 * intensity +
      Math.sin((x + y) * 0.25 + t * 2.2) * 0.14 * intensity;
    wavePos.setZ(i, z);
  }
  wavePos.needsUpdate = true;
  waveGeo.computeVertexNormals();
}

function updateWords(t, dt) {
  for (let i = liveWords.length - 1; i >= 0; i--) {
    const w = liveWords[i];
    const age = t - w.born;
    if (age > w.life) {
      wordRoot.remove(w.mesh);
      w.mesh.geometry.dispose();
      w.mesh.material.map?.dispose();
      w.mesh.material.dispose();
      liveWords.splice(i, 1);
      continue;
    }
    const fade = age < 0.2 ? age / 0.2 : age > w.life - 0.45 ? (w.life - age) / 0.45 : 1;
    w.mesh.material.opacity = Math.max(0, fade);
    w.mesh.position.x += w.vx * dt;
    w.mesh.position.y += w.vy * dt;
    w.mesh.position.z += w.vz * dt;
    w.mesh.rotation.z += w.spin * dt;
    w.mesh.rotation.y += w.spin * 0.35 * dt;
    w.vy -= 0.15 * dt;
  }
}

function processCues(t) {
  while (cueIndex < CUES.length && CUES[cueIndex].t <= t) {
    const cue = CUES[cueIndex++];
    setHudLyric(cue.text, cue.mode);
    spawnWord(cue.text, cue.mode, t);
    // extra floating words for longer lines
    if (cue.mode === 'line') {
      const bits = cue.text.split(/\s+/);
      if (bits.length > 2) {
        const pick = bits[Math.floor(Math.random() * bits.length)];
        spawnWord(pick, 'chorus', t);
      }
    }
  }
}

let lastFrame = performance.now();

function frame(now) {
  const dt = Math.min(0.05, (now - lastFrame) / 1000);
  lastFrame = now;

  if (playing) {
    elapsed = (now - startMs) / 1000;
    if (elapsed >= DURATION) {
      playing = false;
      elapsed = DURATION;
      playBtn.textContent = 'Replay';
      document.body.classList.remove('is-playing');
    }
  }

  const intensity = playing ? 1.15 + Math.sin(elapsed * Math.PI * 2 * (BPM / 60)) * 0.35 : 0.55;
  updateWave(now * 0.001, intensity);
  updateWords(elapsed, dt);
  if (playing) processCues(elapsed);

  particles.rotation.y = now * 0.00005;
  camera.position.x = Math.sin(now * 0.00018) * 0.55;
  camera.position.y = 1.35 + Math.sin(now * 0.0003) * 0.15;
  camera.lookAt(0, 1.1, 0);
  rim.intensity = 1.1 + Math.sin(now * 0.004) * 0.4;

  const pct = (elapsed / DURATION) * 100;
  progressEl.style.width = `${pct}%`;
  timeEl.textContent = `${formatTime(elapsed)} / 2:17`;

  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}

async function boot() {
  await document.fonts.ready;
  resize();
  requestAnimationFrame(frame);
}

function togglePlay() {
  if (!playing) {
    if (elapsed >= DURATION - 0.05) {
      elapsed = 0;
      cueIndex = 0;
      prevLyric = '';
      lyricPrev.textContent = '';
      // clear leftover words
      for (const w of liveWords) {
        wordRoot.remove(w.mesh);
        w.mesh.geometry.dispose();
        w.mesh.material.map?.dispose();
        w.mesh.material.dispose();
      }
      liveWords.length = 0;
    }
    playing = true;
    startMs = performance.now() - elapsed * 1000;
    playBtn.textContent = 'Pause';
    document.body.classList.add('is-playing');
    if (lyricHint) lyricHint.textContent = '';
  } else {
    playing = false;
    playBtn.textContent = 'Play lyrics';
    document.body.classList.remove('is-playing');
  }
}

playBtn.addEventListener('click', togglePlay);
window.addEventListener('keydown', (e) => {
  if (e.code === 'Space') {
    e.preventDefault();
    togglePlay();
  }
});
window.addEventListener('resize', resize);

boot();
