'use client';

import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js';
import { BAT_PATH } from './BatMark';
import { n } from '@/lib/format';

/*
  The swarm: thousands of tiny bats that fly in formation.
    emblem  — together they draw the Scrapee bat
    sites   — each indexed site is a cluster of bats swirling in 3D, sized by its pages
    storm   — while Scrapee works, the swarm becomes a vortex
  The pointer scatters bats around it; dragging turns the scene.
*/

const MAX_SITES = 12;
const EMBLEM_W = 12.5;
// The emblem floats above the command line; a stream of bats pours from its
// tail onto the line, so the input is part of the formation.
const EMBLEM_Y = 1.25;
const CORE_Y = -2.55;
const LOOK_Y = -0.45;
const STREAM_SHARE = 0.07;
const FOV = 45;
const YELLOW = new THREE.Color(1, 0.8, 0.05);

// The logo path (viewBox 0 0 100 40) as a three.js shape centred on the origin.
function batShape(scale) {
  const shape = new THREE.Shape();
  const t = BAT_PATH.match(/[MCLZ]|-?\d*\.?\d+/g);
  const X = (v) => ((v - 50) / 50) * scale;
  const Y = (v) => (-(v - 20) / 50) * scale;
  let i = 0;
  let cmd = 'M';
  const num = () => parseFloat(t[i++]);
  while (i < t.length) {
    if (/[MCLZ]/.test(t[i])) {
      cmd = t[i++];
      if (cmd === 'Z') {
        shape.closePath();
        continue;
      }
    }
    if (cmd === 'M') shape.moveTo(X(num()), Y(num()));
    else if (cmd === 'L') shape.lineTo(X(num()), Y(num()));
    else if (cmd === 'C') {
      const a = [num(), num(), num(), num(), num(), num()];
      shape.bezierCurveTo(X(a[0]), Y(a[1]), X(a[2]), Y(a[3]), X(a[4]), Y(a[5]));
    }
  }
  return shape;
}

// Points spread over the logo's silhouette: the stencil the swarm fills.
function emblemPoints(count) {
  const W = 500;
  const H = 200;
  const c = document.createElement('canvas');
  c.width = W;
  c.height = H;
  const ctx = c.getContext('2d');
  ctx.scale(5, 5);
  ctx.fill(new Path2D(BAT_PATH));
  const data = ctx.getImageData(0, 0, W, H).data;
  const filled = [];
  for (let y = 0; y < H; y += 2) {
    for (let x = 0; x < W; x += 2) if (data[(y * W + x) * 4 + 3] > 128) filled.push(x, y);
  }
  const out = new Float32Array(count * 3);
  for (let k = 0; k < count; k++) {
    const j = ((Math.random() * filled.length) / 2) | 0;
    out[k * 3] = (filled[j * 2] / W - 0.5) * EMBLEM_W;
    out[k * 3 + 1] = -(filled[j * 2 + 1] / H - 0.5) * EMBLEM_W * 0.4 + EMBLEM_Y;
    out[k * 3 + 2] = (Math.random() - 0.5) * 0.5;
  }
  return out;
}

