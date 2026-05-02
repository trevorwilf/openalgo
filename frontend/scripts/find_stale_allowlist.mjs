// Find allowlist entries that no longer correspond to actual hits.
// For each entry, simulate "unallowlisted" and check whether the
// scanner would find any India literal in that file. Helper script
// for Phase 4 (T-34) — drains allowlist entries whose underlying
// files have already been cleaned up.

import { readFile } from 'node:fs/promises'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = fileURLToPath(new URL('.', import.meta.url))
const FRONTEND_ROOT = resolve(__dirname, '..')
const ALLOWLIST_PATH = resolve(FRONTEND_ROOT, 'scripts/literal_scan_allowlist.json')

const INDIA_LITERALS = [
  'Asia/Kolkata', 'IST', 'NSE', 'NFO', 'BSE', 'BFO', 'MCX', 'CDS', 'BCD',
  'MIS', 'CNC', 'NRML', 'DDMMMYY', 'CE', 'PE', '₹', 'INR',
  'NSE_INDEX', 'BSE_INDEX', 'lakh', 'crore', 'Cr', 'L',
]

function compilePattern(literal) {
  if (literal === 'L' || literal === 'Cr') {
    const esc = literal.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    return new RegExp('\\d' + esc + '(?![A-Za-z0-9_])')
  }
  if (/^[A-Za-z][A-Za-z0-9_]*$/.test(literal)) {
    const esc = literal.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    return new RegExp('(?<![A-Za-z0-9_.])' + esc + '(?![A-Za-z0-9_])')
  }
  return new RegExp(literal.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
}

const PATTERNS = INDIA_LITERALS.map((lit) => ({ lit, re: compilePattern(lit) }))

function stripLineComment(line) {
  const idx = line.indexOf('//')
  return idx >= 0 ? line.slice(0, idx) : line
}

async function scanFile(absPath) {
  let text
  try {
    text = await readFile(absPath, 'utf8')
  } catch {
    return null
  }
  const lines = text.split(/\r?\n/)
  const hits = []
  let inBlock = false
  for (let i = 0; i < lines.length; i++) {
    let line = lines[i]
    if (inBlock) {
      const close = line.indexOf('*/')
      if (close === -1) continue
      line = line.slice(close + 2)
      inBlock = false
    }
    while (true) {
      const open = line.indexOf('/*')
      if (open === -1) break
      const close = line.indexOf('*/', open + 2)
      if (close === -1) {
        line = line.slice(0, open)
        inBlock = true
        break
      }
      line = line.slice(0, open) + line.slice(close + 2)
    }
    line = stripLineComment(line)
    if (!line.trim()) continue
    for (const { lit, re } of PATTERNS) {
      if (re.test(line)) {
        hits.push({ line: i + 1, lit, snippet: line.trim().slice(0, 80) })
        break
      }
    }
    if (hits.length > 0) break
  }
  return hits
}

const allowlistRaw = await readFile(ALLOWLIST_PATH, 'utf8')
const allowlistObj = JSON.parse(allowlistRaw)
const stale = []
const active = []
for (const entry of allowlistObj.allowlist) {
  const abs = resolve(FRONTEND_ROOT, 'src', entry.path.replace(/^src\//, ''))
  const hits = await scanFile(abs)
  if (hits === null) {
    stale.push({ path: entry.path, reason: 'file missing' })
  } else if (hits.length === 0) {
    stale.push({ path: entry.path, reason: 'no literals' })
  } else {
    active.push({ path: entry.path, sample: hits[0] })
  }
}
console.log('STALE (safe to remove):', stale.length)
for (const s of stale) console.log('  -', s.path, '—', s.reason)
console.log()
console.log('ACTIVE (still needs literal):', active.length)
for (const a of active) {
  console.log('  -', a.path, 'line', a.sample.line, '—', a.sample.lit)
}
