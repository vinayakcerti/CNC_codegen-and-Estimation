// Offscreen part thumbnails for the Projects cards.
//
// After a part is analysed we have its tessellated mesh in memory — render a
// small isometric snapshot with a throwaway three.js renderer and cache the
// PNG (data URL) in localStorage keyed by filename. Cards then show the real
// part instead of a generic block. Cache is LRU-capped so quota stays safe.

import * as THREE from "three";
import type { Mesh } from "./api";

const KEY = "cnc.thumbs.v1";
const MAX_ENTRIES = 24;
const W = 220;
const H = 130;

type ThumbStore = { order: string[]; data: Record<string, string> };

function load(): ThumbStore {
  try {
    const raw = localStorage.getItem(KEY);
    const s = raw ? (JSON.parse(raw) as ThumbStore) : null;
    if (s && Array.isArray(s.order) && s.data && typeof s.data === "object") return s;
  } catch {
    /* corrupted store — start fresh */
  }
  return { order: [], data: {} };
}

export function getThumb(name: string): string | null {
  return load().data[name] ?? null;
}

export function putThumb(name: string, dataUrl: string) {
  const s = load();
  if (!s.data[name]) s.order.push(name);
  s.data[name] = dataUrl;
  while (s.order.length > MAX_ENTRIES) {
    const evict = s.order.shift();
    if (evict) delete s.data[evict];
  }
  try {
    localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    // Quota: drop half the cache and retry once; give up silently after.
    s.order.splice(0, Math.ceil(s.order.length / 2)).forEach((k) => delete s.data[k]);
    try {
      localStorage.setItem(KEY, JSON.stringify(s));
    } catch {
      /* thumbnails are cosmetic — never break the app over them */
    }
  }
}

// One shared renderer: WebGL contexts are a scarce resource (~8-16 per page),
// so never create one per thumbnail.
let renderer: THREE.WebGLRenderer | null = null;

export function renderMeshThumb(mesh: Mesh): string | null {
  try {
    if (!mesh?.x?.length || !mesh?.i?.length) return null;
    if (!renderer) {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
      renderer.setPixelRatio(1);
      renderer.setSize(W, H);
      renderer.setClearColor(0x000000, 0); // transparent — sits on the card's own bg
    }

    const n = mesh.x.length;
    const pos = new Float32Array(n * 3);
    for (let v = 0; v < n; v++) {
      pos[3 * v] = mesh.x[v];
      pos[3 * v + 1] = mesh.y[v];
      pos[3 * v + 2] = mesh.z[v];
    }
    const idx = new Uint32Array(mesh.i.length * 3);
    for (let t = 0; t < mesh.i.length; t++) {
      idx[3 * t] = mesh.i[t];
      idx[3 * t + 1] = mesh.j[t];
      idx[3 * t + 2] = mesh.k[t];
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    geo.setIndex(new THREE.BufferAttribute(idx, 1));
    geo.computeVertexNormals();
    geo.computeBoundingSphere();
    const bs = geo.boundingSphere;
    if (!bs || !Number.isFinite(bs.radius) || bs.radius <= 0) {
      geo.dispose();
      return null;
    }

    const scene = new THREE.Scene();
    const mat = new THREE.MeshStandardMaterial({ color: 0x9aa4b0, metalness: 0.3, roughness: 0.5 });
    scene.add(new THREE.Mesh(geo, mat));
    scene.add(new THREE.AmbientLight(0xffffff, 0.85));
    const key = new THREE.DirectionalLight(0xffffff, 1.15);
    key.position.set(1, -1, 1.4);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0xffffff, 0.35);
    fill.position.set(-1, 1, -0.5);
    scene.add(fill);

    // Same convention as the viewer: Z up, front-right-top isometric.
    const cam = new THREE.PerspectiveCamera(32, W / H, bs.radius / 100, bs.radius * 20);
    const dir = new THREE.Vector3(1, -1, 0.8).normalize();
    cam.position.copy(bs.center.clone().add(dir.multiplyScalar(bs.radius * 2.7)));
    cam.up.set(0, 0, 1);
    cam.lookAt(bs.center);

    renderer.render(scene, cam);
    const url = renderer.domElement.toDataURL("image/png");
    geo.dispose();
    mat.dispose();
    return url;
  } catch {
    return null; // cosmetic feature — any GL failure just keeps the block icon
  }
}
