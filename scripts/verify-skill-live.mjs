import { build } from 'esbuild'
import { spawnSync } from 'node:child_process'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'

const directory = await mkdtemp(path.join(tmpdir(), 'znfwdd-live-'))
try {
  const outfile = path.join(directory, 'verify.mjs')
  const storageSetup = "for (const key of ['localStorage','sessionStorage']) { const values = new Map(); globalThis[key] = { getItem: name => values.get(name) ?? null, setItem: (name,value) => values.set(name,String(value)), removeItem: name => values.delete(name) }; }"
  await build({ entryPoints: ['tests/skill-live-integration.mjs'], bundle: true, platform: 'node', format: 'esm', outfile, banner: { js: storageSetup } })
  const result = spawnSync(process.execPath, [outfile], { stdio: 'inherit', env: { ...process.env, SKILL_VERIFY_OUTPUT_DIR: path.resolve('../agent-template/output/skill-no-knowledge-integration') } })
  process.exitCode = result.status ?? 1
} finally {
  const resolved = path.resolve(directory)
  if (path.dirname(resolved) !== path.resolve(tmpdir()) || !path.basename(resolved).startsWith('znfwdd-live-')) throw new Error('测试临时目录校验失败')
  await rm(resolved, { recursive: true, force: true })
}
