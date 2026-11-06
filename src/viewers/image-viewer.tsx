import * as sdk from '@hermes/plugin-sdk'
import { stageShell, glassToolbar, glassStatsPill, controlStrip, styledRange, filterPillStyle } from '../lib/ui-tokens'
const { Button } = sdk
import { useEffect, useRef, useState, type ReactNode } from 'react'
import type { MediaScope, MediaSource } from '../cards/next-actions.ts'
import { imageFile } from '../cards/next-actions.ts'
export interface ImageViewerProps {
  source: MediaSource
  before?: MediaSource
  scope: MediaScope
  fallback?: ReactNode
  title?: string
  onError?: () => void
}
export function ImageViewer({
  source,
  before,
  scope,
  fallback,
  title = 'StudioTwin image',
  onError,
}: ImageViewerProps) {
  const [file, setFile] = useState<{ dataUrl: string; bytes?: number; name: string } | null>(null)
  const [parent, setParent] = useState<string>(),
    [failed, setFailed] = useState(false)
  const [size, setSize] = useState([0, 0]),
    [split, setSplit] = useState(50),
    [open, setOpen] = useState(false),
    [zoom, setZoom] = useState(1)
  const viewport = useRef<HTMLDivElement>(null)
  const inspect = useRef<HTMLButtonElement>(null)
  const closeInspection = () => {
    setOpen(false)
    inspect.current?.focus()
  }
  const fail = () => {
    setFailed(true)
    onError?.()
  }
  const drag = useRef<{ x: number; y: number; left: number; top: number } | null>(null)
  useEffect(() => {
    let live = true
    Promise.all([imageFile(scope, source), before ? imageFile(scope, before) : Promise.resolve(null)])
      .then(([f, b]) => {
        if (live) {
          scope.assert()
          setFile(f)
          setParent(b?.dataUrl)
        }
      })
      .catch(() => {
        if (live) fail()
      })
    const stop = scope.watch(() => {
      if (live) {
        setFailed(true)
        setOpen(false)
      }
    })
    return () => {
      live = false
      stop()
    }
  }, [scope, source.path, source.asset, source.url, before?.path, before?.asset, before?.url])
  useEffect(() => {
    if (!open) return
    const close = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeInspection()
    }
    document.addEventListener('keydown', close)
    return () => document.removeEventListener('keydown', close)
  }, [open])
  if (failed || !scope.current()) return <>{fallback ?? <p role="alert">Image preview unavailable.</p>}</>
  if (!file) return <p role="status">Loading image…</p>
  const picture = (
    <div style={{ position: 'relative', width: '100%', background: 'var(--ui-bg-secondary)' }}>
      <img
        src={file.dataUrl}
        alt={title}
        onLoad={(e) => setSize([e.currentTarget.naturalWidth, e.currentTarget.naturalHeight])}
        onError={fail}
        style={{ display: 'block', width: '100%', maxHeight: 440, objectFit: 'contain' }}
      />
      {parent && (
        <img
          src={parent}
          alt="Before image"
          onError={fail}
          style={{
            position: 'absolute',
            inset: 0,
            width: '100%',
            height: '100%',
            objectFit: 'contain',
            clipPath: `inset(0 ${100 - split}% 0 0)`,
          }}
        />
      )}
    </div>
  )
  return (
    <section style={stageShell}>
      {picture}
      {parent && (
        <label style={{ ...glassToolbar, ...controlStrip, flexWrap: 'wrap' }}>
          Before / after{' '}
          <input
            aria-label="Before / after"
            style={{ ...styledRange, flex: 1, minWidth: 120 }}
            type="range"
            min="0"
            max="100"
            value={split}
            onChange={(e) => setSplit(Number(e.target.value))}
          />
        </label>
      )}
      <div style={glassToolbar}>
        <span style={{ ...glassStatsPill, overflowWrap: 'anywhere' }}>
          {size[0]} × {size[1]} · {size[1] ? (size[0] / size[1]).toFixed(2) : '?'}:1 ·{' '}
          {file.bytes === undefined ? 'size not reported' : `${file.bytes} bytes`}
        </span>
        <Button style={filterPillStyle(false)} ref={inspect} onClick={() => setOpen(true)}>
          Inspect image
        </Button>
      </div>
      {open && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Image inspection"
          onKeyDown={(e) => {
            if (e.key === 'Escape') { e.stopPropagation(); closeInspection(); return }
            if (e.key !== 'Tab') return
            const nodes = e.currentTarget.querySelectorAll<HTMLElement>('button,input,[tabindex="0"]')
            const first = nodes[0],
              last = nodes[nodes.length - 1]
            if (e.shiftKey && document.activeElement === first) {
              e.preventDefault()
              last?.focus()
            }
            if (!e.shiftKey && document.activeElement === last) {
              e.preventDefault()
              first?.focus()
            }
          }}
          style={{
            ...stageShell,
            position: 'fixed',
            inset: '5%',
            zIndex: 1000,
            padding: 12,
            background: 'var(--ui-bg-elevated, var(--ui-bg-card))',
            border: '1px solid var(--ui-stroke-secondary)',
            display: 'flex',
            flexDirection: 'column',
            boxShadow: 'var(--ui-shadow-dialog, 0 24px 80px var(--ui-stroke-secondary))',
          }}
        >
          <div style={glassToolbar}>
            <Button style={filterPillStyle(false)} autoFocus onClick={closeInspection}>
              Close inspection
            </Button>{' '}
            {[1, 2, 4].map(value => <Button key={value} style={filterPillStyle(zoom === value)} aria-pressed={zoom === value} onClick={() => setZoom(value)}>{value}×</Button>)}
            <label style={controlStrip}>
              Zoom{' '}
              <input
                aria-label="Zoom"
                style={styledRange}
                type="range"
                min="1"
                max="8"
                step="0.1"
                value={zoom}
                onChange={(e) => setZoom(Number(e.target.value))}
              />
            </label>{' '}
            <span style={glassStatsPill}>{zoom.toFixed(1)}× · drag to pan</span>
            <span style={{ fontSize: 11, color: 'var(--ui-text-secondary)' }}>Pan · drag canvas</span>
          </div>
          <div
            ref={viewport}
            tabIndex={0}
            aria-label="Pan image"
            style={{ overflow: 'auto', flex: 1, minHeight: 0, cursor: 'grab', touchAction: 'none', borderRadius: 12, background: 'var(--ui-bg-secondary)' }}
            onPointerDown={(e) => {
              const el = e.currentTarget
              el.setPointerCapture(e.pointerId)
              drag.current = { x: e.clientX, y: e.clientY, left: el.scrollLeft, top: el.scrollTop }
            }}
            onPointerMove={(e) => {
              const d = drag.current
              if (d) {
                e.currentTarget.scrollLeft = d.left + d.x - e.clientX
                e.currentTarget.scrollTop = d.top + d.y - e.clientY
              }
            }}
            onPointerUp={() => {
              drag.current = null
            }}
            onPointerCancel={() => {
              drag.current = null
            }}
          >
            <img src={file.dataUrl} alt="Image detail" style={{ width: `${zoom * 100}%`, maxWidth: 'none' }} />
          </div>
        </div>
      )}
    </section>
  )
}
