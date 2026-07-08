import { useEffect, useMemo } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { TrackballControls, Bounds, GizmoHelper, GizmoViewcube, Grid, Html, Line, Edges } from "@react-three/drei";
import * as THREE from "three";
import type { Mesh } from "./api";

// CAD/STEP data is Z-up (part height runs along +Z). three.js defaults to
// Y-up, which put the orbit poles on ±Y and gimbal-locked flat faces so the
// part couldn't be flipped bottom-to-top. Everything here assumes Z-up.
const UP: Vec3 = [0, 0, 1];

export type Vec3 = [number, number, number];

export interface Approach {
  origin: Vec3;
  dir: Vec3;
}

export interface Highlight {
  x: number | null;
  y: number | null;
  z: number | null;
  diameter: number;
  length: number;
  width: number;
  depth: number;
  feature_type: string;
}

// Orients the camera to look at `center` from direction `dir` whenever `dir`
// changes. Works WITH OrbitControls (makeDefault) rather than against it:
// the controls' target is moved too, so orbiting continues from the new view.
function CameraRig({ dir, center, dist }: { dir: Vec3 | null; center: Vec3; dist: number }) {
  const camera = useThree((s) => s.camera);
  const controls = useThree((s) => s.controls) as unknown as {
    target: THREE.Vector3;
    update: () => void;
  } | null;

  useEffect(() => {
    if (!dir) return;
    const d = new THREE.Vector3(dir[0], dir[1], dir[2]);
    if (d.lengthSq() < 1e-9) return;
    d.normalize();
    // Nudge off the exact camera-up pole (±Z, since the scene is Z-up) so
    // OrbitControls' azimuth stays well-defined for the Top/Bottom views.
    if (Math.abs(d.z) > 0.999) {
      d.x += 0.02;
      d.y += 0.02;
      d.normalize();
    }
    const c = new THREE.Vector3(center[0], center[1], center[2]);
    camera.position.copy(c).addScaledVector(d, dist);
    camera.lookAt(c);
    if (controls) {
      controls.target.copy(c);
      controls.update();
    }
  }, [dir, center, dist, camera, controls]);

  return null;
}

// Toolpath-style approach cone: tip touches the setup's bbox face center,
// body extends outward opposite the tool direction. Drawn through the part
// (depthTest false) so it reads even when the face is occluded.
function ApproachCone({ approach, partSize }: { approach: Approach; partSize: number }) {
  const { pos, quat, len, rad } = useMemo(() => {
    const d = new THREE.Vector3(approach.dir[0], approach.dir[1], approach.dir[2]);
    if (d.lengthSq() < 1e-9) d.set(0, 0, -1);
    d.normalize();
    const len = Math.max(partSize * 0.12, 4);
    const rad = len * 0.35;
    // ConeGeometry's apex points +Y — rotate it onto the approach direction,
    // then back the center off so the apex lands exactly on the face center.
    const quat = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), d);
    const pos = new THREE.Vector3(approach.origin[0], approach.origin[1], approach.origin[2])
      .addScaledVector(d, -len / 2);
    return { pos, quat, len, rad };
  }, [approach, partSize]);

  return (
    <mesh position={pos} quaternion={quat} renderOrder={12}>
      <coneGeometry args={[rad, len, 24]} />
      <meshBasicMaterial color="#e0a63b" transparent opacity={0.9} depthTest={false} depthWrite={false} />
    </mesh>
  );
}

// ---- Workholding scene v1 (grid floor + vise jaws + flip indicator) ----
// Rendered only while a setup is active, and OUTSIDE the <Bounds> wrapper
// so fixture visuals never affect the camera fit.
interface Bbox {
  mins: Vec3;
  maxs: Vec3;
}

// Flip arrow: torus arc + arrowhead cone at the arc's end, tangent to it.
const FLIP_ARC = Math.PI * 1.4;
const FLIP_HEAD_QUAT = new THREE.Quaternion().setFromUnitVectors(
  new THREE.Vector3(0, 1, 0),
  new THREE.Vector3(-Math.sin(FLIP_ARC), Math.cos(FLIP_ARC), 0),
);

