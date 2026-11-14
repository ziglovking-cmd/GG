import * as THREE from 'three';
import { AUDIO_SRC, CUES, DURATION, EVENTS, LYRIC_LAG } from './lyrics.js';
import { createFigure, createPartyLights, createProps } from './figure.js';

const canvas = document.getElementById('stage');
const lyricNow = document.getElementById('lyric-now');
const lyricPrev = document.getElementById('lyric-prev');
const lyricHint = document.getElementById('lyric-hint');
const playBtn = document.getElementById('play-btn');
const progressEl = document.getElementById('progress');
const timeEl = document.getElementById('time');
const sceneLabel = document.getElementById('scene-label');
const seekEl = document.getElementById('seek');

/** Web Audio — sample clock stays locked to real playback. */
let audioCtx = null;
/** @type {AudioBuffer | null} */
let audioBuffer = null;
/** @type {AudioBufferSourceNode | null} */
let sourceNode = null;
let audioReady = false;
let playing = false;
let elapsed = 0;
/** buffer offset (sec) when current source started */
let offsetWhenStarted = 0;
/** performance.now() when current source started — lyrics rail */
let startedAtPerf = 0;
/** position while paused */
let pausedAt = 0;
let prevLyric = '';
let sceneName = 'horizon';
let flash = 0;
let beatKick = 0;
/** @type {null | typeof CUES[number]} */
let shownCue = null;
let lastScene = '';
let spawnedKey = '';

const renderer = new THREE.WebGLRenderer({
  canvas,
  antialias: true,
  alpha: false,
  powerPreference: 'high-performance',
});
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
renderer.setClearColor(0x06101c, 1);

const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(0x06101c, 0.042);

const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 120);
camera.position.set(0, 1.5, 8.8);

const ambient = new THREE.AmbientLight(0x6ea0d8, 0.5);
const key = new THREE.DirectionalLight(0xcfe4ff, 1.1);
key.position.set(4, 8, 6);
const rim = new THREE.PointLight(0xff4d3a, 1.2, 30);
rim.position.set(-4, 1.2, 2);
scene.add(ambient, key, rim);

const waveGeo = new THREE.PlaneGeometry(40, 40, 96, 96);
const waveMat = new THREE.MeshStandardMaterial({
  color: 0x1d4f8c,
  emissive: 0x12325a,
  metalness: 0.45,
  roughness: 0.4,
  flatShading: true,
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
    opacity: 0.1,
  })
);
waveWire.rotation.copy(wave.rotation);
waveWire.position.copy(wave.position);
waveWire.position.y += 0.02;
scene.add(waveWire);
const wavePos = waveGeo.attributes.position;

const COUNT = 420;
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
    opacity: 0.7,
    depthWrite: false,
  })
);
scene.add(particles);

const figure = createFigure();
const props = createProps();
const party = createPartyLights();
scene.add(figure, props, party);

// Soft ground disc under figure so silhouette reads against the wave
const ground = new THREE.Mesh(
  new THREE.CircleGeometry(1.1, 32),
  new THREE.MeshBasicMaterial({
    color: 0x9ec7ff,
    transparent: true,
    opacity: 0.12,
  })
);
ground.rotation.x = -Math.PI / 2;
ground.position.set(0, -1.32, -2.2);
scene.add(ground);
figure.userData.ground = ground;

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
  if (!text) return;
  const { tex, aspect } = makeWordTexture(text, mode);
  const h = mode === 'stamp' ? 2.0 : mode === 'impact' ? 1.7 : mode === 'chorus' ? 1.4 : 1.0;
  const mesh = new THREE.Mesh(
    new THREE.PlaneGeometry(h * aspect, h),
    new THREE.MeshBasicMaterial({
      map: tex,
      transparent: true,
      depthWrite: false,
      side: THREE.DoubleSide,
    })
  );
  const angle = (Math.random() - 0.5) * Math.PI * 0.9;
  const radius = mode === 'chorus' ? 1.4 + Math.random() * 2.2 : 0.5 + Math.random() * 1.5;
  mesh.position.set(
    Math.sin(angle) * radius,
    mode === 'stamp' ? 2.0 : 0.7 + Math.random() * 1.6,
    -1.2 - Math.random() * 2.2
  );
  mesh.rotation.y = angle * 0.35;
  wordRoot.add(mesh);
  liveWords.push({
    mesh,
    born: t,
    life: mode === 'chorus' ? 2.6 : mode === 'stamp' ? 3.4 : 3.0,
    vx: Math.sin(angle) * (mode === 'chorus' ? 1.5 : 0.4),
    vy: mode === 'impact' ? 0.75 : 0.2 + Math.random() * 0.35,
    vz: mode === 'chorus' ? -1.1 : -0.4,
    spin: (Math.random() - 0.5) * 1.0,
  });
}

