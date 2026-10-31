#!/usr/bin/env node
// Deterministic GLB contact sheets, using the preview's anonymous Chrome pipe.
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { findChrome, findThree, moduleSources, BOOT, cdpConnect } from './render_harness.mjs'

const VIEWS = [
  { name: 'front', label: 'FRONT', yaw: 0, pitch: 12 },
  { name: 'right', label: 'RIGHT', yaw: 90, pitch: 12 },
  { name: 'back', label: 'BACK', yaw: 180, pitch: 12 },
  { name: 'left', label: 'LEFT', yaw: 270, pitch: 12 },
  { name: 'three_quarter', label: '3/4', yaw: 35, pitch: 22 },
  { name: 'top', label: 'TOP', yaw: 0, pitch: 85 },
]
const fail = message => { throw new Error(message) }
function parseArgs(argv) {
  const a = { views: 4, shading: 'textured', tileSize: 512, transparent: false, labels: true }
  const rest = []
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i]
    const value = () => {
      if (i + 1 >= argv.length || argv[i + 1].startsWith('--')) fail(`missing value for ${k}`)
      return argv[++i]
    }
    if (k === '--out') a.out = value()
    else if (k === '--split-dir') a.splitDir = value()
    else if (k === '--views') a.views = Number(value())
    else if (k === '--shading') a.shading = value()
    else if (k === '--tile-size') a.tileSize = Number(value())
    else if (k === '--transparent') a.transparent = true
    else if (k === '--no-labels') a.labels = false
    else if (k === '--chrome') a.chrome = value()
    else if (k === '--help' || k === '-h') {
      console.log('node render_multiview.mjs model.glb [--out sheet.png] [--split-dir DIR] [--views 4|6] [--shading textured|clay|normals|wireframe] [--tile-size 512] [--transparent] [--no-labels] [--chrome PATH]')
      return null
    } else if (k.startsWith('-')) fail(`unknown option ${k}`)
    else rest.push(k)
  }
  if (rest.length !== 1) fail('expected one local model.glb')
  a.input = path.resolve(rest[0])
  if (![4, 6].includes(a.views)) fail('--views must be 4 or 6')
  if (!['textured', 'clay', 'normals', 'wireframe'].includes(a.shading)) fail('invalid --shading')
  if (!Number.isInteger(a.tileSize) || a.tileSize < 64 || a.tileSize > 2048) fail('--tile-size must be an integer in 64..2048')
  if (!/\.glb$/i.test(a.input) || !fs.statSync(a.input).isFile()) fail('input must be a local .glb file')
  a.out = path.resolve(a.out || a.input.replace(/\.glb$/i, '-multiview.png'))
  if (!/\.png$/i.test(a.out)) fail('--out must end in .png')
  if (a.splitDir) a.splitDir = path.resolve(a.splitDir)
  return a
}

