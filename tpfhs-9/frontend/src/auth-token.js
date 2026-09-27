const TOKEN_KEY = 'Admin-Token'

let runtimeToken = null
const pendingResolvers = []

function decodeToken(value) {
  if (!value) return null
  try {
    return decodeURIComponent(value)
  } catch (error) {
    return value
  }
}

export function readAuthToken() {
  const cookie = document.cookie
    .split(';')
    .map(item => item.trim())
    .find(item => item.startsWith(`${TOKEN_KEY}=`))
  if (cookie) {
    return decodeToken(cookie.slice(TOKEN_KEY.length + 1))
  }

  for (const storage of [window.localStorage, window.sessionStorage]) {
    try {
      const value = storage.getItem(TOKEN_KEY)
      if (value) return decodeToken(value)
    } catch (error) {
      // Storage can be unavailable when the model is opened in a restricted iframe.
    }
  }
  return null
}

export function getAuthToken() {
  return readAuthToken() || runtimeToken
}

export function setAuthToken(token) {
  runtimeToken = token ? decodeToken(token) : null
  if (runtimeToken) {
    while (pendingResolvers.length) pendingResolvers.shift()(runtimeToken)
  }
}

export function requestAuthToken(timeout = 1500) {
  const current = getAuthToken()
  if (current) return Promise.resolve(current)
  if (window.parent === window) return Promise.resolve(null)

  return new Promise(resolve => {
    let settled = false
    const finish = token => {
      if (settled) return
      settled = true
      resolve(token || null)
    }
    pendingResolvers.push(finish)
    const parentOrigin = document.referrer ? new URL(document.referrer).origin : '*'
    window.parent.postMessage({ type: 'carbon:request-auth-token' }, parentOrigin)
    window.setTimeout(() => {
      const index = pendingResolvers.indexOf(finish)
      if (index >= 0) pendingResolvers.splice(index, 1)
      finish(null)
    }, timeout)
  })
}