function WorkholdingScene({
  bbox,
  partSize,
  toolAxis,
  method,
  flip,
}: {
  bbox: Bbox;
  partSize: number;
  // Outward normal of the face being machined in the active setup (the tool
  // approaches along it). null → default to top-facing. The fixture must
  // clamp PERPENDICULAR to this and never sit on the machined face.
  toolAxis: Vec3 | null;
  // Recommended workholding method — chooses vise vs fixture-plate + clamps.
  method: string | null;
  flip: boolean;
}) {
  const mins = bbox.mins;
  const maxs = bbox.maxs;
  const cx = (mins[0] + maxs[0]) / 2;
  const cy = (mins[1] + maxs[1]) / 2;
  const zmax = maxs[2];
  const c: Vec3 = [cx, cy, (mins[2] + maxs[2]) / 2];
  const span: Vec3 = [
    Math.max(maxs[0] - mins[0], 1),
    Math.max(maxs[1] - mins[1], 1),
    Math.max(maxs[2] - mins[2], 1),
  ];

  // Machined-face axis = dominant tool-approach axis (default top, +Z).
  const t: Vec3 =
    toolAxis && Math.abs(toolAxis[0]) + Math.abs(toolAxis[1]) + Math.abs(toolAxis[2]) > 0.4
      ? toolAxis
      : [0, 0, 1];
  const at = [Math.abs(t[0]), Math.abs(t[1]), Math.abs(t[2])];
  const mAx = at[0] >= at[1] && at[0] >= at[2] ? 0 : at[1] >= at[2] ? 1 : 2;
  const tSign = t[mAx] >= 0 ? 1 : -1;
  const perp = [0, 1, 2].filter((a) => a !== mAx);
  // Clamp across the WIDER perpendicular axis so grips sit far apart & stable.
  const clampAx = span[perp[0]] >= span[perp[1]] ? perp[0] : perp[1];
  const otherAx = perp[0] === clampAx ? perp[1] : perp[0];
  const triple = (byAx: (a: number) => number): Vec3 => [byAx(0), byAx(1), byAx(2)];

  const isPlate = method ? /plate|toe|clamp/i.test(method) : false;
  const steel = "#3d5a80";

  // Fixture-plate style: backing plate on the tool-OPPOSITE face + two toe
  // clamps gripping the machined-face perimeter edges (tool faces interior).
  const plateT = Math.max(partSize * 0.03, 4);
  const platePos = triple((a) =>
    a === mAx ? (tSign > 0 ? mins[mAx] - plateT / 2 : maxs[mAx] + plateT / 2) : c[a],
  );
  const plateSize = triple((a) => (a === mAx ? plateT : span[a] * 1.2));
  const cw = Math.max(partSize * 0.06, 6);
  const clampM = c[mAx] + tSign * span[mAx] * 0.42;
  const clampSize = triple((a) => (a === clampAx ? cw * 1.3 : a === mAx ? cw : cw * 1.7));
  const clampPosA = triple((a) => (a === clampAx ? mins[clampAx] : a === mAx ? clampM : c[a]));
  const clampPosB = triple((a) => (a === clampAx ? maxs[clampAx] : a === mAx ? clampM : c[a]));

  // Vise style: two soft jaws on the ±clamp-axis faces, biased to the
  // tool-opposite portion so the machined face stays clear.
  const jt = Math.max(partSize * 0.05, 6);
  const jawSize = triple((a) =>
    a === clampAx ? jt : a === otherAx ? span[otherAx] * 0.7 : span[mAx] * 0.55,
  );
  const jawM = c[mAx] - tSign * span[mAx] * 0.2;
  const jawPosA = triple((a) => (a === clampAx ? mins[clampAx] - jt / 2 : a === otherAx ? c[otherAx] : jawM));
  const jawPosB = triple((a) => (a === clampAx ? maxs[clampAx] + jt / 2 : a === otherAx ? c[otherAx] : jawM));

  const r = Math.max(partSize * 0.18, 6);
  const tube = r * 0.07;

  return (
    <group>
      {/* The gridded bed (SceneFloor) is the ground; fixture clamps clear of
          the machined face (perpendicular to the active tool axis). */}
      {isPlate ? (
        <>
          <mesh position={platePos}>
            <boxGeometry args={plateSize} />
            <meshStandardMaterial color={steel} metalness={0.3} roughness={0.55} />
          </mesh>
          <mesh position={clampPosA}>
            <boxGeometry args={clampSize} />
            <meshStandardMaterial color="#c07a2a" metalness={0.4} roughness={0.5} />
          </mesh>
          <mesh position={clampPosB}>
            <boxGeometry args={clampSize} />
            <meshStandardMaterial color="#c07a2a" metalness={0.4} roughness={0.5} />
          </mesh>
        </>
      ) : (
        <>
          <mesh position={jawPosA}>
            <boxGeometry args={jawSize} />
            <meshStandardMaterial color={steel} metalness={0.3} roughness={0.5} />
          </mesh>
          <mesh position={jawPosB}>
            <boxGeometry args={jawSize} />
            <meshStandardMaterial color={steel} metalness={0.3} roughness={0.5} />
          </mesh>
        </>
      )}
      {flip && (
        // Local XY arc rotated into a vertical plane; drawn through the part
        // (depthTest false) but BELOW the approach cone (renderOrder 11 < 12).
        <group position={[cx, cy, zmax + r * 1.05]} rotation={[Math.PI / 2, 0, 0]}>
          <mesh renderOrder={11}>
            <torusGeometry args={[r, tube, 12, 48, FLIP_ARC]} />
            <meshBasicMaterial color="#e0a63b" transparent opacity={0.95} depthTest={false} depthWrite={false} />
          </mesh>
          <mesh
            position={[r * Math.cos(FLIP_ARC), r * Math.sin(FLIP_ARC), 0]}
            quaternion={FLIP_HEAD_QUAT}
            renderOrder={11}
          >
            <coneGeometry args={[tube * 2.6, tube * 7, 16]} />
            <meshBasicMaterial color="#e0a63b" transparent opacity={0.95} depthTest={false} depthWrite={false} />
          </mesh>
        </group>
      )}
    </group>
  );
}

