#!/usr/bin/env node
// Frontend India-literal scanner.
//
// Walks frontend/src/{hooks,components,lib,pages,api}/**/*.{ts,tsx}
// and fails on any India-specific literal listed in INDIA_LITERALS,
// matching whole tokens only. Files in
// frontend/scripts/literal_scan_allowlist.json are exempt.
//
// Usage: node scripts/literal_scan.mjs
// Exit code: 0 = clean, 1 = violations found, 2 = config error.

import { readdir, readFile, stat } from 'node:fs/promises'
import { resolve, relative, sep, posix } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = fileURLToPath(new URL('.', import.meta.url))
const FRONTEND_ROOT = resolve(__dirname, '..')
const SRC_ROOT = resolve(FRONTEND_ROOT, 'src')

const SCAN_SUBDIRS = ['hooks', 'components', 'lib', 'pages', 'api']
const SCAN_EXTS = ['.ts', '.tsx']

const INDIA_LITERALS = [
  'Asia/Kolkata',
  'IST',
  'NSE',
  'NFO',
  'BSE',
  'BFO',
  'MCX',
  'CDS',
  'BCD',
  'MIS',
  'CNC',
  'NRML',
  'DDMMMYY',
  'CE',
  'PE',
  '₹',
  'INR',
  'NSE_INDEX',
  'BSE_INDEX',
  'lakh',
  'crore',
  'Cr',
  'L',
]

function compilePattern(literal) {
  // Rupee abbreviation pattern — `L` / `Cr` only match when
  // preceded by a digit (the `₹1.5L` form), so `P&L` and
  // identifiers like `Crash` / `Local` do not trip.
  if (literal === 'L' || literal === 'Cr') {
    const esc = literal.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    return new RegExp(`\\d${esc}(?![A-Za-z0-9_])`)
  }
  // Identifier-ish literal? Use a strict word-boundary that also
  // excludes a leading '.', so attribute access (`Currency.INR`) does
  // not trip the scanner.
  if (/^[A-Za-z][A-Za-z0-9_]*$/.test(literal)) {
    const esc = literal.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    return new RegExp(`(?<![A-Za-z0-9_.])${esc}(?![A-Za-z0-9_])`)
  }
  return new RegExp(literal.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
}

const PATTERNS = INDIA_LITERALS.map((lit) => ({ lit, re: compilePattern(lit) }))

async function loadAllowlist() {
  const path = resolve(__dirname, 'literal_scan_allowlist.json')
  try {
    const text = await readFile(path, 'utf8')
    const parsed = JSON.parse(text)
    return new Set((parsed.allowlist || []).map((e) => e.path))
  } catch (err) {
    console.error(`Failed to load allowlist at ${path}: ${err.message}`)
    process.exit(2)
  }
}

async function* walk(dir) {
  let entries
  try {
    entries = await readdir(dir, { withFileTypes: true })
  } catch {
    return
  }
  for (const entry of entries) {
    const full = resolve(dir, entry.name)
    if (entry.isDirectory()) {
      if (entry.name === 'node_modules' || entry.name === '__tests__' || entry.name.startsWith('.')) continue
      yield* walk(full)
    } else if (entry.isFile()) {
      if (SCAN_EXTS.some((ext) => entry.name.endsWith(ext))) {
        // Skip generated declaration files
        if (entry.name.endsWith('.d.ts')) continue
        // Skip .test.* / .spec.* files
        if (/\.(test|spec)\.(ts|tsx)$/.test(entry.name)) continue
        yield full
      }
    }
  }
}

function stripComments(line) {
  // Remove // comments (best-effort; ignore strings)
  const idx = line.indexOf('//')
  if (idx !== -1) return line.slice(0, idx)
  return line
}

async function scanFile(filePath, allowlist) {
  const relPath = relative(FRONTEND_ROOT, filePath).split(sep).join(posix.sep)
  if (allowlist.has(relPath)) return []
  const text = await readFile(filePath, 'utf8')
  const violations = []
  const lines = text.split(/\r?\n/)
  let inBlockComment = false
  for (let i = 0; i < lines.length; i++) {
    let line = lines[i]
    // Multi-line block comments
    if (inBlockComment) {
      const close = line.indexOf('*/')
      if (close === -1) continue
      line = line.slice(close + 2)
      inBlockComment = false
    }
    const open = line.indexOf('/*')
    if (open !== -1) {
      const close = line.indexOf('*/', open + 2)
      if (close === -1) {
        line = line.slice(0, open)
        inBlockComment = true
      } else {
        line = line.slice(0, open) + line.slice(close + 2)
      }
    }
    line = stripComments(line)
    if (!line.trim()) continue
    for (const { lit, re } of PATTERNS) {
      if (re.test(line)) {
        violations.push({ file: relPath, line: i + 1, literal: lit })
      }
    }
  }
  return violations
}

async function main() {
  const allowlist = await loadAllowlist()
  const files = []
  for (const sub of SCAN_SUBDIRS) {
    for await (const f of walk(resolve(SRC_ROOT, sub))) {
      files.push(f)
    }
  }
  files.sort()
  let total = 0
  for (const f of files) {
    const hits = await scanFile(f, allowlist)
    if (hits.length) {
      total += hits.length
      for (const h of hits) {
        console.error(`${h.file}:${h.line}: India-specific literal '${h.literal}'`)
      }
    }
  }
  if (total === 0) {
    console.log(`OK: scanned ${files.length} files, no India-literal violations.`)
    process.exit(0)
  } else {
    console.error(`FAIL: ${total} India-literal violations across ${files.length} files.`)
    process.exit(1)
  }
}

main().catch((err) => {
  console.error(err)
  process.exit(2)
})
