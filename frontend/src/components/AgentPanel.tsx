/**
 * AgentPanel — real conversational /agent/ask integration
 * Full Liquid-Glass visual treatment: backdrop blur, specular highlight,
 * SVG edge-refraction filter, chromatic fringing, glass bubbles.
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

// ── Known option sets for structured choice buttons ────────────────────────
const FIELD_OPTIONS: Record<string, { label: string; value: string }[]> = {
  age_group: [
    { label: '👶 Child', value: 'child' },
    { label: '🧑 Adult', value: 'adult' },
    { label: '🧓 Elderly', value: 'elderly' },
  ],
  condition: [
    { label: '✅ None', value: 'none' },
    { label: '🫁 Respiratory', value: 'respiratory' },
    { label: '❤️ Cardiac', value: 'cardiac' },
  ],
  activity: [
    { label: '😴 Rest', value: 'rest' },
    { label: '🚶 Moderate', value: 'moderate' },
    { label: '🏃 Vigorous', value: 'vigorous' },
  ],
}

// ── Suggestion pills ───────────────────────────────────────────────────────
const SUGGESTIONS = [
  { label: 'Quiet walk', query: 'Find me a quiet park for a 30-minute walk' },
  { label: 'Best time to run', query: 'When is the cleanest time to run today?' },
  { label: 'Family outing', query: 'Is it safe for my child to play outside?' },
]

// ── Send icon (lucide-style inline SVG, no import needed) ──────────────────
function SendIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <line x1="22" y1="2" x2="11" y2="13" />
      <polygon points="22 2 15 22 11 13 2 9 22 2" />
    </svg>
  )
}

// ── Component ──────────────────────────────────────────────────────────────
export function AgentPanel() {
  const [sessionId] = useState<string>(() => uuidv4())
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [lastResponse, setLastResponse] = useState<AgentAskResponse | null>(null)
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

        setMessages((prev) => [...prev.filter((m) => m.id !== 'typing'), agentMsg])
        setLastResponse(data)
      } catch {
        const errMsg: ChatMessage = {
          id: uuidv4(),
          role: 'agent',
          text: "Sorry — I couldn't reach the air quality network right now. Please try again in a moment.",
        }
        setMessages((prev) => [...prev.filter((m) => m.id !== 'typing'), errMsg])
        setLastResponse(null)
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

  // Derive which structured choice buttons to show (if any)
  const choiceField =
    lastResponse?.status === 'clarifying'
      ? (lastResponse.missing_fields ?? []).find((f) => f in FIELD_OPTIONS) ?? null
      : null
  const choiceOptions = choiceField ? FIELD_OPTIONS[choiceField] : []

  const isEmpty = messages.length === 0

  return (
    <>
      {/* ── SVG filter for edge refraction (feDisplacementMap) ── */}
      <svg width="0" height="0" style={{ position: 'absolute', overflow: 'hidden' }} aria-hidden="true">
        <defs>
          <filter id="glass-refract" x="-5%" y="-5%" width="110%" height="110%" colorInterpolationFilters="sRGB">
            {/* Turbulence creates the warping texture */}
            <feTurbulence
              type="fractalNoise"
              baseFrequency="0.65 0.68"
              numOctaves="1"
              seed="3"
              result="noise"
            />
            {/* Displacement warps the card's backdrop by ~2.5px max */}
            <feDisplacementMap
              in="SourceGraphic"
              in2="noise"
              scale="2.5"
              xChannelSelector="R"
              yChannelSelector="G"
              result="displaced"
            />
            <feComposite in="displaced" in2="SourceGraphic" operator="in" />
          </filter>
        </defs>
      </svg>

      <style>{`
        /* ══════════════════════════════════════════════════════════════
           AGENT PANEL — FULL LIQUID GLASS
        ══════════════════════════════════════════════════════════════ */
        .agent-panel-lg {
          position: relative;
          isolation: isolate;
          overflow: hidden;

          /* Larger padding (~35% more than before) */
          padding: 36px 34px 30px;

          border-radius: 24px;
          border: 1px solid rgba(255,255,255,.72);
          align-self: center;

          /* ── 1. Glass base: real blur-through ── */
          background: rgba(255,255,255,.50);
          backdrop-filter: blur(22px) saturate(1.6);
          -webkit-backdrop-filter: blur(22px) saturate(1.6);

          /* Depth + chromatic edge fringing */
          box-shadow:
            0 24px 48px rgba(50,90,110,.10),
            0 8px 20px rgba(50,90,110,.06),
            /* ── 4. Faint chromatic dispersion — barely-there color fringing ── */
            inset 0 0 0 0.5px rgba(92,190,235,.045),   /* blue left */
            inset 0 0 0 0.5px rgba(220,120,190,.032),  /* pink right */
            /* ── 2. Specular highlight: concentrated white at TOP edge ── */
            inset 0 1px 0 rgba(255,255,255,.96),
            inset 0 2px 18px rgba(255,255,255,.22),
            inset 0 4px 32px rgba(255,255,255,.08);
        }

        /* ── 2. Specular highlight layer — top-left radial catch-light ── */
        .agent-panel-lg::before {
          content: '';
          position: absolute;
          inset: 0;
          z-index: 0;
          border-radius: inherit;
          pointer-events: none;
          background:
            radial-gradient(ellipse 72% 36% at 38% -4%, rgba(255,255,255,.72) 0%, transparent 70%),
            linear-gradient(120deg, rgba(255,255,255,.48) 0%, rgba(255,255,255,.12) 22%, transparent 50%);
          mix-blend-mode: screen;
        }

        /* ── 3. Edge refraction ring — applies SVG filter to the perimeter ── */
        .agent-panel-lg::after {
          content: '';
          position: absolute;
          inset: -1px;
          z-index: 0;
          border-radius: inherit;
          pointer-events: none;
          filter: url('#glass-refract');
          /* Refraction only visible at the edge — mask interior */
          background:
            linear-gradient(rgba(255,255,255,.055), rgba(255,255,255,.055));
          opacity: 0.6;
        }

        .agent-panel-lg > * { position: relative; z-index: 1; }

        /* ── Header ── */
        .agent-panel-head {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding-bottom: 22px;
          border-bottom: 1px solid rgba(129,160,174,.20);
          margin-bottom: 22px;
        }

        .agent-panel-head strong {
          display: block;
          font-size: 20px;
          font-weight: 700;
          color: #17324d;
          letter-spacing: -.03em;
          line-height: 1.1;
        }

        .agent-panel-head .agent-subtitle {
          display: block;
          margin-top: 3px;
          font-size: 14px;
          color: #7190a1;
          font-weight: 400;
          letter-spacing: -.005em;
        }

        .agent-online {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: #42cfc0;
          box-shadow: 0 0 0 2px rgba(66,207,192,.22);
          flex-shrink: 0;
          transition: background .3s;
        }

        /* ── Suggestion pills ── */
        .agent-suggestions {
          display: flex;
          gap: 8px;
          margin-bottom: 20px;
          flex-wrap: wrap;
        }

        .agent-suggestions button {
          padding: 9px 16px;
          color: #36566b;
          border: 1px solid rgba(129,160,174,.32);
          border-radius: 100px;
          background: rgba(255,255,255,.55);
          backdrop-filter: blur(8px);
          -webkit-backdrop-filter: blur(8px);
          font-size: 15px;
          font-weight: 500;
          cursor: pointer;
          transition: background .18s, border-color .18s, color .18s, transform .12s;
        }

        .agent-suggestions button:hover {
          color: #17324d;
          background: rgba(255,255,255,.82);
          border-color: rgba(66,207,192,.50);
          transform: translateY(-1px);
        }

        /* ── Empty state ── */
        .agent-empty-state {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 12px;
          padding: 28px 0 24px;
          user-select: none;
          pointer-events: none;
          animation: fade-in-up 0.4s cubic-bezier(.2,.8,.2,1) both;
        }

        .agent-empty-icon {
          width: 62px;
          height: 62px;
          border-radius: 50%;
          background: linear-gradient(135deg, rgba(66,207,192,.18), rgba(66,207,192,.06));
          border: 1px solid rgba(66,207,192,.26);
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 30px;
          animation: float-bob 3s ease-in-out infinite;
          /* Subtle glass on the icon orb too */
          backdrop-filter: blur(8px);
          -webkit-backdrop-filter: blur(8px);
        }

        .agent-empty-label {
          font-size: 16px;
          color: #7190a1;
          font-style: italic;
          text-align: center;
          line-height: 1.55;
          margin: 0;
        }

        @keyframes float-bob {
          0%, 100% { transform: translateY(0); }
          50%       { transform: translateY(-5px); }
        }

        @keyframes fade-in-up {
          from { opacity: 0; transform: translateY(8px); }
          to   { opacity: 1; transform: translateY(0); }
        }

        /* ── Chat thread ── */
        .agent-thread {
          display: flex;
          flex-direction: column;
          gap: 11px;
          max-height: 300px;
          overflow-y: auto;
          margin: 0 0 16px;
          padding-right: 4px;
          scrollbar-width: thin;
          scrollbar-color: rgba(66,207,192,.25) transparent;
        }

        /* ── Structured choice buttons ── */
        .agent-choices {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          margin-bottom: 12px;
          animation: fade-in-up 0.28s cubic-bezier(.2,.8,.2,1) both;
        }

        .agent-choice-label {
          width: 100%;
          font-size: 11px;
          font-weight: 700;
          letter-spacing: .06em;
          text-transform: uppercase;
          color: #42cfc0;
          margin-bottom: 2px;
        }

        .agent-choice-btn {
          padding: 8px 16px;
          border-radius: 100px;
          border: 1.5px solid rgba(66,207,192,.40);
          background: rgba(255,255,255,.52);
          backdrop-filter: blur(8px);
          -webkit-backdrop-filter: blur(8px);
          color: #1d6e65;
          font-size: 14px;
          font-weight: 500;
          cursor: pointer;
          transition: background 0.18s, border-color 0.18s, transform 0.12s;
          white-space: nowrap;
        }

        .agent-choice-btn:hover {
          background: rgba(66,207,192,.18);
          border-color: rgba(66,207,192,.70);
          transform: translateY(-1px);
        }

        .agent-choice-btn:active {
          transform: translateY(0) scale(.97);
        }

        /* ── Bubbles — glass treatment ── */
        @keyframes bubble-in {
          from { opacity: 0; transform: translateY(6px) scale(.98); }
          to   { opacity: 1; transform: translateY(0)   scale(1);   }
        }

        .chat-bubble {
          animation: bubble-in 0.22s cubic-bezier(.2,.8,.2,1) both;
          max-width: 88%;
          font-size: 14px;
          line-height: 1.65;
          padding: 12px 16px;
          border-radius: 16px;
          word-break: break-word;
        }

        /* User bubble — lighter glass */
        .chat-bubble.user {
          align-self: flex-end;
          border-radius: 16px 16px 5px 16px;
          background: rgba(255,255,255,.72);
          backdrop-filter: blur(12px) saturate(1.3);
          -webkit-backdrop-filter: blur(12px) saturate(1.3);
          border: 1px solid rgba(255,255,255,.80);
          color: #17324d;
          box-shadow:
            0 4px 14px rgba(65,126,151,.09),
            inset 0 1px 0 rgba(255,255,255,.92);
        }

        /* Agent bubble — teal-tinted glass */
        .chat-bubble.agent {
          align-self: flex-start;
          border-radius: 5px 16px 16px 16px;
          background: rgba(220,248,245,.55);
          backdrop-filter: blur(12px) saturate(1.4);
          -webkit-backdrop-filter: blur(12px) saturate(1.4);
          border: 1px solid rgba(66,207,192,.28);
          border-left: 2px solid #42cfc0;
          color: #1e4555;
          box-shadow:
            0 4px 14px rgba(66,207,192,.08),
            inset 0 1px 0 rgba(255,255,255,.60);
        }

        /* ── Typing indicator ── */
        .typing-indicator {
          align-self: flex-start;
          display: flex;
          align-items: center;
          gap: 5px;
          padding: 12px 16px;
          border-radius: 5px 16px 16px 16px;
          background: rgba(220,248,245,.50);
          backdrop-filter: blur(10px);
          -webkit-backdrop-filter: blur(10px);
          border: 1px solid rgba(66,207,192,.22);
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

        /* ── Composer ── */
        .agent-composer {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 8px 8px 8px 18px;
          border: 1px solid rgba(129,160,174,.32);
          border-radius: 100px;
          background: rgba(255,255,255,.52);
          backdrop-filter: blur(10px);
          -webkit-backdrop-filter: blur(10px);
          box-shadow: inset 0 1px 0 rgba(255,255,255,.80);
          transition: border-color .2s, box-shadow .2s;
        }

        .agent-composer:focus-within {
          border-color: rgba(66,207,192,.55);
          box-shadow:
            inset 0 1px 0 rgba(255,255,255,.80),
            0 0 0 3px rgba(66,207,192,.10);
        }

        .agent-composer input {
          flex: 1;
          border: 0;
          outline: 0;
          background: transparent;
          color: #17324d;
          font-size: 16px;
          font-family: inherit;
          min-width: 0;
        }

        .agent-composer input::placeholder {
          color: #8aabbf;
          font-size: 16px;
        }

        /* ── Send button — 44px circle, hover scale+shadow ── */
        .agent-send-btn {
          flex-shrink: 0;
          width: 44px;
          height: 44px;
          border-radius: 50%;
          border: 0;
          background: #42cfc0;
          color: #17324d;
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          transition:
            transform .18s cubic-bezier(.2,.8,.2,1),
            box-shadow .18s,
            background .18s,
            opacity .18s;
          box-shadow: 0 4px 12px rgba(66,207,192,.28);
        }

        .agent-send-btn:hover:not(:disabled) {
          transform: scale(1.09);
          box-shadow: 0 8px 22px rgba(66,207,192,.42);
          background: #38c4b5;
        }

        .agent-send-btn:active:not(:disabled) {
          transform: scale(.96);
          box-shadow: 0 2px 8px rgba(66,207,192,.22);
        }

        .agent-send-btn:disabled {
          opacity: .40;
          cursor: default;
          box-shadow: none;
        }
      `}</style>

      <div className="agent-panel agent-panel-lg">
        {/* Header */}
        <div className="agent-panel-head">
          <div>
            <strong>Hawa</strong>
            <span className="agent-subtitle">
              {isLoading ? 'Thinking…' : 'Ready when you are'}
            </span>
          </div>
          <span
            className="agent-online"
            aria-label={isLoading ? 'Thinking' : 'Online'}
            style={{ background: isLoading ? '#f4a261' : undefined }}
          />
        </div>

        {/* Suggestion pills — only when thread is empty */}
        {isEmpty && (
          <div className="agent-suggestions">
            {SUGGESTIONS.map((s) => (
              <button key={s.label} onClick={() => handleSuggestion(s.query)}>
                {s.label}
              </button>
            ))}
          </div>
        )}

        {/* Empty state illustration — replaces blank space when no messages */}
        {isEmpty && (
          <div className="agent-empty-state" aria-hidden="true">
            <div className="agent-empty-icon">🌬️</div>
            <p className="agent-empty-label">
              Ask me anything to get started —<br />
              air quality, best time to head out, or safe spots nearby.
            </p>
          </div>
        )}

        {/* Chat thread — only rendered when there are messages */}
        {!isEmpty && (
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
        )}

        {/* Structured choice buttons for known-option clarifying fields */}
        {choiceOptions.length > 0 && !isLoading && (
          <div className="agent-choices" role="group" aria-label={`Choose ${choiceField}`}>
            <span className="agent-choice-label">Quick answer:</span>
            {choiceOptions.map((opt) => (
              <button
                key={opt.value}
                className="agent-choice-btn"
                onClick={() => sendMessage(opt.value)}
                aria-label={`Answer: ${opt.label}`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        )}

        {/* Composer */}
        <form className="agent-composer" onSubmit={handleSubmit}>
          <input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={choiceOptions.length > 0 ? 'Or type a custom answer…' : 'Ask anything about going outside…'}
            aria-label="Ask HawaGuide"
            disabled={isLoading}
          />
          <button
            type="submit"
            className="agent-send-btn"
            aria-label="Send question"
            disabled={isLoading || !input.trim()}
          >
            <SendIcon />
          </button>
        </form>
      </div>
    </>
  )
}
