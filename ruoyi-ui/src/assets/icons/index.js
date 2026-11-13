const source = import.meta.glob('./svg/*.svg', { query: '?raw', import: 'default', eager: true })
const sprite = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
sprite.setAttribute('aria-hidden', 'true')
sprite.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden'
sprite.innerHTML = Object.entries(source).map(([path, svg]) => {
  const name = path.split('/').pop().replace(/\.svg$/, '')
  return svg.replace(/<\?xml[^>]*>/g, '').replace(/<!DOCTYPE[^>]*>/g, '').replace(/<svg\b/, `<symbol id="icon-${name}"`).replace(/<\/svg>\s*$/, '</symbol>')
}).join('')
document.body.prepend(sprite)
