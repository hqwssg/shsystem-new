import { readFile, mkdir, writeFile } from 'node:fs/promises'
import { resolve, join } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

export function planPanoramaRepair(storage, canonical, restoreLayout = false, mapOnly = false) {
  if (!Array.isArray(storage?.componentList)) throw new Error('Project has no component list')
  const required = ['dash-map-001', 'dash-3d-001', 'dash-line-001', 'dash-pie-001', 'dash-table-001', 'dash-kpi-001']
  const byId = new Map(storage.componentList.map(item => [item.id, item]))
  if (byId.size !== storage.componentList.length) throw new Error('Duplicate component IDs; manual inspection required')
  for (const id of required) {
    const reference = canonical.componentList.find(item => item.id === id)
    if (!byId.has(id) || byId.get(id).key !== reference?.key) throw new Error(`This is not the supported panorama: ${id}`)
  }
  const output = structuredClone(storage), changes = []
  for (const component of output.componentList) {
    if (mapOnly && component.id !== 'dash-map-001') continue
    const reference = canonical.componentList.find(item => item.id === component.id)
    if (!reference) continue // User-added components stay intact.
    if (component.key !== reference.key) throw new Error(`Component type changed: ${component.id}`)
    const before = JSON.stringify(component)
    const dataset = component.option?.dataset
    component.option = { ...component.option, ...structuredClone(reference.option) }
    // Preserve route geometry, project text, and saved data. Runtime bindings provide live values.
    if (dataset !== undefined) component.option.dataset = structuredClone(dataset)
    if (['dash-line-001', 'dash-pie-001', 'dash-3d-001'].includes(component.id)) {
      const previous = component.request || {}, params = previous.requestParams || {}
      component.request = {
        ...previous, ...structuredClone(reference.request),
        requestParams: { ...params, Header: params.Header || {}, Body: params.Body || {},
          Params: { ...params.Params, ...reference.request.requestParams.Params } }
      }
      component.filter = reference.filter
    }
    if (restoreLayout) component.attr = structuredClone(reference.attr)
    if (JSON.stringify(component) !== before) changes.push(component.id)
  }
  if (restoreLayout && !mapOnly) {
    output.editCanvasConfig.width = canonical.editCanvasConfig.width
    output.editCanvasConfig.height = canonical.editCanvasConfig.height
  }
  return { output, changes, restoreLayout, mapOnly }
}

export async function repairProject(options, request = fetch) {
  const { base, id, headers = {}, canonical, apply = false, backupDir, restoreLayout = false, mapOnly = false } = options
  if (!/^https?:\/\//.test(base || '') || !/^\d+$/.test(id || '')) throw new Error('Explicit API base and numeric project ID required')
  if (apply && (!backupDir || !Object.keys(headers).length)) throw new Error('Apply requires an explicit backup directory and existing login credentials')
  const getProject = async () => {
    const response = await request(`${base.replace(/\/$/, '')}/project/getData?projectId=${encodeURIComponent(id)}`, { headers })
    const body = await response.json()
    if (!response.ok || body.code !== 200 || !body.data?.content) throw new Error(`Read project failed: ${response.status}/${body.code}`)
    return body.data
  }
  const project = await getProject()
  const original = typeof project.content === 'string' ? JSON.parse(project.content) : project.content
  const plan = planPanoramaRepair(original, canonical, restoreLayout, mapOnly)
  if (!apply) return { projectId: id, mode: 'READ_ONLY', changes: plan.changes, restoreLayout, mapOnly }
  await mkdir(backupDir, { recursive: true })
  const backup = join(backupDir, `panorama-${id}-${Date.now()}.json`)
  await writeFile(backup, JSON.stringify(project, null, 2) + '\n', { encoding: 'utf8', mode: 0o600, flag: 'wx' })
  const latest = await getProject()
  if (JSON.stringify(latest.content) !== JSON.stringify(project.content)) throw new Error(`Project changed during inspection; nothing written. Backup: ${backup}`)
  const form = new FormData()
  form.append('projectId', id); form.append('content', JSON.stringify(plan.output))
  const response = await request(`${base.replace(/\/$/, '')}/project/save/data`, { method: 'POST', headers, body: form })
  const result = await response.json()
  if (!response.ok || result.code !== 200) throw new Error(`Save failed; backup retained: ${backup}`)
  const saved = await getProject()
  const actual = typeof saved.content === 'string' ? JSON.parse(saved.content) : saved.content
  if (JSON.stringify(actual) !== JSON.stringify(plan.output)) throw new Error(`Saved content verification failed; inspect before retrying. Backup: ${backup}`)
  return { projectId: id, mode: 'APPLIED_AND_VERIFIED', changes: plan.changes, restoreLayout, mapOnly, backup }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const args = process.argv.slice(2)
  if (args.includes('--help')) {
    console.log('Node18+. GOVIEW_API_BASE + --project-id <id>. Default is read-only. --map-only aligns only railway visual options, preserving other components. --apply --backup-dir <private directory> writes after backup and concurrent-edit check. --restore-layout also restores template positions. Credentials: GOVIEW_AUTHORIZATION or explicit GOVIEW_TOKEN_NAME/GOVIEW_TOKEN_VALUE. --template <json> overrides the bundled canonical template.')
  } else {
    try {
      const value = flag => args.includes(flag) ? args[args.indexOf(flag) + 1] : undefined
      const env = process.env
      const headers = env.GOVIEW_AUTHORIZATION ? { Authorization: env.GOVIEW_AUTHORIZATION }
        : env.GOVIEW_TOKEN_NAME && env.GOVIEW_TOKEN_VALUE ? { [env.GOVIEW_TOKEN_NAME]: env.GOVIEW_TOKEN_VALUE } : {}
      const bundled = new URL('../../goview/go-view-master-fetch/public/templates/shuohuang-carbon-dashboard.json', import.meta.url)
      const canonical = JSON.parse(await readFile(value('--template') || fileURLToPath(bundled), 'utf8'))
      console.log(JSON.stringify(await repairProject({ base: env.GOVIEW_API_BASE, id: value('--project-id'), headers, canonical,
        apply: args.includes('--apply'), backupDir: value('--backup-dir'), restoreLayout: args.includes('--restore-layout'), mapOnly: args.includes('--map-only') }), null, 2))
    } catch (error) { console.error(error.message); process.exitCode = 1 }
  }
}
