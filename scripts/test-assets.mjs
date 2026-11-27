import {build} from 'esbuild'
import {spawnSync} from 'node:child_process'
import {mkdtemp, rm} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import path from 'node:path'

const directory = await mkdtemp(path.join(tmpdir(), 'znfwdd-asset-tests-'))
try {
  const outputs = []
  const storageSetup = "import { createRequire } from 'node:module'; const require = createRequire(import.meta.url); for (const key of ['localStorage','sessionStorage']) { const values = new Map(); Object.defineProperty(globalThis, key, { configurable: true, value: { getItem: name => values.get(name) ?? null, setItem: (name,value) => values.set(name,String(value)), removeItem: name => values.delete(name) } }); } globalThis.window = { localStorage: globalThis.localStorage };"
  const urlAssets = {name:'vite-url-assets', setup(builder) {
    builder.onResolve({filter:/\?url$/}, args => ({path:args.path, namespace:'url-asset'}))
    builder.onLoad({filter:/.*/, namespace:'url-asset'}, args => ({contents:`export default ${JSON.stringify(args.path)}`, loader:'js'}))
  }}
  for (const filename of ['asset-stages', 'asset-auth']) {
    const outfile = path.join(directory, `${filename}.mjs`)
    await build({entryPoints:[`tests/${filename}.test.mjs`], bundle:true, platform:'node', format:'esm', outfile,
      banner:{js:storageSetup}, plugins:[urlAssets], alias:{'@/lib/resourceStorage':path.resolve('tests/fixtures/resourceStorage.mjs')}})
    outputs.push(outfile)
  }
  const result = spawnSync(process.execPath, ['--test', ...outputs], {stdio:'inherit'})
  process.exitCode = result.status ?? 1
} finally {
  if (path.dirname(path.resolve(directory)) !== path.resolve(tmpdir()) || !path.basename(directory).startsWith('znfwdd-asset-tests-')) throw new Error('测试目录校验失败')
  await rm(directory, {recursive:true,force:true})
}