// ---- Scene floor: machine-bed grid + scale + dimension labels ----------
// Toolpath-style "meshed base" that grounds the part and doubles as the
// scale reference (each grid cell = a round number of mm), plus an L×W×H
// dimension frame. Rendered outside <Bounds> so it never affects the fit.
function fmtMm(v: number): string {
  return v >= 100 ? `${Math.round(v)} mm` : `${v.toFixed(1)} mm`;
}

function DimLabel({ pos, text, light }: { pos: Vec3; text: string; light: boolean }) {
  return (
    <Html position={pos} center style={{ pointerEvents: "none", userSelect: "none" }}>
      <div
        style={{
          fontFamily: "system-ui, sans-serif",
          fontSize: 11,
          fontWeight: 600,
          whiteSpace: "nowrap",
          padding: "1px 6px",
          borderRadius: 4,
          color: light ? "#2a2f36" : "#e6e9ee",
          background: light ? "rgba(255,255,255,0.85)" : "rgba(20,24,28,0.8)",
          border: `1px solid ${light ? "#c2c8d0" : "#3a4048"}`,
        }}
      >
        {text}
      </div>
    </Html>
  );
}

function SceneFloor({
  bbox,
  partSize,
  light,
  showGrid,
  showDims,
}: {
  bbox: Bbox;
  partSize: number;
  light: boolean;
  showGrid: boolean;
  showDims: boolean;
}) {
  const [xmin, ymin, zmin] = bbox.mins;
  const [xmax, ymax, zmax] = bbox.maxs;
  const cx = (xmin + xmax) / 2;
  const cy = (ymin + ymax) / 2;
  const cz = (zmin + zmax) / 2;
  const xspan = xmax - xmin;
  const yspan = ymax - ymin;
  const zspan = zmax - zmin;
  const floorZ = zmin - Math.max(partSize * 0.01, 0.5);
  const pad = Math.max(partSize * 0.05, 4);

  // Round grid cell to a sensible mm step for the part scale (10/25/50 mm).
  const cell = partSize > 400 ? 50 : partSize > 120 ? 25 : 10;
  const section = cell * 5;

  const edges = useMemo(() => {
    const box = new THREE.BoxGeometry(Math.max(xspan, 0.1), Math.max(yspan, 0.1), Math.max(zspan, 0.1));
    const e = new THREE.EdgesGeometry(box);
    box.dispose();
    return e;
  }, [xspan, yspan, zspan]);
  useEffect(() => () => edges.dispose(), [edges]);

  return (
    <group>
      {showGrid && (
        // Gridded machine bed on the XY plane at the part base
        <Grid
          position={[cx, cy, floorZ]}
          rotation={[-Math.PI / 2, 0, 0]}
          args={[partSize * 3, partSize * 3]}
          cellSize={cell}
          cellThickness={0.6}
          cellColor={light ? "#c2c8d0" : "#3a4048"}
          sectionSize={section}
          sectionThickness={1.1}
          sectionColor={light ? "#8a94a0" : "#5a6570"}
          fadeDistance={partSize * 6}
          fadeStrength={1.2}
          infiniteGrid={false}
        />
      )}
      {showDims && (
        <>
          {/* Bounding-box dimension frame */}
          <lineSegments geometry={edges} position={[cx, cy, cz]} renderOrder={2}>
            <lineBasicMaterial color={light ? "#7b8794" : "#6b7480"} transparent opacity={0.55} />
          </lineSegments>
          {/* L × W × H labels along the three edges */}
          <DimLabel pos={[cx, ymin - pad, zmin]} text={fmtMm(xspan)} light={light} />
          <DimLabel pos={[xmax + pad, cy, zmin]} text={fmtMm(yspan)} light={light} />
          <DimLabel pos={[xmax + pad, ymin - pad, cz]} text={fmtMm(zspan)} light={light} />
        </>
      )}
    </group>
  );
}

