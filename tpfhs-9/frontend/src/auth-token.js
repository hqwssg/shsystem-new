const TOKEN_KEY = 'Admin-Token'

let runtimeToken = null

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
}

