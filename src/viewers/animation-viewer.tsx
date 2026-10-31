import { useEffect, useState } from 'react'
import * as sdk from '@hermes/plugin-sdk'
const { Button } = sdk
import type { AnimationController } from './model-data.ts'
import { ModelViewer, type ModelViewerProps } from './model-viewer.tsx'
export interface RigAudit {
  riggable: boolean
  joints: number
  warnings: string[]
}
/** Provider data only: model inspection must never manufacture an audit verdict. */
export function parseRigAudit(doc: unknown): RigAudit | null {
  if (!doc || typeof doc !== 'object' || Array.isArray(doc)) return null
  const d = doc as Record<string, unknown>
  if (
    typeof d.riggable !== 'boolean' ||
    typeof d.joints !== 'number' || !Number.isInteger(d.joints) || d.joints < 0 ||
    !Array.isArray(d.warnings) || !d.warnings.every((w: unknown) => typeof w === 'string')
  ) return null
  return { riggable: d.riggable, joints: d.joints, warnings: [...d.warnings] }
}
export function AnimationControls({
  controller,
  invalidate,
  audit
}: {
  controller: AnimationController
  invalidate: () => void
  audit?: RigAudit
}) {
  const [state, setState] = useState(() => controller.state())
  useEffect(() => {
    const id = setInterval(() => setState(controller.state()), 120)
    return () => clearInterval(id)
  }, [controller])
  const change = (fn: () => void) => {
    fn()
    invalidate()
    setState(controller.state())
  }
  return (
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: 8,
        alignItems: 'center',
        color: 'var(--ui-text-secondary)',
        background: 'var(--ui-bg-secondary)',
        padding: 8
      }}
    >
      <label>
        Clip{' '}
        <select
          aria-label="Animation clip"
          value={state.index}
          onChange={(e) =>
            change(() => {
              controller.select(Number(e.target.value))
            })
          }
          style={{ color: 'var(--ui-text)', background: 'var(--ui-bg-secondary)' }}
        >
          {controller.clips.map((c, i) => (
            <option key={i} value={i}>
              {c.name || `Clip ${i + 1}`}
            </option>
          ))}
        </select>
      </label>
      <Button size="sm" onClick={() => change(() => controller.setPlaying(!controller.state().playing))}>
        {state.playing ? 'Pause' : 'Play'}
      </Button>
      <label>
        Speed{' '}
        <select
          aria-label="Playback speed"
          value={state.speed}
          onChange={(e) => change(() => controller.setSpeed(Number(e.target.value)))}
          style={{ color: 'var(--ui-text)', background: 'var(--ui-bg-secondary)' }}
        >
          {[0.25, 0.5, 1, 2].map((n) => (
            <option key={n} value={n}>
              {n}x
            </option>
          ))}
        </select>
      </label>
      <label>
        <input
          type="checkbox"
          checked={state.loop}
          onChange={(e) => change(() => controller.setLoop(e.target.checked))}
        />{' '}
        Loop
      </label>
      <input
        aria-label="Animation position"
        type="range"
        min={0}
        max={state.duration}
        step={0.001}
        value={state.time}
        onChange={(e) => change(() => controller.seek(Number(e.target.value)))}
        style={{ flex: 1, minWidth: 100, accentColor: 'var(--ui-accent)' }}
      />
      <output>
        {state.time.toFixed(2)} / {state.duration.toFixed(2)} s
      </output>
      {audit && (
        <span>
          Rig audit: {audit.riggable ? 'passed' : 'needs attention'} · {audit.joints} joints
          {audit.warnings.length ? ` · ${audit.warnings.length} warnings` : ''}
          {audit.warnings.map((w, i) => <span key={i} style={{ display: 'block' }}>{w}</span>)}
        </span>
      )}
    </div>
  )
}
/** GLB skeletal clips and StudioTwin joint-sample JSON share the same deterministic mixer path. */
export function AnimationViewer(props: ModelViewerProps) {
  return <ModelViewer {...props} />
}
