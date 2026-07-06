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

function PartMesh({ mesh, dimmed, light }: { mesh: Mesh; dimmed: boolean; light: boolean }) {
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
        opacity={dimmed ? 0.4 : 1}
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
}: {
  mesh: Mesh | null;
  highlight?: Highlight | null;
  theme?: "dark" | "light";
  // Direction from part center to camera — set to re-orient the view (setup click)
  cameraDir?: Vec3 | null;
  // Tool-approach cone: origin on the part face, dir pointing into the part
  approach?: Approach | null;
}) {
  const light = theme === "light";
  const { meshTopZ, partSize, center } = useMemo(() => {
    const none = { meshTopZ: 0, partSize: 100, center: [0, 0, 0] as Vec3 };
    if (!mesh || !mesh.z.length) return none;
    const finite = (a: number[]) => a.slice(0, 20000).filter(Number.isFinite);
    const zs = finite(mesh.z);
    const xs = finite(mesh.x);
    const ys = finite(mesh.y);
    if (!zs.length || !xs.length || !ys.length) return none;
    const span = (a: number[]) => Math.max(...a) - Math.min(...a);
    const mid = (a: number[]) => (Math.max(...a) + Math.min(...a)) / 2;
    const size = Math.max(span(xs), span(ys), span(zs));
    return {
      meshTopZ: Math.max(...zs),
      partSize: Number.isFinite(size) && size > 0 ? size : 100,
      center: [mid(xs), mid(ys), mid(zs)] as Vec3,
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
          <PartMesh mesh={mesh} dimmed={!!highlight} light={light} />
        </Bounds>
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
