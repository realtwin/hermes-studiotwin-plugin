import * as T from "three";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";
import { baseStage, OrbitControls } from "./env-stage.ts";
import { fetchModel, type ModelSource } from "./model-source.ts";
import type { PluginContext } from "@hermes/plugin-sdk";
export const channels = [
  "albedo",
  "normal",
  "roughness",
  "metalness",
  "heightmap",
] as const;
export type Channel = (typeof channels)[number];
export type MaterialMaps = Partial<Record<Channel, ModelSource>>;
export type Geometry = "Sphere" | "Cube" | "Rounded Plane";
export function createMaterialStage(host: HTMLElement) {
  const base = baseStage(host),
    { scene, camera, render } = base;
  camera.position.set(0, 0, 3.2);
  const controls = new OrbitControls(camera, base.renderer.domElement);
  controls.addEventListener("change", render);
  const rig = new T.Group();
  scene.add(rig);
  scene.add(new T.HemisphereLight(0xffffff, 0x888888, 2));
  const light = new T.DirectionalLight(0xffffff, 4);
  light.position.set(3, 3, 4);
  rig.add(light);
  const textures: Partial<Record<Channel, T.Texture>> = {};
  let disposed = false;
  const pbr = new T.MeshStandardMaterial({ roughness: 0.6 }),
    raw = new T.MeshBasicMaterial();
  const mesh = new T.Mesh<T.BufferGeometry, T.Material>(
    new T.SphereGeometry(0.9, 96, 64),
    pbr,
  );
  scene.add(mesh);
  const geometries = {
    Sphere: () => new T.SphereGeometry(0.9, 96, 64),
    Cube: () => new T.BoxGeometry(1.4, 1.4, 1.4, 48, 48, 48),
    "Rounded Plane": () => new RoundedBoxGeometry(1.8, 1.8, 0.08, 16, 0.1),
  };
  let geometry: Geometry = "Sphere";
  return {
    ...base,
    async load(rest: PluginContext["rest"], maps: MaterialMaps) {
      if (!maps.albedo) throw new Error("Albedo map required");
      // Await every decoder even when one fails, so disposal also owns late completions.
      const outcomes = await Promise.allSettled(
        channels
          .filter((c) => maps[c])
          .map(async (c) => {
            const f = await fetchModel(rest, maps[c]!);
            const url = URL.createObjectURL(new Blob([f.buffer]));
            try {
              const t = await new T.TextureLoader().loadAsync(url);
              if (disposed) {
                t.dispose();
                return;
              }
              t.colorSpace = c === "albedo" ? T.SRGBColorSpace : T.NoColorSpace;
              t.wrapS = t.wrapT = T.RepeatWrapping;
              textures[c] = t;
            } finally {
              URL.revokeObjectURL(url);
            }
          }),
      );
      if (outcomes.some((o) => o.status === "rejected"))
        throw new Error("Material map decode failed");
      if (disposed) return;
      pbr.map = textures.albedo ?? null;
      pbr.normalMap = textures.normal ?? null;
      pbr.roughnessMap = textures.roughness ?? null;
      pbr.metalnessMap = textures.metalness ?? null;
      pbr.metalness = textures.metalness ? 1 : 0;
      pbr.displacementMap = textures.heightmap ?? null;
      pbr.needsUpdate = true;
      render();
    },
    settings(
      channel: Channel | "Combined PBR",
      shape: Geometry,
      repeat: number,
      scale: number,
      rotation: number,
      swatch: boolean,
    ) {
      Object.values(textures).forEach((t) => t.repeat.set(repeat, repeat));
      pbr.displacementScale = scale;
      if (geometry !== shape) {
        mesh.geometry.dispose();
        mesh.geometry = geometries[shape]();
        geometry = shape;
      }
      if (channel === "Combined PBR") {
        mesh.material = pbr;
      } else {
        raw.map = textures[channel] ?? null;
        raw.needsUpdate = true;
        mesh.material = raw;
      }
      if (swatch) {
        raw.map =
          textures[channel === "Combined PBR" ? "albedo" : channel] ?? null;
        raw.needsUpdate = true;
        mesh.material = raw;
        mesh.rotation.set(0, 0, 0);
        mesh.geometry.dispose();
        mesh.geometry = new T.PlaneGeometry(1.8, 1.8);
        geometry = "Rounded Plane";
      } else if (mesh.geometry.type === "PlaneGeometry") {
        mesh.geometry.dispose();
        mesh.geometry = geometries[shape]();
        geometry = shape;
      }
      controls.enabled = !swatch;
      rig.rotation.y = T.MathUtils.degToRad(rotation);
      render();
    },
    dispose() {
      disposed = true;
      controls.dispose();
      Object.values(textures).forEach((t) => t.dispose());
      mesh.geometry.dispose();
      pbr.dispose();
      raw.dispose();
      base.dispose();
    },
  };
}
