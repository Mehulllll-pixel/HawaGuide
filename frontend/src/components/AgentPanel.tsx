/**
 * AgentPanel — real conversational /agent/ask integration
 * Liquid-glass visual treatment matching the hero widgets.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

// ── UUID helper (no external dep) ──────────────────────────────────────────
function uuidv4(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16)
  })
}

// ── Types ──────────────────────────────────────────────────────────────────
interface AgentAskResponse {
  session_id: string
  status: 'clarifying' | 'complete'
  message: string
  missing_fields: string[]
  extraction_degraded: boolean
  recommendation: Record<string, unknown> | null
  disclaimer: string
}

type MessageRole = 'user' | 'agent' | 'typing'

interface ChatMessage {
  id: string
  role: MessageRole
  text: string
}

// ── Suggestion pills ───────────────────────────────────────────────────────
const SUGGESTIONS = [
  { label: 'Quiet walk', query: 'Find me a quiet park for a 30-minute walk' },
  { label: 'Best time to run', query: 'When is the cleanest time to run today?' },
  { label: 'Family outing', query: 'Is it safe for my child to play outside?' },
]

// ── Component ──────────────────────────────────────────────────────────────
export function AgentPanel() {
  const [sessionId] = useState<string>(() => uuidv4())
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Auto-scroll to latest message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const sendMessage = useCallback(
    async (text: string) => {
      const trimmed = text.trim()
      if (!trimmed || isLoading) return

      const userMsg: ChatMessage = { id: uuidv4(), role: 'user', text: trimmed }
      const typingMsg: ChatMessage = { id: 'typing', role: 'typing', text: '' }

      setMessages((prev) => [...prev, userMsg, typingMsg])
      setInput('')
      setIsLoading(true)

      try {
        const res = await fetch('/agent/ask', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: sessionId, message: trimmed }),
        })

        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data: AgentAskResponse = await res.json()

        const agentMsg: ChatMessage = {
          id: uuidv4(),
          role: 'agent',
          text: data.message,
        }

        // Replace the typing placeholder with the real response
        setMessages((prev) => [...prev.filter((m) => m.id !== 'typing'), agentMsg])
      } catch {
        const errMsg: ChatMessage = {
          id: uuidv4(),
          role: 'agent',
          text: 'Sorry — I couldn\'t reach the air quality network right now. Please try again in a moment.',
        }
        setMessages((prev) => [...prev.filter((m) => m.id !== 'typing'), errMsg])
      } finally {
        setIsLoading(false)
        inputRef.current?.focus()
      }
    },
    [sessionId, isLoading],
  )

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    sendMessage(input)
  }

  function handleSuggestion(query: string) {
    setInput(query)
    inputRef.current?.focus()
  }

  return (
    <>
      <style>{`
        /* ── Agent panel — liquid glass, same recipe as glass-widget ── */
        .agent-panel-lg {
          position: relative;
          isolation: isolate;
          overflow: hidden;
          padding: 26px;
          border: 1px solid rgba(255,255,255,.64);
          border-radius: 19px;
          background: rgba(255,255,255,.70);
          backdrop-filter: blur(16px) saturate(1.62);
          -webkit-backdrop-filter: blur(16px) saturate(1.62);
          box-shadow:
            0 20px 40px rgba(0,0,0,.08),
            0 28px 60px rgba(67,106,127,.10),
            inset 0 1px 0 rgba(255,255,255,.52),
            inset 1px 0 0 rgba(108,174,224,.035),
            inset -1px 0 0 rgba(223,133,190,.03);
          align-self: center;
        }

        .agent-panel-lg::before {
          content: '';
          position: absolute;
          inset: -1px;
          z-index: -1;
          border-radius: inherit;
          background: rgba(255,255,255,.43);
          backdrop-filter: blur(24px) saturate(1.62);
          -webkit-backdrop-filter: blur(24px) saturate(1.62);
          filter: url('#liquid-glass-edge');
        }

        .agent-panel-lg::after {
          content: '';
          position: absolute;
          inset: 0;
          z-index: 0;
          border-radius: inherit;
          pointer-events: none;
          background: linear-gradient(116deg, rgba(255,255,255,.46), rgba(255,255,255,.12) 23%, transparent 54%);
          box-shadow:
            inset 0 1px 0 rgba(255,255,255,.92),
            inset 0 2px 10px rgba(255,255,255,.18),
            inset 1px 0 0 rgba(114,188,235,.04),
            inset -1px 0 0 rgba(218,131,196,.035);
          mix-blend-mode: screen;
        }

        .agent-panel-lg > * { position: relative; z-index: 1; }

        /* ── Chat thread ── */
        .agent-thread {
          display: flex;
          flex-direction: column;
          gap: 10px;
          min-height: 120px;
          max-height: 280px;
          overflow-y: auto;
          margin: 16px 0 14px;
          padding-right: 4px;
          scrollbar-width: thin;
          scrollbar-color: rgba(66,207,192,.25) transparent;
        }

        .agent-thread:empty::before {
          content: 'Ask me anything about air quality, parks, or when to head out…';
          display: block;
          color: #9ab5c2;
          font-size: 12px;
          font-style: italic;
          padding: 12px 0;
        }

        /* ── Bubbles ── */
        @keyframes bubble-in {
          from { opacity: 0; transform: translateY(6px) scale(.98); }
          to   { opacity: 1; transform: translateY(0)   scale(1);   }
        }

        .chat-bubble {
          animation: bubble-in 0.22s cubic-bezier(.2,.8,.2,1) both;
          max-width: 88%;
          font-size: 12.5px;
          line-height: 1.6;
          padding: 10px 13px;
          border-radius: 14px;
          word-break: break-word;
        }

        .chat-bubble.user {
          align-self: flex-end;
          border-radius: 14px 14px 4px 14px;
          background: rgba(255,255,255,.82);
          border: 1px solid rgba(129,160,174,.22);
          color: #17324d;
          box-shadow: 0 3px 10px rgba(65,126,151,.07);
        }

        .chat-bubble.agent {
          align-self: flex-start;
          border-radius: 4px 14px 14px 14px;
          background: rgba(66,207,192,.12);
          border: 1px solid rgba(66,207,192,.22);
          border-left: 2px solid #42cfc0;
          color: #24485a;
        }

        /* ── Typing indicator ── */
        .typing-indicator {
          align-self: flex-start;
          display: flex;
          align-items: center;
          gap: 5px;
          padding: 10px 14px;
          border-radius: 4px 14px 14px 14px;
          background: rgba(66,207,192,.10);
          border: 1px solid rgba(66,207,192,.18);
          border-left: 2px solid #42cfc0;
          animation: bubble-in 0.22s cubic-bezier(.2,.8,.2,1) both;
        }

        @keyframes breathe-dot {
          0%, 100% { opacity: .3; transform: scaleY(.7); }
          50%       { opacity: .9; transform: scaleY(1.1); }
        }

        .typing-dot {
          width: 5px;
          height: 5px;
          border-radius: 50%;
          background: #42cfc0;
          animation: breathe-dot 1.4s ease-in-out infinite;
        }
        .typing-dot:nth-child(2) { animation-delay: .18s; }
        .typing-dot:nth-child(3) { animation-delay: .36s; }
      `}</style>

      <div className="agent-panel agent-panel-lg">
        {/* Header */}
        <div className="agent-panel-head">
          <span className="agent-avatar">∿</span>
          <div>
            <strong>Hawa</strong>
            <span>{isLoading ? 'Thinking…' : 'Ready when you are'}</span>
          </div>
          <span className="agent-online" style={{ background: isLoading ? '#f4a261' : undefined }} />
        </div>

        {/* Suggestion pills — only when thread is empty */}
        {messages.length === 0 && (
          <div className="agent-suggestions">
            {SUGGESTIONS.map((s) => (
              <button key={s.label} onClick={() => handleSuggestion(s.query)}>
                {s.label}
              </button>
            ))}
          </div>
        )}

        {/* Chat thread */}
        <div className="agent-thread" role="log" aria-live="polite" aria-label="Conversation with Hawa">
          {messages.map((msg) =>
            msg.role === 'typing' ? (
              <div key="typing" className="typing-indicator" aria-label="Hawa is thinking">
                <span className="typing-dot" />
                <span className="typing-dot" />
                <span className="typing-dot" />
              </div>
            ) : (
              <div key={msg.id} className={`chat-bubble ${msg.role}`}>
                {msg.text}
              </div>
            ),
          )}
          <div ref={bottomRef} />
        </div>

        {/* Composer */}
        <form className="agent-composer" onSubmit={handleSubmit}>
          <input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask anything about going outside…"
            aria-label="Ask HawaGuide"
            disabled={isLoading}
          />
          <button type="submit" aria-label="Send question" disabled={isLoading || !input.trim()}>
            ↗
          </button>
        </form>
      </div>
    </>
  )
}