// Colored X/Y/Z axis triad (Toolpath-style: X red, Y green, Z blue) at the
// part's lower corner — an orientation aid that reads with the free rotation.
function AxisTriad({ bbox, partSize }: { bbox: Bbox; partSize: number }) {
  const [xmin, ymin, zmin] = bbox.mins;
  const pad = partSize * 0.06;
  const o: Vec3 = [xmin - pad, ymin - pad, zmin - pad];
  const L = partSize * 0.32;
  return (
    <group>
      <Line points={[o, [o[0] + L, o[1], o[2]]]} color="#e05a5a" lineWidth={2} />
      <Line points={[o, [o[0], o[1] + L, o[2]]]} color="#5ac36a" lineWidth={2} />
      <Line points={[o, [o[0], o[1], o[2] + L]]} color="#5a9eff" lineWidth={2} />
    </group>
  );
}

// Translucent raw-stock envelope: the part bbox grown by the per-side
// allowance (Streamlit had this; the React viewer had dropped it). Stays in
// the mesh frame so it works for the assembly and any scoped body.
function StockBox({ bbox, allowance, light }: { bbox: Bbox; allowance: number; light: boolean }) {
  const [xmin, ymin, zmin] = bbox.mins;
  const [xmax, ymax, zmax] = bbox.maxs;
  const a = Math.max(allowance, 0);
  const sx = xmax - xmin + 2 * a;
  const sy = ymax - ymin + 2 * a;
  const sz = zmax - zmin + 2 * a;
  const cx = (xmin + xmax) / 2;
  const cy = (ymin + ymax) / 2;
  const cz = (zmin + zmax) / 2;
  const edges = useMemo(() => {
    const box = new THREE.BoxGeometry(Math.max(sx, 0.1), Math.max(sy, 0.1), Math.max(sz, 0.1));
    const e = new THREE.EdgesGeometry(box);
    box.dispose();
    return e;
  }, [sx, sy, sz]);
  useEffect(() => () => edges.dispose(), [edges]);
  return (
    <group position={[cx, cy, cz]}>
      <mesh renderOrder={1}>
        <boxGeometry args={[sx, sy, sz]} />
        <meshStandardMaterial
          color={light ? "#5a86c0" : "#4a78b0"}
          transparent
          opacity={0.06}
          depthWrite={false}
          metalness={0}
          roughness={1}
        />
      </mesh>
      <lineSegments geometry={edges} renderOrder={2}>
        <lineBasicMaterial color="#5a86c0" transparent opacity={0.5} />
      </lineSegments>
    </group>
  );
}

