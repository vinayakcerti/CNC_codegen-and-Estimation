import { useEffect, useMemo } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { OrbitControls, Bounds, GizmoHelper, GizmoViewcube } from "@react-three/drei";
import * as THREE from "three";
import type { Mesh } from "./api";

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
    // Nudge off the exact camera-up pole (±Y) so OrbitControls' azimuth
    // stays well-defined for the Front/Back views.
    if (Math.abs(d.y) > 0.999) {
      d.x += 0.02;
      d.z += 0.02;
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
  flip,
  light,
}: {
  bbox: Bbox;
  partSize: number;
  flip: boolean;
  light: boolean;
}) {
  const [xmin, ymin, zmin] = bbox.mins;
  const [xmax, ymax, zmax] = bbox.maxs;
  const cx = (xmin + xmax) / 2;
  const cy = (ymin + ymax) / 2;
  const xspan = Math.max(xmax - xmin, 1);
  const yspan = Math.max(ymax - ymin, 1);
  const zspan = Math.max(zmax - zmin, 1);

  // Grid floor: large thin plate 2 mm under the part (raw CAD frame, Z-up)
  const floorSize = partSize * 2.5;
  const floorT = Math.max(partSize * 0.005, 0.5);
  const floorZ = zmin - 2 - floorT / 2;

  // Vise: two jaw blocks clamping the shortest horizontal axis, flush to
  // the part's bbox sides and rising from its base (below the approach cone).
  const clampX = xspan <= yspan;
  const jawT = Math.max(partSize * 0.15, 2); // thickness along the clamp axis
  const jawH = Math.max(zspan * 0.4, 2); // height
  const jawL = (clampX ? yspan : xspan) * 0.7; // length along the other axis
  const jawZ = zmin + jawH / 2;
  const jawArgs: [number, number, number] = clampX ? [jawT, jawL, jawH] : [jawL, jawT, jawH];
  const jawA: Vec3 = clampX ? [xmin - jawT / 2, cy, jawZ] : [cx, ymin - jawT / 2, jawZ];
  const jawB: Vec3 = clampX ? [xmax + jawT / 2, cy, jawZ] : [cx, ymax + jawT / 2, jawZ];

  // Flip indicator: amber curved arrow hovering over the top face
  const r = Math.max(partSize * 0.18, 6);
  const tube = r * 0.07;

  return (
    <group>
      <mesh position={[cx, cy, floorZ]}>
        <boxGeometry args={[floorSize, floorSize, floorT]} />
        <meshStandardMaterial color={light ? "#d6dae0" : "#2a2f36"} metalness={0} roughness={0.9} />
      </mesh>
      <mesh position={jawA}>
        <boxGeometry args={jawArgs} />
        <meshStandardMaterial color="#3d5a80" metalness={0.3} roughness={0.5} />
      </mesh>
      <mesh position={jawB}>
        <boxGeometry args={jawArgs} />
        <meshStandardMaterial color="#3d5a80" metalness={0.3} roughness={0.5} />
      </mesh>
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
  const geometry = useMemo(() => {
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
  }, [mesh]);

  return (
    <mesh geometry={geometry}>
      <meshStandardMaterial
        color={light ? "#a7aeb8" : "#c9ced6"}
        metalness={0.15}
        roughness={0.55}
        transparent
        opacity={(dimmed ? 0.4 : 1) * opacity}
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

  return (
    <group position={[x, y, z]} renderOrder={10}>
      {isArea ? (
        <mesh renderOrder={10}>
          <boxGeometry args={[num(hl.length, 10), num(hl.width, 10), depth]} />
          <meshStandardMaterial
            color="#4a9eff" emissive="#4a9eff" emissiveIntensity={0.6}
            transparent opacity={0.45} depthWrite={false} depthTest={false}
          />
        </mesh>
      ) : (
        <mesh rotation={[Math.PI / 2, 0, 0]} renderOrder={10}>
          <cylinderGeometry args={[r, r, depth + 6, 32]} />
          <meshStandardMaterial
            color="#4a9eff" emissive="#4a9eff" emissiveIntensity={0.6}
            transparent opacity={0.6} depthWrite={false} depthTest={false}
          />
        </mesh>
      )}
      <mesh renderOrder={11}>
        <ringGeometry args={[ringR, ringR * 1.18, 48]} />
        <meshBasicMaterial
          color="#4a9eff" side={THREE.DoubleSide}
          transparent opacity={0.95} depthWrite={false} depthTest={false}
        />
      </mesh>
    </group>
  );
}

export function PartViewer({
  mesh,
  highlight,
  theme = "dark",
  cameraDir = null,
  approach = null,
  opacity = 1,
  workholding = null,
}: {
  mesh: Mesh | null;
  highlight?: Highlight | null;
  theme?: "dark" | "light";
  // Direction from part center to camera — set to re-orient the view (setup click)
  cameraDir?: Vec3 | null;
  // Tool-approach cone: origin on the part face, dir pointing into the part
  approach?: Approach | null;
  // Part opacity (0.2–1); multiplies the dim-on-highlight factor
  opacity?: number;
  // Fixture visuals for the active setup; flip = secondary face, re-fixture hint
  workholding?: { flip: boolean } | null;
}) {
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
      camera={{ position: [400, 320, 400], fov: 45, near: 1, far: 20000 }}
      style={{ width: "100%", height: "100%" }}
    >
      <color attach="background" args={[light ? "#eef0f3" : "#191c20"]} />
      <ambientLight intensity={0.85} />
      <directionalLight position={[300, 500, 200]} intensity={1.3} />
      <directionalLight position={[-200, -100, -300]} intensity={0.4} />
      {mesh && (
        <Bounds fit clip observe margin={1.25}>
          <PartMesh mesh={mesh} dimmed={!!highlight} light={light} opacity={opacity} />
        </Bounds>
      )}
      {mesh && workholding && bbox && (
        <WorkholdingScene bbox={bbox} partSize={partSize} flip={workholding.flip} light={light} />
      )}
      {mesh && highlight && <HighlightMarker hl={highlight} meshTopZ={meshTopZ} partSize={partSize} />}
      {mesh && approach && <ApproachCone approach={approach} partSize={partSize} />}
      <CameraRig dir={cameraDir} center={center} dist={Math.max(partSize * 1.8, 50)} />
      <OrbitControls makeDefault enableDamping dampingFactor={0.12} />
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
