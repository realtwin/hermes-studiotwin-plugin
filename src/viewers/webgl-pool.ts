/** One pool per plugin bundle, shared by inline and workspace viewers. */
export class WebGLPool {
  private entries = new Map<string, () => void>()
  private limit = 4
  constructor(limit = 4) {
    this.setLimit(limit)
  }
  get size() {
    return this.entries.size
  }
  setLimit(limit: number) {
    this.limit = Number.isFinite(limit) ? Math.max(1, Math.min(4, Math.floor(limit))) : 4
    while (this.size > this.limit) this.release(this.entries.keys().next().value!)
  }
  acquire(key: string, dispose: () => void) {
    this.release(key)
    while (this.size >= this.limit) this.release(this.entries.keys().next().value!)
    this.entries.set(key, dispose)
  }
  touch(key: string) {
    const d = this.entries.get(key)
    if (d) {
      this.entries.delete(key)
      this.entries.set(key, d)
    }
  }
  release(key: string) {
    const d = this.entries.get(key)
    this.entries.delete(key)
    d?.()
  }
  clear() {
    for (const key of [...this.entries.keys()]) this.release(key)
  }
}
export const modelWebGLPool = new WebGLPool()
