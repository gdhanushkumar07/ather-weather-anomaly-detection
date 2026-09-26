import React, { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import type maplibregl from 'maplibre-gl';

const SUN_URL = new URL('../../assets/sun.glb', import.meta.url).href;

// Scene units are Earth radii (the globe has radius 1 in MapLibre's globe
// camera space), so distances and sizes below are in true proportion.
const EARTH_RADIUS_KM = 6371;
const SUN_DISTANCE_KM = 50_000_000;
const SUN_RADIUS_KM = 696_350;
const SUN_DISTANCE = SUN_DISTANCE_KM / EARTH_RADIUS_KM; // ~7,850 Earth radii
// 1 = true size for that distance (~1.6 deg across, ~35 px on screen).
const SUN_SIZE_BOOST = 1;
const SUN_RADIUS = (SUN_RADIUS_KM / EARTH_RADIUS_KM) * SUN_SIZE_BOOST;

// sun.glb is a sphere of radius 10 (its outer shell is 1.01x that).
const SUN_MODEL_RADIUS = 10;

const FOV_DEG = 36.87;

// The Sun sits at a fixed spot in space, so it moves across the screen as the
// globe is rotated and leaves the view when you look away from it. Its
// direction is chosen so that it is visible up-left of the Earth in the
// default view (center [15, 20]); it is defined in that view's screen space
// and converted to a world direction once.
const DEFAULT_CENTER = { lng: 15, lat: 20 };
const SUN_AZIMUTH_DEG = -27; // negative = toward screen-left
const SUN_ELEVATION_DEG = 6; // positive = toward screen-top

// Beyond this zoom the flat map fully covers the canvas; skip rendering.
const MAX_ZOOM = 6;

const rad = (d: number) => (d * Math.PI) / 180;

/** World-space (globe camera space: +Y north, lng 0 on +Z) unit vector from
 * Earth's centre toward the Sun. */
function sunWorldDirection(): THREE.Vector3 {
  const az = rad(SUN_AZIMUTH_DEG);
  const el = rad(SUN_ELEVATION_DEG);
  // Direction in the default camera's view space (camera looks down -Z).
  const v = new THREE.Vector3(Math.sin(az) * Math.cos(el), Math.sin(el), -Math.cos(az) * Math.cos(el));
  // View space -> world: Ry(lng) * Rx(-lat).
  v.applyAxisAngle(new THREE.Vector3(1, 0, 0), -rad(DEFAULT_CENTER.lat));
  v.applyAxisAngle(new THREE.Vector3(0, 1, 0), rad(DEFAULT_CENTER.lng));
  return v.normalize();
}

interface SunLayerProps {
  map: maplibregl.Map | null;
}

/**
 * The Sun, rendered with Three.js on a transparent canvas between the star
 * field and the MapLibre globe. It is fixed in space, not on screen: its
 * camera is rebuilt every frame from MapLibre's own globe camera, so the Sun
 * moves as the Earth is rotated, and the Earth hides it when it is behind
 * the planet.
 */
export const SunLayer: React.FC<SunLayerProps> = ({ map }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !map) return;

    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    renderer.setClearColor(0x000000, 0);
    renderer.toneMapping = THREE.NoToneMapping;
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(FOV_DEG, 1, 1000, 20_000);
    camera.matrixAutoUpdate = false;

    const sun = new THREE.Group();
    sun.visible = false;
    scene.add(sun);
    const modelScale = SUN_RADIUS / SUN_MODEL_RADIUS;
    sun.scale.setScalar(modelScale);
    sun.position.copy(sunWorldDirection()).multiplyScalar(SUN_DISTANCE);

    let disposed = false;
    new GLTFLoader().load(SUN_URL, (gltf) => {
      if (disposed) return;
      gltf.scene.traverse((o) => {
        const mesh = o as THREE.Mesh;
        if (!mesh.isMesh) return;
        const old = mesh.material as THREE.MeshStandardMaterial;
        const tex = old.emissiveMap || old.map;
        if (old.transparent) {
          // Outer shell: additive so it brightens the disc edge without
          // darkening the sky behind it.
          mesh.material = new THREE.MeshBasicMaterial({
            map: tex, transparent: true, opacity: 0.6, blending: THREE.AdditiveBlending, depthWrite: false
          });
        } else {
          // Sun is self-lit: show its texture unshaded.
          mesh.material = new THREE.MeshBasicMaterial({ map: tex });
        }
        old.dispose();
      });
      sun.add(gltf.scene);
    });

    const view = new THREE.Matrix4();
    const tmp = new THREE.Matrix4();
    let raf = 0;
    let w = 0;
    let h = 0;

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      w = Math.max(1, rect.width);
      h = Math.max(1, rect.height);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };

    const frame = () => {
      raf = requestAnimationFrame(frame);
      const tr = map.transform as any;
      if (map.getZoom() > MAX_ZOOM || !tr?.worldSize || !tr?.cameraToCenterDistance) {
        canvas.style.visibility = 'hidden';
        return;
      }
      canvas.style.visibility = 'visible';

      const center = map.getCenter();
      const globeRadiusPx = tr.worldSize / (2 * Math.PI) / Math.cos(rad(center.lat));
      const camDist = tr.cameraToCenterDistance / globeRadiusPx;

      // Mirrors MapLibre's globe view matrix (vertical_perspective_transform):
      // T(0,0,-D) * Rx(-pitch) * Rz(bearing) * T(0,0,-1) * Rx(lat) * Ry(-lng)
      view.makeTranslation(0, 0, -camDist);
      view.multiply(tmp.makeRotationX(-tr.pitchInRadians));
      view.multiply(tmp.makeRotationZ(tr.bearingInRadians));
      view.multiply(tmp.makeTranslation(0, 0, -1));
      view.multiply(tmp.makeRotationX(rad(center.lat)));
      view.multiply(tmp.makeRotationY(-rad(center.lng)));
      camera.matrixWorldInverse.copy(view);
      camera.matrixWorld.copy(view).invert();

      sun.rotation.y = performance.now() * 0.00005; // slow spin in place
      sun.visible = sun.children.length > 0;
      renderer.render(scene, camera);
    };

    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    resize();
    frame();

    return () => {
      disposed = true;
      cancelAnimationFrame(raf);
      ro.disconnect();
      scene.traverse((o) => {
        const m = o as THREE.Mesh;
        if (m.isMesh) {
          m.geometry.dispose();
          (m.material as THREE.Material).dispose();
        }
      });
      renderer.dispose();
    };
  }, [map]);

  return <canvas ref={canvasRef} className="sun-layer" aria-hidden="true" />;
};
