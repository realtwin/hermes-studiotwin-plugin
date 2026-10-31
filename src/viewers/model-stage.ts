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
export type ShadingMode = 'textured' | 'wireframe' | 'clay' | 'normals'
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
  const renderer = new WebGLRenderer({ antialias: true, preserveDrawingBuffer: true })
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
