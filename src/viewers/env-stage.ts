import * as T from "three";
import { RGBELoader } from "three/examples/jsm/loaders/RGBELoader.js";
import { EXRLoader } from "three/examples/jsm/loaders/EXRLoader.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
export interface Sticker {
  assetId: string;
  yawDeg: number;
  pitchDeg: number;
  rollDeg: number;
  hFovDeg: number;
  sourceAspect?: number;
}
export function parseStickers(value: unknown): Sticker[] {
  if (!Array.isArray(value)) throw new Error("Expected stickers array");
  return value.map((s) => {
    if (
      !s ||
      typeof s.assetId !== "string" ||
      !["yawDeg", "pitchDeg", "rollDeg", "hFovDeg"].every(
        (k) => typeof s[k] === "number" && Number.isFinite(s[k]),
      ) ||
      s.hFovDeg <= 0 ||
      s.hFovDeg >= 180 ||
      Math.abs(s.pitchDeg) > 90 ||
      (s.sourceAspect !== undefined &&
        !(Number.isFinite(s.sourceAspect) && s.sourceAspect > 0))
    )
      throw new Error("Invalid sticker placement");
    return s as Sticker;
  });
}
export function direction(yaw: number, pitch: number) {
  const y = T.MathUtils.degToRad(yaw),
    p = T.MathUtils.degToRad(pitch);
  return new T.Vector3(
    Math.sin(y) * Math.cos(p),
    Math.sin(p),
    -Math.cos(y) * Math.cos(p),
  );
}
/** Project a rolled tangent-plane FOV boundary back onto the unit sphere. */
export function stickerBoundary(s: Sticker) {
  const forward = direction(s.yawDeg, s.pitchDeg),
    right = new T.Vector3()
      .crossVectors(forward, new T.Vector3(0, 1, 0))
      .normalize();
  if (right.lengthSq() === 0) right.set(1, 0, 0);
  const up = new T.Vector3().crossVectors(right, forward).normalize(),
    roll = T.MathUtils.degToRad(s.rollDeg);
  const r = right
      .clone()
      .multiplyScalar(Math.cos(roll))
      .addScaledVector(up, Math.sin(roll)),
    u = up
      .clone()
      .multiplyScalar(Math.cos(roll))
      .addScaledVector(right, -Math.sin(roll));
  const w = Math.tan(T.MathUtils.degToRad(s.hFovDeg / 2)),
    h = w / (s.sourceAspect ?? 1);
  const corners = [
    [-w, -h],
    [w, -h],
    [w, h],
    [-w, h],
    [-w, -h],
  ];
  const points: T.Vector3[] = [];
  for (let i = 0; i < 4; i++)
    for (let j = 0; j < 16; j++) {
      const t = j / 16;
      points.push(
        forward
          .clone()
          .addScaledVector(r, corners[i][0] * (1 - t) + corners[i + 1][0] * t)
          .addScaledVector(u, corners[i][1] * (1 - t) + corners[i + 1][1] * t)
          .normalize(),
      );
    }
  points.push(points[0].clone());
  return points;
}
export async function environmentTexture(
  buffer: ArrayBuffer,
  name: string,
): Promise<T.Texture> {
  const ext = name.split(".").pop()?.toLowerCase();
  if (ext === "hdr" || ext === "exr") {
    const p =
      ext === "hdr"
        ? new RGBELoader().parse(buffer)
        : new EXRLoader().parse(buffer);
    const t = new T.DataTexture(
      p.data,
      p.width,
      p.height,
      T.RGBAFormat,
      p.type,
    );
    t.colorSpace = T.LinearSRGBColorSpace;
    t.minFilter = t.magFilter = T.LinearFilter;
    t.generateMipmaps = false;
    t.flipY = ext === "hdr";
    t.needsUpdate = true;
    t.mapping = T.EquirectangularReflectionMapping;
    return t;
  }
  if (!["png", "jpg", "jpeg", "webp"].includes(ext || ""))
    throw new Error("Unsupported panorama");
  const url = URL.createObjectURL(new Blob([buffer]));
  try {
    const t = await new T.TextureLoader().loadAsync(url);
    t.colorSpace = T.SRGBColorSpace;
    t.mapping = T.EquirectangularReflectionMapping;
    return t;
  } finally {
    URL.revokeObjectURL(url);
  }
}
export function themeColor(host: HTMLElement, token: string) {
  const c = document.createElement("canvas");
  c.width = c.height = 1;
  const g = c.getContext("2d")!;
  g.fillStyle = getComputedStyle(host).getPropertyValue(token).trim();
  g.fillRect(0, 0, 1, 1);
  const [r, b, v] = g.getImageData(0, 0, 1, 1).data;
  return new T.Color().setRGB(r / 255, b / 255, v / 255, T.SRGBColorSpace);
}
export function baseStage(host: HTMLElement) {
  const renderer = new T.WebGLRenderer({
    antialias: true,
    preserveDrawingBuffer: true,
  });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  renderer.toneMapping = T.ACESFilmicToneMapping;
  host.append(renderer.domElement);
  renderer.domElement.style.cssText =
    "display:block;width:100%;height:100%;touch-action:none";
  const scene = new T.Scene();
  scene.background = themeColor(host, "--ui-bg-secondary");
  const camera = new T.PerspectiveCamera(65, 1, 0.01, 100);
  camera.position.set(0, 0, 3);
  let disposed = false;
  const render = () => {
    if (!disposed) renderer.render(scene, camera);
  };
  const resize = () => {
    renderer.setSize(
      Math.max(1, host.clientWidth),
      Math.max(1, host.clientHeight),
      false,
    );
    camera.aspect =
      Math.max(1, host.clientWidth) / Math.max(1, host.clientHeight);
    camera.updateProjectionMatrix();
    render();
  };
  const observer = new ResizeObserver(resize);
  observer.observe(host);
  resize();
  return {
    renderer,
    scene,
    camera,
    render,
    snapshot: () => renderer.domElement.toDataURL(),
    dispose() {
      disposed = true;
      observer.disconnect();
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
    },
  };
}
export function createEnvStage(
  host: HTMLElement,
  stickers: Sticker[],
  select: (id: string) => void,
) {
  const base = baseStage(host),
    { scene, camera, renderer, render } = base;
  camera.position.set(0, 0, 0.001);
  let disposed = false;
  let texture: T.Texture | null = null,
    yaw = 0,
    pitch = 0,
    flat = false,
    preview = false,
    overlay = true;
  const sphere = new T.Mesh(
    new T.SphereGeometry(0.4, 48, 24),
    new T.MeshStandardMaterial({ metalness: 1, roughness: 0.08 }),
  );
  sphere.position.set(-0.5, 0, -2);
  const matte = new T.Mesh(
    new T.SphereGeometry(0.4, 48, 24),
    new T.MeshStandardMaterial({ roughness: 1 }),
  );
  matte.position.set(0.5, 0, -2);
  const plane = new T.Mesh(
    new T.PlaneGeometry(4, 2),
    new T.MeshBasicMaterial(),
  );
  plane.position.z = -2;
  scene.add(sphere, matte, plane);
  const group = new T.Group();
  scene.add(group);
  const accent = themeColor(host, "--ui-accent");
  stickers.forEach((s) => {
    const line = new T.Line(
      new T.BufferGeometry().setFromPoints(
        stickerBoundary(s).map((p) => p.multiplyScalar(4)),
      ),
      new T.LineBasicMaterial({ color: accent }),
    );
    group.add(line);
    const pin = new T.Mesh(
      new T.SphereGeometry(0.045, 12, 8),
      new T.MeshBasicMaterial({ color: accent }),
    );
    pin.position.copy(direction(s.yawDeg, s.pitchDeg).multiplyScalar(3.9));
    pin.userData.assetId = s.assetId;
    group.add(pin);
  });
  const update = () => {
    camera.lookAt(flat ? direction(0, 0) : direction(yaw, pitch));
    sphere.visible = matte.visible = preview && !flat;
    plane.visible = flat;
    group.visible = overlay && !flat;
    scene.background = flat ? themeColor(host, "--ui-bg-secondary") : texture;
    render();
  };
  let drag: { x: number; y: number } | null = null;
  const down = (e: PointerEvent) => {
    drag = { x: e.clientX, y: e.clientY };
    renderer.domElement.setPointerCapture(e.pointerId);
  };
  const move = (e: PointerEvent) => {
    if (drag) {
      yaw -= (e.clientX - drag.x) * 0.2;
      pitch = T.MathUtils.clamp(pitch + (e.clientY - drag.y) * 0.2, -89, 89);
      drag = { x: e.clientX, y: e.clientY };
      update();
    }
  };
  const up = (e: PointerEvent) => {
    drag = null;
    const rect = renderer.domElement.getBoundingClientRect(),
      ray = new T.Raycaster();
    ray.setFromCamera(
      new T.Vector2(
        ((e.clientX - rect.left) / rect.width) * 2 - 1,
        (-(e.clientY - rect.top) / rect.height) * 2 + 1,
      ),
      camera,
    );
    const hit = group.visible
      ? ray
          .intersectObjects(group.children)
          .find((h) => h.object.userData.assetId)
      : null;
    if (hit) select(hit.object.userData.assetId);
  };
  const wheel = (e: WheelEvent) => {
    e.preventDefault();
    camera.fov = T.MathUtils.clamp(camera.fov + e.deltaY * 0.03, 25, 100);
    camera.updateProjectionMatrix();
    update();
  };
  const el = renderer.domElement;
  let spinFrame = 0, spinning = false, previousTime = 0;
  const rotate = (now: number) => {
    if (disposed || !spinning) return;
    if (!drag && previousTime) yaw += Math.min(now - previousTime, 100) * 0.006;
    previousTime = now;
    update();
    spinFrame = requestAnimationFrame(rotate);
  };
  el.addEventListener("pointerdown", down);
  el.addEventListener("pointermove", move);
  el.addEventListener("pointerup", up);
  el.addEventListener("wheel", wheel, { passive: false });
  return {
    ...base,
    autoRotate(enabled: boolean) {
      cancelAnimationFrame(spinFrame);
      spinning = enabled;
      previousTime = 0;
      if (enabled && !disposed) spinFrame = requestAnimationFrame(rotate);
    },
    reset() {
      yaw = pitch = 0;
      camera.fov = 65;
      camera.updateProjectionMatrix();
      update();
    },
    select(assetId: string) {
      group.children.forEach((o) => {
        if (o instanceof T.Mesh)
          o.scale.setScalar(o.userData.assetId === assetId ? 1.8 : 1);
      });
      render();
    },
    async load(buffer: ArrayBuffer, name: string) {
      const t = await environmentTexture(buffer, name);
      if (disposed) {
        t.dispose();
        return;
      }
      texture = t;
      scene.environment = t;
      plane.material.map = t;
      plane.material.needsUpdate = true;
      update();
    },
    settings(ev: number, isFlat: boolean, lighting: boolean, show: boolean) {
      renderer.toneMappingExposure = 2 ** ev;
      flat = isFlat;
      preview = lighting;
      overlay = show;
      update();
    },
    dispose() {
      disposed = true;
      texture?.dispose();
      spinning = false;
      cancelAnimationFrame(spinFrame);
      scene.traverse((o) => {
        const m = o as T.Mesh;
        if (m.geometry) m.geometry.dispose();
        const a = m.material;
        if (a) (Array.isArray(a) ? a : [a]).forEach((v) => v.dispose());
      });
      el.removeEventListener("pointerdown", down);
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("wheel", wheel);
      base.dispose();
    },
  };
}
export { OrbitControls };
