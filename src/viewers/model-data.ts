/** Stage data adapted from Meshy (MIT, Nous Research). No renderer required. */
import {
  AnimationMixer,
  AnimationClip,
  LoopOnce,
  LoopRepeat,
  Bone,
  Group,
  VectorKeyframeTrack,
  SkeletonHelper,
  type Object3D,
  type Mesh,
  type SkinnedMesh,
  type Material,
  type AnimationAction
} from 'three'
import type { ParsedModel } from './model-parse.ts'
export function modelStats(p: ParsedModel) {
  let vertices = 0,
    triangles = 0,
    meshes = 0,
    bones = 0,
    skinnedMeshes = 0
  p.root.traverse((n) => {
    if ((n as Bone).isBone) bones++
    const m = n as Mesh
    if (!m.isMesh) return
    meshes++
    if ((m as SkinnedMesh).isSkinnedMesh) skinnedMeshes++
    vertices += m.geometry.getAttribute('position')?.count ?? 0
    triangles += (m.geometry.index?.count ?? m.geometry.getAttribute('position')?.count ?? 0) / 3
  })
  return { vertices, triangles, meshes, bones, skinnedMeshes, clips: p.clips.map((c, i) => c.name || `Clip ${i + 1}`) }
}
export type ModelStats = ReturnType<typeof modelStats>
export function disposeModel(root: Object3D) {
  const resources = new Set<{ dispose: () => void }>()
  root.traverse((n) => {
    const m = n as Mesh
    if (m.geometry) resources.add(m.geometry)
    const mats: Material[] = Array.isArray(m.material) ? m.material : m.material ? [m.material] : []
    for (const mat of mats) {
      resources.add(mat)
      for (const value of Object.values(mat))
        if (value?.isTexture) {
          resources.add(value)
          // ImageBitmaps made by GLTFLoader do not close themselves on Texture.dispose().
          if (value.source?.data?.close) resources.add({ dispose: () => value.source.data.close() })
        }
    }
    const skeleton = (n as Mesh & { skeleton?: { dispose: () => void } }).skeleton
    if (skeleton) resources.add(skeleton)
  })
  resources.forEach((r) => r.dispose())
}
export class AnimationController {
  readonly mixer: AnimationMixer
  private action: AnimationAction | null = null
  private playing = false
  private loop = true
  private speed = 1
  private time = 0
  private index = -1
  constructor(
    private root: Object3D,
    readonly clips: AnimationClip[]
  ) {
    this.mixer = new AnimationMixer(root)
  }
  select(clip: number | string) {
    const i = typeof clip === 'number' ? clip : this.clips.findIndex((c) => c.name === clip)
    if (!Number.isInteger(i) || !this.clips[i]) return -1
    this.mixer.stopAllAction()
    this.index = i
    this.action = this.mixer.clipAction(this.clips[i])
    this.action.reset().play()
    this.action.setLoop(this.loop ? LoopRepeat : LoopOnce, Infinity)
    this.action.clampWhenFinished = true
    this.time = 0
    this.playing = true
    this.seek(0)
    return i
  }
  setPlaying(on: boolean) {
    if (on && this.time >= this.duration()) this.time = 0
    this.playing = on
  }
  setSpeed(speed: number) {
    if (![0.25, 0.5, 1, 2].includes(speed)) throw new Error('Unsupported playback speed')
    this.speed = speed
  }
  setLoop(on: boolean) {
    this.loop = on
    this.action?.setLoop(on ? LoopRepeat : LoopOnce, Infinity)
  }
  private duration() {
    return this.clips[this.index]?.duration ?? 0
  }
  seek(seconds: number) {
    if (!this.action || !Number.isFinite(seconds)) return
    this.time = Math.max(0, Math.min(this.duration(), seconds))
    // Apply absolute clip time, independent of playback rate or paused state.
    this.action.enabled = true
    this.action.paused = false
    this.action.setEffectiveTimeScale(1)
    this.action.setLoop(LoopOnce, 1)
    this.action.clampWhenFinished = true
    this.mixer.timeScale = 1
    this.mixer.setTime(this.time)
    this.action.paused = true
    this.root.updateMatrixWorld(true)
  }
  update(delta: number) {
    if (!this.playing || !this.action) return
    let time = this.time + Math.max(0, delta) * this.speed
    const duration = this.duration()
    if (time >= duration) {
      if (this.loop && duration > 0) time %= duration
      else {
        time = duration
        this.playing = false
      }
    }
    this.seek(time)
  }
  state() {
    return {
      time: this.time,
      duration: this.duration(),
      playing: this.playing,
      index: this.index,
      speed: this.speed,
      loop: this.loop
    }
  }
  dispose() {
    this.mixer.stopAllAction()
    this.mixer.uncacheRoot(this.root)
  }
}
/** StudioTwin frame-sampled joint translations. Unknown schemas are refused, never guessed. */
export function parseMotion(doc: unknown): ParsedModel {
  const d = doc as {
    fps: number
    frames: number
    joints: Record<string, number[][]>
    clips: { name: string; start: number; end: number }[]
  }
  if (
    !d ||
    !Number.isFinite(d.fps) ||
    d.fps <= 0 ||
    !Number.isInteger(d.frames) ||
    d.frames < 1 ||
    !d.joints ||
    !Array.isArray(d.clips)
  )
    throw new Error('Unsupported motion JSON: expected fps, frames, joints and clips')
  const root = new Group()
  const jointNames = Object.keys(d.joints)
  for (const name of jointNames) {
    if (!/^[a-zA-Z_][\w-]*$/.test(name)) throw new Error('Unsupported joint name')
    const samples = d.joints[name]
    if (
      !Array.isArray(samples) ||
      samples.length !== d.frames ||
      samples.some((v) => !Array.isArray(v) || v.length !== 3 || v.some((n) => !Number.isFinite(n)))
    )
      throw new Error('Invalid joint samples')
    const bone = new Bone()
    bone.name = name
    root.add(bone)
  }
  const clips = d.clips.map((c) => {
    if (!Number.isInteger(c.start) || !Number.isInteger(c.end) || c.start < 0 || c.end >= d.frames || c.end < c.start)
      throw new Error('Invalid motion clip bounds')
    const times = Array.from({ length: c.end - c.start + 1 }, (_, i) => i / d.fps)
    return new AnimationClip(
      c.name,
      (c.end - c.start) / d.fps,
      jointNames.map(
        (name) => new VectorKeyframeTrack(`${name}.position`, times, d.joints[name].slice(c.start, c.end + 1).flat())
      )
    )
  })
  // Joint-only motion has no skinned surface; show a skeleton and joint marker geometry in the stage.
  root.add(new SkeletonHelper(root))
  return { root, clips }
}
