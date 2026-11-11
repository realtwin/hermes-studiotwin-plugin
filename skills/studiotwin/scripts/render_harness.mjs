// Shared unchanged preview discovery, blob modules and anonymous CDP pipe.
import { spawn, execFileSync } from 'node:child_process'
import { createHash, randomUUID } from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const THREE_VERSION = '0.180.0'
const THREE_TARBALL = `https://registry.npmjs.org/three/-/three-${THREE_VERSION}.tgz`
const THREE_SRI = 'sha512-o+qycAMZrh+TsE01GqWUxUIKR1AL0S8pq7zDkYOQw8GqfX8b8VoCKYUoHbhiX5j+7hr8XsuHDVU6+gkQJQKg9w=='
const dbg = (...m) => { if (process.env.STUDIOTWIN_PREVIEW_DEBUG) console.error('[preview]', ...m) }
const HERE = path.dirname(fileURLToPath(import.meta.url))

function die(msg, extra = {}) {
  console.log(JSON.stringify({ ok: false, error: msg, ...extra }))
  process.exit(1)
}

const hermesHome = () => path.resolve(process.env.HERMES_HOME || path.join(os.homedir(), '.hermes'))

// Hermes' managed tool store: HERMES_RUNTIME_DIR when set (Hermes exports it to its children),
// else <hermes root>/tools. Profiles live under <root>/profiles/<name>, the store at <root>/tools.
function toolStores() {
  const out = []
  if (process.env.HERMES_RUNTIME_DIR) out.push(process.env.HERMES_RUNTIME_DIR)
  const home = hermesHome()
  out.push(path.join(home, 'tools'))
  const m = home.match(/^(.*)[\\/]profiles[\\/][^\\/]+$/)
  if (m) out.push(path.join(m[1], 'tools'))
  out.push(path.join(os.homedir(), '.hermes', 'tools'))
  return [...new Set(out)].filter(d => fs.existsSync(d))
}

function globDirs(dir, prefix) {
  try { return fs.readdirSync(dir).filter(n => n.startsWith(prefix)).sort().reverse().map(n => path.join(dir, n)) } catch { return [] }
}

function which(name) {
  const exts = process.platform === 'win32' ? ['.exe', '.cmd', ''] : ['']
  for (const d of (process.env.PATH || '').split(path.delimiter)) for (const e of exts) {
    const p = path.join(d, name + e)
    try { if (fs.statSync(p).isFile()) return p } catch {}
  }
  return null
}

const firstFile = list => list.find(p => { try { return p && fs.statSync(p).isFile() } catch { return false } }) || null

function findFfmpeg() {
  const exe = process.platform === 'win32' ? 'ffmpeg.exe' : 'ffmpeg'
  const c = [process.env.FFMPEG_PATH]
  for (const s of toolStores()) for (const d of globDirs(s, 'ffmpeg')) c.push(path.join(d, 'bin', exe), path.join(d, exe))
  return firstFile(c) || which('ffmpeg')
}

