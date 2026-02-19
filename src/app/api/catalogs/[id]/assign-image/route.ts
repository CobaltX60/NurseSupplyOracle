import { NextRequest, NextResponse } from 'next/server'

const FLASK = 'http://localhost:5001'

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params
  try {
    const body = await request.json()
    const res = await fetch(`${FLASK}/api/catalogs/${id}/assign-image`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const data = await res.json()
    if (!res.ok) return NextResponse.json(data, { status: res.status })
    return NextResponse.json(data, { status: 200 })
  } catch (e) {
    console.error(e)
    return NextResponse.json({ error: 'Catalog service unavailable' }, { status: 502 })
  }
}
