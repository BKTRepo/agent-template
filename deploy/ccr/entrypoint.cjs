const { spawn } = require('node:child_process')
const { existsSync, mkdirSync, readFileSync, writeFileSync } = require('node:fs')
const { join } = require('node:path')
const { createInterface } = require('node:readline')

for (const name of ['CCR_UPSTREAM_OPENAI_BASE_URL', 'CCR_UPSTREAM_MODEL',
  'CCR_UPSTREAM_API_KEY', 'CCR_WEB_AUTH_TOKEN', 'CCR_PLATFORM_API_KEY']) {
  if (!process.env[name]?.trim()) {
    throw new Error(`Missing ${name}`)
  }
}

const configDirectory = join(process.env.HOME, '.claude-code-router')
const userDataDirectory = join(configDirectory, 'app-data')
const requestLogsEnabled = process.env.CCR_REQUEST_LOGS_ENABLED !== 'false'
const legacyConfig = join(configDirectory, 'config.json')
mkdirSync(configDirectory, { recursive: true, mode: 0o700 })
mkdirSync(userDataDirectory, { recursive: true, mode: 0o700 })
// CCR imports this configuration into SQLite on first boot. Keep subsequent UI changes.
if (!existsSync(legacyConfig) && !existsSync(join(configDirectory, 'config.sqlite'))) {
  const baseUrl = process.env.CCR_UPSTREAM_OPENAI_BASE_URL.replace(/\/+$/, '')
  const model = process.env.CCR_UPSTREAM_MODEL
  const config = {
    HOST: '0.0.0.0',
    PORT: 3456,
    gateway: { enabled: true, host: '0.0.0.0', port: 3456 },
    APIKEY: process.env.CCR_PLATFORM_API_KEY,
    Providers: [{
      name: 'intranet',
      api_base_url: `${baseUrl}/chat/completions`,
      api_key: process.env.CCR_UPSTREAM_API_KEY,
      models: [model],
      capabilities: [{ type: 'openai_chat_completions', baseUrl }],
    }],
    Router: { default: `intranet,${model}` },
    observability: { requestLogs: requestLogsEnabled },
  }
  writeFileSync(legacyConfig, JSON.stringify(config, null, 2) + '\n', { mode: 0o600 })
}

const databasePath = join(configDirectory, 'config.sqlite')
if (existsSync(databasePath)) {
  const Database = require('better-sqlite3')
  const database = new Database(databasePath)
  try {
    database.transaction(() => {
      const row = database.prepare('SELECT value_json FROM app_config WHERE key = ?').get('default')
      if (!row) throw new Error('CCR default configuration is missing')
      const config = JSON.parse(row.value_json)
      config.observability = { ...config.observability, requestLogs: requestLogsEnabled }
      database.prepare('UPDATE app_config SET value_json = ?, updated_at = ? WHERE key = ?')
        .run(JSON.stringify(config), new Date().toISOString(), 'default')
    }).immediate()
  } finally {
    database.close()
  }
} else {
  const config = JSON.parse(readFileSync(legacyConfig, 'utf8'))
  config.observability = { ...config.observability, requestLogs: requestLogsEnabled }
  writeFileSync(legacyConfig, JSON.stringify(config, null, 2) + '\n', { mode: 0o600 })
}

const server = spawn(process.execPath, [
  '/opt/ccr/node_modules/@musistudio/claude-code-router/dist/main/cli.js',
  'serve', '--host', '0.0.0.0', '--port', '3458', '--no-open',
], { stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, CCR_INTERNAL_USER_DATA_DIR: userDataDirectory } })
// The upstream CLI prints an authenticated browser URL during startup.
for (const [input, output] of [[server.stdout, process.stdout], [server.stderr, process.stderr]]) {
  createInterface({ input }).on('line', (line) => {
    output.write(line.replace(/([?&])ccr_web_token=[^&\s]+/g, '$1ccr_web_token=[redacted]') + '\n')
  })
}
for (const signal of ['SIGTERM', 'SIGINT']) {
  process.on(signal, () => server.kill(signal))
}
server.once('error', (error) => {
  console.error(error.message)
  process.exitCode = 1
})
server.once('exit', (code) => {
  process.exitCode = code ?? 1
})
