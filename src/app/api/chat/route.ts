import { NextRequest, NextResponse } from 'next/server'
import { fetch as undiciFetch, Agent } from 'undici'

// LLM with CPU offload can take 5+ minutes; use long timeouts so the client doesn't abort before Flask responds.
const CHAT_TIMEOUT_MS = 10 * 60 * 1000 // 10 minutes
const chatAgent = new Agent({
  headersTimeout: CHAT_TIMEOUT_MS,
  bodyTimeout: CHAT_TIMEOUT_MS,
  connectTimeout: 30_000,
})

export async function POST(request: NextRequest) {
  const startTime = Date.now()
  
  try {
    const { question } = await request.json()
    
    if (!question) {
      return NextResponse.json({ error: 'Question is required' }, { status: 400 })
    }

    console.log(`Processing question: "${question.substring(0, 50)}..."`)
    
    const flaskResponse = await undiciFetch('http://localhost:5001/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ question: question.trim() }),
      dispatcher: chatAgent,
    })
    
    if (!flaskResponse.ok) {
      const errorText = await flaskResponse.text()
      console.error(`Flask server error: ${flaskResponse.status} - ${errorText}`)
      throw new Error(`Flask server error: ${flaskResponse.status}`)
    }
    
    const flaskData = await flaskResponse.json() as {
      answer?: string
      cached?: boolean
      sources?: string[]
      image_refs?: string[]
      product_cards?: unknown[]
      debug_error?: string
    }
    const responseTime = Date.now() - startTime

    console.log(`Response generated in ${responseTime}ms`)

    const out: Record<string, unknown> = {
      answer: flaskData.answer ?? '',
      responseTime: responseTime,
      cached: flaskData.cached ?? false,
      sources: flaskData.sources ?? [],
      image_refs: flaskData.image_refs ?? [],
      product_cards: flaskData.product_cards ?? []
    }
    if (flaskData.debug_error) out.debug_error = flaskData.debug_error
    return NextResponse.json(out)
    
  } catch (error) {
    const responseTime = Date.now() - startTime
    console.error(`API error after ${responseTime}ms:`, error)
    
    const errorMessage = error instanceof Error ? error.message : 'Unknown error occurred'
    console.error('Detailed error:', errorMessage)
    
    return NextResponse.json({ 
      error: `Internal server error: ${errorMessage}`,
      responseTime 
    }, { status: 500 })
  }
} 