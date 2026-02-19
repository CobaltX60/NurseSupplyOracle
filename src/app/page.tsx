'use client'

import { useState, useRef, useEffect } from 'react'

export interface ProductCard {
  id: number
  manufacturer_part_number: string
  product_name: string
  description: string
  secondary_description: string
  category: string
  page_number: number
  manufacturer: string
  image_refs: string[]
}

interface ChatMessage {
  id: string
  type: 'question' | 'answer'
  content: string
  timestamp: Date
  responseTime?: number
  cached?: boolean
  sources?: string[]
  image_refs?: string[]
  product_cards?: ProductCard[]
  debug_error?: string
}

export default function Home() {
  const [question, setQuestion] = useState('')
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loadingTime, setLoadingTime] = useState<number>(0)
  const [imagesPanelCleared, setImagesPanelCleared] = useState(false)
  const [zoomedImageUrl, setZoomedImageUrl] = useState<string | null>(null)
  const chatEndRef = useRef<HTMLDivElement>(null)

  // Side panel: prefer product cards from latest answer, then image_refs (unless user cleared)
  const panelProductCardsDerived = (() => {
    for (let i = chatHistory.length - 1; i >= 0; i--) {
      const msg = chatHistory[i]
      if (msg.type === 'answer' && msg.product_cards && msg.product_cards.length > 0)
        return msg.product_cards
    }
    return []
  })()
  const panelImagesDerived = (() => {
    for (let i = chatHistory.length - 1; i >= 0; i--) {
      const msg = chatHistory[i]
      if (msg.type === 'answer' && msg.image_refs && msg.image_refs.length > 0)
        return msg.image_refs
    }
    return []
  })()
  const panelProductCards = imagesPanelCleared ? [] : panelProductCardsDerived
  const panelImages = imagesPanelCleared ? [] : panelImagesDerived
  const showProductCards = panelProductCards.length > 0

  // Auto-scroll to bottom when new messages are added
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatHistory])

  const askQuestion = async () => {
    if (!question.trim()) return

    const currentQuestion = question.trim()
    const questionId = Date.now().toString()
    
    // Add question to chat history
    const questionMessage: ChatMessage = {
      id: questionId,
      type: 'question',
      content: currentQuestion,
      timestamp: new Date()
    }
    
    setChatHistory(prev => [...prev, questionMessage])
    setQuestion('')
    setLoading(true)
    setError(null)
    setLoadingTime(0)
    
    // Start loading timer
    const startTime = Date.now()
    const timer = setInterval(() => {
      setLoadingTime(Math.floor((Date.now() - startTime) / 1000))
    }, 1000)

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: currentQuestion })
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.error || 'Failed to get answer')
      }

      // Add answer to chat history (debug_error is set when backend returns Gemini exception details)
      const answerMessage: ChatMessage = {
        id: `${questionId}-answer`,
        type: 'answer',
        content: data.answer,
        timestamp: new Date(),
        responseTime: data.responseTime,
        cached: data.cached,
        sources: data.sources,
        image_refs: data.image_refs,
        product_cards: data.product_cards,
        debug_error: data.debug_error
      }
      
      setChatHistory(prev => [...prev, answerMessage])
      setImagesPanelCleared(false)
    } catch (err) {
      console.error('Frontend error:', err)
      const errorMessage = err instanceof Error ? err.message : 'An error occurred'
      setError(`Error: ${errorMessage}`)
    } finally {
      clearInterval(timer)
      setLoading(false)
      setLoadingTime(0)
    }
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      askQuestion()
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 p-4">
      <div className="max-w-6xl mx-auto">
        <header className="text-center mb-6">
          <h1 className="text-4xl font-bold text-gray-800 mb-2">
            Instrument Oracle
          </h1>
          <p className="text-gray-600">
            Ask questions about instruments and product data and get instant answers
          </p>
          <p className="mt-2">
            <a href="/catalog-setup" className="text-indigo-600 hover:underline text-sm font-medium">
              Catalog setup →
            </a>
          </p>
        </header>

        <main className="flex gap-4 flex-col lg:flex-row">
          {/* Left: Chat */}
          <div className="flex-1 min-w-0 bg-white rounded-lg shadow-lg p-6 flex flex-col">
          {/* Chat History */}
          <div className="flex-1 mb-4 max-h-[520px] overflow-y-auto border border-gray-200 rounded-lg p-4 bg-gray-50">
            {chatHistory.length === 0 ? (
              <div className="text-center text-gray-500 py-8">
                <svg className="mx-auto h-12 w-12 text-gray-400 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                </svg>
                <p>Start a conversation by asking a question below</p>
              </div>
            ) : (
              <div className="space-y-4">
                {chatHistory.map((message) => (
                  <div key={message.id} className={`flex ${message.type === 'question' ? 'justify-end' : 'justify-start'}`}>
                    <div className={`max-w-3xl ${message.type === 'question' ? 'bg-blue-600 text-white' : 'bg-white border border-gray-200'} rounded-lg p-3 shadow-sm`}>
                      <div className="text-sm font-medium mb-1">
                        {message.type === 'question' ? 'You' : 'Instrument Oracle'}
                      </div>
                      <div className={`whitespace-pre-wrap leading-relaxed ${message.type === 'question' ? 'text-white' : 'text-gray-700'}`}>
                        {message.content}
                      </div>
                      
                      {/* Show response metadata for answers */}
                      {message.type === 'answer' && (
                        <div className="mt-2 pt-2 border-t border-gray-200">
                          <div className="flex items-center space-x-2 text-xs text-gray-500">
                            {message.responseTime && (
                              <span className="bg-blue-100 text-blue-800 px-2 py-1 rounded">
                                {message.responseTime.toFixed(0)}ms
                              </span>
                            )}
                            {message.cached && (
                              <span className="bg-green-100 text-green-800 px-2 py-1 rounded">
                                Cached
                              </span>
                            )}
                          </div>
                          
                          {/* Backend debug error (when RETURN_CHAT_ERROR=1 and Gemini failed) */}
                          {message.type === 'answer' && message.debug_error && (
                            <div className="mt-2 p-2 bg-amber-50 border border-amber-200 rounded text-xs font-mono text-amber-900 break-all">
                              <strong>Server error:</strong> {message.debug_error}
                            </div>
                          )}
                          {/* Source Citation Section */}
                          {message.sources && message.sources.length > 0 && (
                            <div className="mt-2">
                              <div className="flex items-start">
                                <div className="flex-shrink-0">
                                  <svg className="h-4 w-4 text-gray-400 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                                  </svg>
                                </div>
                                <div className="ml-2">
                                  <h5 className="text-xs font-medium text-gray-600 mb-1">Sources:</h5>
                                  <div className="text-xs text-gray-500">
                                    {message.sources.map((source: string, index: number) => (
                                      <div key={index} className="mb-1">
                                        <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                                          {source}
                                        </span>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              </div>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
                
                {/* Loading indicator */}
                {loading && (
                  <div className="flex justify-start">
                    <div className="bg-white border border-gray-200 rounded-lg p-3 shadow-sm">
                      <div className="flex items-center space-x-2">
                        <svg className="animate-spin h-4 w-4 text-blue-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                        </svg>
                        <span className="text-sm text-gray-600">
                          Getting answer... {loadingTime > 0 && `(${loadingTime}s)`}
                        </span>
                      </div>
                    </div>
                  </div>
                )}
                
                <div ref={chatEndRef} />
              </div>
            )}
          </div>

          {/* Error Display */}
          {error && (
            <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg">
              <div className="flex">
                <div className="flex-shrink-0">
                  <svg className="h-5 w-5 text-red-400" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                  </svg>
                </div>
                <div className="ml-3">
                  <h3 className="text-sm font-medium text-red-800">Error</h3>
                  <div className="mt-2 text-sm text-red-700">{error}</div>
                </div>
              </div>
            </div>
          )}

          {/* Question Input */}
          <div>
            <label htmlFor="question" className="block text-sm font-medium text-gray-700 mb-2">
              Ask a question about instruments or product data:
            </label>
            <textarea
              id="question"
              className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"
              rows={2}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder="Type your question here... (Press Enter to submit)"
              disabled={loading}
            />
            <div className="mt-3 flex justify-between items-center flex-wrap gap-2">
              <div className="flex items-center space-x-4">
                <button
                  className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  onClick={askQuestion}
                  disabled={loading || !question.trim()}
                >
                  {loading ? (
                    <span className="flex items-center">
                      <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                      </svg>
                      Processing...
                    </span>
                  ) : (
                    'Ask Question'
                  )}
                </button>
              </div>
              <div className="flex items-center space-x-2">
                {chatHistory.length > 0 && (
                  <button
                    type="button"
                    className="px-4 py-2 text-gray-600 hover:text-gray-800 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    onClick={() => { setChatHistory([]); setImagesPanelCleared(true); setError(null); }}
                    disabled={loading}
                  >
                    Clear chat
                  </button>
                )}
                {question && (
                  <button
                    className="px-4 py-2 text-gray-600 hover:text-gray-800 transition-colors"
                    onClick={() => setQuestion('')}
                    disabled={loading}
                  >
                    Clear
                  </button>
                )}
              </div>
            </div>
          </div>
          </div>

          {/* Right: Product cards or catalog images */}
          <div className="w-full lg:w-80 xl:w-96 flex-shrink-0 bg-white rounded-lg shadow-lg border border-gray-200 overflow-hidden flex flex-col">
            <div className="px-4 py-3 border-b border-gray-200 bg-gray-50 flex items-center justify-between gap-2">
              <div>
                <h2 className="text-sm font-semibold text-gray-700">
                  {showProductCards ? 'Product information' : 'Catalog images'}
                </h2>
                <p className="text-xs text-gray-500 mt-0.5">From the latest response · Click any image to zoom</p>
              </div>
              {(panelProductCardsDerived.length > 0 || panelImagesDerived.length > 0) && (
                <button
                  type="button"
                  onClick={() => setImagesPanelCleared(true)}
                  className="flex-shrink-0 px-2 py-1.5 text-xs font-medium text-gray-600 hover:text-gray-800 bg-white border border-gray-300 rounded hover:bg-gray-50 transition-colors"
                >
                  Clear
                </button>
              )}
            </div>
            <div className="flex-1 overflow-y-auto p-3 min-h-[200px]">
              {showProductCards ? (
                <div className="space-y-4">
                  {panelProductCards.map((card: ProductCard) => (
                    <article key={card.id} className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
                      <div className="p-3 space-y-2">
                        {card.image_refs.length > 0 && (
                          <div className="flex flex-wrap justify-center gap-1">
                            {card.image_refs.map((ref: string, i: number) => (
                              <button
                                key={i}
                                type="button"
                                onClick={() => setZoomedImageUrl(ref)}
                                className="block w-32 h-32 rounded border border-gray-200 overflow-hidden bg-gray-50 hover:border-blue-400 hover:ring-2 ring-blue-200 focus:outline-none focus:ring-2 focus:ring-blue-400"
                                title="Click to zoom"
                              >
                                <img src={ref} alt="" className="w-full h-full object-contain" />
                              </button>
                            ))}
                          </div>
                        )}
                        <div>
                          <span className="text-xs font-medium text-gray-500">Part number</span>
                          <p className="text-sm font-semibold text-gray-900">{card.manufacturer_part_number || '—'}</p>
                        </div>
                        {card.product_name && (
                          <div>
                            <span className="text-xs font-medium text-gray-500">Product name</span>
                            <p className="text-sm text-gray-700">{card.product_name}</p>
                          </div>
                        )}
                        {card.description && (
                          <div>
                            <span className="text-xs font-medium text-gray-500">Description</span>
                            <p className="text-xs text-gray-600 whitespace-pre-wrap">{card.description}</p>
                          </div>
                        )}
                        {card.secondary_description && (
                          <div>
                            <span className="text-xs font-medium text-gray-500">Secondary description</span>
                            <p className="text-xs text-gray-600 whitespace-pre-wrap">{card.secondary_description}</p>
                          </div>
                        )}
                        {card.category && (
                          <div>
                            <span className="text-xs font-medium text-gray-500">Category</span>
                            <p className="text-xs text-gray-700">{card.category}</p>
                          </div>
                        )}
                        {(card.manufacturer || card.page_number != null) && (
                          <div className="flex flex-wrap gap-3 text-xs">
                            {card.manufacturer && (
                              <div>
                                <span className="font-medium text-gray-500">Manufacturer</span>
                                <p className="text-gray-700">{card.manufacturer}</p>
                              </div>
                            )}
                            {card.page_number != null && (
                              <div>
                                <span className="font-medium text-gray-500">Page</span>
                                <p className="text-gray-700">{card.page_number}</p>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    </article>
                  ))}
                </div>
              ) : panelImages.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full min-h-[200px] text-gray-400 text-center px-4">
                  <svg className="h-12 w-12 mb-2 opacity-60" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                  </svg>
                  <p className="text-sm">No images yet</p>
                  <p className="text-xs mt-1">Product cards or images from your answers will appear here</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {panelImages.map((ref: string, index: number) => (
                    <div key={index} className="rounded-lg border border-gray-200 overflow-hidden bg-gray-50 hover:border-blue-300 hover:shadow transition-colors">
                      <button
                        type="button"
                        onClick={() => setZoomedImageUrl(ref)}
                        className="block w-full text-left focus:outline-none focus:ring-2 focus:ring-blue-400 rounded-lg"
                        title="Click to zoom"
                      >
                        <img src={ref} alt={`Catalog ${index + 1}`} className="w-full h-auto object-contain max-h-64 cursor-zoom-in" />
                      </button>
                      <a href={ref} target="_blank" rel="noopener noreferrer" className="block text-center py-1 text-xs text-gray-500 hover:text-gray-700">Open in new tab</a>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </main>

        {/* Image zoom modal */}
        {zoomedImageUrl && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70"
            onClick={() => setZoomedImageUrl(null)}
            role="dialog"
            aria-modal="true"
            aria-label="Zoomed image"
          >
            <button
              type="button"
              onClick={() => setZoomedImageUrl(null)}
              className="absolute top-4 right-4 z-10 p-2 rounded-full bg-white/90 text-gray-700 hover:bg-white shadow-lg focus:outline-none focus:ring-2 focus:ring-blue-400"
              aria-label="Close zoom"
            >
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
            </button>
            <img
              src={zoomedImageUrl}
              alt="Zoomed"
              className="max-w-[90vw] max-h-[90vh] w-auto h-auto object-contain rounded shadow-2xl"
              onClick={(e) => e.stopPropagation()}
            />
          </div>
        )}

        <footer className="mt-8 text-center text-gray-500 text-sm">
          <p>Powered by Next.js, FAISS, and Google Gemini</p>
        </footer>
      </div>
    </div>
  )
}