const MAIN = `
import * as THREE from 'three'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js'
try {
  const P = window.__P, S = P.tileSize
  const errors = []
  const originalError = console.error.bind(console)
  console.error = (...args) => { errors.push(args.map(String).join(' ')); originalError(...args) }
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true })
  renderer.setPixelRatio(1); renderer.setSize(S, S, false)
  renderer.outputColorSpace = THREE.SRGBColorSpace
  renderer.toneMapping = P.shading === 'normals' ? THREE.NoToneMapping : THREE.ACESFilmicToneMapping
  const scene = new THREE.Scene()
  if (!P.transparent) scene.background = new THREE.Color('#d9dce1')
  renderer.setClearColor(0x000000, 0)
  const pmrem = new THREE.PMREMGenerator(renderer)
  const room = new RoomEnvironment()
  const environment = pmrem.fromScene(room, 0.04)
  scene.environment = environment.texture
  scene.add(new THREE.HemisphereLight(0xffffff, 0x777777, 1.2))
  const key = new THREE.DirectionalLight(0xffffff, 2.5); key.position.set(3, 5, 4); scene.add(key)
  const manager = new THREE.LoadingManager()
  manager.setURLModifier(u => {
    if (/^(data|blob):/i.test(u)) return u
    throw new Error('external GLB resource refused: ' + u)
  })
  const gltf = await new GLTFLoader(manager).parseAsync(window.__glb.buffer, '')
  window.__glb = null
  const model = gltf.scene
  // Fixed rest pose, including skinned meshes; never advance by wall clock.
  model.updateMatrixWorld(true)
  const box = new THREE.Box3().setFromObject(model, true)
  if (box.isEmpty()) throw new Error('model has no renderable bounds')
  const center = box.getCenter(new THREE.Vector3())
  const radius = box.getSize(new THREE.Vector3()).length() / 2
  if (!Number.isFinite(radius) || radius <= 0) throw new Error('invalid model bounds')
  const group = new THREE.Group(); group.add(model); group.position.copy(center).negate(); scene.add(group)
  const materials = new Set()
  model.traverse(o => {
    if (!o.isMesh) return
    o.frustumCulled = false
    if (P.shading === 'textured') return
    const flatShading = !o.geometry.attributes.normal
    const replacement = () => {
      const m = P.shading === 'normals' ? new THREE.MeshNormalMaterial({ side: THREE.DoubleSide, flatShading })
        : P.shading === 'wireframe' ? new THREE.MeshBasicMaterial({ color: 0x566a82, wireframe: true, side: THREE.DoubleSide })
        : new THREE.MeshStandardMaterial({ color: 0xb8b4ae,
            roughness: 0.85, metalness: 0, flatShading, side: THREE.DoubleSide })
      materials.add(m); return m
    }
    o.material = Array.isArray(o.material) ? o.material.map(replacement) : replacement()
  })
  const camera = new THREE.PerspectiveCamera(35, 1, radius / 100, radius * 100)
  const distance = radius / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2)) * 1.12
  const columns = P.views.length / 2
  const sheet = document.createElement('canvas'); sheet.width = S * columns; sheet.height = S * 2
  const ctx = sheet.getContext('2d')
  const tile = document.createElement('canvas'); tile.width = tile.height = S
  const tc = tile.getContext('2d')
  window.renderTile = i => {
    const view = P.views[i]
    const yaw = THREE.MathUtils.degToRad(view.yaw), pitch = THREE.MathUtils.degToRad(view.pitch)
    camera.position.set(distance * Math.cos(pitch) * Math.sin(yaw), distance * Math.sin(pitch), distance * Math.cos(pitch) * Math.cos(yaw))
    camera.lookAt(0, 0, 0)
    renderer.render(scene, camera)
    if (errors.length) throw new Error(errors.join(' | '))
    tc.clearRect(0, 0, S, S); tc.drawImage(renderer.domElement, 0, 0)
    if (P.labels) {
      const font = Math.max(12, Math.round(S * 0.035)), pad = Math.round(S * 0.035)
      tc.font = '600 ' + font + 'px sans-serif'; tc.textBaseline = 'middle'
      tc.fillStyle = 'rgba(20,22,26,0.8)'
      tc.fillRect(pad, S - pad - font * 1.8, tc.measureText(view.label).width + font, font * 1.8)
      tc.fillStyle = '#fff'; tc.fillText(view.label, pad + font / 2, S - pad - font * 0.9)
    }
    ctx.drawImage(tile, (i % columns) * S, Math.floor(i / columns) * S)
    return tile.toDataURL('image/png')
  }
  window.renderSheet = () => sheet.toDataURL('image/png')
  window.__ready = true
} catch (e) { window.__error = String(e.message || e) }
`

function checkTarget(target, input) {
  const source = fs.statSync(input)
  let targetStat
  try { fs.lstatSync(target); targetStat = fs.statSync(target) } catch (e) {
    // Dangling symlinks are existing targets too.
    if (e.code !== 'ENOENT') throw e
    try { fs.lstatSync(target); fail('output exists: ' + target) } catch (other) { if (other.code !== 'ENOENT') throw other }
  }
  if (path.resolve(target) === input || (targetStat && targetStat.ino === source.ino && targetStat.dev === source.dev)) fail('refusing to overwrite source file: ' + target)
  if (targetStat) fail('output exists: ' + target)
}
const decode = url => Buffer.from(url.slice(url.indexOf(',') + 1), 'base64')

