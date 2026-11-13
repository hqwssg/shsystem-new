// API rejections have already been presented by the shared request interceptor.
// Catch only the request boundary; component/programming errors remain visible.
export async function requestResult(promise) {
  try { return { ok: true, response: await promise } } catch (error) { return { ok: false, error } }
}
