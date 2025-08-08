import { NextRequest, NextResponse } from 'next/server'

export async function POST(request: NextRequest) {
  const startTime = Date.now()
  
  try {
    const { question } = await request.json()
    
    if (!question) {
      return NextResponse.json({ error: 'Question is required' }, { status: 400 })
    }

    console.log(`Processing question: "${question.substring(0, 50)}..."`)
    
    // Send request to Flask server
    const flaskResponse = await fetch('http://localhost:5001/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ question: question.trim() })
    })
    
    if (!flaskResponse.ok) {
      const errorText = await flaskResponse.text()
      console.error(`Flask server error: ${flaskResponse.status} - ${errorText}`)
      throw new Error(`Flask server error: ${flaskResponse.status}`)
    }
    
    const flaskData = await flaskResponse.json()
    const responseTime = Date.now() - startTime
    
    console.log(`Response generated in ${responseTime}ms`)
    
    return NextResponse.json({
      answer: flaskData.answer,
      responseTime: responseTime,
      cached: flaskData.cached || false,
      sources: flaskData.sources || []
    })
    
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