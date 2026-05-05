#!/usr/bin/env node
// Phase 8 — frontend/src/charts/* lint rules.
//
// Enforces:
//
//   1. No `5.5 * 60 * 60 * 1000` literal (hardcoded IST offset).
//   2. No `'Asia/Kolkata'` / `'IST'` literal.
//   3. No import from `@/india_legacy/...`.
//   4. No engine sub-module import from outside loader.ts / base.ts —
//      `@/charts/engine/{lightweight,klinechart,tradingview}/...`.
//
// Usage: node scripts/lint_charts_rules.mjs
// Exit code: 0 = clean, 1 = violations found.
//
// Complements `lint:literals` (the broader India-literal scanner).

import { readdir, readFile } from 'node:fs/promises'
import { resolve, relative, sep, posix } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = fileURLToPath(new URL('.', import.meta.url))
const FRONTEND_ROOT = resolve(__dirname, '..')
const CHARTS_ROOT = resolve(FRONTEND_ROOT, 'src', 'charts')

const ENGINE_LOADER = resolve(CHARTS_ROOT, 'engine', 'loader.ts')
const ENGINE_BASE = resolve(CHARTS_ROOT, 'engine', 'base.ts')

const FORBIDDEN_LITERALS = [
  { name: 'IST_OFFSET_MULT', re: /5\.5\s*\*\s*60\s*\*\s*60\s*\*\s*1000/ },
  { name: 'ASIA_KOLKATA', re: /['"]Asia\/Kolkata['"]/ },
  // Match the bare token 'IST' — but avoid false positives from
  // identifiers like `LIST` / `EXISTS`. Same regex shape as the
  // wider literal scanner.
  { name: 'IST_LITERAL', re: /(?<![A-Za-z0-9_.])['"]IST['"](?![A-Za-z0-9_])/ },
]

const FORBIDDEN_IMPORT_PATTERNS = [
  {
    name: 'india_legacy_import',
    re: /from\s+['"]@\/india_legacy\/[^'"]+['"]/,
    appliesTo: () => true,
  },
  {
    name: 'lightweight_engine_static_import',
    re: /from\s+['"]\@\/charts\/engine\/lightweight\/[^'"]+['"]|from\s+['"]\.\.\/lightweight\/[^'"]+['"]|from\s+['"]\.\.\/\.\.\/engine\/lightweight\/[^'"]+['"]/,
    // Allowed only inside the engine loader / base / the lightweight
    // adapter's own folder + tests there.
    appliesTo: (filePath) => {
      const isLoader = filePath === ENGINE_LOADER
      const isBase = filePath === ENGINE_BASE
      const isLightweightAdapter = filePath.includes(`charts${sep}engine${sep}lightweight${sep}`)
      return !isLoader && !isBase && !isLightweightAdapter
    },
  },
  {
    name: 'klinechart_engine_static_import',
    re: /from\s+['"]\@\/charts\/engine\/klinechart\/[^'"]+['"]|from\s+['"]\.\.\/klinechart\/[^'"]+['"]|from\s+['"]\.\.\/\.\.\/engine\/klinechart\/[^'"]+['"]/,
    appliesTo: (filePath) => {
      const isLoader = filePath === ENGINE_LOADER
      const isBase = filePath === ENGINE_BASE
      const isKLineAdapter = filePath.includes(`charts${sep}engine${sep}klinechart${sep}`)
      return !isLoader && !isBase && !isKLineAdapter
    },
  },
  {
    name: 'tradingview_engine_static_import',
    re: /from\s+['"]\@\/charts\/engine\/tradingview\/[^'"]+['"]|from\s+['"]\.\.\/tradingview\/[^'"]+['"]|from\s+['"]\.\.\/\.\.\/engine\/tradingview\/[^'"]+['"]/,
    appliesTo: (filePath) => {
      const isLoader = filePath === ENGINE_LOADER
      const isBase = filePath === ENGINE_BASE
      const isTVAdapter = filePath.includes(`charts${sep}engine${sep}tradingview${sep}`)
      return !isLoader && !isBase && !isTVAdapter
    },
  },
]

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
      if (entry.name === 'node_modules' || entry.name.startsWith('.')) continue
      yield* walk(full)
    } else if (entry.isFile()) {
      if (full.endsWith('.ts') || full.endsWith('.tsx')) {
        if (full.endsWith('.d.ts')) continue
        yield full
      }
    }
  }
}

function stripComments(text) {
  // Per-line comment + multi-line block-comment strip. Mirrors the
  // logic in literal_scan.mjs so this charts-specific lint matches
  // only real code, not pattern references in doc-comments.
  const lines = text.split(/\r?\n/)
  const out = []
  let inBlock = false
  for (let line of lines) {
    if (inBlock) {
      const close = line.indexOf('*/')
      if (close === -1) {
        out.push('')
        continue
      }
      line = line.slice(close + 2)
      inBlock = false
    }
    const open = line.indexOf('/*')
    if (open !== -1) {
      const close = line.indexOf('*/', open + 2)
      if (close === -1) {
        line = line.slice(0, open)
        inBlock = true
      } else {
        line = line.slice(0, open) + line.slice(close + 2)
      }
    }
    const lineCommentIdx = line.indexOf('//')
    if (lineCommentIdx !== -1) line = line.slice(0, lineCommentIdx)
    out.push(line)
  }
  return out
}

async function main() {
  let total = 0
  for await (const file of walk(CHARTS_ROOT)) {
    const text = await readFile(file, 'utf8')
    const rel = relative(FRONTEND_ROOT, file).split(sep).join(posix.sep)

    // Skip test files for forbidden-literal checks (tests legitimately
    // mention the tokens). Import-pattern checks still apply.
    const isTest = /\.(test|spec)\.(ts|tsx)$/.test(file)
    const stripped = stripComments(text)

    if (!isTest) {
      stripped.forEach((line, idx) => {
        if (!line.trim()) return
        for (const { name, re } of FORBIDDEN_LITERALS) {
          const m = line.match(re)
          if (m) {
            total += 1
            console.error(
              `${rel}:${idx + 1}: forbidden literal ${name} (matched: ${m[0]})`,
            )
          }
        }
      })
    }

    for (const { name, re, appliesTo } of FORBIDDEN_IMPORT_PATTERNS) {
      if (!appliesTo(file)) continue
      stripped.forEach((line, idx) => {
        if (re.test(line)) {
          total += 1
          console.error(`${rel}:${idx + 1}: forbidden import pattern ${name}`)
        }
      })
    }
  }
  if (total === 0) {
    console.log('OK: charts lint rules clean.')
    process.exit(0)
  } else {
    console.error(`FAIL: ${total} charts-rule violations.`)
    process.exit(1)
  }
}

main().catch((err) => {
  console.error(err)
  process.exit(2)
})
