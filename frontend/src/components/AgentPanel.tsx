/**
 * AgentPanel — real conversational /agent/ask integration
 * Full Liquid-Glass visual treatment: backdrop blur, specular highlight,
 * SVG edge-refraction filter, chromatic fringing, glass bubbles.
 * Includes localStorage profile memory & reset support.
 * Clean line icons only — no decorative emojis.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { MapPickerModal, reverseGeocodeNominatim } from './MapPickerModal'

// ── Storage key ────────────────────────────────────────────────────────────
const PROFILE_STORAGE_KEY = 'hawaguide_profile'

export interface SavedUserProfile {
  age_group: 'adult' | 'child' | 'elderly'
  conditions: string[]
  smoker: boolean
  planned_activity: 'rest' | 'moderate' | 'vigorous'
}

export function loadSavedProfile(): SavedUserProfile | null {
  try {
    const raw = localStorage.getItem(PROFILE_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (
      parsed &&
      ['adult', 'child', 'elderly'].includes(parsed.age_group) &&
      Array.isArray(parsed.conditions) &&
      typeof parsed.smoker === 'boolean' &&
      ['rest', 'moderate', 'vigorous'].includes(parsed.planned_activity)
    ) {
      return parsed as SavedUserProfile
    }
    return null
  } catch {
    return null
  }
}

export function saveProfileToStorage(profile: SavedUserProfile): void {
  try {
    localStorage.setItem(PROFILE_STORAGE_KEY, JSON.stringify(profile))
  } catch {
    // Storage unavailable
  }
}

export function clearSavedProfile(): void {
  try {
    localStorage.removeItem(PROFILE_STORAGE_KEY)
  } catch {
    // Storage unavailable
  }
}

export function formatProfileSummary(p: SavedUserProfile): string {
  const age = p.age_group.charAt(0).toUpperCase() + p.age_group.slice(1)
  const cond =
    p.conditions.length === 0 || p.conditions.includes('none')
      ? 'No conditions'
      : p.conditions
          .map((c) => c.charAt(0).toUpperCase() + c.slice(1))
          .join(', ')
  const smoke = p.smoker ? 'Smoker' : 'Non-smoker'
  const act = p.planned_activity.charAt(0).toUpperCase() + p.planned_activity.slice(1)
  return `${age} · ${cond} · ${smoke} · ${act}`
}

// ── UUID helper ────────────────────────────────────────────────────────────
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
  collected_profile?: Partial<SavedUserProfile> | null
  disclaimer: string
}

type MessageRole = 'user' | 'agent' | 'typing'

interface ChatMessage {
  id: string
  role: MessageRole
  text: string
}

// ── Known option sets for structured choice buttons (No emojis — clean text) ─
const FIELD_OPTIONS: Record<string, { label: string; value: string }[]> = {
  conditions: [
    { label: 'None', value: 'none' },
    { label: 'Asthma', value: 'asthma' },
    { label: 'Cardiac', value: 'cardiac' },
  ],
  condition: [
    { label: 'None', value: 'none' },
    { label: 'Asthma', value: 'asthma' },
    { label: 'Cardiac', value: 'cardiac' },
  ],
  smoker: [
    { label: 'Non-smoker', value: 'no' },
    { label: 'Smoker', value: 'yes' },
  ],
  planned_activity: [
    { label: 'Rest', value: 'rest' },
    { label: 'Moderate', value: 'moderate' },
    { label: 'Vigorous', value: 'vigorous' },
  ],
  activity: [
    { label: 'Rest', value: 'rest' },
    { label: 'Moderate', value: 'moderate' },
    { label: 'Vigorous', value: 'vigorous' },
  ],
}

// ── Suggestion pills ───────────────────────────────────────────────────────
const SUGGESTIONS = [
  { label: 'Quiet walk', query: 'Find me a quiet park for a 30-minute walk' },
  { label: 'Best time to run', query: 'When is the cleanest time to run today?' },
  { label: 'Family outing', query: 'Is it safe for my child to play outside?' },
]

// ── Line Icons (Lucide style) ──────────────────────────────────────────────
function UserLineIcon() {
  return (
    <svg
      width="13"
      height="13"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  )
}

function CrosshairLineIcon() {
  return (
    <svg
      width="15"
      height="15"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="10" />
      <line x1="22" y1="12" x2="18" y2="12" />
      <line x1="6" y1="12" x2="2" y2="12" />
      <line x1="12" y1="6" x2="12" y2="2" />
      <line x1="12" y1="22" x2="12" y2="18" />
    </svg>
  )
}

function MapLineIcon() {
  return (
    <svg
      width="15"
      height="15"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <polygon points="3 6 9 3 15 6 21 3 21 18 15 21 9 18 3 21" />
      <line x1="9" y1="3" x2="9" y2="18" />
      <line x1="15" y1="6" x2="15" y2="21" />
    </svg>
  )
}

function SpinnerLineIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="spin-animate"
      aria-hidden="true"
    >
      <path d="M21 12a9 9 0 1 1-6.219-8.56" />
    </svg>
  )
}

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
  const [sessionId, setSessionId] = useState<string>(() => uuidv4())
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [lastResponse, setLastResponse] = useState<AgentAskResponse | null>(null)
  
  // Saved profile memory state
  const [savedProfile, setSavedProfile] = useState<SavedUserProfile | null>(() => loadSavedProfile())
  const [resetNotice, setResetNotice] = useState<string | null>(null)

  // Location selector state
  const [isLocating, setIsLocating] = useState(false)
  const [locationNotice, setLocationNotice] = useState<string | null>(null)
  const [isMapOpen, setIsMapOpen] = useState(false)

  // Greeting typewriter state
  const [greetingText, setGreetingText] = useState('')
  const [isGreetingDone, setIsGreetingDone] = useState(false)

  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Derive initial greeting based on whether a saved profile exists
  const initialGreeting = savedProfile
    ? `Hi, I'm Hawa. Using your saved profile (${formatProfileSummary(savedProfile)}). To give you the best recommendation, I just need to know how long you'll be outside and your location.`
    : "Hi, I'm Hawa. To give you the best recommendation, I'll need to know your age, any health conditions, and your location."

  // Proactive greeting typewriter effect
  useEffect(() => {
    let charIdx = 0
    const charSpeed = 30 // ms per character
    setGreetingText('')
    setIsGreetingDone(false)

    const interval = setInterval(() => {
      charIdx++
      if (charIdx <= initialGreeting.length) {
        setGreetingText(initialGreeting.slice(0, charIdx))
      } else {
        setIsGreetingDone(true)
        clearInterval(interval)
      }
    }, charSpeed)

    return () => clearInterval(interval)
  }, [initialGreeting, sessionId])

  // Auto-scroll to latest message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, greetingText, lastResponse, resetNotice])

  const sendMessage = useCallback(
    async (text: string) => {
      const trimmed = text.trim()
      if (!trimmed || isLoading) return

      const userMsg: ChatMessage = { id: uuidv4(), role: 'user', text: trimmed }
      const typingMsg: ChatMessage = { id: 'typing', role: 'typing', text: '' }

      setMessages((prev) => [...prev, userMsg, typingMsg])
      setInput('')
      setIsLoading(true)
      setLocationNotice(null)
      setResetNotice(null)

      try {
        const payload: Record<string, unknown> = {
          session_id: sessionId,
          message: trimmed,
        }

        // Attach saved profile if available
        if (savedProfile) {
          payload.profile = savedProfile
        }

        const res = await fetch('/agent/ask', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
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

        // Save collected profile to localStorage if all fields are gathered
        if (data.collected_profile) {
          const cp = data.collected_profile
          if (
            cp.age_group &&
            Array.isArray(cp.conditions) &&
            typeof cp.smoker === 'boolean' &&
            cp.planned_activity
          ) {
            const completeProf = cp as SavedUserProfile
            setSavedProfile(completeProf)
            saveProfileToStorage(completeProf)
          }
        }
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
    [sessionId, isLoading, savedProfile],
  )

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    sendMessage(input)
  }

  function handleSuggestion(query: string) {
    setInput(query)
    inputRef.current?.focus()
  }

  // Handle resetting profile
  const handleResetProfile = () => {
    clearSavedProfile()
    setSavedProfile(null)
    setSessionId(uuidv4())
    setMessages([])
    setLastResponse(null)
    setResetNotice('Saved profile cleared. Starting fresh with all questions!')
    setTimeout(() => {
      setResetNotice(null)
    }, 4000)
    inputRef.current?.focus()
  }

  // Geolocation handler
  const handleUseCurrentLocation = useCallback(() => {
    if (!navigator.geolocation) {
      setLocationNotice('Geolocation is not supported by your browser.')
      return
    }

    setIsLocating(true)
    setLocationNotice(null)

    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const { latitude, longitude } = pos.coords
        const readablePlace = await reverseGeocodeNominatim(latitude, longitude)
        setIsLocating(false)
        sendMessage(readablePlace)
      },
      (err) => {
        setIsLocating(false)
        if (err.code === err.PERMISSION_DENIED) {
          setLocationNotice('Location access was denied. You can pick your spot on the map or type your location below.')
        } else {
          setLocationNotice('Unable to retrieve location. Please pick on the map or type your area below.')
        }
      },
      {
        enableHighAccuracy: true,
        timeout: 9000,
        maximumAge: 60000,
      },
    )
  }, [sendMessage])

  // Derive active field
  const activeMissingField =
    lastResponse?.status === 'clarifying'
      ? lastResponse.missing_fields?.[0] ?? null
      : null
  
  const isLocationActive = activeMissingField === 'location'

  const choiceOptions =
    activeMissingField && !isLocationActive && FIELD_OPTIONS[activeMissingField]
      ? FIELD_OPTIONS[activeMissingField]
      : []

  const hasUserSentMessage = messages.some((m) => m.role === 'user')

  return (
    <>
      {/* ── SVG filter for edge refraction ── */}
      <svg width="0" height="0" style={{ position: 'absolute', overflow: 'hidden' }} aria-hidden="true">
        <defs>
          <filter id="glass-refract" x="-5%" y="-5%" width="110%" height="110%" colorInterpolationFilters="sRGB">
            <feTurbulence
              type="fractalNoise"
              baseFrequency="0.65 0.68"
              numOctaves="1"
              seed="3"
              result="noise"
            />
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

      {/* ── Leaflet Delhi Map Picker Modal ── */}
      <MapPickerModal
        isOpen={isMapOpen}
        onClose={() => setIsMapOpen(false)}
        onSelectLocation={(locStr) => {
          sendMessage(locStr)
        }}
      />

      <style>{`
        /* ══════════════════════════════════════════════════════════════
           AGENT PANEL — FULL LIQUID GLASS
        ══════════════════════════════════════════════════════════════ */
        .agent-panel-lg {
          position: relative;
          isolation: isolate;
          overflow: hidden;
          padding: 34px 32px 28px;
          border-radius: 24px;
          border: 1px solid rgba(255,255,255,.72);
          align-self: center;

          background: rgba(255,255,255,.50);
          backdrop-filter: blur(22px) saturate(1.6);
          -webkit-backdrop-filter: blur(22px) saturate(1.6);

          box-shadow:
            0 24px 48px rgba(50,90,110,.10),
            0 8px 20px rgba(50,90,110,.06),
            inset 0 0 0 0.5px rgba(92,190,235,.045),
            inset 0 0 0 0.5px rgba(220,120,190,.032),
            inset 0 1px 0 rgba(255,255,255,.96),
            inset 0 2px 18px rgba(255,255,255,.22),
            inset 0 4px 32px rgba(255,255,255,.08);
        }

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

        .agent-panel-lg::after {
          content: '';
          position: absolute;
          inset: -1px;
          z-index: 0;
          border-radius: inherit;
          pointer-events: none;
          filter: url('#glass-refract');
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
          padding-bottom: 18px;
          border-bottom: 1px solid rgba(129,160,174,.20);
          margin-bottom: 16px;
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

        /* ── Saved Profile Banner ── */
        .agent-profile-banner {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 10px;
          padding: 7px 14px;
          border-radius: 12px;
          background: rgba(220, 248, 245, 0.45);
          backdrop-filter: blur(8px);
          -webkit-backdrop-filter: blur(8px);
          border: 1px solid rgba(66, 207, 192, 0.35);
          margin-bottom: 14px;
          animation: fade-in-up 0.25s ease-out both;
          flex-wrap: wrap;
        }

        .profile-banner-left {
          display: flex;
          align-items: center;
          gap: 8px;
          flex-wrap: wrap;
        }

        .profile-badge {
          display: inline-flex;
          align-items: center;
          gap: 5px;
          font-size: 10.5px;
          font-weight: 700;
          letter-spacing: .06em;
          text-transform: uppercase;
          color: #11786c;
          background: rgba(66, 207, 192, 0.22);
          padding: 3px 8px;
          border-radius: 6px;
          border: 1px solid rgba(66, 207, 192, 0.4);
        }

        .profile-summary-text {
          font-size: 13px;
          color: #1d4d5e;
          font-weight: 500;
        }

        .profile-reset-btn {
          background: rgba(255, 255, 255, 0.65);
          border: 1px solid rgba(220, 110, 90, 0.3);
          color: #b54732;
          font-size: 12px;
          font-weight: 600;
          padding: 3px 10px;
          border-radius: 100px;
          cursor: pointer;
          transition: all 0.15s ease;
        }

        .profile-reset-btn:hover {
          background: rgba(255, 238, 235, 0.95);
          color: #8c2613;
          border-color: rgba(220, 90, 70, 0.6);
          transform: translateY(-0.5px);
        }

        /* ── Reset Notice Toast ── */
        .agent-reset-notice {
          font-size: 12.5px;
          color: #126359;
          background: rgba(220, 248, 245, 0.7);
          border: 1px solid rgba(66, 207, 192, 0.4);
          border-radius: 10px;
          padding: 6px 12px;
          margin-bottom: 12px;
          animation: fade-in-up 0.2s ease-out both;
        }

        /* ── Suggestion pills ── */
        .agent-suggestions {
          display: flex;
          gap: 8px;
          margin: 14px 0 16px;
          flex-wrap: wrap;
          animation: fade-in-up 0.3s cubic-bezier(.2,.8,.2,1) both;
        }

        .agent-suggestions button {
          padding: 8px 15px;
          color: #36566b;
          border: 1px solid rgba(129,160,174,.32);
          border-radius: 100px;
          background: rgba(255,255,255,.55);
          backdrop-filter: blur(8px);
          -webkit-backdrop-filter: blur(8px);
          font-size: 14px;
          font-weight: 500;
          cursor: pointer;
          transition: background .18s, border-color .18s, color .18s, transform .12s;
        }

        .agent-suggestions button:hover {
          color: #17324d;
          background: rgba(255,255,255,.85);
          border-color: rgba(66,207,192,.50);
          transform: translateY(-1px);
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
          max-height: 320px;
          overflow-y: auto;
          margin: 0 0 16px;
          padding-right: 4px;
          scrollbar-width: thin;
          scrollbar-color: rgba(66,207,192,.25) transparent;
        }

        /* ── Structured choice & Location buttons ── */
        .agent-choices {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          margin-bottom: 12px;
          animation: fade-in-up 0.28s cubic-bezier(.2,.8,.2,1) both;
        }

        .agent-choice-label {
          width: 100%;
          font-size: 11.5px;
          font-weight: 700;
          letter-spacing: .06em;
          text-transform: uppercase;
          color: #1a756b;
          margin-bottom: 2px;
          display: flex;
          align-items: center;
          gap: 5px;
        }

        .agent-choice-btn {
          padding: 8px 16px;
          border-radius: 100px;
          border: 1.5px solid rgba(66,207,192,.40);
          background: rgba(255,255,255,.55);
          backdrop-filter: blur(8px);
          -webkit-backdrop-filter: blur(8px);
          color: #1d6e65;
          font-size: 14px;
          font-weight: 500;
          cursor: pointer;
          transition: background 0.18s, border-color 0.18s, transform 0.12s, box-shadow 0.18s;
          white-space: nowrap;
        }

        .agent-choice-btn:hover {
          background: rgba(66,207,192,.18);
          border-color: rgba(66,207,192,.70);
          transform: translateY(-1px);
          box-shadow: 0 4px 12px rgba(66,207,192,.15);
        }

        .agent-choice-btn:active {
          transform: translateY(0) scale(.97);
        }

        /* ── Location Action Buttons ── */
        .agent-location-options {
          display: flex;
          flex-wrap: wrap;
          gap: 9px;
          margin-bottom: 12px;
          animation: fade-in-up 0.28s cubic-bezier(.2,.8,.2,1) both;
        }

        .agent-location-btn {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          padding: 9px 18px;
          border-radius: 100px;
          border: 1.5px solid rgba(66,207,192,.55);
          background: rgba(255,255,255,.68);
          backdrop-filter: blur(10px) saturate(1.4);
          -webkit-backdrop-filter: blur(10px) saturate(1.4);
          color: #145850;
          font-size: 14px;
          font-weight: 600;
          cursor: pointer;
          box-shadow:
            0 4px 14px rgba(66,207,192,.12),
            inset 0 1px 0 rgba(255,255,255,.95);
          transition: all 0.18s cubic-bezier(.16,1,.3,1);
        }

        .agent-location-btn:hover:not(:disabled) {
          background: rgba(220,248,245,.82);
          border-color: #42cfc0;
          transform: translateY(-1px);
          box-shadow:
            0 6px 18px rgba(66,207,192,.28),
            inset 0 1px 0 rgba(255,255,255,.95);
          color: #0d403a;
        }

        .agent-location-btn:active:not(:disabled) {
          transform: translateY(0) scale(.98);
        }

        .agent-location-btn:disabled {
          opacity: 0.6;
          cursor: default;
        }

        .agent-location-icon {
          display: inline-flex;
          align-items: center;
          justify-content: center;
        }

        .spin-animate {
          animation: spin 1s linear infinite;
        }

        @keyframes spin {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }

        .agent-location-notice {
          width: 100%;
          font-size: 13px;
          color: #a0422d;
          background: rgba(255, 238, 235, 0.75);
          border: 1px solid rgba(220, 100, 80, 0.3);
          border-radius: 12px;
          padding: 8px 14px;
          margin-top: 4px;
          backdrop-filter: blur(8px);
          animation: fade-in-up 0.22s ease-out both;
        }

        /* ── Bubbles — glass treatment ── */
        @keyframes bubble-in {
          from { opacity: 0; transform: translateY(6px) scale(.98); }
          to   { opacity: 1; transform: translateY(0)   scale(1);   }
        }

        .chat-bubble {
          animation: bubble-in 0.22s cubic-bezier(.2,.8,.2,1) both;
          max-width: 88%;
          font-size: 14.5px;
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
          background: rgba(220,248,245,.58);
          backdrop-filter: blur(12px) saturate(1.4);
          -webkit-backdrop-filter: blur(12px) saturate(1.4);
          border: 1px solid rgba(66,207,192,.28);
          border-left: 2.5px solid #42cfc0;
          color: #1e4555;
          box-shadow:
            0 4px 14px rgba(66,207,192,.08),
            inset 0 1px 0 rgba(255,255,255,.60);
        }

        /* Typewriter blinking cursor */
        .typewriter-cursor {
          display: inline-block;
          margin-left: 2px;
          color: #138578;
          font-weight: 700;
          animation: cursor-blink 0.75s step-start infinite;
        }

        @keyframes cursor-blink {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0; }
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
          font-size: 15.5px;
          font-family: inherit;
          min-width: 0;
        }

        .agent-composer input::placeholder {
          color: #8aabbf;
          font-size: 15px;
        }

        /* ── Send button ── */
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

        {/* Saved Profile Confirmation Banner (Clean Lucide-style User Line Icon, No Emoji) */}
        {savedProfile && (
          <div className="agent-profile-banner" role="status" aria-label="Saved health profile status">
            <div className="profile-banner-left">
              <span className="profile-badge">
                <UserLineIcon />
                <span>Saved Profile</span>
              </span>
              <span className="profile-summary-text">
                {formatProfileSummary(savedProfile)}
              </span>
            </div>
            <button
              type="button"
              className="profile-reset-btn"
              onClick={handleResetProfile}
              aria-label="Clear saved profile and reset info"
            >
              Not you? Reset my info
            </button>
          </div>
        )}

        {/* Reset feedback notice */}
        {resetNotice && (
          <div className="agent-reset-notice" role="alert">
            {resetNotice}
          </div>
        )}

        {/* Chat thread with Animated Proactive Greeting */}
        <div className="agent-thread" role="log" aria-live="polite" aria-label="Conversation with Hawa">
          {/* Proactive Greeting Bubble */}
          <div className="chat-bubble agent" aria-label="Hawa greeting">
            {greetingText}
            {!isGreetingDone && <span className="typewriter-cursor">|</span>}
          </div>

          {/* User & Agent conversation turns */}
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

        {/* Suggestion pills — visible below the intro greeting before user's first message */}
        {!hasUserSentMessage && (
          <div className="agent-suggestions">
            {SUGGESTIONS.map((s) => (
              <button key={s.label} onClick={() => handleSuggestion(s.query)}>
                {s.label}
              </button>
            ))}
          </div>
        )}

        {/* Location selector (Use current location / Pick on map / Manual input) */}
        {isLocationActive && !isLoading && (
          <div className="agent-location-options" role="group" aria-label="Choose your location">
            <span className="agent-choice-label">
              Location options:
            </span>
            <button
              type="button"
              className="agent-location-btn"
              onClick={handleUseCurrentLocation}
              disabled={isLocating}
              aria-label="Use my current location via GPS"
            >
              <span className="agent-location-icon">
                {isLocating ? <SpinnerLineIcon /> : <CrosshairLineIcon />}
              </span>
              <span>{isLocating ? 'Detecting location…' : 'Use my current location'}</span>
            </button>

            <button
              type="button"
              className="agent-location-btn"
              onClick={() => setIsMapOpen(true)}
              aria-label="Pick location on map of Delhi NCR"
            >
              <span className="agent-location-icon">
                <MapLineIcon />
              </span>
              <span>Pick on map</span>
            </button>

            {locationNotice && (
              <div className="agent-location-notice" role="alert">
                {locationNotice}
              </div>
            )}
          </div>
        )}

        {/* Structured choice buttons for other clarifying fields (age, conditions, smoker, etc.) */}
        {choiceOptions.length > 0 && !isLoading && (
          <div className="agent-choices" role="group" aria-label={`Choose ${activeMissingField}`}>
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

        {/* Composer with contextual placeholder */}
        <form className="agent-composer" onSubmit={handleSubmit}>
          <input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={
              isLocationActive
                ? 'Or type your location (e.g. Lodhi Garden, Saket)…'
                : choiceOptions.length > 0
                ? 'Or type a custom answer…'
                : 'Ask anything about going outside…'
            }
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
