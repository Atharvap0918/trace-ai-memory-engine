/* Adapted from the user-supplied Jarvis_Brain_Visualization_Expanded.zip.
   Geometry and rendering stages are retained; lifecycle, sizing and input are
   scoped to the dashboard card. No telemetry represents actual user memory. */
(function(){
'use strict';
function mount(canvas, options={}) {
if(!canvas) return null;

const ctx = canvas.getContext("2d");

let W, H, DPR;
let paused = false;
let reducedMotion=matchMedia('(prefers-reduced-motion: reduce)').matches;
let alive=true,frameId=null,simulationTime=0,viewScale=1,visible=true,dirty=true,renderedFrames=0;
const listeners=[];
function listen(target,type,handler,config){target.addEventListener(type,handler,config);listeners.push(()=>target.removeEventListener(type,handler,config));}
let yaw = 0.25;
let pitch = -0.08;
let zoom = 1;
const BRAIN_SCALE = 1.12;
let dragging = false;
let frameAccumulator = 0;
let lastFrameTime = 0;
let lastX = 0;
let lastY = 0;

const TAU = Math.PI * 2;
const nodes = [];
const links = [];
const streams = [];
const rings = [];

function resize() {
  DPR = Math.min(window.devicePixelRatio || 1, 1.5);
  const width=Math.max(1,canvas.clientWidth),height=Math.max(1,canvas.clientHeight);
  if(width===W&&height===H) return;
  W=width;H=height;
  viewScale=Math.min(W/720,H/740)*.88;
  dirty=true;
  canvas.width = Math.floor(W * DPR);
  canvas.height = Math.floor(H * DPR);
  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  buildJarvisBrain();
}

function rand(min, max) {
  return min + Math.random() * (max - min);
}

function clamp(v, a, b) {
  return Math.max(a, Math.min(b, v));
}

/*
  JARVIS SHAPE
  -------------
  This is intentionally NOT a biological brain.
  It is shaped like the reference: a compact spherical holographic AI core
  with a dense outer shell, layered circular circuitry, a central processor,
  vertical structures, and many glowing information paths.
*/

function addNode(x, y, z, group = "shell") {
  nodes.push({
    x, y, z,
    group,
    phase: Math.random() * TAU,
    size: rand(0.45, 1.35),
    brightness: rand(0.45, 1.0)
  });
}

function buildJarvisBrain() {
  nodes.length = 0;
  links.length = 0;
  streams.length = 0;
  rings.length = 0;

  // Dense spherical JARVIS silhouette.
  // The reference is closer to an illuminated spherical AI processor
  // than a natural anatomical brain.
  const shellCount = Math.min(2200, Math.max(1550, Math.floor(W * H / 560)));

  for (let i = 0; i < shellCount; i++) {
    const u = Math.random();
    const v = Math.random();

    const theta = TAU * u;
    const phi = Math.acos(2 * v - 1);

    // Slightly flattened/deepened sphere, with a gentle top crown.
    let sx = 238 * BRAIN_SCALE;
    let sy = 248 * BRAIN_SCALE;
    let sz = 192 * BRAIN_SCALE;

    const yy = Math.cos(phi);

    // Reference-like silhouette: broad middle, slightly tighter poles.
    const crown = 1 + 0.055 * Math.max(0, yy);
    const waist = 1 - 0.055 * Math.abs(yy) ** 2;

    // Most points sit on/near the holographic shell.
    const shellDepth = 0.82 + Math.random() * 0.20;

    let x = Math.sin(phi) * Math.cos(theta) * sx * waist * crown * shellDepth;
    let y = Math.cos(phi) * sy * crown * shellDepth;
    let z = Math.sin(phi) * Math.sin(theta) * sz * shellDepth;

    // Slight center fissure / twin-lobe separation without making it anatomical.
    // It gives the JARVIS orb its recognizable two-sided architecture.
    if (Math.abs(x) < 9 && Math.random() < 0.72) {
      x += x < 0 ? -12 : 12;
    }

    addNode(x, y, z, "shell");
  }

  // Interior circuitry: layered spherical/elliptical paths.
  for (let layer = 0; layer < 7; layer++) {
    const ry = (48 + layer * 25) * BRAIN_SCALE;
    const rx = (62 + layer * 29) * BRAIN_SCALE;
    const rz = (44 + layer * 23) * BRAIN_SCALE;
    const count = 75 + layer * 16;

    for (let i = 0; i < count; i++) {
      const a = TAU * i / count + layer * 0.19;
      const wobble = 1 + 0.06 * Math.sin(a * 5 + layer);

      addNode(
        Math.cos(a) * rx * wobble,
        Math.sin(a) * ry * wobble,
        Math.sin(a * 2 + layer) * rz * 0.52,
        "inner"
      );
    }
  }

  // Vertical/top circuitry that gives the reference its distinctive
  // dense machine-like structure.
  for (let strip = -5; strip <= 5; strip++) {
    const x = strip * 26 * BRAIN_SCALE;
    for (let i = 0; i < 58; i++) {
      const y = (-150 + i * 5.2) * BRAIN_SCALE;
      const depth = Math.sqrt(Math.max(0, 1 - (x / 235) ** 2 - (y / 245) ** 2));
      const z = 135 * BRAIN_SCALE * depth + Math.sin(i * .45 + strip) * 10 * BRAIN_SCALE;
      addNode(x, y, z, "circuit");
    }
  }

  // Horizontal/diagonal circuit bands around the sphere.
  for (let band = 0; band < 12; band++) {
    const yy = (-180 + band * 33) * BRAIN_SCALE;
    const width = Math.sqrt(Math.max(0, 1 - (yy / 248) ** 2));
    const count = 80;

    for (let i = 0; i < count; i++) {
      const a = TAU * i / count;
      addNode(
        Math.cos(a) * 235 * BRAIN_SCALE * width,
        yy + Math.sin(a * 3 + band) * 5,
        Math.sin(a) * 190 * BRAIN_SCALE * width,
        "band"
      );
    }
  }

  // Reference-style circular processor rings.
  for (let i = 0; i < 9; i++) {
    rings.push({
      rx: 72 + i * 21,
      ry: 55 + i * 18,
      rz: 48 + i * 17,
      tilt: (i % 2 ? 0.08 : -0.05),
      phase: Math.random() * TAU,
      speed: (i % 2 ? -1 : 1) * rand(0.00025, 0.00065)
    });
  }

  // Connect nodes mostly to nearby nodes so the orb remains dense,
  // while avoiding a solid glowing blob.
  for (let i = 0; i < nodes.length; i += 2) {
    const a = nodes[i];
    const candidates = [];

    for (let j = 0; j < nodes.length; j += 8) {
      if (i === j) continue;
      const b = nodes[j];
      const dx = a.x - b.x;
      const dy = a.y - b.y;
      const dz = a.z - b.z;
      const d2 = dx * dx + dy * dy + dz * dz;

      if (d2 < 3400) {
        candidates.push([d2, j]);
      }
    }

    candidates.sort((p, q) => p[0] - q[0]);

    for (let k = 0; k < Math.min(2, candidates.length); k++) {
      links.push([i, candidates[k][1], Math.random()]);
    }
  }

  // Continuous information packets.
  for (let i = 0; i < 145; i++) {
    streams.push({
      a: Math.floor(Math.random() * nodes.length),
      b: Math.floor(Math.random() * nodes.length),
      t: Math.random(),
      speed: rand(0.003, 0.012),
      life: rand(0.45, 1)
    });
  }
}

function rotate3D(p) {
  let x = p.x, y = p.y, z = p.z;

  const cx = Math.cos(yaw), sx = Math.sin(yaw);
  [x, z] = [x * cx - z * sx, x * sx + z * cx];

  const cy = Math.cos(pitch), sy = Math.sin(pitch);
  [y, z] = [y * cy - z * sy, y * sy + z * cy];

  return { x, y, z };
}

function project(p) {
  const depth = 650;
  const scale = (depth / (depth + p.z)) * zoom * viewScale;

  return {
    x: W / 2 + p.x * scale,
    y: H / 2 + p.y * scale,
    s: scale,
    z: p.z
  };
}

function drawBackground() {
  // Absolutely black background.
  ctx.fillStyle = "#000000";
  ctx.fillRect(0, 0, W, H);
}

function drawOrbitalDiscs(t) {
  const cx = W / 2;
  const cy = H / 2;
  const base = Math.min(W, H) * 0.365;

  // Subtle holographic discs around the enlarged brain. They sit behind the
  // circuitry and use a perspective-like flattening so the brain feels like
  // a rotating JARVIS core rather than a flat 2D graphic.
  ctx.save();
  ctx.translate(cx, cy);
  ctx.globalCompositeOperation = "lighter";

  const discs = [
    { rx: 1.00, ry: 0.17, rot: -0.18, speed: 0.00042, alpha: 0.18 },
    { rx: 0.92, ry: 0.10, rot:  0.22, speed: -0.00058, alpha: 0.14 },
    { rx: 0.78, ry: 0.065, rot: 1.08, speed: 0.00072, alpha: 0.11 }
  ];

  for (let i = 0; i < discs.length; i++) {
    const d = discs[i];
    const a = t * d.speed;

    ctx.save();
    ctx.rotate(d.rot + a);

    // Main thin disc.
    ctx.strokeStyle = `rgba(255, 167, 31, ${d.alpha})`;
    ctx.lineWidth = 0.9;
    ctx.beginPath();
    ctx.ellipse(0, 0, base * d.rx, base * d.ry, 0, 0, TAU);
    ctx.stroke();

    // A few broken segments make the disc feel engineered, not decorative.
    for (let k = 0; k < 4; k++) {
      const start = k * 1.57 + 0.12;
      ctx.strokeStyle = `rgba(255, 194, 65, ${d.alpha * 1.45})`;
      ctx.lineWidth = 1.15;
      ctx.beginPath();
      ctx.ellipse(
        0, 0,
        base * d.rx,
        base * d.ry,
        0,
        start,
        start + 0.34 + (k % 2) * 0.14
      );
      ctx.stroke();
    }

    // Small moving signal marker on each disc.
    const markerAngle = a * 5 + i * 2.1;
    const mx = Math.cos(markerAngle) * base * d.rx;
    const my = Math.sin(markerAngle) * base * d.ry;
    ctx.shadowBlur = 7;
    ctx.shadowColor = "rgba(255, 173, 30, .8)";
    ctx.fillStyle = "rgba(255, 204, 89, .72)";
    ctx.beginPath();
    ctx.arc(mx, my, 1.25, 0, TAU);
    ctx.fill();
    ctx.shadowBlur = 0;

    ctx.restore();
  }

  ctx.restore();
}

function drawConnections(rotated, projected, t) {
  for (const [ai, bi, phase] of links) {
    const a = projected[ai];
    const b = projected[bi];
    const ar = rotated[ai];
    const br = rotated[bi];

    // Keep some rear circuitry visible, like the reference.
    if (ar.z < -125 && br.z < -125) continue;

    const depth = clamp(((ar.z + br.z) / 2 + 230) / 460, 0, 1);
    const pulse =
      0.08 +
      0.20 * (0.5 + 0.5 * Math.sin(t * 0.004 + phase * 18));

    ctx.strokeStyle = `rgba(255, 151, 22, ${pulse * (0.28 + depth * 0.9)})`;
    ctx.lineWidth = 0.55 + depth * 0.45;

    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
  }
}

function drawCircuitRings(t) {
  const cx = W / 2;
  const cy = H / 2;

  ctx.save();
  ctx.translate(cx, cy);

  for (const r of rings) {
    const angle = r.phase + t * r.speed;

    ctx.save();
    ctx.rotate(angle);

    ctx.strokeStyle = "rgba(255, 157, 28, 0.15)";
    ctx.lineWidth = 0.8;

    ctx.beginPath();
    ctx.ellipse(
      0, 0,
      r.rx * zoom * viewScale,
      r.ry * zoom * viewScale,
      r.tilt,
      0,
      TAU
    );
    ctx.stroke();

    // Break the ring into JARVIS-like circuit segments.
    for (let k = 0; k < 5; k++) {
      const start = k * 1.25 + 0.15;
      const length = 0.25 + (k % 2) * 0.16;

      ctx.strokeStyle = "rgba(255, 184, 58, 0.30)";
      ctx.beginPath();
      ctx.ellipse(
        0, 0,
        r.rx * zoom * viewScale,
        r.ry * zoom * viewScale,
        r.tilt,
        start,
        start + length
      );
      ctx.stroke();
    }

    ctx.restore();
  }

  ctx.restore();
}

function drawStreams(rotated, projected) {
  for (const s of streams) {
    const a = projected[s.a];
    const b = projected[s.b];

    if(!paused) s.t += s.speed * frameAccumulator;
    if (s.t > 1) {
      s.t = 0;
      s.a = (Math.random() * nodes.length) | 0;
      s.b = (Math.random() * nodes.length) | 0;
    }

    const x = a.x + (b.x - a.x) * s.t;
    const y = a.y + (b.y - a.y) * s.t;
    const alpha = Math.sin(Math.PI * s.t) * s.life;

    ctx.fillStyle = `rgba(255, 213, 125, ${alpha})`;
    ctx.beginPath();
    ctx.arc(x, y, 1.3 + alpha * 1.8, 0, TAU);
    ctx.fill();

    ctx.strokeStyle = `rgba(255, 141, 10, ${alpha * .42})`;
    ctx.lineWidth = 0.8;
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x - (b.x - a.x) * 0.045, y - (b.y - a.y) * 0.045);
    ctx.stroke();
  }
}

function drawNodes(rotated, projected, t) {
  for (let i = 0; i < nodes.length; i++) {
    const p = rotated[i];
    const q = projected[i];
    const depth = clamp((p.z + 245) / 490, 0, 1);
    const pulse = 0.62 + 0.38 * Math.sin(t * 0.003 + nodes[i].phase);

    let groupBoost = 1;
    if (nodes[i].group === "circuit") groupBoost = 1.18;
    else if (nodes[i].group === "inner") groupBoost = 1.12;
    else if (nodes[i].group === "band") groupBoost = 0.95;

    const alpha = (0.12 + depth * 0.64) * pulse * groupBoost * nodes[i].brightness;
    ctx.fillStyle = `rgba(255, ${130 + Math.floor(depth * 90)}, 20, ${alpha})`;
    ctx.beginPath();
    ctx.arc(q.x, q.y, nodes[i].size * q.s * (0.75 + depth * 0.35), 0, TAU);
    ctx.fill();
  }
}

function drawCentralProcessor(t) {
  const cx = W / 2;
  const cy = H / 2;
  const r = Math.min(W, H) * 0.075;

  const glow = ctx.createRadialGradient(
    cx, cy, 0,
    cx, cy, r * 2.4
  );

  glow.addColorStop(0, "rgba(255, 247, 205, .98)");
  glow.addColorStop(.10, "rgba(255, 211, 103, .9)");
  glow.addColorStop(.32, "rgba(255, 146, 12, .45)");
  glow.addColorStop(1, "rgba(255, 80, 0, 0)");

  ctx.fillStyle = glow;
  ctx.beginPath();
  ctx.arc(cx, cy, r * 2.4, 0, TAU);
  ctx.fill();

  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(t * 0.00075);

  for (let i = 0; i < 6; i++) {
    ctx.rotate(Math.PI / 6);

    ctx.strokeStyle =
      `rgba(255, ${190 + i * 8}, 70, ${0.28 - i * .025})`;

    ctx.lineWidth = 1;

    ctx.beginPath();
    ctx.ellipse(
      0, 0,
      r * (0.8 + i * .28),
      r * (0.34 + i * .12),
      0,
      0,
      TAU
    );
    ctx.stroke();
  }

  ctx.restore();
}

function drawScanningArcs(t) {
  const cx = W / 2;
  const cy = H / 2;
  const radius = Math.min(W, H) * 0.35;

  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(t * 0.0008);

  for (let i = 0; i < 4; i++) {
    ctx.strokeStyle =
      `rgba(255, 155, 24, ${0.12 - i * .018})`;
    ctx.lineWidth = 0.9;

    ctx.beginPath();
    ctx.arc(
      0,
      0,
      radius + i * 8,
      -0.8,
      0.8
    );
    ctx.stroke();
  }

  ctx.restore();
}

function updateTelemetry(t) {

}

function animate(t) {
  if(!alive||!canvas.isConnected)return;
  frameId=null;
  if(document.hidden||!visible){lastFrameTime=0;return}
  frameId=requestAnimationFrame(animate);
  if(lastFrameTime&&t-lastFrameTime<32)return;
  const delta=lastFrameTime?Math.min(50,t-lastFrameTime):16.7;lastFrameTime=t;
  if(paused&&!dirty)return;
  frameAccumulator=delta/16.7;
  if(!paused){yaw+=.0019*frameAccumulator*(reducedMotion?.15:1);simulationTime+=delta*(reducedMotion?.15:1)}
  dirty=false;t=simulationTime;
  drawBackground();drawOrbitalDiscs(t);
  const rotated=new Array(nodes.length),projected=new Array(nodes.length);
  const cy=Math.cos(yaw),sy=Math.sin(yaw),cp=Math.cos(pitch),sp=Math.sin(pitch);
  for(let i=0;i<nodes.length;i++){
    const p=nodes[i];let x=p.x,y=p.y,z=p.z;
    const rx=x*cy-z*sy,rz=x*sy+z*cy;x=rx;z=rz;
    const ry=y*cp-z*sp;z=y*sp+z*cp;y=ry;
    rotated[i]={x,y,z};const scale=(650/(650+z))*zoom*viewScale;
    projected[i]={x:W/2+x*scale,y:H/2+y*scale,s:scale,z};
  }
  drawConnections(rotated,projected,t);drawCircuitRings(t);
  drawStreams(rotated,projected);drawNodes(rotated,projected,t);
  drawCentralProcessor(t);drawScanningArcs(t);renderedFrames++;
}
listen(canvas,"pointerdown", e => {
  dragging = true;dirty=true;
  lastX = e.clientX;
  lastY = e.clientY;
  canvas.setPointerCapture(e.pointerId);
});

listen(canvas,"pointermove", e => {
  if (!dragging) return;

  dirty=true;
  yaw += (e.clientX - lastX) * 0.006;
  pitch += (e.clientY - lastY) * 0.004;

  pitch = clamp(pitch, -0.75, 0.75);

  lastX = e.clientX;
  lastY = e.clientY;
});

listen(canvas,"pointerup", () => {
  dragging = false;
});

listen(canvas,"pointercancel", () => {
  dragging = false;
});

listen(canvas,
  "wheel",
  e => {
    if(!e.ctrlKey&&!e.metaKey)return;
    e.preventDefault();dirty=true;

    zoom *= Math.exp(-e.deltaY * 0.001);
    zoom = clamp(zoom, 0.65, 1.55);
  },
  { passive: false }
);

function setPaused(value){paused=!!value;dirty=true;lastFrameTime=0;options.onPause?.(paused)}
const observer=new ResizeObserver(resize);observer.observe(canvas);
function schedule(){if(alive&&canvas.isConnected&&!document.hidden&&visible&&frameId===null)frameId=requestAnimationFrame(animate)}
const intersection=new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;dirty=true;lastFrameTime=0;if(visible)schedule()});intersection.observe(canvas);
listen(document,'visibilitychange',()=>{lastFrameTime=0;dirty=true;schedule()});
const motion=matchMedia('(prefers-reduced-motion: reduce)');
listen(motion,'change',e=>{reducedMotion=e.matches;dirty=true;schedule()});

resize();
frameId=requestAnimationFrame(animate);

return {get paused(){return paused},get frames(){return renderedFrames},setPaused,stop(){alive=false;cancelAnimationFrame(frameId);observer.disconnect();intersection.disconnect();listeners.forEach(off=>off());nodes.length=links.length=streams.length=rings.length=0;}};
}
window.TraceJarvis={mount};
})();
