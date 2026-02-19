import { NextRequest, NextResponse } from 'next/server'

const FLASK = 'http://localhost:5001'

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params
  const format = request.nextUrl.searchParams.get('format') || 'json'
  try {
    const res = await fetch(`${FLASK}/api/catalogs/${id}/products/export?format=${format}`)
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      return NextResponse.json(data, { status: res.status })
    }
    const contentType = res.headers.get('content-type') || (format === 'csv' ? 'text/csv' : 'application/json')
    const disposition = res.headers.get('content-disposition')
    const body = await res.arrayBuffer()
    const headers = new Headers()
    headers.set('Content-Type', contentType)
    if (disposition) headers.set('Content-Disposition', disposition)
    return new NextResponse(body, { status: 200, headers })
  } catch (e) {
    console.error(e)
    return NextResponse.json({ error: 'Catalog service unavailable' }, { status: 502 })
  }
}