function findChrome(explicit) {
  const c = [explicit, process.env.STUDIOTWIN_PREVIEW_CHROME, process.env.AGENT_BROWSER_EXECUTABLE_PATH, process.env.CHROME_PATH]
  const rel = {
    linux: ['chrome-linux64/chrome', 'chrome-linux/chrome', 'chrome-headless-shell-linux64/chrome-headless-shell'],
    darwin: ['chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing',
      'chrome-mac-x64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing',
      'chrome-mac/Chromium.app/Contents/MacOS/Chromium',
      'chrome-headless-shell-mac-arm64/chrome-headless-shell', 'chrome-headless-shell-mac-x64/chrome-headless-shell'],
    win32: ['chrome-win64/chrome.exe', 'chrome-win/chrome.exe', 'chrome-headless-shell-win64/chrome-headless-shell.exe'],
  }[process.platform] || []
  const pwRoots = [process.env.PLAYWRIGHT_BROWSERS_PATH, ...toolStores(),
    path.join(os.homedir(), '.cache', 'ms-playwright'), path.join(os.homedir(), 'Library', 'Caches', 'ms-playwright'),
    process.env.LOCALAPPDATA && path.join(process.env.LOCALAPPDATA, 'ms-playwright')].filter(Boolean)
  for (const r of pwRoots) for (const pre of ['chromium-', 'chromium_headless_shell-', 'chromium'])
    for (const d of globDirs(r, pre)) for (const x of rel) c.push(path.join(d, x))
  c.push('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/Applications/Chromium.app/Contents/MacOS/Chromium',
    process.env.PROGRAMFILES && path.join(process.env.PROGRAMFILES, 'Google/Chrome/Application/chrome.exe'),
    process.env['PROGRAMFILES(X86)'] && path.join(process.env['PROGRAMFILES(X86)'], 'Microsoft/Edge/Application/msedge.exe'))
  return firstFile(c) || ['google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'chrome', 'msedge'].map(which).find(Boolean) || null
}

// three@0.180.0: the plugin's own node_modules when present (dev checkout), else a verified copy
// of the npm tarball cached once under <HERMES_HOME>/cache/studiotwin-preview/.
async function findThree() {
  const want = d => { try { return JSON.parse(fs.readFileSync(path.join(d, 'package.json'), 'utf8')).version === THREE_VERSION ? d : null } catch { return null } }
  for (let d = HERE; d !== path.dirname(d); d = path.dirname(d)) {
    const hit = want(path.join(d, 'node_modules', 'three'))
    if (hit) return hit
  }
  const cache = path.join(hermesHome(), 'cache', 'studiotwin-preview', `three-${THREE_VERSION}`)
  if (want(path.join(cache, 'package'))) return path.join(cache, 'package')
  let res
  try { res = await fetch(THREE_TARBALL) } catch (e) {
    die(`could not download three ${THREE_VERSION} from ${THREE_TARBALL} (first run needs network once): ${e.cause?.code || e.cause?.message || e.message}`)
  }
  if (!res.ok) die(`could not download three ${THREE_VERSION}: HTTP ${res.status}`)
  const buf = Buffer.from(await res.arrayBuffer())
  if ('sha512-' + createHash('sha512').update(buf).digest('base64') !== THREE_SRI) die('three tarball integrity mismatch')
  fs.mkdirSync(cache, { recursive: true })
  const tgz = path.join(cache, 'three.tgz')
  fs.writeFileSync(tgz, buf)
  execFileSync('tar', ['-xzf', tgz, '-C', cache, 'package/package.json', 'package/build', 'package/examples/jsm'])
  fs.rmSync(tgz)
  return want(path.join(cache, 'package')) || die('three extraction failed')
}

// The page never navigates or touches the network: it stays on about:blank, three.js modules
// are turned into blob: URLs behind an import map, the GLB bytes are pushed in over CDP, and the
// loader refuses external resource URLs a GLB may name (see setURLModifier in MAIN).
// (Some hosts' Chromium builds hang on any http/file navigation in headless mode.)
function moduleSources(threeDir) {
  const rd = r => fs.readFileSync(path.join(threeDir, r), 'utf8')
  const fix = src => src.replace(/from '\.\.\/utils\/BufferGeometryUtils\.js'/g, "from 'three/addons/utils/BufferGeometryUtils.js'")
  return {
    core: rd('build/three.core.js'),
    three: rd('build/three.module.js'),
    bgu: rd('examples/jsm/utils/BufferGeometryUtils.js'),
    gltf: fix(rd('examples/jsm/loaders/GLTFLoader.js')),
    room: rd('examples/jsm/environments/RoomEnvironment.js'),
  }
}

const BOOT = `(async (M, P) => {
  const url = s => URL.createObjectURL(new Blob([s], { type: 'text/javascript' }))
  const core = url(M.core)
  const imports = {
    'three': url(M.three.split("'./three.core.js'").join(JSON.stringify(core))),
    'three/addons/utils/BufferGeometryUtils.js': url(M.bgu),
    'three/addons/loaders/GLTFLoader.js': url(M.gltf),
    'three/addons/environments/RoomEnvironment.js': url(M.room),
  }
  const map = document.createElement('script'); map.type = 'importmap'
  map.textContent = JSON.stringify({ imports }); document.head.appendChild(map)
  document.body.style.cssText = 'margin:0;background:#000'
  window.__P = P
  return true
})`

async function cdpConnect(chromeBin, profileDir, size) {
  // Chromium's anonymous debugging pipe: no local server, TCP port or WebSocket.
  const proc = spawn(chromeBin, ['--headless=new', '--no-sandbox', '--no-first-run', '--disable-extensions',
    '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--mute-audio', '--password-store=basic',
    `--window-size=${size},${size}`, `--user-data-dir=${profileDir}`, '--remote-debugging-pipe', 'about:blank'],
    { stdio: ['ignore','ignore','pipe','pipe','pipe'] })
  let stderr='', buffer='', id=0, sessionId
  const pending=new Map(), pageErrors=[]
  proc.stderr.on('data',d=>{stderr=(stderr+d).slice(-4000)})
  proc.stdio[4].on('data',d=>{
    buffer+=d.toString()
    for(let cut;(cut=buffer.indexOf('\0'))>=0;) {
      const text=buffer.slice(0,cut);buffer=buffer.slice(cut+1);if(!text) continue
      const msg=JSON.parse(text)
      if(msg.id && pending.has(msg.id)) {pending.get(msg.id)(msg);pending.delete(msg.id)}
      else if(msg.method==='Runtime.exceptionThrown') pageErrors.push(msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text)
    }
  })
  const send=(method,params={},session=sessionId)=>new Promise((resolve,reject)=>{
    const my=++id
    const timer=setTimeout(()=>{pending.delete(my);reject(new Error('Chromium debugging pipe timed out: '+method))},30000)
    pending.set(my,msg=>{clearTimeout(timer);msg.error?reject(new Error(msg.error.message)):resolve(msg.result)})
    proc.stdio[3].write(JSON.stringify({id:my,method,params,...(session?{sessionId:session}:{})})+'\0')
  })
  const reap=()=>{try{proc.kill('SIGKILL')}catch{}}
  process.on('exit',reap)
  for(const sig of ['SIGINT','SIGTERM','SIGHUP']) process.once(sig,()=>{reap();process.exit(130)})
  proc.on('error',e=>{pageErrors.push(e.message)})
  const page=await send('Target.createTarget',{url:'about:blank'})
  sessionId=(await send('Target.attachToTarget',{targetId:page.targetId,flatten:true})).sessionId
  await send('Runtime.enable')
  const evaluate=async expression=>{
    const r=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true})
    if(r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text)
    return r.result.value
  }
  return {evaluate,close:reap,proc,stderr:()=>stderr,pageErrors}
}


export { findChrome, findThree, moduleSources, BOOT, cdpConnect }