async function main() {
  const a = parseArgs(process.argv.slice(2)); if (!a) return
  const views = VIEWS.slice(0, a.views)
  const splitFiles = Object.fromEntries(a.splitDir ? views.map(v => [v.name, path.join(a.splitDir, v.name + '.png')]) : [])
  const targets = [a.out, ...Object.values(splitFiles)]
  if (new Set(targets).size !== targets.length) fail('sheet and split outputs must be distinct')
  for (const target of targets) checkTarget(target, a.input)
  if (a.splitDir && fs.existsSync(a.splitDir) && !fs.statSync(a.splitDir).isDirectory()) fail('--split-dir must be a directory')
  const chrome = findChrome(a.chrome); if (!chrome) fail('no Chromium/Chrome found; pass --chrome PATH')
  const three = await findThree()
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'studiotwin-multiview-'))
  let browser
  const published = []
  try {
    browser = await cdpConnect(chrome, path.join(work, 'profile'), a.tileSize)
    const params = { tileSize: a.tileSize, views, shading: a.shading, transparent: a.transparent, labels: a.labels }
    await browser.evaluate(BOOT + '(' + JSON.stringify(moduleSources(three)) + ',' + JSON.stringify(params) + ')')
    const glb = fs.readFileSync(a.input)
    await browser.evaluate('window.__glb = new Uint8Array(' + glb.length + '); 0')
    const chunk = 8 * 1024 * 1024
    for (let offset = 0; offset < glb.length; offset += chunk) {
      const data = glb.subarray(offset, offset + chunk).toString('base64')
      await browser.evaluate(`(() => { const s = atob(${JSON.stringify(data)}); for (let i=0;i<s.length;i++) window.__glb[${offset}+i]=s.charCodeAt(i); return 0 })()`)
    }
    await browser.evaluate(`(() => { const s = document.createElement('script'); s.type='module'; s.src=URL.createObjectURL(new Blob([${JSON.stringify(MAIN)}],{type:'text/javascript'})); document.body.appendChild(s); return 0 })()`)
    const started = Date.now()
    for (;;) {
      const status = await browser.evaluate('({ready: !!window.__ready, error: window.__error})')
      if (status.error) fail(status.error)
      if (browser.pageErrors.length) fail(browser.pageErrors.join(' | '))
      if (status.ready) break
      if (Date.now() - started > 120000) fail('model load timed out')
      await new Promise(r => setTimeout(r, 50))
    }
    const staged = []
    for (let i = 0; i < views.length; i++) {
      const url = await browser.evaluate('window.renderTile(' + i + ')')
      if (a.splitDir) {
        const file = path.join(work, views[i].name + '.png'); fs.writeFileSync(file, decode(url))
        staged.push([file, splitFiles[views[i].name]])
      }
    }
    const sheet = path.join(work, 'sheet.png')
    fs.writeFileSync(sheet, decode(await browser.evaluate('window.renderSheet()')))
    staged.push([sheet, a.out])
    // COPYFILE_EXCL is no-clobber, including concurrent writers and symlink aliases.
    for (const [file, target] of staged) {
      fs.mkdirSync(path.dirname(target), { recursive: true })
      fs.copyFileSync(file, target, fs.constants.COPYFILE_EXCL)
      published.push(target)
    }
    console.log(JSON.stringify({ ok: true, sheet: a.out, views: views.map(v => v.name), split_files: splitFiles,
      shading: a.shading, width: a.tileSize * (a.views / 2), height: a.tileSize * 2, bytes: fs.statSync(a.out).size }))
  } catch (e) {
    for (const target of published) fs.unlinkSync(target)
    throw e
  } finally {
    browser?.close()
    fs.rmSync(work, { recursive: true, force: true })
  }
}
main().catch(e => { console.log(JSON.stringify({ ok: false, error: String(e.message || e) })); process.exitCode = 1 })
