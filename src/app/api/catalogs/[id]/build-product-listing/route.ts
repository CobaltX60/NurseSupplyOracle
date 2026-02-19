import { NextRequest, NextResponse } from 'next/server'

const FLASK = 'http://localhost:5001'

// Build product listing runs the LLM on every page; can take several minutes for large catalogs.
const BUILD_LISTING_TIMEOUT_MS = 10 * 60 * 1000 // 10 minutes

export const maxDuration = 600 // seconds (10 min) for Vercel/serverless

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params
  try {
    const body = await request.json().catch(() => ({}))
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), BUILD_LISTING_TIMEOUT_MS)
    const res = await fetch(`${FLASK}/api/catalogs/${id}/build-product-listing`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
    clearTimeout(timeoutId)
    const data = await res.json()
    if (!res.ok) return NextResponse.json(data, { status: res.status })
    return NextResponse.json(data)
  } catch (e) {
    console.error(e)
    const isTimeout = e instanceof Error && (e.name === 'AbortError' || e.message?.includes('abort'))
    return NextResponse.json(
      {
        error: isTimeout
          ? 'Build product listing timed out. Try again or run on a smaller catalog.'
          : 'Catalog service unavailable',
        created: 0,
        pages_processed: 0,
        errors: [],
      },
      { status: 502 }
    )
  }
}
