import { NextRequest, NextResponse } from 'next/server'

const FLASK = 'http://localhost:5001'

export async function DELETE(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string; imageId: string }> }
) {
  const { id, imageId } = await params
  try {
    const res = await fetch(`${FLASK}/api/products/${id}/images/${imageId}`, { method: 'DELETE' })
    const data = await res.json()
    if (!res.ok) return NextResponse.json(data, { status: res.status })
    return NextResponse.json(data)
  } catch (e) {
    console.error(e)
    return NextResponse.json({ error: 'Catalog service unavailable' }, { status: 502 })
  }
}
