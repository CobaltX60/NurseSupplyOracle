import { NextRequest, NextResponse } from 'next/server'

const FLASK = 'http://localhost:5001'

// Per-page build runs LLM extraction (slow on large/dense pages). Watch Flask server console for progress:
// [Build listing] page=N — loaded chunks / running LLM extraction / LLM done / DB write done
const PAGE_TIMEOUT_MS = 10 * 60 * 1000 // 10 minutes per page

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string; page: string }> }
) {
  const { id, page } = await params
  const pageNumber = parseInt(page, 10)
  if (Number.isNaN(pageNumber) || pageNumber < 1) {
    return NextResponse.json({ error: 'Invalid page number', created: 0, page_number: pageNumber, errors: [] }, { status: 400 })
  }
  try {
    const body = await request.json().catch(() => ({}))
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), PAGE_TIMEOUT_MS)
    const res = await fetch(`${FLASK}/api/catalogs/${id}/build-product-listing/page/${pageNumber}`, {
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
        error: isTimeout ? 'Page build timed out' : 'Catalog service unavailable',
        created: 0,
        page_number: pageNumber,
        errors: [],
      },
      { status: 502 }
    )
  }
}