// Shared Mesh-dict → BufferGeometry builder (part body + exact-face overlays).
function buildGeometry(mesh: Mesh): THREE.BufferGeometry {
  const g = new THREE.BufferGeometry();
  const n = mesh.x.length;
  const pos = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    pos[i * 3] = mesh.x[i];
    pos[i * 3 + 1] = mesh.y[i];
    pos[i * 3 + 2] = mesh.z[i];
  }
  // Sanitize: OCC tessellation occasionally emits NaN vertices on
  // complex weldments — they break bounding-sphere computation.
  for (let i = 0; i < pos.length; i++) {
    if (!Number.isFinite(pos[i])) pos[i] = 0;
  }
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  const tri = mesh.i.length;
  const idx = new Uint32Array(tri * 3);
  for (let i = 0; i < tri; i++) {
    idx[i * 3] = mesh.i[i];
    idx[i * 3 + 1] = mesh.j[i];
    idx[i * 3 + 2] = mesh.k[i];
  }
  g.setIndex(new THREE.BufferAttribute(idx, 1));
  g.computeVertexNormals();
  return g;
}

function PartMesh({
  mesh,
  dimmed,
  light,
  opacity,
}: {
  mesh: Mesh;
  dimmed: boolean;
  light: boolean;
  opacity: number;
}) {
  const geometry = useMemo(() => buildGeometry(mesh), [mesh]);

  const effOpacity = (dimmed ? 0.4 : 1) * opacity;
  const isTransparent = effOpacity < 0.999;
  return (
    <mesh geometry={geometry}>
      <meshStandardMaterial
        // key remounts the material when transparency mode flips — three.js
        // does not re-sort/re-compile on a `transparent` prop change alone,
        // which left the part looking see-through at 100% opacity.
        key={isTransparent ? "t" : "o"}
        color={light ? "#b6bdc8" : "#dbe0e8"}
        metalness={0.12}
        roughness={0.48}
        transparent={isTransparent}
        opacity={effOpacity}
      />
      {/* Crisp edge lines so corners/edges read against the dark scene —
          like Toolpath's part view. threshold hides curved-surface
          tessellation but keeps sharp feature/silhouette edges. Kept
          visible (faded) when the body is dimmed so the outline still
          orients you while a feature is highlighted. */}
      <Edges
        threshold={20}
        color={light ? "#5b636e" : "#7c8794"}
        transparent
        opacity={isTransparent ? 0.4 : 1}
      />
    </mesh>
  );
}

function HighlightMarker({ hl, meshTopZ, partSize }: { hl: Highlight; meshTopZ: number; partSize: number }) {
  const num = (v: number | null | undefined, fallback: number) =>
    Number.isFinite(v as number) ? (v as number) : fallback;
  const x = num(hl.x, 0);
  const y = num(hl.y, 0);
  const z = num(hl.z, meshTopZ);
  const r = Math.max(num(hl.diameter, 0) / 2, num(hl.width, 0) / 2, 5);
  const isArea = num(hl.length, 0) > 0 && num(hl.width, 0) > 0 && !num(hl.diameter, 0);
  const depth = Math.max(num(hl.depth, 0), 2);
  // Locator ring scales with the part so small features stay findable
  const ringR = Math.max(r + 3, num(partSize, 100) * 0.02);

  const L = num(hl.length, 10);
  const W = num(hl.width, 10);
  return (
    <group position={[x, y, z]} renderOrder={10}>
      {isArea ? (
        // Area feature (facing / step / pocket) with no exact faces: a filled
        // slab sized to the machined region + a bright wireframe outline so it
        // reads as "this surface/area", NOT a hole ring.
        <group renderOrder={10}>
          <mesh>
            <boxGeometry args={[L, W, depth]} />
            <meshStandardMaterial
              color="#4a9eff" emissive="#4a9eff" emissiveIntensity={0.5}
              transparent opacity={0.32} depthWrite={false} depthTest={false}
            />
          </mesh>
          <mesh>
            <boxGeometry args={[L, W, depth]} />
            <meshBasicMaterial
              color="#8fc4ff" wireframe
              transparent opacity={0.9} depthWrite={false} depthTest={false}
            />
          </mesh>
        </group>
      ) : (
        // Hole / drill: short cylinder down the bore + a locator ring (the
        // ring is intuitive for round holes; kept for this case only).
        <>
          <mesh rotation={[Math.PI / 2, 0, 0]} renderOrder={10}>
            <cylinderGeometry args={[r, r, depth + 6, 32]} />
            <meshStandardMaterial
              color="#4a9eff" emissive="#4a9eff" emissiveIntensity={0.6}
              transparent opacity={0.6} depthWrite={false} depthTest={false}
            />
          </mesh>
          <mesh renderOrder={11}>
            <ringGeometry args={[ringR, ringR * 1.18, 48]} />
            <meshBasicMaterial
              color="#4a9eff" side={THREE.DoubleSide}
              transparent opacity={0.95} depthWrite={false} depthTest={false}
            />
          </mesh>
        </>
      )}
    </group>
  );
}

