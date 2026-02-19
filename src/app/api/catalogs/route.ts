import { NextResponse } from 'next/server'

const FLASK = 'http://localhost:5001'

export async function GET() {
  try {
    const res = await fetch(`${FLASK}/api/catalogs`)
    const data = await res.json()
    if (!res.ok) return NextResponse.json(data, { status: res.status })
    return NextResponse.json(data)
  } catch (e) {
    console.error(e)
    return NextResponse.json({ error: 'Catalog service unavailable' }, { status: 502 })
  }
}
