/** Pure UI lifecycle contracts. No runtime dependencies or host access. */
export type StagePhase = 'poster' | 'loading' | 'ready' | 'evicted' | 'error' | 'audit'
export type StageLifecycleState = { [P in StagePhase]: { phase: P; poster?: string } }[StagePhase]
export type StageEvent = { type: 'start' | 'ready' | 'error' | 'audit' } | { type: 'evict' | 'reset'; poster?: string }
export function stageTransition(state: StageLifecycleState, event: StageEvent): StageLifecycleState {
  const poster = 'poster' in event ? event.poster : state.poster
  switch (event.type) {
    case 'reset': return { phase: 'poster', poster }
    case 'start': return state.phase === 'loading' || state.phase === 'ready' ? state : { phase: 'loading', poster }
    case 'ready': return state.phase === 'loading' ? { phase: 'ready', poster } : state
    case 'error': return { phase: 'error', poster }
    case 'audit': return state.phase === 'loading' ? { phase: 'audit', poster } : state
    case 'evict': return state.phase === 'error' || state.phase === 'audit' || state.phase === 'poster' ? state : { phase: 'evicted', poster: event.poster ?? state.poster }
  }
}
export function stageProjection(state: StageLifecycleState) {
  return { live: state.phase === 'loading' || state.phase === 'ready', ready: state.phase === 'ready', error: state.phase === 'error' }
}
export type MultiviewState<T> = { phase: 'idle' } | { phase: 'capturing' } | { phase: 'staging'; capture: T } | { phase: 'staged'; capture: T; sheetPath: string } | { phase: 'partial_error'; capture: T; message: string } | { phase: 'error'; message: string }
export type MultiviewEvent<T> = { type: 'start' | 'reset' } | { type: 'captured'; capture: T } | { type: 'staged'; sheetPath: string } | { type: 'error'; message: string }
export function multiviewTransition<T>(state: MultiviewState<T>, event: MultiviewEvent<T>): MultiviewState<T> {
  switch (event.type) {
    case 'reset': return { phase: 'idle' }
    case 'start': return state.phase === 'capturing' || state.phase === 'staging' ? state : { phase: 'capturing' }
    case 'captured': return state.phase === 'capturing' ? { phase: 'staging', capture: event.capture } : state
    case 'staged': return state.phase === 'staging' ? { phase: 'staged', capture: state.capture, sheetPath: event.sheetPath } : state
    case 'error': return state.phase === 'staging' ? { phase: 'partial_error', capture: state.capture, message: event.message } : state.phase === 'capturing' ? { phase: 'error', message: event.message } : state
  }
}
export type JobStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
export function normalizeJobStatus(raw: unknown): JobStatus {
  const status = typeof raw === 'string' ? raw.toLowerCase().replace(/[- ]/g, '_') : ''
  if (['done', 'complete', 'completed', 'succeeded', 'success'].includes(status)) return 'completed'
  if (['executing', 'in_progress', 'processing', 'running'].includes(status)) return 'running'
  if (['canceled', 'cancelled'].includes(status)) return 'cancelled'
  if (['failed', 'error'].includes(status)) return 'failed'
  return 'queued'
}
export type TaskLifecycleState = { phase: 'stale' | 'loading' | 'completed' | 'cancelled' | 'failed' } | { phase: 'queued' | 'running' | 'cancelling'; cancelWarning?: string }
export function deriveTaskCardState(input: { status?: unknown; stale?: boolean; loading?: boolean; failed?: boolean; cancelled?: boolean; cancelling?: boolean; cancelWarning?: string }): TaskLifecycleState {
  if (input.stale) return { phase: 'stale' }
  const status = normalizeJobStatus(input.status)
  if (input.cancelled) return { phase: 'cancelled' }
  if (input.failed) return { phase: 'failed' }
  if (input.loading) return { phase: 'loading' }
  if (status === 'completed' || status === 'failed' || status === 'cancelled') return { phase: status }
  return { phase: input.cancelling ? 'cancelling' : status, ...(input.cancelWarning ? { cancelWarning: input.cancelWarning } : {}) }
}
type Row = Record<string, any>
type ResolutionQuery = { data?: Row; isLoading?: boolean; isError?: boolean }
export type InspectorResolutionState = { phase: 'loading_job_output' } | { phase: 'job_output_error' } | { phase: 'rig_check_summary'; target: Row } | { phase: 'ready'; target: Row; modality: string; resolutionWarning?: string }
export function resolveInspectorTargetState(row: Row, detail: ResolutionQuery, job: ResolutionQuery, modality: (row: Row) => string = row => row.type ?? 'unknown'): InspectorResolutionState {
  const jobOnly = row.jobOnly || row.type === 'job_output'
  if (jobOnly && job.isError) return { phase: 'job_output_error' }
  if (jobOnly && !job.data) return { phase: 'loading_job_output' }
  const target = jobOnly ? { ...row, ...job.data } : { ...row, ...detail.data }
  if (target.type === 'rig_check') return { phase: 'rig_check_summary', target }
  return { phase: 'ready', target, modality: modality(target), ...(!jobOnly && detail.isError && !row.path && !row.local_path ? { resolutionWarning: 'Asset details could not be resolved. Showing the selected preview; download the original if unavailable.' } : {}) }
}
export type UploadLifecycleState<T> = { phase: 'idle' } | { phase: 'uploading'; filename: string; destination: 'local' | 'cloud' } | { phase: 'succeeded'; result: T } | { phase: 'failed'; message: string }
export type AudioViewerState<T> = ({ phase: 'loading' } | { phase: 'ready'; data: T } | { phase: 'error' }) & { convertingFormat: string | null }
export type VideoLoadState = { phase: 'loading' } | { phase: 'ready_video'; url: string; frameTimes?: number[] } | { phase: 'ready_sequence'; urls: string[]; duration: number } | { phase: 'error' }
