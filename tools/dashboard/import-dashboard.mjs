import { readFile } from 'node:fs/promises'
import { pathToFileURL } from 'node:url'
import { resolve } from 'node:path'

// Creates a new GoView draft using the target environment's existing login.
// It never publishes or overwrites an existing project.
export async function importDashboard({ base, template, headers }, request = fetch) {
  if (!base || !headers || !Object.keys(headers).length) {
    throw new Error('API base and explicit login credentials are required')
  }
  if (!Array.isArray(template?.componentList) || !template?.editCanvasConfig?.projectName) {
    throw new Error('Invalid GoView template')
  }
  const storage = structuredClone(template)
  const post = async (path, body) => {
    const form = body instanceof FormData
    const response = await request(base.replace(/\/$/, '') + path, {
      method: 'POST',
      headers: form ? headers : { 'Content-Type': 'application/json', ...headers },
      body: form ? body : JSON.stringify(body)
    })
    const result = await response.json()
    if (!response.ok || result.code !== 200) {
      throw new Error(`${path} failed (${response.status}/${result.code})`)
    }
    return result.data
  }

  const project = await post('/project/create', {
    projectName: storage.editCanvasConfig.projectName,
    remarks: storage.editCanvasConfig.remarks || 'Imported dashboard template',
    indexImage: null
  })
  if (!project?.id || (typeof project.id === 'number' && !Number.isSafeInteger(project.id))) {
    throw new Error('Missing or unsafe project ID; inspect the newly created draft before retrying')
  }
  const id = String(project.id)
  storage.editCanvasConfig.projectId = id
  const body = new FormData()
  body.append('projectId', id)
  body.append('content', JSON.stringify(storage))
  try {
    await post('/project/save/data', body)
  } catch {
    throw new Error(`Draft ${id} was created but content save failed; inspect this draft before retrying`)
  }
  return id
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  if (process.argv.includes('--help')) {
    console.log('Node 18+. Set GOVIEW_API_BASE and GOVIEW_AUTHORIZATION (Bearer ...), or GOVIEW_TOKEN_NAME/GOVIEW_TOKEN_VALUE for legacy login. Run: node import-dashboard.mjs <template.json>')
  } else {
    try {
      if (!process.argv[2]) throw new Error('Template path required; use --help')
      const env = process.env
      const headers = env.GOVIEW_AUTHORIZATION
        ? { Authorization: env.GOVIEW_AUTHORIZATION }
        : env.GOVIEW_TOKEN_NAME && env.GOVIEW_TOKEN_VALUE
          ? { [env.GOVIEW_TOKEN_NAME]: env.GOVIEW_TOKEN_VALUE }
          : {}
      const template = JSON.parse(await readFile(process.argv[2], 'utf8'))
      const id = await importDashboard({ base: env.GOVIEW_API_BASE, template, headers })
      console.log(`Created new draft: ${id}`)
      console.log(`Editor path: /#/chart/home/${id}`)
      console.log('Preview and publish through the target environment UI.')
    } catch (error) {
      console.error(error.message)
      process.exitCode = 1
    }
  }
}