function clearWords() {
  for (const w of liveWords) {
    wordRoot.remove(w.mesh);
    w.mesh.geometry.dispose();
    w.mesh.material.map?.dispose();
    w.mesh.material.dispose();
  }
  liveWords.length = 0;
}

function setHudLyric(text, mode) {
  if (shownCue && shownCue.text === text && shownCue.mode === mode) {
    lyricNow.style.opacity = '';
    lyricNow.classList.remove('is-pause');
    return;
  }
  lyricPrev.textContent = prevLyric;
  prevLyric = text;
  lyricNow.textContent = text;
  lyricNow.className = `lyric-now is-${mode}`;
  void lyricNow.offsetWidth;
  lyricNow.className = `lyric-now is-${mode}`;
  lyricNow.style.opacity = '';
}

function enterTextPause() {
  if (!lyricNow.textContent) return;
  lyricNow.classList.add('is-pause');
  lyricNow.style.opacity = '0.22';
}

function findActiveCue(lyricT) {
  // Prefer the latest cue whose window contains lyricT
  let hit = null;
  for (const c of CUES) {
    if (lyricT >= c.t && lyricT < c.end) hit = c;
  }
  return hit;
}

function findActiveScene(sceneT) {
  let hit = EVENTS[0];
  for (const e of EVENTS) {
    if (e.t <= sceneT) hit = e;
  }
  return hit;
}

