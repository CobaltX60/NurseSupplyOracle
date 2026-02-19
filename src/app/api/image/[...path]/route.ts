import { NextRequest, NextResponse } from 'next/server'

const FLASK_BASE = 'http://localhost:5001'

// Log backend-unavailable only once per process to avoid spamming when many images fail
let _loggedBackendDown = false
function logBackendDownOnce(e: unknown) {
  if (_loggedBackendDown) return
  _loggedBackendDown = true
  const msg = e instanceof Error ? e.message : String(e)
  const cause = e instanceof Error && e.cause ? (e.cause as { code?: string }) : undefined
  console.warn(
    `[Image proxy] Backend unreachable (${cause?.code ?? msg}). ` +
      'Start the Flask server: python scripts/chat_server.py'
  )
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params
  const pathSegments = path.join('/')
  const url = `${FLASK_BASE}/api/image/${pathSegments}`

  try {
    const res = await fetch(url)
    if (!res.ok) {
      return new NextResponse(res.statusText, { status: res.status })
    }
    const contentType = res.headers.get('content-type') || 'application/octet-stream'
    const blob = await res.blob()
    return new NextResponse(blob, {
      headers: { 'Content-Type': contentType },
    })
  } catch (e) {
    const isRefused =
      e instanceof Error &&
      e.cause != null &&
      typeof (e.cause as { code?: string }).code === 'string' &&
      ((e.cause as { code: string }).code === 'ECONNREFUSED' ||
        (e.cause as { code: string }).code === 'ECONNRESET')
    if (isRefused) {
      logBackendDownOnce(e)
      return new NextResponse('Backend unavailable. Start: python scripts/chat_server.py', {
        status: 503,
        headers: { 'Content-Type': 'text/plain' },
      })
    }
    if (!_loggedBackendDown) console.error('Image proxy error:', e)
    return new NextResponse('Image unavailable', { status: 502 })
  }
}
