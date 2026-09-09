import React, { Suspense, useEffect } from 'react';
import * as THREE from 'three';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, useGLTF, Html } from '@react-three/drei';
import earthGlbUrl from '../../assets/earth.glb?url';
import { latLngToVector3 } from './latLngToVector3';

export interface GlobeCluster {
  lat: number;
  lng: number;
  count: number;
}

interface Globe3DProps {
  clusters: GlobeCluster[];
  visible: boolean;
}

const GLOBE_RADIUS = 2;

// Mirrors the color/size steps used by the flat map's cluster circles
// (StationLayer.ts CLUSTERS_LAYER_ID paint expressions) so the globe
// shows "same counts, same colors".
function getClusterColor(count: number): string {
  if (count >= 100) return 'rgba(8, 48, 80, 0.94)';
  if (count >= 20) return 'rgba(12, 38, 64, 0.92)';
  return 'rgba(14, 28, 48, 0.90)';
}

function getClusterDiameter(count: number): number {
  if (count >= 100) return 30;
  if (count >= 20) return 24;
  return 20;
}

function formatCount(count: number): string {
  return count >= 1000 ? `${Math.round(count / 1000)}k` : String(count);
}

function EarthMesh() {
  const gltf = useGLTF(earthGlbUrl);
  const { scene } = gltf;

  useEffect(() => {
    // This GLB's diffuse (color) texture is only wired via the deprecated
    // KHR_materials_pbrSpecularGlossiness glTF extension, which modern
    // three.js's GLTFLoader no longer maps to the resulting material
    // automatically -- it falls back to a flat white MeshStandardMaterial
    // with no `.map`, even though the texture itself decoded fine.
    // The parser still has the texture available on request; pull it
    // directly and apply it to the mesh's material by hand.
    let cancelled = false;
    const parser = (gltf as any).parser;
    if (!parser) return;

    parser.getDependency('texture', 0).then((texture: THREE.Texture | undefined) => {
      if (cancelled || !texture) return;
      texture.colorSpace = THREE.SRGBColorSpace;
      texture.needsUpdate = true;

      scene.traverse((child) => {
        const mesh = child as THREE.Mesh;
        if ((mesh as any).isMesh && mesh.material) {
          const mat = mesh.material as THREE.MeshStandardMaterial;
          mat.map = texture;
          mat.color.set(0xffffff);
          mat.needsUpdate = true;
        }
      });
    });

    return () => {
      cancelled = true;
    };
  }, [gltf, scene]);

  return <primitive object={scene} scale={GLOBE_RADIUS} />;
}

function ClusterMarker({ cluster }: { cluster: GlobeCluster }) {
  const position = latLngToVector3(cluster.lat, cluster.lng, GLOBE_RADIUS * 1.015);
  const diameter = getClusterDiameter(cluster.count);

  return (
    <Html position={position} center distanceFactor={8} occlude sprite>
      <div
        style={{
          width: diameter,
          height: diameter,
          borderRadius: '50%',
          background: getClusterColor(cluster.count),
          border: '2px solid #00e5ff',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#ffffff',
          fontSize: 11,
          fontWeight: 600,
          fontFamily: 'inherit',
          pointerEvents: 'none',
          userSelect: 'none',
          whiteSpace: 'nowrap',
        }}
      >
        {formatCount(cluster.count)}
      </div>
    </Html>
  );
}

export const Globe3D: React.FC<Globe3DProps> = ({ clusters, visible }) => {
  return (
    <div
      className="globe-3d-viewport"
      style={{
        position: 'absolute',
        inset: 0,
        opacity: visible ? 1 : 0,
        pointerEvents: visible ? 'auto' : 'none',
        transition: 'opacity 400ms ease',
        zIndex: visible ? 2 : 1,
        background: '#05070d',
      }}
    >
      <Canvas camera={{ position: [0, 0, 6], fov: 45 }} dpr={[1, 2]}>
        <ambientLight intensity={1.3} />
        <directionalLight position={[5, 3, 5]} intensity={1.0} />
        <Suspense fallback={null}>
          <EarthMesh />
          {clusters.map((c, i) => (
            <ClusterMarker key={i} cluster={c} />
          ))}
        </Suspense>
        <OrbitControls
          enablePan={false}
          enableDamping
          dampingFactor={0.08}
          minDistance={2.6}
          maxDistance={9}
          rotateSpeed={0.5}
          zoomSpeed={0.6}
        />
      </Canvas>
    </div>
  );
};

useGLTF.preload(earthGlbUrl);
