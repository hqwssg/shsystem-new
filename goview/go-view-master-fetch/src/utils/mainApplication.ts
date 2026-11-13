export const mainApplicationUrl = () => {
  const configured = String(import.meta.env.VITE_CARBON_MAIN_URL || '').trim()
  if (configured) return configured.replace(/\/$/, '') + '/'

  try {
    const referrer = document.referrer ? new URL(document.referrer) : null
    if (referrer && referrer.origin !== window.location.origin) return `${referrer.origin}/`
  } catch {
    // Fall through to the known local/production port mapping.
  }

  const targetPort = window.location.port === '53231' ? '53221' : window.location.port === '3000' ? '8080' : ''
  return `${window.location.protocol}//${window.location.hostname}${targetPort ? `:${targetPort}` : ''}/`
}
