import { readFile, writeFile } from 'node:fs/promises'
import { buildPanoramaDemo } from '../src/assets/dashboard/panoramaDemo.mjs'

const route = JSON.parse(await readFile(new URL('../src/packages/components/Charts/Maps/RailwayCarbonMap/data.json', import.meta.url), 'utf8'))
const snapshot = buildPanoramaDemo(route.points.points.map(point => point.name))
const target = new URL('../src/assets/dashboard/panorama-demo.json', import.meta.url)
const content = JSON.stringify(snapshot, null, 2) + '\n'
if (process.argv.includes('--check')) {
  if (await readFile(target, 'utf8') !== content) throw new Error('Demo snapshot is stale; run npm run dashboard:panorama:demo:init')
  console.log('Demo snapshot verified; no files or database modified.')
} else {
  await writeFile(target, content)
  console.log(`Presentation demo initialized: ${snapshot.rank.length} stations, 3 years × 12 months. No database writes.`)
}
