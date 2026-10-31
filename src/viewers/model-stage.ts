/** Three.js stage adapted from meshy/src/stage.ts (MIT, Nous Research). */
import {
  Scene,
  Color,
  WebGLRenderer,
  PerspectiveCamera,
  AmbientLight,
  DirectionalLight,
  GridHelper,
  Box3,
  Vector3,
  Vector2,
  Sphere,
  type Texture,
  MeshNormalMaterial,
  MeshStandardMaterial,
  MeshBasicMaterial,
  SphereGeometry,
  Mesh,
  type Material,
  type Object3D,
  SRGBColorSpace,
  ACESFilmicToneMapping
} from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { parseModel, type ParsedModel } from './model-parse.ts'
import { AnimationController, disposeModel, modelStats, parseMotion } from './model-data.ts'
import { environmentTexture } from './env-stage.ts'
export type ShadingMode = 'textured' | 'wireframe' | 'clay' | 'normals'
export interface MultiviewOptions {
  views?: 4 | 6
  shading?: ShadingMode
  tileSize?: number
  background?: 'transparent' | 'studio'
}
export interface MultiviewCapture {
  views: { name: string; label: string; dataUrl: string }[]
  sheetDataUrl: string
  width: number
  height: number
  shading: ShadingMode
  tileSize: number
}
export const canonicalViews = [
  { name: 'front', label: 'FRONT', yaw: 0, pitch: 12 },
  { name: 'right', label: 'RIGHT', yaw: 90, pitch: 12 },
  { name: 'back', label: 'BACK', yaw: 180, pitch: 12 },
  { name: 'left', label: 'LEFT', yaw: 270, pitch: 12 },
  { name: 'three_quarter', label: '3/4', yaw: 35, pitch: 22 },
  { name: 'top', label: 'TOP', yaw: 0, pitch: 85 }
] as const
/** Let Canvas resolve CSS Color 4/color-mix theme values before handing linear RGB to Three. */
function themeColor(value: string) {
  const swatch = document.createElement('canvas')
  swatch.width = swatch.height = 1
  const g = swatch.getContext('2d')
  if (!g) return new Color()
  g.fillStyle = value
  g.fillRect(0, 0, 1, 1)
  const [r, green, b] = g.getImageData(0, 0, 1, 1).data
  return new Color().setRGB(r / 255, green / 255, b / 255, SRGBColorSpace)
}
export function createModelStage(host: HTMLElement) {
  const renderer = new WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true })
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2))
  renderer.outputColorSpace = SRGBColorSpace
  renderer.toneMapping = ACESFilmicToneMapping
  host.appendChild(renderer.domElement)
  renderer.domElement.style.cssText = 'display:block;width:100%;height:100%'
  const css = getComputedStyle(host)
  const bg = css.getPropertyValue('--ui-bg-secondary').trim()
  const accent = css.getPropertyValue('--ui-text-secondary').trim()
  const scene = new Scene()
  scene.background = themeColor(bg)
  const studioBackground = scene.background
  let environment: Texture | null = null, environmentVersion = 0
  const clearEnvironment = () => {
    environmentVersion++
    scene.environment = null
    scene.background = studioBackground
    environment?.dispose()
    environment = null
    dirty = true
  }
  scene.add(new AmbientLight(0xffffff, 1.5))
  const light = new DirectionalLight(0xffffff, 3)
  light.position.set(3, 5, 4)
  scene.add(light)
  const grid = new GridHelper(4, 16, themeColor(accent), themeColor(accent))
  scene.add(grid)
  const camera = new PerspectiveCamera(40, 1, 0.01, 1000)
  camera.position.set(2, 2, 3)
  const controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true
  let parsed: ParsedModel | null = null,
    animation: AnimationController | null = null,
    disposed = false,
    frame = 0,
    dirty = true,
    last = 0
  let home = { position: camera.position.clone(), target: new Vector3() }
  const originals = new Map<Mesh, Material | Material[]>()
  const overrides = new Set<Material>()
  let mode: ShadingMode = 'textured'
  const resize = () => {
    const w = Math.max(1, host.clientWidth),
      h = Math.max(1, host.clientHeight)
    renderer.setSize(w, h, false)
    camera.aspect = w / h
    camera.updateProjectionMatrix()
    dirty = true
  }
  const observer = new ResizeObserver(resize)
  observer.observe(host)
  resize()
  const invalidate = () => {
    dirty = true
  }
  controls.addEventListener('change', invalidate)
  const tick = (now: number) => {
    if (disposed) return
    frame = requestAnimationFrame(tick)
    const delta = Math.min((now - last) / 1000, 0.1)
    last = now
    if (document.hidden) return
    const moved = controls.update()
    const playing = animation?.state().playing
    animation?.update(delta)
    if (dirty || moved || playing) {
      renderer.render(scene, camera)
      dirty = false
    }
  }
  frame = requestAnimationFrame(tick)
  const shading = (next: ShadingMode) => {
    mode = next
    for (const [mesh, mat] of originals) mesh.material = mat
    overrides.forEach((m) => m.dispose())
    overrides.clear()
    for (const mesh of originals.keys()) {
      if (next === 'textured') continue
      const mat =
        next === 'normals'
          ? new MeshNormalMaterial()
          : new MeshStandardMaterial({ color: themeColor(accent), roughness: 0.8, wireframe: next === 'wireframe' })
      overrides.add(mat)
      mesh.material = mat
    }
    dirty = true
  }
  return {
    async load(bytes: ArrayBuffer, name: string) {
      const p = name.toLowerCase().endsWith('.json')
        ? parseMotion(JSON.parse(new TextDecoder().decode(bytes)))
        : await parseModel(bytes, { name })
      if (disposed) {
        disposeModel(p.root)
        throw new Error('Viewer closed')
      }
      if (parsed) {
        shading('textured')
        animation?.dispose()
        disposeModel(parsed.root)
        scene.remove(parsed.root)
      }
      originals.clear()
      parsed = p
      scene.add(p.root)
      const stats = modelStats(p)
      if (name.toLowerCase().endsWith('.json')) {
        // The supported JSON schema has joint positions but no hierarchy/skin. Mark joints honestly.
        const bones: Object3D[] = []
        p.root.traverse((n) => {
          if ((n as Object3D & { isBone?: boolean }).isBone) bones.push(n)
        })
        for (const bone of bones)
          bone.add(new Mesh(new SphereGeometry(0.025, 8, 6), new MeshBasicMaterial({ color: themeColor(accent) })))
      }
      p.root.traverse((n) => {
        const m = n as Mesh
        if (m.isMesh) {
          if (!m.geometry.getAttribute('normal')) m.geometry.computeVertexNormals()
          originals.set(m, m.material)
        }
      })
      animation = new AnimationController(p.root, p.clips)
      if (p.clips.length) animation.select(0)
      const box = new Box3().setFromObject(p.root),
        size = box.getSize(new Vector3()),
        center = box.getCenter(new Vector3())
      if (name.toLowerCase().endsWith('.json')) {
        // Joint-only clips have no surface bounds; include their sampled travel, not just frame zero.
        for (const clip of p.clips)
          for (const track of clip.tracks)
            for (let i = 0; i < track.values.length; i += 3)
              box.expandByPoint(new Vector3(track.values[i], track.values[i + 1], track.values[i + 2]))
        box.expandByScalar(0.03)
        box.getSize(size)
        box.getCenter(center)
      }
      if (!box.isEmpty()) {
        const radius = Math.max(size.x, size.y, size.z, 0.1),
          target = center
        camera.near = radius / 100
        camera.far = radius * 100
        camera.updateProjectionMatrix()
        camera.position.copy(target).add(new Vector3(0.75, 0.45, 1).normalize().multiplyScalar(radius * 2.5))
        controls.target.copy(target)
        grid.scale.setScalar(radius / 2)
        grid.position.y = box.min.y
      }
      controls.update()
      home = { position: camera.position.clone(), target: controls.target.clone() }
      shading(mode)
      dirty = true
      return stats
    },
    clearEnvironment,
    async setEnvironment(buffer: ArrayBuffer | null, name = 'environment.hdr', showBackground = false) {
      if (disposed) throw new Error('Viewer closed')
      if (buffer === null) { clearEnvironment(); return }
      const version = ++environmentVersion
      const texture = await environmentTexture(buffer, name)
      if (disposed || version !== environmentVersion) { texture.dispose(); return }
      const previous = environment
      environment = texture
      scene.environment = texture
      scene.background = showBackground ? texture : studioBackground
      previous?.dispose()
      dirty = true
    },
    async captureMultiview(opts: MultiviewOptions = {}): Promise<MultiviewCapture> {
      if (disposed || !parsed) throw new Error('Load a model before capturing multiview')
      const count = opts.views ?? 4, pass = opts.shading ?? mode
      if (count !== 4 && count !== 6) throw new Error('Expected 4 or 6 views')
      if (!['textured', 'clay', 'normals', 'wireframe'].includes(pass)) throw new Error('Invalid shading mode')
      if (opts.background !== undefined && !['transparent', 'studio'].includes(opts.background)) throw new Error('Invalid background')
      const size = Math.round(Math.min(1024, Math.max(128, Number.isFinite(opts.tileSize) ? opts.tileSize! : 384)))
      const cols = count === 6 ? 3 : 2
      const sheet = document.createElement('canvas')
      sheet.width = cols * size; sheet.height = 2 * size
      const g = sheet.getContext('2d')
      if (!g) throw new Error('Canvas composition unavailable')
      const saved = {
        position: camera.position.clone(), quaternion: camera.quaternion.clone(), target: controls.target.clone(),
        aspect: camera.aspect, near: camera.near, far: camera.far,
        spin: controls.autoRotate, grid: grid.visible, background: scene.background,
        pixelRatio: renderer.getPixelRatio(), size: renderer.getSize(new Vector2()), alpha: renderer.getClearAlpha()
      }
      const materials = new Map<Mesh, Material | Material[]>(), temporary: Material[] = []
      // No await while changing the live stage: animation, controls and ResizeObserver cannot
      // advance between tiles. Preserve the current posed model, including skinned meshes.
      try {
        controls.autoRotate = false
        grid.visible = false
        scene.background = opts.background === 'transparent' ? null : studioBackground
        renderer.setClearAlpha(opts.background === 'transparent' ? 0 : 1)
        renderer.setPixelRatio(1); renderer.setSize(size, size, false)
        const sphere = new Box3().setFromObject(parsed.root).getBoundingSphere(new Sphere())
        if (!Number.isFinite(sphere.radius)) throw new Error('Model has no finite bounds')
        const radius = Math.max(sphere.radius, 0.001)
        camera.aspect = 1; camera.near = radius / 100; camera.far = radius * 100
        camera.updateProjectionMatrix()
        const distance = radius / Math.sin(camera.fov * Math.PI / 360) * 1.08
        for (const [mesh, original] of originals) {
          materials.set(mesh, mesh.material)
          if (pass === 'textured') mesh.material = original
          else {
            const material = pass === 'normals' ? new MeshNormalMaterial()
              : pass === 'wireframe' ? new MeshBasicMaterial({ color: themeColor(accent), wireframe: true })
              : new MeshStandardMaterial({ color: themeColor(accent), roughness: 0.8 })
            temporary.push(material); mesh.material = material
          }
        }
        const views: MultiviewCapture['views'] = []
        canonicalViews.slice(0, count).forEach((view, i) => {
          const yaw = view.yaw * Math.PI / 180, pitch = view.pitch * Math.PI / 180
          camera.position.copy(sphere.center).add(new Vector3(
            Math.sin(yaw) * Math.cos(pitch), Math.sin(pitch), Math.cos(yaw) * Math.cos(pitch)
          ).multiplyScalar(distance))
          camera.lookAt(sphere.center)
          renderer.render(scene, camera)
          const tile = document.createElement('canvas'); tile.width = tile.height = size
          const ctx = tile.getContext('2d')!
          ctx.drawImage(renderer.domElement, 0, 0)
          const fontSize = Math.max(12, Math.round(size * 0.045))
          ctx.font = `600 ${fontSize}px sans-serif`; ctx.textBaseline = 'top'
          ctx.fillStyle = bg; ctx.fillRect(6, 6, ctx.measureText(view.label).width + 12, fontSize + 10)
          ctx.fillStyle = accent; ctx.fillText(view.label, 12, 11)
          views.push({ name: view.name, label: view.label, dataUrl: tile.toDataURL('image/png') })
          g.drawImage(tile, (i % cols) * size, Math.floor(i / cols) * size)
        })
        return { views, sheetDataUrl: sheet.toDataURL('image/png'), width: sheet.width, height: sheet.height, shading: pass, tileSize: size }
      } finally {
        materials.forEach((material, mesh) => { mesh.material = material })
        temporary.forEach((material) => material.dispose())
        camera.position.copy(saved.position); camera.quaternion.copy(saved.quaternion)
        controls.target.copy(saved.target); controls.autoRotate = saved.spin
        camera.aspect = saved.aspect; camera.near = saved.near; camera.far = saved.far; camera.updateProjectionMatrix()
        grid.visible = saved.grid; scene.background = saved.background
        renderer.setClearAlpha(saved.alpha); renderer.setPixelRatio(saved.pixelRatio)
        renderer.setSize(saved.size.x, saved.size.y, false)
        dirty = true
        renderer.render(scene, camera)
      }
    },
    animation: () => animation,
    setShading: shading,
    setAutoRotate(on: boolean) {
      controls.autoRotate = on
      dirty = true
    },
    setGrid(on: boolean) {
      grid.visible = on
      dirty = true
    },
    reset() {
      camera.position.copy(home.position)
      controls.target.copy(home.target)
      controls.update()
      dirty = true
    },
    invalidate,
    snapshot() {
      renderer.render(scene, camera)
      return renderer.domElement.toDataURL('image/png')
    },
    dispose() {
      if (disposed) return
      disposed = true
      clearEnvironment()
      cancelAnimationFrame(frame)
      observer.disconnect()
      controls.removeEventListener('change', invalidate)
      controls.dispose()
      shading('textured')
      animation?.dispose()
      if (parsed) disposeModel(parsed.root)
      grid.geometry.dispose()
      ;(Array.isArray(grid.material) ? grid.material : [grid.material]).forEach((m) => m.dispose())
      renderer.dispose()
      renderer.forceContextLoss()
      renderer.domElement.remove()
    }
  }
}
export type ModelStage = ReturnType<typeof createModelStage>
