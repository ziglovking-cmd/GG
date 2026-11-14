const BPM = 168;
const BEAT_MS = 60000 / BPM;

const canvas = document.getElementById('wave');
const ctx = canvas.getContext('2d', { alpha: true });
const feelBtn = document.getElementById('feel-bpm');
const creditTrack = document.getElementById('credit-track');
const rollSection = document.getElementById('roll');

let width = 0;
let height = 0;
let dpr = 1;
let pulsing = false;
let pulseStart = 0;
let raf = 0;
let mouseX = 0.5;
let mouseY = 0.5;

function resize() {
  dpr = Math.min(window.devicePixelRatio || 1, 2);
  width = window.innerWidth;
  height = window.innerHeight;
  canvas.width = Math.floor(width * dpr);
  canvas.height = Math.floor(height * dpr);
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function beatPhase(now) {
  if (!pulsing) return 0.18;
  const t = (now - pulseStart) % BEAT_MS;
  const p = t / BEAT_MS;
  return 0.25 + Math.pow(Math.sin(p * Math.PI), 2) * 0.9;
}

function draw(now) {
  ctx.clearRect(0, 0, width, height);

  const amp = beatPhase(now);
  const layers = [
    { color: 'rgba(158, 199, 255, 0.28)', y: height * 0.58, speed: 0.0012, thick: 1.6, freq: 2.4 },
    { color: 'rgba(42, 95, 158, 0.42)', y: height * 0.66, speed: 0.00085, thick: 2.6, freq: 3.2 },
    { color: 'rgba(255, 77, 58, 0.22)', y: height * 0.74, speed: 0.00155, thick: 1.3, freq: 4.1 },
    { color: 'rgba(242, 246, 252, 0.12)', y: height * 0.8, speed: 0.0007, thick: 1.1, freq: 1.7 },
  ];

  for (const layer of layers) {
    ctx.beginPath();
    for (let x = 0; x <= width; x += 3) {
      const nx = x / width;
      const sway =
        Math.sin(nx * Math.PI * layer.freq + now * layer.speed * 60) * 36 * amp +
        Math.sin(nx * Math.PI * (layer.freq * 2.2) + now * layer.speed * 38 + mouseX * 2.4) *
          16 *
          amp +
        Math.cos(nx * Math.PI * 1.3 - now * layer.speed * 22) * 10 * amp +
        (mouseY - 0.5) * 48;
      const y = layer.y + sway;
      if (x === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.strokeStyle = layer.color;
    ctx.lineWidth = layer.thick;
    ctx.stroke();
  }

  // soft horizon bloom on beat
  if (pulsing) {
    const glow = ctx.createRadialGradient(
      width * mouseX,
      height * 0.72,
      0,
      width * mouseX,
      height * 0.72,
      width * 0.35
    );
    glow.addColorStop(0, `rgba(158, 199, 255, ${0.08 * amp})`);
    glow.addColorStop(1, 'rgba(158, 199, 255, 0)');
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, width, height);
  }

  raf = requestAnimationFrame(draw);
}

function updateCredits() {
  if (!rollSection || !creditTrack) return;
  const rect = rollSection.getBoundingClientRect();
  const total = rect.height - window.innerHeight;
  if (total <= 0) return;
  const progress = Math.min(1, Math.max(0, -rect.top / total));
  const travel = window.innerHeight * 0.7 + creditTrack.offsetHeight;
  creditTrack.style.transform = `translateY(${35 - progress * (35 + (travel / window.innerHeight) * 100)}vh)`;
}

function togglePulse() {
  pulsing = !pulsing;
  document.body.classList.toggle('is-pulsing', pulsing);
  pulseStart = performance.now();
  feelBtn.textContent = pulsing ? 'Stop pulse' : 'Feel 168 BPM';
  feelBtn.setAttribute('aria-pressed', String(pulsing));
}

feelBtn?.addEventListener('click', togglePulse);

window.addEventListener(
  'pointermove',
  (e) => {
    mouseX = e.clientX / window.innerWidth;
    mouseY = e.clientY / window.innerHeight;
  },
  { passive: true }
);

window.addEventListener('resize', resize, { passive: true });
window.addEventListener('scroll', updateCredits, { passive: true });

resize();
updateCredits();
raf = requestAnimationFrame(draw);

// Intersection reveal for pulse meters when in view
const meters = document.querySelector('.meters');
if (meters && 'IntersectionObserver' in window) {
  const io = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting && !pulsing) {
          // gentle idle motion without full pulse mode
          meters.classList.add('in-view');
        }
      }
    },
    { threshold: 0.35 }
  );
  io.observe(meters);
}
