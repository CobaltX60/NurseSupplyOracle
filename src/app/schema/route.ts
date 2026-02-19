import { NextResponse } from 'next/server'

/**
 * GET /schema — minimal response for clients that request a schema (e.g. dev tools).
 * Instrument Oracle does not expose an OpenAPI/schema; this avoids 404s.
 */
export async function GET() {
  return NextResponse.json({
    name: 'instrument-oracle',
    version: '0.1.0',
    chat: { method: 'POST', path: '/api/chat', body: { question: 'string' } },
  })
}
