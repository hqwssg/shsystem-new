export default {
  resolve(...parts) {
    const result = []
    for (const path of parts) {
      if (path.startsWith('/')) result.length = 0
      for (const piece of path.split('/')) { if (piece === '..') result.pop(); else if (piece && piece !== '.') result.push(piece) }
    }
    return '/' + result.join('/')
  }
}
