import { build } from 'esbuild'
import { spawnSync } from 'node:child_process'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
const directory = await mkdtemp(path.join(tmpdir(), 'znfwdd-tests-'))
try {
  const outputs = []
  for (const filename of ['skill-client', 'frontend-integration', 'realtime-debug']) {
    const outfile = path.join(directory, `${filename}.mjs`)
    const storageSetup = "for (const key of ['localStorage','sessionStorage']) { const values = new Map(); Object.defineProperty(globalThis, key, { configurable: true, value: { getItem: name => values.get(name) ?? null, setItem: (name,value) => values.set(name,String(value)), removeItem: name => values.delete(name) } }); } globalThis.window = { localStorage: globalThis.localStorage };"
    await build({ entryPoints: [`tests/${filename}.test.mjs`], bundle: true, platform: 'node', format: 'esm', outfile, banner: { js: storageSetup }, alias: filename !== 'skill-client' ? { '@/lib/resourceStorage': path.resolve('tests/fixtures/resourceStorage.mjs') } : {} })
    outputs.push(outfile)
  }
  const result = spawnSync(process.execPath, ['--test', 'tests/skill-form.test.mjs', ...outputs], { stdio: 'inherit' })
  process.exitCode = result.status ?? 1
} finally {
  const resolved = path.resolve(directory)
  if (path.dirname(resolved) !== path.resolve(tmpdir()) || !path.basename(resolved).startsWith('znfwdd-tests-')) throw new Error('测试临时目录校验失败')
  await rm(resolved, { recursive: true, force: true })
}
