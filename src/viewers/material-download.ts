import type { PluginContext } from "@hermes/plugin-sdk";
import { fetchModel, type ModelSource } from "./model-source.ts";
/** Store-only ZIP, no compression dependency; filenames are fixed channel names. */
export function mapZip(
  files: { name: string; buffer: ArrayBuffer }[],
): ArrayBuffer {
  const chunks: Uint8Array[] = [];
  const central: Uint8Array[] = [];
  let offset = 0,
    centralSize = 0;
  const crc = (a: Uint8Array) => {
    let c = 0xffffffff;
    for (const b of a) {
      c ^= b;
      for (let j = 0; j < 8; j++) c = (c >>> 1) ^ (c & 1 ? 0xedb88320 : 0);
    }
    return (c ^ 0xffffffff) >>> 0;
  };
  for (const file of files) {
    const data = new Uint8Array(file.buffer),
      name = new TextEncoder().encode(file.name),
      sum = crc(data),
      local = new Uint8Array(30 + name.length),
      v = new DataView(local.buffer);
    v.setUint32(0, 0x04034b50, true);
    v.setUint16(4, 20, true);
    v.setUint32(14, sum, true);
    v.setUint32(18, data.length, true);
    v.setUint32(22, data.length, true);
    v.setUint16(26, name.length, true);
    local.set(name, 30);
    chunks.push(local, data);
    const c = new Uint8Array(46 + name.length),
      w = new DataView(c.buffer);
    w.setUint32(0, 0x02014b50, true);
    w.setUint16(4, 20, true);
    w.setUint16(6, 20, true);
    w.setUint32(16, sum, true);
    w.setUint32(20, data.length, true);
    w.setUint32(24, data.length, true);
    w.setUint16(28, name.length, true);
    w.setUint32(42, offset, true);
    c.set(name, 46);
    central.push(c);
    centralSize += c.length;
    offset += local.length + data.length;
  }
  const end = new Uint8Array(22),
    v = new DataView(end.buffer);
  v.setUint32(0, 0x06054b50, true);
  v.setUint16(8, files.length, true);
  v.setUint16(10, files.length, true);
  v.setUint32(12, centralSize, true);
  v.setUint32(16, offset, true);
  const result = new Uint8Array(offset + centralSize + 22);
  let pos = 0;
  for (const c of [...chunks, ...central, end]) {
    result.set(c, pos);
    pos += c.length;
  }
  return result.buffer;
}
export async function downloadSource(
  rest: PluginContext["rest"],
  source: ModelSource,
  assert: () => void,
) {
  const f = await fetchModel(rest, source);
  assert();
  saveBytes(f.buffer, f.name);
}
export function saveBytes(buffer: ArrayBuffer, name: string) {
  const url = URL.createObjectURL(new Blob([buffer]));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
