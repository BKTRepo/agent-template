// 由后端WRQ测试进程启动；不读写用户浏览器会话，不把Token写入报告。
import { build } from 'esbuild'
import { readFile } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'
import path from 'node:path'

const configPath = process.argv[2]
if (!configPath) throw new Error('缺少本轮后端生成的测试配置')
const config = JSON.parse(await readFile(configPath, 'utf8'))
const target = new URL(config.base)
if (target.hostname !== '127.0.0.1') throw new Error('测试服务必须绑定127.0.0.1')
const storage = "for(const key of ['localStorage','sessionStorage']){const values=new Map();Object.defineProperty(globalThis,key,{configurable:true,value:{getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,String(v)),removeItem:k=>values.delete(k)}})}globalThis.window={localStorage:globalThis.localStorage};"
await build({entryPoints:['tests/debug-cloud-lifecycle.mjs'],bundle:true,platform:'node',format:'esm',
  outfile:config.bundleFile,banner:{js:storage},
  alias:{'@/lib/resourceStorage':path.resolve('tests/fixtures/resourceStorage.mjs')}})
const child = spawnSync(process.execPath,[config.bundleFile,configPath],{stdio:'inherit'})
process.exitCode = child.status ?? 1