// Exact-face highlight: the op's actual CAD faces draped on the part.
// These faces lie ON the part skin, so depthTest stays TRUE (depthTest:false
// would bleed them through the whole body) and polygonOffset pulls them just
// in front of the coincident part triangles so they win the depth tie.
function FaceMeshOverlay({ meshes }: { meshes: Mesh[] }) {
  const geoms = useMemo(() => meshes.map(buildGeometry), [meshes]);
  // Face overlays churn with every op click — free the GPU buffers.
  useEffect(() => () => geoms.forEach((g) => g.dispose()), [geoms]);
  return (
    <group>
      {geoms.map((g, n) => (
        <mesh key={n} geometry={g} renderOrder={9}>
          <meshStandardMaterial
            color="#4a9eff"
            emissive="#4a9eff"
            emissiveIntensity={0.7}
            transparent
            opacity={0.85}
            depthWrite={false}
            side={THREE.DoubleSide}
            polygonOffset
            polygonOffsetFactor={-2}
            polygonOffsetUnits={-2}
          />
        </mesh>
      ))}
    </group>
  );
}

export function PartViewer({
  mesh,
  highlight,
  faceMeshes = null,
  theme = "dark",
  cameraDir = null,
  approach = null,
  opacity = 1,
  workholding = null,
  layers,
  stockAllowance = 5,
}: {
  mesh: Mesh | null;
  highlight?: Highlight | null;
  // Exact tessellated faces of the selected op's feature (raw-CAD frame,
  // same as `mesh`). When present they replace the approximate marker.
  faceMeshes?: Mesh[] | null;
  theme?: "dark" | "light";
  // Direction from part center to camera — set to re-orient the view (setup click)
  cameraDir?: Vec3 | null;
  // Tool-approach cone: origin on the part face, dir pointing into the part
  approach?: Approach | null;
  // Part opacity (0.2–1); multiplies the dim-on-highlight factor
  opacity?: number;
  // Fixture visuals for the active setup. toolAxis = machined-face normal so
  // the fixture clamps clear of it; method picks vise vs fixture-plate; flip =
  // secondary face re-fixture hint.
  workholding?: { flip: boolean; toolAxis?: Vec3 | null; method?: string | null } | null;
  // Toggleable scene layers (operator-controlled render settings)
  layers?: { grid: boolean; dims: boolean; stock: boolean; fixture: boolean };
  // Per-side stock allowance (mm) for the translucent stock envelope
  stockAllowance?: number;
}) {
  const L = layers ?? { grid: true, dims: true, stock: false, fixture: false };
  const light = theme === "light";
  const { meshTopZ, partSize, center, bbox } = useMemo(() => {
    const none = {
      meshTopZ: 0,
      partSize: 100,
      center: [0, 0, 0] as Vec3,
      bbox: null as Bbox | null,
    };
    if (!mesh || !mesh.z.length) return none;
    // Loop-based bbox over the full arrays (spread over huge meshes would
    // overflow the stack; the old 20k-vertex sample under-measured big parts).
    const mins: Vec3 = [Infinity, Infinity, Infinity];
    const maxs: Vec3 = [-Infinity, -Infinity, -Infinity];
    const axes = [mesh.x, mesh.y, mesh.z];
    for (let a = 0; a < 3; a++) {
      const arr = axes[a];
      for (let i = 0; i < arr.length; i++) {
        const v = arr[i];
        if (!Number.isFinite(v)) continue;
        if (v < mins[a]) mins[a] = v;
        if (v > maxs[a]) maxs[a] = v;
      }
    }
    if (![...mins, ...maxs].every(Number.isFinite)) return none;
    const size = Math.max(maxs[0] - mins[0], maxs[1] - mins[1], maxs[2] - mins[2]);
    return {
      meshTopZ: maxs[2],
      partSize: size > 0 ? size : 100,
      center: [
        (mins[0] + maxs[0]) / 2,
        (mins[1] + maxs[1]) / 2,
        (mins[2] + maxs[2]) / 2,
      ] as Vec3,
      bbox: { mins, maxs } as Bbox,
    };
  }, [mesh]);

  return (
    <Canvas
      camera={{ position: [420, -520, 380], up: UP, fov: 45, near: 1, far: 20000 }}
      style={{ width: "100%", height: "100%" }}
    >
      <color attach="background" args={[light ? "#eef0f3" : "#191c20"]} />
      <ambientLight intensity={0.98} />
      <directionalLight position={[300, 200, 500]} intensity={1.55} />
      <directionalLight position={[-200, -300, -100]} intensity={0.55} />
      {mesh && (
        <Bounds fit clip observe margin={1.25}>
          <PartMesh mesh={mesh} dimmed={!!highlight} light={light} opacity={opacity} />
        </Bounds>
      )}
      {mesh && bbox && (
        <SceneFloor bbox={bbox} partSize={partSize} light={light} showGrid={L.grid} showDims={L.dims} />
      )}
      {mesh && bbox && L.grid && <AxisTriad bbox={bbox} partSize={partSize} />}
      {mesh && bbox && L.stock && (
        <StockBox bbox={bbox} allowance={stockAllowance} light={light} />
      )}
      {/* Fixture: App decides visibility (Fixture layer or an active setup)
          and passes the machined-face axis so it clamps clear of it. */}
      {mesh && bbox && workholding && (
        <WorkholdingScene
          bbox={bbox}
          partSize={partSize}
          toolAxis={workholding.toolAxis ?? null}
          method={workholding.method ?? null}
          flip={workholding.flip}
        />
      )}
      {/* Exact faces win; the marker is the fallback for ops without them.
          Both render OUTSIDE <Bounds> so selection never re-fits the camera. */}
      {mesh && faceMeshes && faceMeshes.length > 0 && <FaceMeshOverlay meshes={faceMeshes} />}
      {mesh && highlight && !(faceMeshes && faceMeshes.length > 0) && (
        <HighlightMarker hl={highlight} meshTopZ={meshTopZ} partSize={partSize} />
      )}
      {mesh && approach && <ApproachCone approach={approach} partSize={partSize} />}
      <CameraRig dir={cameraDir} center={center} dist={Math.max(partSize * 1.8, 50)} />
      {/* Free arcball rotation (like Toolpath): no up-axis pole, so the part
          turns in ANY direction — fixes the "can't rotate horizontally at the
          edge-on/top view" pole lock that OrbitControls can't escape. */}
      <TrackballControls
        makeDefault
        rotateSpeed={3.5}
        zoomSpeed={1.2}
        panSpeed={0.8}
        dynamicDampingFactor={0.18}
      />
      <GizmoHelper alignment="top-right" margin={[64, 64]}>
        <GizmoViewcube
          color={light ? "#dde1e6" : "#2a2f36"}
          textColor={light ? "#4a4f57" : "#a8adb5"}
          strokeColor={light ? "#aab1bb" : "#444a52"}
        />
      </GizmoHelper>
    </Canvas>
  );
}