function glyphTexture(ch) {
  const c = document.createElement('canvas');
  c.width = 64;
  c.height = 64;
  const ctx = c.getContext('2d');
  ctx.fillStyle = '#fff';
  ctx.font = 'bold 52px "JetBrains Mono", monospace';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(ch, 32, 34);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

// Where each site's cluster sits: a tilted ring around the centre.
function nodePosition(i, count, out) {
  // Tilted so clusters passing in front of the command line dip below it
  // and the ones behind rise above it.
  const a = (i / Math.max(count, 1)) * Math.PI * 2 + 0.4;
  out.set(Math.cos(a) * 7.8, 1.1 + Math.sin(a) * 1.5 + Math.sin(a * 2) * 0.5, Math.sin(a) * 4.4);
  return out;
}

export default function Swarm({ sources, mode, highlight, ping, shift, pulse, onPickSite }) {
  const mountRef = useRef(null);
  const labelRefs = useRef([]);
  const live = useRef({ mode, sources, highlight, ping, shift });
  const api = useRef(null);

  const sites = (sources || []).slice(0, MAX_SITES);

  useEffect(() => {
    live.current.mode = mode;
    live.current.highlight = highlight;
    live.current.shift = shift;
  }, [mode, highlight, shift]);

  useEffect(() => {
    live.current.sources = sites;
    api.current?.allocate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(sites.map((s) => [s.domain, s.docs]))]);

  useEffect(() => {
    if (ping) api.current?.burst(ping);
  }, [ping]);

  useEffect(() => {
    if (pulse) api.current?.ripple();
  }, [pulse]);

  useEffect(() => {
    const mount = mountRef.current;
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const small = window.innerWidth < 760;
    const N = small ? 900 : 1700;

    const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    // Pure black: the output pass converts to sRGB, which lifts any near-black to grey.
    renderer.setClearColor(0x000000, 1);
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x000000, 0.026);
    const camera = new THREE.PerspectiveCamera(FOV, 1, 0.1, 200);
    const root = new THREE.Group(); // shifts aside when the transmission opens
    const world = new THREE.Group(); // turned by dragging
    root.add(world);
    scene.add(root);

    // ── The bats ─────────────────────────────────────────────
    const geometry = new THREE.ShapeGeometry(batShape(0.105), 8);
    const material = new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.DoubleSide, toneMapped: false });
    const bats = new THREE.InstancedMesh(geometry, material, N);
    bats.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    bats.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(N * 3), 3);
    bats.instanceColor.setUsage(THREE.DynamicDrawUsage);
    world.add(bats);

    const pos = new Float32Array(N * 3);
    const vel = new Float32Array(N * 3);
    const phase = new Float32Array(N);
    const size = new Float32Array(N);
    const glow = new Float32Array(N);
    const orbit = new Float32Array(N * 3); // radius, polar angle, angular speed
    const site = new Int16Array(N).fill(-1);
    for (let k = 0; k < N; k++) {
      // Everyone starts in one point and bursts out into formation.
      const th = Math.random() * Math.PI * 2;
      const ph2 = Math.acos(2 * Math.random() - 1);
      const sp = 6 + Math.random() * 10;
      pos[k * 3] = (Math.random() - 0.5) * 0.3;
      pos[k * 3 + 1] = (Math.random() - 0.5) * 0.3;
      pos[k * 3 + 2] = (Math.random() - 0.5) * 0.3;
      vel[k * 3] = Math.sin(ph2) * Math.cos(th) * sp;
      vel[k * 3 + 1] = Math.cos(ph2) * sp;
      vel[k * 3 + 2] = Math.sin(ph2) * Math.sin(th) * sp;
      phase[k] = Math.random();
      size[k] = 0.75 + Math.random() * 0.7;
      glow[k] = 0.45 + Math.random() * 0.5;
      orbit[k * 3 + 1] = Math.acos(2 * Math.random() - 1);
      orbit[k * 3 + 2] = (0.5 + Math.random() * 0.9) * (Math.random() < 0.5 ? -1 : 1);
    }
    const emblem = emblemPoints(N);
    const nodes = Array.from({ length: MAX_SITES }, () => new THREE.Vector3());
    const clusterR = new Float32Array(MAX_SITES);
    const burstUntil = new Float32Array(MAX_SITES);

    // Give each site a share of the swarm by the square root of its pages.
    function allocate() {
      const list = live.current.sources || [];
      const most = Math.max(1, ...list.map((s) => s.docs));
      const weights = list.map((s) => Math.sqrt(s.docs));
      const total = weights.reduce((a, b) => a + b, 0) || 1;
      const budget = Math.floor(N * 0.93);
      let k = 0;
      list.forEach((s, i) => {
        nodePosition(i, list.length, nodes[i]);
        clusterR[i] = 0.28 + 0.95 * Math.sqrt(s.docs / most);
        const share = Math.max(24, Math.round((weights[i] / total) * budget));
        for (let j = 0; j < share && k < N; j++, k++) {
          site[k] = i;
          orbit[k * 3] = clusterR[i] * (0.35 + 0.65 * Math.cbrt(Math.random()));
        }
      });
      for (; k < N; k++) {
        site[k] = -1;
        orbit[k * 3] = 12 + Math.random() * 4;
      }
    }

    // A keystroke: bats nearest the command line flinch outward and settle back.
    function ripple() {
      for (let k = 0; k < N; k++) {
        const y = pos[k * 3 + 1];
        const near = Math.max(0, 1 - Math.abs(y - CORE_Y) / 3.4);
        if (!near) continue;
        vel[k * 3 + 1] += Math.sign(y - CORE_Y || 1) * near * (0.8 + Math.random() * 0.8);
        vel[k * 3] += (Math.random() - 0.5) * near * 0.6;
      }
    }

    function burst(domain) {
      const i = (live.current.sources || []).findIndex((s) => s.domain === domain);
      if (i < 0) return;
      burstUntil[i] = clock.elapsedTime + 3.5;
      for (let k = 0; k < N; k++) {
        if (site[k] !== i) continue;
        pos[k * 3] = nodes[i].x;
        pos[k * 3 + 1] = nodes[i].y;
        pos[k * 3 + 2] = nodes[i].z;
        vel[k * 3] = (Math.random() - 0.5) * 9;
        vel[k * 3 + 1] = (Math.random() - 0.5) * 9;
        vel[k * 3 + 2] = (Math.random() - 0.5) * 9;
      }
    }

    // ── Binary rain in depth ─────────────────────────────────
    const rain = ['0', '1'].map((ch) => {
      const count = small ? 220 : 520;
      const g = new THREE.BufferGeometry();
      const p = new Float32Array(count * 3);
      for (let k = 0; k < count; k++) {
        p[k * 3] = (Math.random() - 0.5) * 46;
        p[k * 3 + 1] = (Math.random() - 0.5) * 30;
        p[k * 3 + 2] = -28 + Math.random() * 30;
      }
      g.setAttribute('position', new THREE.BufferAttribute(p, 3));
      const m = new THREE.PointsMaterial({
        map: glyphTexture(ch),
        size: 0.34,
        color: 0xffc400,
        transparent: true,
        opacity: 0.32,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      });
      const pts = new THREE.Points(g, m);
      scene.add(pts);
      return pts;
    });

    // ── Bloom ────────────────────────────────────────────────
    const pr = renderer.getPixelRatio();
    const msaaTarget = new THREE.WebGLRenderTarget(window.innerWidth * pr, window.innerHeight * pr, {
      samples: 4,
      type: THREE.HalfFloatType,
    });
    const composer = new EffectComposer(renderer, msaaTarget);
    composer.setPixelRatio(pr);
    composer.addPass(new RenderPass(scene, camera));
    // Only the brightest bats (fast fliers, lit clusters) bloom; the void stays black.
    const bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.85, 0.4, 0.42);
    composer.addPass(bloom);
    composer.addPass(new OutputPass());

    let width = 1;
    let height = 1;
    let viewW = 1; // visible world width at z = 0
    let viewH = 1;
    function resize() {
      width = mount.clientWidth;
      height = mount.clientHeight;
      camera.aspect = width / height;
      const tan = Math.tan(THREE.MathUtils.degToRad(FOV / 2));
      // Far enough back that the split emblem fits both ways, centred on the core.
      const fitW = (EMBLEM_W * 1.16) / (2 * tan * camera.aspect);
      const span = EMBLEM_Y + EMBLEM_W * 0.2 - (CORE_Y - 0.9); // emblem top to below the hints
      const fitH = (span * 1.35) / (2 * tan);
      camera.position.set(0, LOOK_Y, Math.max(15, fitW, fitH));
      camera.lookAt(0, LOOK_Y, 0);
      camera.updateProjectionMatrix();
      viewH = 2 * camera.position.z * tan;
      viewW = viewH * camera.aspect;
      renderer.setSize(width, height);
      composer.setSize(width, height);
      bloom.resolution.set(width / 2, height / 2);
    }
    resize();
    window.addEventListener('resize', resize);

    // ── Pointer: scatter + drag to turn ──────────────────────
    const ndc = new THREE.Vector2(9, 9);
    const ray = new THREE.Raycaster();
    const plane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
    const hit = new THREE.Vector3();
    const local = new THREE.Vector3();
    let pointerActive = false;
    let dragging = false;
    let lastX = 0;
    let lastY = 0;
    let yaw = 0;
    let pitch = 0;
    let yawVel = 0;
    let pitchVel = 0;
    let lastDrag = -10;

    const onMove = (e) => {
      ndc.set((e.clientX / width) * 2 - 1, -(e.clientY / height) * 2 + 1);
      // Only scatter when the pointer is over the swarm itself, not resting
      // on the command line or a label.
      pointerActive = e.target === renderer.domElement;
      if (dragging) {
        yawVel = (e.clientX - lastX) * 0.005;
        pitchVel = (e.clientY - lastY) * 0.003;
        yaw += yawVel;
        pitch = THREE.MathUtils.clamp(pitch + pitchVel, -0.6, 0.6);
        lastX = e.clientX;
        lastY = e.clientY;
        lastDrag = clock.elapsedTime;
      }
    };
    const onDown = (e) => {
      dragging = true;
      lastX = e.clientX;
      lastY = e.clientY;
    };
    const onUp = () => {
      dragging = false;
    };
    const onLeave = () => {
      pointerActive = false;
    };
    renderer.domElement.addEventListener('pointerdown', onDown);
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    document.addEventListener('pointerleave', onLeave);

    // ── Simulation ───────────────────────────────────────────
    const clock = new THREE.Clock();
    const host = mount.parentElement;
    let coreX = -1;
    let coreY = -1;
    const dummy = new THREE.Object3D();
    const proj = new THREE.Vector3();
    const tmp = new THREE.Vector3();
    let raf = 0;

    function targetOf(k, t, m, out) {
      const ph = phase[k];
      if (m === 'storm') {
        // A vortex swirling around the command line, never through it.
        const h = (ph * 7 + t * 0.35) % 1;
        const th = ph * 40 + t * (3.4 - h * 2);
        return out.set(Math.cos(th) * (5.4 + h * 2.6), CORE_Y + 1.2 + Math.sin(th) * (1.5 + h * 2.6), Math.sin(th * 2 + ph * 9) * 1.8);
      }
      if (m === 'sites' && (live.current.sources || []).length) {
        const s = site[k];
        const r = orbit[k * 3];
        const th = ph * 6.283 + t * orbit[k * 3 + 2] * (s < 0 ? 0.05 : 0.9);
        if (s < 0) return out.set(Math.cos(th) * r, Math.sin(ph * 40 + t * 0.2) * 3.5, Math.sin(th) * r - 2);
        const phi = orbit[k * 3 + 1];
        const node = nodes[s];
        return out.set(node.x + r * Math.sin(phi) * Math.cos(th), node.y + r * Math.cos(phi), node.z + r * Math.sin(phi) * Math.sin(th));
      }
      if (k >= N * (1 - STREAM_SHARE)) {
        const u = (ph + t * 0.22) % 1;
        const side = (k & 1 ? 1 : -1) * (0.25 + ((ph * 97) % 1) * 0.75);
        const tailY = EMBLEM_Y - EMBLEM_W * 0.18;
        const ease = 1 - (1 - u) * (1 - u);
        return out.set(side * ease * 4.6 + Math.sin(t * 2 + ph * 30) * 0.06, tailY + (CORE_Y + 0.42 - tailY) * Math.min(1, u * 1.6), (ph - 0.5) * 0.4);
      }
      const b = 1 + Math.sin(t * 1.2 + ph * 6.283) * 0.012;
      return out.set(emblem[k * 3] * b, emblem[k * 3 + 1] * b + Math.sin(t * 0.8) * 0.12, emblem[k * 3 + 2]);
    }

    function step(dt, t, settle) {
      const m = live.current.mode;
      const hl = live.current.highlight || [];
      const list = live.current.sources || [];
      const lit = new Set(hl.map((d) => list.findIndex((s) => s.domain === d)).filter((i) => i >= 0));

      // The pointer, in the swarm's own coordinates.
      let mx = 1e9;
      let my = 1e9;
      let mz = 1e9;
      if (pointerActive && !dragging) {
        ray.setFromCamera(ndc, camera);
        if (ray.ray.intersectPlane(plane, hit)) {
          local.copy(hit);
          world.worldToLocal(local);
          mx = local.x;
          my = local.y;
          mz = local.z;
        }
      }
      const R = m === 'emblem' ? 1.9 : 1.5;
      const pull = m === 'storm' ? 3.4 : 2.6;
      const damp = Math.pow(0.86, dt * 60);

      for (let k = 0; k < N; k++) {
        const i3 = k * 3;
        targetOf(k, t, m, tmp);
        if (settle) {
          pos[i3] = tmp.x;
          pos[i3 + 1] = tmp.y;
          pos[i3 + 2] = tmp.z;
        } else {
          let vx = vel[i3] + (tmp.x - pos[i3]) * pull * dt;
          let vy = vel[i3 + 1] + (tmp.y - pos[i3 + 1]) * pull * dt;
          let vz = vel[i3 + 2] + (tmp.z - pos[i3 + 2]) * pull * dt;
          const dx = pos[i3] - mx;
          const dy = pos[i3 + 1] - my;
          const dz = pos[i3 + 2] - mz;
          const d2 = dx * dx + dy * dy + dz * dz;
          if (d2 < R * R) {
            const d = Math.sqrt(d2) || 0.001;
            const f = (1 - d / R) * 38 * dt;
            vx += (dx / d) * f;
            vy += (dy / d) * f;
            vz += (dz / d) * f * 0.6;
          }
          vel[i3] = vx * damp;
          vel[i3 + 1] = vy * damp;
          vel[i3 + 2] = vz * damp;
          pos[i3] += vel[i3] * dt * 4;
          pos[i3 + 1] += vel[i3 + 1] * dt * 4;
          pos[i3 + 2] += vel[i3 + 2] * dt * 4;
        }

        const speed = Math.min(1, Math.hypot(vel[i3], vel[i3 + 1]) * 0.8);
        const flap = settle ? 1 : 0.55 + 0.45 * Math.abs(Math.sin(t * (7 + phase[k] * 5) + phase[k] * 40));
        const s = size[k];
        dummy.position.set(pos[i3], pos[i3 + 1], pos[i3 + 2]);
        dummy.rotation.set(0, Math.sin(t * 0.6 + phase[k] * 9) * 0.18, THREE.MathUtils.clamp(-vel[i3] * 0.2, -0.5, 0.5));
        dummy.scale.set(s, s * flap, s);
        dummy.updateMatrix();
        bats.setMatrixAt(k, dummy.matrix);

        const si = site[k];
        let b = glow[k] * (0.8 + speed * 0.9);
        if (m === 'emblem' && k >= N * (1 - STREAM_SHARE)) {
          b *= 1.25 - ((phase[k] + t * 0.22) % 1) * 0.95; // fade as they reach the line
        }
        if (m === 'sites') {
          if (si >= 0 && (lit.has(si) || burstUntil[si] > t)) b *= 2.4;
          else if (lit.size) b *= 0.35;
          if (si < 0) b *= 0.3;
        }
        bats.instanceColor.setXYZ(k, YELLOW.r * b, YELLOW.g * b, YELLOW.b * b + 0.02);
      }
      bats.instanceMatrix.needsUpdate = true;
      bats.instanceColor.needsUpdate = true;

      for (const pts of rain) {
        const p = pts.geometry.attributes.position;
        for (let k = 0; k < p.count; k++) {
          let y = p.getY(k) - dt * (1.2 + (k % 7) * 0.35);
          if (y < -15) y = 15;
          p.setY(k, y);
        }
        p.needsUpdate = true;
      }

      // Turn: drag with inertia; idle drift in the constellation; the emblem faces you.
      if (!dragging) {
        yawVel *= 0.94;
        pitchVel *= 0.94;
        yaw += yawVel;
        if (t - lastDrag > 2.5) {
          if (m === 'emblem') {
            yaw += (Math.round(yaw / (Math.PI * 2)) * Math.PI * 2 - yaw) * 0.03;
            pitch += (0 - pitch) * 0.03;
          } else {
            yaw += dt * 0.06;
            pitch += (0.18 - pitch) * 0.02;
          }
        }
      }
      world.rotation.set(pitch, yaw, 0);
      // An open transmission slides the scene aside: left on wide screens,
      // up on narrow ones where the transmission rises from the bottom.
      const narrow = width < 760;
      const wantX = live.current.shift && !narrow ? -viewW * 0.22 : 0;
      const wantY = live.current.shift && narrow ? viewH * 0.24 : 0;
      root.position.x += (wantX - root.position.x) * 0.06;
      root.position.y += (wantY - root.position.y) * 0.06;

      // Publish where the core (the gap) sits on screen so the command line
      // can live exactly in it.
      proj.set(0, CORE_Y, 0);
      root.localToWorld(proj);
      proj.project(camera);
      const cx = (proj.x * 0.5 + 0.5) * width;
      const cy = (-proj.y * 0.5 + 0.5) * height;
      if (Math.abs(cx - coreX) > 0.5 || Math.abs(cy - coreY) > 0.5) {
        coreX = cx;
        coreY = cy;
        host.style.setProperty('--core-x', `${cx.toFixed(1)}px`);
        host.style.setProperty('--core-y', `${cy.toFixed(1)}px`);
      }

      // Site labels follow their clusters. Nearest clusters claim their spot
      // first; a label that would overlap a nearer one waits until it's clear.
      const showLabels = m === 'sites';
      const placed = [];
      list
        .map((s, i) => {
          proj.copy(nodes[i]);
          proj.y += clusterR[i] + 0.12;
          world.localToWorld(proj);
          const depth = proj.z;
          proj.project(camera);
          return { i, depth, x: (proj.x * 0.5 + 0.5) * width, y: (-proj.y * 0.5 + 0.5) * height };
        })
        .sort((a, b) => b.depth - a.depth)
        .forEach(({ i, depth, x, y }) => {
          const el = labelRefs.current[i];
          if (!el) return;
          const front = THREE.MathUtils.clamp((depth + 5) / 8, 0.55, 1);
          const w = el.offsetWidth || 120;
          const h = el.offsetHeight || 36;
          const rect = [x - w / 2, y - h, x + w / 2, y];
          const clash = placed.some((r) => rect[0] < r[2] && rect[2] > r[0] && rect[1] < r[3] && rect[3] > r[1]);
          const visible = showLabels && !clash;
          if (visible) placed.push(rect);
          el.style.transform = `translate(${x}px, ${y}px) translate(-50%, -100%) scale(${0.8 + front * 0.25})`;
          el.style.opacity = visible ? String(front) : '0';
          el.style.pointerEvents = visible ? 'auto' : 'none';
          el.style.zIndex = String(Math.round(front * 10));
        });
    }

    function frame() {
      raf = requestAnimationFrame(frame);
      const dt = Math.min(clock.getDelta(), 0.05);
      step(dt, clock.elapsedTime, false);
      composer.render();
    }

    allocate();
    if (reduce) {
      step(0, 0, true);
      composer.render();
    } else {
      raf = requestAnimationFrame(frame);
    }
    api.current = {
      allocate: () => {
        allocate();
        if (reduce) {
          step(0, 0, true);
          composer.render();
        }
      },
      burst,
      ripple,
      redraw: () => {
        if (reduce) {
          step(0, 0, true);
          composer.render();
        }
      },
    };

    const onVisibility = () => {
      cancelAnimationFrame(raf);
      if (!document.hidden && !reduce) {
        clock.getDelta();
        raf = requestAnimationFrame(frame);
      }
    };
    document.addEventListener('visibilitychange', onVisibility);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      document.removeEventListener('pointerleave', onLeave);
      document.removeEventListener('visibilitychange', onVisibility);
      geometry.dispose();
      material.dispose();
      rain.forEach((p) => {
        p.geometry.dispose();
        p.material.map.dispose();
        p.material.dispose();
      });
      composer.dispose?.();
      renderer.dispose();
      mount.removeChild(renderer.domElement);
      api.current = null;
    };
  }, []);

  // With reduced motion there is no loop, so redraw when the mode changes.
  useEffect(() => {
    api.current?.redraw();
  }, [mode, highlight]);

  return (
    <>
      <div ref={mountRef} className="swarm" aria-hidden="true" />
      <div className="site-labels">
        {sites.map((s, i) => (
          <button
            key={s.domain}
            ref={(el) => {
              labelRefs.current[i] = el;
            }}
            type="button"
            className={`site-label ${highlight?.includes(s.domain) ? 'is-lit' : ''}`}
            onClick={() => onPickSite(s.domain)}
          >
            <span className="site-name">{s.domain.replace(/^www\./, '')}</span>
            <span className="site-n num">
              {n(s.docs)} {s.docs === 1 ? 'page' : 'pages'}
            </span>
          </button>
        ))}
      </div>
    </>
  );
}
