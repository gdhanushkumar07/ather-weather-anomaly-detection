import React, { useMemo } from 'react';
import * as THREE from 'three';

/**
 * Single tunable scale constant for every AWS model instance.
 * Change this, not individual mesh dimensions scattered across files.
 */
export const AWS_MODEL_SCALE = 1.0;

export const AWS_STATUS_COLORS: Record<string, string> = {
  NORMAL: '#10b981',
  WARNING: '#f59e0b',
  ANOMALY: '#ef4444',
  OFFLINE: '#94a3b8',
};

export function awsStatusColor(status?: string): string {
  return AWS_STATUS_COLORS[status || 'NORMAL'] || AWS_STATUS_COLORS.NORMAL;
}

interface AWSModelProps {
  status?: string;
  selected?: boolean;
  scale?: number;
}

/**
 * Procedural low-poly Automatic Weather Station.
 *
 * No AWS GLB/GLTF asset exists anywhere in this repository (verified by a
 * full-repo search before building this) -- only earth.glb, used for the
 * Earth model. Rather than silently downloading an unlicensed third-party
 * model, this composes the AWS from primitive Three.js geometries: a
 * mounting pole, an electronics enclosure, a tilted solar panel, a stacked
 * radiation-shield/sensor housing, an anemometer arm, and a cable run.
 *
 * Materials are created once at module scope (shared across every instance,
 * per the project's "reuse materials" performance requirement) rather than
 * per-render. Pivot/origin is at the base of the pole (y=0), so placing this
 * group at a projected station position plants it upright and correctly.
 */
const MATERIALS = {
  pole: new THREE.MeshStandardMaterial({ color: '#c7ccd1', metalness: 0.6, roughness: 0.35 }),
  enclosure: new THREE.MeshStandardMaterial({ color: '#e8eaed', metalness: 0.15, roughness: 0.55 }),
  panel: new THREE.MeshStandardMaterial({ color: '#151b2e', metalness: 0.4, roughness: 0.25 }),
  sensor: new THREE.MeshStandardMaterial({ color: '#f4f4f5', metalness: 0.1, roughness: 0.6 }),
  cable: new THREE.MeshStandardMaterial({ color: '#22262e', metalness: 0.2, roughness: 0.7 }),
};

export const AWSModel: React.FC<AWSModelProps> = ({ status = 'NORMAL', selected = false, scale = AWS_MODEL_SCALE }) => {
  const statusColor = useMemo(() => awsStatusColor(status), [status]);
  const sensorDiscYs = useMemo(() => [0, 0.05, 0.1, 0.15], []);

  return (
    <group scale={scale}>
      {/* Status/selection ring at the base -- communicates NORMAL/WARNING/ANOMALY/selected */}
      <mesh position={[0, 0.02, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[0.55, 0.7, 32]} />
        <meshBasicMaterial
          color={selected ? '#00e5ff' : statusColor}
          transparent
          opacity={selected ? 0.9 : 0.55}
          side={THREE.DoubleSide}
        />
      </mesh>

      {/* Base plate */}
      <mesh position={[0, 0.03, 0]} material={MATERIALS.pole}>
        <cylinderGeometry args={[0.18, 0.22, 0.06, 16]} />
      </mesh>

      {/* Vertical mounting pole */}
      <mesh position={[0, 1.1, 0]} material={MATERIALS.pole}>
        <cylinderGeometry args={[0.045, 0.05, 2.1, 12]} />
      </mesh>

      {/* Electronics enclosure */}
      <mesh position={[0.1, 1.0, 0]} material={MATERIALS.enclosure}>
        <boxGeometry args={[0.16, 0.24, 0.1]} />
      </mesh>

      {/* Solar panel, tilted toward the sky */}
      <group position={[0, 1.85, 0.02]} rotation={[-0.5, 0, 0]}>
        <mesh material={MATERIALS.panel}>
          <boxGeometry args={[0.5, 0.02, 0.35]} />
        </mesh>
      </group>

      {/* Radiation shield / temperature-humidity sensor housing (stacked discs) */}
      <group position={[0, 1.55, 0.14]}>
        {sensorDiscYs.map((y, i) => (
          <mesh key={i} position={[0, y, 0]} material={MATERIALS.sensor}>
            <cylinderGeometry args={[0.09, 0.09, 0.02, 16]} />
          </mesh>
        ))}
      </group>

      {/* Anemometer arm + cup */}
      <mesh position={[0, 2.2, 0]} material={MATERIALS.pole}>
        <cylinderGeometry args={[0.015, 0.015, 0.3, 8]} />
      </mesh>
      <mesh position={[0, 2.32, 0]} material={MATERIALS.sensor}>
        <sphereGeometry args={[0.05, 8, 8]} />
      </mesh>

      {/* Cable run along the pole */}
      <mesh position={[-0.05, 0.9, 0.04]} material={MATERIALS.cable}>
        <cylinderGeometry args={[0.008, 0.008, 1.6, 6]} />
      </mesh>
    </group>
  );
};
