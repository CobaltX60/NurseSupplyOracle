'use client'

import { useState, useRef, useEffect } from 'react'

interface ChatMessage {
  id: string
  type: 'question' | 'answer'
  content: string
  timestamp: Date
  responseTime?: number
  cached?: boolean
  sources?: string[]
}

export default function Home() {
  const [question, setQuestion] = useState('')
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loadingTime, setLoadingTime] = useState<number>(0)
  const chatEndRef = useRef<HTMLDivElement>(null)

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

      // Add answer to chat history
      const answerMessage: ChatMessage = {
        id: `${questionId}-answer`,
        type: 'answer',
        content: data.answer,
        timestamp: new Date(),
        responseTime: data.responseTime,
        cached: data.cached,
        sources: data.sources
      }
      
      setChatHistory(prev => [...prev, answerMessage])
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
      <div className="max-w-4xl mx-auto">
        <header className="text-center mb-8">
          <h1 className="text-4xl font-bold text-gray-800 mb-2">
            Nurse Supply Oracle
          </h1>
          <p className="text-gray-600">
            Ask questions about your nursing textbook content and get instant answers
          </p>
        </header>

        <main className="bg-white rounded-lg shadow-lg p-6">
          {/* Chat History */}
          <div className="mb-6 max-h-[600px] overflow-y-auto border border-gray-200 rounded-lg p-4 bg-gray-50">
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
                        {message.type === 'question' ? 'You' : 'Nurse Supply Oracle'}
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
                          Processing with GPU... {loadingTime > 0 && `(${loadingTime}s)`}
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
            <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg">
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
          <div className="mb-6">
            <label htmlFor="question" className="block text-sm font-medium text-gray-700 mb-2">
              Ask a question about your nursing textbook:
            </label>
            <textarea
              id="question"
              className="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"
              rows={3}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder="Type your nursing question here... (Press Enter to submit)"
              disabled={loading}
            />
            <div className="mt-3 flex justify-between items-center">
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
        </main>

        <footer className="mt-8 text-center text-gray-500 text-sm">
          <p>Powered by Next.js, FAISS, and local LLM</p>
        </footer>
      </div>
    </div>
  )
}
