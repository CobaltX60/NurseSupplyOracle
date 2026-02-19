import { NextRequest, NextResponse } from 'next/server'

const FLASK = 'http://localhost:5001'

export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params
  try {
    const res = await fetch(`${FLASK}/api/catalogs/${id}/build-product-listing/clear`, { method: 'POST' })
    const data = await res.json()
    if (!res.ok) return NextResponse.json(data, { status: res.status })
    return NextResponse.json(data)
  } catch (e) {
    console.error(e)
    return NextResponse.json({ ok: false, error: 'Catalog service unavailable' }, { status: 502 })
  }
}
