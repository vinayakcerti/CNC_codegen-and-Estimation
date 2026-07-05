import { useMemo } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, Bounds, GizmoHelper, GizmoViewcube } from "@react-three/drei";
import * as THREE from "three";
import type { Mesh } from "./api";

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
}: {
  mesh: Mesh | null;
  highlight?: Highlight | null;
  theme?: "dark" | "light";
}) {
  const light = theme === "light";
  const { meshTopZ, partSize } = useMemo(() => {
    if (!mesh || !mesh.z.length) return { meshTopZ: 0, partSize: 100 };
    const finite = (a: number[]) => a.slice(0, 20000).filter(Number.isFinite);
    const zs = finite(mesh.z);
    const xs = finite(mesh.x);
    const ys = finite(mesh.y);
    if (!zs.length) return { meshTopZ: 0, partSize: 100 };
    const span = (a: number[]) => Math.max(...a) - Math.min(...a);
    const size = Math.max(span(xs), span(ys), span(zs));
    return {
      meshTopZ: Math.max(...zs),
      partSize: Number.isFinite(size) && size > 0 ? size : 100,
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
