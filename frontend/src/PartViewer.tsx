import { useMemo } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, Bounds, GizmoHelper, GizmoViewcube } from "@react-three/drei";
import * as THREE from "three";
import type { Mesh } from "./api";

function PartMesh({ mesh }: { mesh: Mesh }) {
  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry();
    const n = mesh.x.length;
    const pos = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      pos[i * 3] = mesh.x[i];
      pos[i * 3 + 1] = mesh.y[i];
      pos[i * 3 + 2] = mesh.z[i];
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
    g.center();
    return g;
  }, [mesh]);

  return (
    <mesh geometry={geometry}>
      <meshStandardMaterial color="#c9ced6" metalness={0.15} roughness={0.55} />
    </mesh>
  );
}

export function PartViewer({ mesh }: { mesh: Mesh | null }) {
  return (
    <Canvas
      camera={{ position: [400, 320, 400], fov: 45, near: 1, far: 20000 }}
      style={{ width: "100%", height: "100%" }}
    >
      <color attach="background" args={["#191c20"]} />
      <ambientLight intensity={0.85} />
      <directionalLight position={[300, 500, 200]} intensity={1.3} />
      <directionalLight position={[-200, -100, -300]} intensity={0.4} />
      {mesh && (
        <Bounds fit clip observe margin={1.25}>
          <PartMesh mesh={mesh} />
        </Bounds>
      )}
      <OrbitControls makeDefault enableDamping dampingFactor={0.12} />
      <GizmoHelper alignment="top-right" margin={[64, 64]}>
        <GizmoViewcube color="#2a2f36" textColor="#a8adb5" strokeColor="#444a52" />
      </GizmoHelper>
    </Canvas>
  );
}