function formatTime(sec) {
  const s = Math.max(0, Math.min(DURATION, sec | 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
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
    const fade = age < 0.25 ? age / 0.25 : age > w.life - 0.5 ? (w.life - age) / 0.5 : 1;
    w.mesh.material.opacity = Math.max(0, fade);
    w.mesh.position.x += w.vx * dt;
    w.mesh.position.y += w.vy * dt;
    w.mesh.position.z += w.vz * dt;
    w.mesh.rotation.z += w.spin * dt;
    w.vy -= 0.12 * dt;
  }
}

function applyScene(name, t) {
  sceneName = name;
  sceneLabel.textContent = `scene · ${name}`;
  const { suitcase, lifebuoy, foxGlow } = props.userData;
  const { lights } = party.userData;
  const { armL, armR, legL, legR } = figure.userData;

  suitcase.visible = false;
  lifebuoy.visible = false;
  foxGlow.intensity = 0;
  for (const l of lights) l.intensity = 0;
  flash = Math.max(flash, 0.35);
  beatKick = 1;

  figure.visible = true;
  figure.position.set(0, -1.15, -2.2);
  figure.rotation.set(0, 0, 0);
  armL.rotation.set(0, 0, 0.25);
  armR.rotation.set(0, 0, -0.25);
  if (figure.userData.ground) {
    figure.userData.ground.position.set(0, -1.32, -2.2);
    figure.userData.ground.visible = true;
  }

  switch (name) {
    case 'horizon':
      figure.position.set(0.2, -1.15, -4.5);
      break;
    case 'walk':
      figure.position.set(-1.2, -1.15, -2.5);
      if (figure.userData.ground) figure.userData.ground.position.copy(figure.position).setY(-1.32);
      break;
    case 'void':
      flash = 0.8;
      particles.material.opacity = 0.25;
      break;
    case 'chorus-pulse':
      beatKick = 1.4;
      break;
    case 'party':
    case 'drown-party':
      for (const l of lights) l.intensity = 2.2;
      break;
    case 'hotel':
      rim.color.setHex(0xffd27a);
      break;
    case 'suitcase':
      suitcase.visible = true;
      figure.position.set(-0.6, -1.15, -2.0);
      break;
    case 'scrub':
      flash = 0.6;
      break;
    case 'melancholy':
      particles.material.color.setHex(0x7a93b8);
      break;
    case 'hands':
      armL.rotation.z = 1.1;
      armR.rotation.z = -1.1;
      armL.rotation.x = -0.6;
      armR.rotation.x = -0.6;
      break;
    case 'sink':
      figure.position.y = -1.55;
      break;
    case 'lifebuoy':
      lifebuoy.visible = true;
      flash = 1;
      break;
    case 'stamp-onda':
      flash = 0.9;
      break;
    case 'fox':
      foxGlow.intensity = 3.2;
      break;
    case 'run':
      figure.position.set(1.5, -1.15, -2.0);
      legL.rotation.x = 0.6;
      legR.rotation.x = -0.55;
      break;
    case 'scream':
      armL.rotation.z = 1.4;
      armR.rotation.z = -1.4;
      flash = 1;
      break;
    case 'end':
      figure.position.set(0, -1.15, -5);
      break;
    default:
      break;
  }
}

function animateFigure(t, dt) {
  const { legL, legR, armL, armR } = figure.userData;
  const walk = sceneName === 'walk' || sceneName === 'run' || sceneName === 'party';
  if (walk) {
    const sp = sceneName === 'run' ? 10 : 4.5;
    legL.rotation.x = Math.sin(t * sp) * 0.55;
    legR.rotation.x = Math.sin(t * sp + Math.PI) * 0.55;
    armL.rotation.x = Math.sin(t * sp + Math.PI) * 0.35;
    armR.rotation.x = Math.sin(t * sp) * 0.35;
    figure.position.x += (sceneName === 'run' ? 0.9 : 0.25) * dt;
    if (figure.position.x > 3.5) figure.position.x = -3.2;
    if (figure.userData.ground) {
      figure.userData.ground.position.x = figure.position.x;
      figure.userData.ground.position.z = figure.position.z;
    }
  }

  if (sceneName === 'sink' || sceneName === 'drown-party') {
    figure.position.y = THREE.MathUtils.lerp(figure.position.y, -2.05, dt * 0.6);
    figure.rotation.z = Math.sin(t * 2) * 0.08;
  }

  if (sceneName === 'lifebuoy') {
    const buoy = props.userData.lifebuoy;
    buoy.rotation.z += dt * 2.5;
    buoy.scale.setScalar(1 + Math.sin(t * 8) * 0.08);
    if (elapsed > 102.8) {
      buoy.position.x += dt * 1.4;
      buoy.position.y -= dt * 0.6;
      buoy.rotation.x += dt * 3;
    }
  }

  if (sceneName === 'party' || sceneName === 'drown-party' || sceneName === 'chorus-pulse') {
    const { lights } = party.userData;
    lights.forEach((l, i) => {
      l.intensity = 1.2 + Math.sin(t * 8 + i) * 1.4 + beatKick * 0.8;
    });
  }

  if (sceneName === 'suitcase') {
    props.userData.suitcase.rotation.y = Math.sin(t * 1.2) * 0.15;
  }

  beatKick = Math.max(0, beatKick - dt * 2.2);
  flash = Math.max(0, flash - dt * 1.4);
}

function heardLatency() {
  if (!audioCtx) return 0.12;
  const out = Number(audioCtx.outputLatency) || 0;
  const base = Number(audioCtx.baseLatency) || 0;
  // Speakers always trail the sample clock a bit — keep lyrics on what you hear.
  return Math.min(0.35, Math.max(0.05, out + base || 0.12));
}

function processTimeline(t) {
  // Recompute every frame from wall clock — no drifting cueIndex.
  const lag = LYRIC_LAG + heardLatency();
  const sceneT = Math.max(0, t - lag * 0.35);
  const lyricT = Math.max(0, t - lag);

  const scene = findActiveScene(sceneT);
  if (scene.scene !== lastScene) {
    lastScene = scene.scene;
    applyScene(scene.scene, t);
  }

  const cue = findActiveCue(lyricT);
  if (cue) {
    const key = `${cue.t}|${cue.text}`;
    setHudLyric(cue.text, cue.mode);
    shownCue = cue;
    if (spawnedKey !== key) {
      spawnedKey = key;
      spawnWord(cue.text, cue.mode, t);
    }
  } else {
    // In a gap (e.g. after «осталось» before «а-а-о»)
    shownCue = null;
    enterTextPause();
  }
}

function syncFromPlayer() {
  if (!audioReady) return elapsed;
  if (!playing) {
    elapsed = pausedAt;
    return elapsed;
  }
  // Lyrics always follow performance.now() (true 1×). Audio buffer plays in parallel.
  elapsed = offsetWhenStarted + (performance.now() - startedAtPerf) / 1000;
  if (elapsed >= DURATION) {
    elapsed = DURATION;
    playing = false;
    pausedAt = DURATION;
    stopSource();
    playBtn.textContent = 'Replay';
  }
  return elapsed;
}

function stopSource() {
  if (sourceNode) {
    try {
      sourceNode.onended = null;
      sourceNode.stop();
    } catch {
      /* already stopped */
    }
    sourceNode.disconnect();
    sourceNode = null;
  }
}

function startSource(offset) {
  if (!audioCtx || !audioBuffer) return;
  stopSource();
  const start = Math.max(0, Math.min(offset, audioBuffer.duration - 0.05));
  sourceNode = audioCtx.createBufferSource();
  sourceNode.buffer = audioBuffer;
  sourceNode.connect(audioCtx.destination);
  offsetWhenStarted = start;
  pausedAt = start;
  startedAtPerf = performance.now();
  sourceNode.onended = () => {
    /* natural end handled by syncFromPlayer duration check */
  };
  sourceNode.start(0, start);
  playing = true;
}

function rebuildTimelineIndex(t) {
  shownCue = null;
  spawnedKey = '';
  lastScene = '';
  prevLyric = '';
  lyricPrev.textContent = '';
  clearWords();
  processTimeline(t);
  if (!findActiveCue(Math.max(0, t - LYRIC_LAG - heardLatency())) && t < 9) {
    lyricNow.textContent = 'ONDA ANDAR';
    lyricNow.className = 'lyric-now';
    lyricNow.style.opacity = '';
  }
}

let lastFrame = performance.now();

function frame(now) {
  const dt = Math.min(0.05, (now - lastFrame) / 1000);
  lastFrame = now;

  syncFromPlayer();

  const intensity =
    (playing ? 1.05 : 0.45) +
    Math.sin(elapsed * Math.PI * 2 * (168 / 60)) * (playing ? 0.35 : 0.08) +
    beatKick * 0.25 +
    flash * 0.4;

  updateWave(now * 0.001, intensity);
  updateWords(elapsed, dt);
  // Keep lyrics locked to the audio clock whenever we have a position
  if (audioReady && (playing || elapsed > 0.05)) processTimeline(elapsed);
  animateFigure(elapsed, dt);

  particles.rotation.y = now * 0.00005;
  camera.position.x = Math.sin(now * 0.00018) * 0.45 + flash * 0.15;
  camera.position.y = 1.4 + Math.sin(now * 0.0003) * 0.12;
  camera.lookAt(0, 1.0, 0);
  rim.intensity = 1.0 + Math.sin(now * 0.004) * 0.35 + flash * 1.5;
  renderer.setClearColor(flash > 0.05 ? 0x1a3058 : 0x06101c, 1);

  progressEl.style.width = `${(elapsed / DURATION) * 100}%`;
  timeEl.textContent = `${formatTime(elapsed)} / 2:17`;
  document.body.classList.toggle('is-playing', playing);

  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}

async function loadAudio() {
  audioCtx = new AudioContext();
  const res = await fetch(AUDIO_SRC);
  if (!res.ok) throw new Error('audio fetch failed');
  const arr = await res.arrayBuffer();
  audioBuffer = await audioCtx.decodeAudioData(arr);
  audioReady = true;
}

async function togglePlay() {
  if (!audioReady) {
    playBtn.textContent = 'Loading…';
    try {
      await loadAudio();
    } catch {
      playBtn.textContent = 'Play song';
      return;
    }
  }
  if (audioCtx.state === 'suspended') await audioCtx.resume();

  if (playing) {
    // pause
    pausedAt = offsetWhenStarted + (performance.now() - startedAtPerf) / 1000;
    elapsed = pausedAt;
    playing = false;
    stopSource();
    playBtn.textContent = 'Play song';
    return;
  }

  if (pausedAt >= DURATION - 0.35) {
    pausedAt = 0;
    elapsed = 0;
    rebuildTimelineIndex(0);
  }

  try {
    startSource(pausedAt);
    elapsed = pausedAt;
    playBtn.textContent = 'Pause';
    if (lyricHint) lyricHint.textContent = '';
  } catch {
    playBtn.textContent = 'Play song';
  }
}

playBtn.addEventListener('click', () => {
  togglePlay();
});

window.addEventListener('keydown', (e) => {
  if (e.code === 'Space') {
    e.preventDefault();
    togglePlay();
  }
});

seekEl.addEventListener('click', (e) => {
  if (!audioReady) return;
  const rect = seekEl.getBoundingClientRect();
  const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
  const t = ratio * DURATION;
  pausedAt = t;
  elapsed = t;
  rebuildTimelineIndex(t);
  if (playing) startSource(t);
});

window.addEventListener('resize', resize);

async function boot() {
  await document.fonts.ready;
  resize();
  applyScene('horizon', 0);
  requestAnimationFrame(frame);
  try {
    await loadAudio();
    playBtn.textContent = 'Play song';
    sceneLabel.textContent = 'credits · sync-v4';
  } catch {
    playBtn.textContent = 'Play song';
    sceneLabel.textContent = 'audio missing';
  }
}

boot();
