// Adapted from vercelll/app/page.tsx
// Changes: removed 'use client', replaced hardcoded data with real API, fixed imports

import { useEffect, useMemo, useState } from 'react'
import { getLocations } from './api/locations'
import type { LocationItem } from './api/types'
import { getPeviColor } from './utils/peviColor'
import { AgentPanel } from './components/AgentPanel'

export default function App() {
  const [query, setQuery] = useState('')
  const [selectedTime, setSelectedTime] = useState('12 PM')
  const [locations, setLocations] = useState<LocationItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getLocations()
      .then((res) => setLocations(res.locations || []))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  // Compute real average PEVI from live API data
  const avgPevi = useMemo(() => {
    const valid = locations.filter((l) => l.data_available && l.current_pevi !== null)
    if (!valid.length) return null
    return valid.reduce((sum, l) => sum + (l.current_pevi as number), 0) / valid.length
  }, [locations])

  // Best (cleanest) and worst parks from live data
  const bestPark = useMemo(
    () =>
      locations
        .filter((l) => l.data_available && l.current_pevi !== null)
        .sort((a, b) => (a.current_pevi as number) - (b.current_pevi as number))[0] ?? null,
    [locations],
  )

  // Map locations → park-card shape expected by the v0 design
  const parks = useMemo(
    () =>
      locations
        .filter((l) => l.data_available && l.current_pevi !== null)
        .map((l) => ({
          name: l.name,
          area: l.zone ?? '',
          score: l.current_pevi as number,
          risk: l.personalized_risk_band ?? '',
          pm25: l.pollutants?.pm25 ?? 0,
          pm10: l.pollutants?.pm10 ?? 0,
          color: getPeviColor(l.current_pevi, 3.12, 7.07),
        })),
    [locations],
  )

  const filteredParks = useMemo(
    () =>
      parks.filter((park) =>
        `${park.name} ${park.area}`.toLowerCase().includes(query.toLowerCase()),
      ),
    [parks, query],
  )

  // Build forecast rail from live avg (placeholder until /forecast endpoint is wired)
  const forecast = useMemo(() => {
    const base = avgPevi ?? 4.86
    // Slight simulated diurnal curve around the live average
    const offsets = [0, -0.44, -0.95, -0.7, +0.16, +0.62]
    const labels = ['Now', '10 AM', '12 PM', '2 PM', '4 PM', '6 PM']
    const descs = ['Live avg', 'Improving', 'Best window', 'Good', 'Building', 'Heavier']
    return labels.map((time, i) => ({
      time,
      score: Math.max(3.12, Math.min(7.07, base + offsets[i])),
      air: descs[i],
    }))
  }, [avgPevi])

  const forecastMin = Math.min(...forecast.map((f) => f.score))
  const forecastMax = Math.max(...forecast.map((f) => f.score))

  function getForecastColor(score: number) {
    const teal = [66, 207, 192]
    const coral = [248, 113, 113]
    const ratio = forecastMax > forecastMin ? (score - forecastMin) / (forecastMax - forecastMin) : 0
    const softened = Math.min(1, Math.max(0, ratio * 0.9 + 0.05))
    return `rgb(${teal.map((ch, i) => Math.round(ch + (coral[i] - ch) * softened)).join(', ')})`
  }

  function askAgent() {
    document.getElementById('agent')?.scrollIntoView({ behavior: 'smooth' })
  }

  function moveHero(event: React.MouseEvent<HTMLElement>) {
    const rect = event.currentTarget.getBoundingClientRect()
    const x = ((event.clientX - rect.left) / rect.width - 0.5) * 2
    const y = ((event.clientY - rect.top) / rect.height - 0.5) * 2
    event.currentTarget.style.setProperty('--parallax-x', `${x}`)
    event.currentTarget.style.setProperty('--parallax-y', `${y}`)
  }

  const displayAvg = avgPevi?.toFixed(2) ?? '—'
  const bestName = bestPark?.name ?? 'Loading…'
  const bestScore = bestPark?.current_pevi?.toFixed(2) ?? '—'

  return (
    <main className="hawaguide-shell">
      <svg className="liquid-glass-defs" aria-hidden="true" focusable={false}>
        <filter id="liquid-glass-edge" x="-12%" y="-12%" width="124%" height="124%" colorInterpolationFilters="sRGB">
          <feTurbulence type="fractalNoise" baseFrequency="0.018 0.08" numOctaves={2} seed={7} result="edgeNoise" />
          <feDisplacementMap in="SourceGraphic" in2="edgeNoise" scale={3.5} xChannelSelector="R" yChannelSelector="G" result="bentEdge" />
          <feSpecularLighting in="bentEdge" surfaceScale={2} specularConstant={0.32} specularExponent={28} lightingColor="#ffffff" result="specular">
            <feDistantLight azimuth={225} elevation={58} />
          </feSpecularLighting>
          <feComposite in="specular" in2="SourceAlpha" operator="in" result="specularMask" />
          <feBlend in="bentEdge" in2="specularMask" mode="screen" />
        </filter>
      </svg>

      <header className="site-header">
        <a className="brand" href="#top" aria-label="HawaGuide home">
          <span className="nav-wordmark">HawaGuide</span>
        </a>
        <nav className="desktop-nav" aria-label="Primary navigation">
          <a href="#spaces">Green spaces</a>
          <a href="#forecast">Forecast</a>
          <a href="#agent">Ask the agent</a>
        </nav>
        <button
          className="header-location"
          onClick={() => document.getElementById('spaces')?.scrollIntoView({ behavior: 'smooth' })}
        >
          <span className="location-dot" /> Delhi NCR <span aria-hidden="true">⌄</span>
        </button>
      </header>

      {/* ── Hero ──────────────────────────────────────────────────────────── */}
      <section id="top" className="hero-section widget-hero" onMouseMove={moveHero}>
        <div className="hero-copy">
          <h1>
            Where should you go
            <br />
            for a walk today?
          </h1>
          <p className="hero-text">
            Find cleaner air near you — hours before you go. See live air quality across 40 Delhi NCR
            green spaces, ranked so you can choose the healthiest park for a walk, run, or family
            outing today.
          </p>
          <div className="hero-actions">
            <button className="button-primary" onClick={askAgent}>
              Ask the agent
            </button>
            <a className="button-secondary" href="#spaces">
              See live conditions
            </a>
          </div>
          <div className="network-stat">
            <span className="pulse-dot" />
            <div>
              <strong>Live network average</strong>
              <span>
                {loading ? 'Loading…' : `${displayAvg} PEVI across ${locations.length} parks`}
              </span>
            </div>
            <span className="stat-time">Live</span>
          </div>
        </div>

        <div className="widget-stage" aria-label="HawaGuide feature preview">
          <div className="pevi-atmosphere" aria-hidden="true" />

          {/* Widget 1 — live conditions */}
          <article
            className="glass-widget widget-conditions"
            style={{ transform: 'translate(calc(var(--parallax-x) * 4px), calc(var(--parallax-y) * 3px))' }}
          >
            <div className="widget-kicker">
              <span className="widget-icon pulse-dot" /> Live conditions
            </div>
            <strong className="widget-score">{displayAvg}</strong>
            <span className="widget-unit">PEVI · Delhi NCR</span>
            <div className="widget-park">
              <span className="park-swatch" />
              <div>
                <b>{bestName}</b>
                <small>
                  {bestScore} · {bestPark?.personalized_risk_band ?? 'Low'}
                </small>
              </div>
              <span className="widget-arrow">↗</span>
            </div>
          </article>

          {/* Widget 2 — forecast sparkline */}
          <article
            className="glass-widget widget-forecast-card"
            style={{ transform: 'rotate(2deg) translate(calc(var(--parallax-x) * 7px), calc(var(--parallax-y) * 5px))' }}
          >
            <div className="widget-card-head">
              <span className="widget-kicker">6-hour forecast</span>
              <span className="widget-muted">Delhi NCR</span>
            </div>
            <svg className="forecast-sparkline" viewBox="0 0 220 62" role="img" aria-label="Forecast dips then rises">
              <path d="M3 31 C25 30 40 29 61 30 S92 42 113 44 S145 35 163 27 S195 14 217 18" />
              <circle cx="113" cy="44" r="4" />
              <circle className="spark-end" cx="217" cy="18" r="3" />
            </svg>
            <div className="widget-forecast-foot">
              <span>Best window</span>
              <b>in 3 hours</b>
            </div>
          </article>

          {/* Widget 3 — agent chat preview */}
          <article
            className="glass-widget widget-agent-card"
            style={{ transform: 'rotate(-2deg) translate(calc(var(--parallax-x) * 3px), calc(var(--parallax-y) * 2px))' }}
          >
            <div className="widget-kicker">
              <span className="agent-mini">∿</span> Ask the agent
            </div>
            <p>&#8220;Is it safe to walk near Lodhi Garden?&#8221;</p>
            <div className="chat-preview">
              <span>Hawa</span>
              <b>Yes — try around 12 PM for the cleanest window.</b>
            </div>
          </article>
        </div>
      </section>

      {/* ── Forecast ──────────────────────────────────────────────────────── */}
      <section id="forecast" className="forecast-section">
        <div className="section-heading">
          <div>
            <h2>Six hours, in breathable moments.</h2>
          </div>
          <p className="section-note">
            A forecast shaped by wind, traffic, weather
            <br className="desktop-break" />
            and the way pollution moves between parks.
          </p>
        </div>
        <div className="forecast-rail">
          {forecast.map((item) => {
            const color = getForecastColor(item.score)
            const height =
              forecastMax > forecastMin
                ? 24 + ((item.score - forecastMin) / (forecastMax - forecastMin)) * 76
                : 50
            const selected = selectedTime === item.time
            return (
              <button
                key={item.time}
                className={`forecast-item ${selected ? 'selected' : ''}`}
                aria-pressed={selected}
                aria-label={`${item.time}, PEVI ${item.score.toFixed(2)}, ${item.air}${selected ? ', current selection' : ''}`}
                onClick={() => setSelectedTime(item.time)}
              >
                <span className="forecast-time">
                  {item.time}
                  {selected && <small className="forecast-now-pill">Now</small>}
                </span>
                <span className="forecast-score" style={{ color }}>
                  {item.score.toFixed(2)}
                </span>
                <span className="forecast-air">{item.air}</span>
                <span className="forecast-bar" aria-hidden="true">
                  <i style={{ height: `${height}%`, background: color }} />
                </span>
              </button>
            )
          })}
        </div>
      </section>

      {/* ── Green Spaces ──────────────────────────────────────────────────── */}
      <section id="spaces" className="spaces-section">
        <div className="section-heading spaces-heading">
          <div>
            <h2>
              Delhi NCR
              <br />
              <em>green spaces.</em>
            </h2>
          </div>
          <div className="space-tools">
            <label className="search-box">
              <span aria-hidden="true">⌕</span>
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search a park or area"
                aria-label="Search parks"
              />
            </label>
            <span className="result-count">
              {filteredParks.length} of {locations.length || 40} mapped
            </span>
          </div>
        </div>

        <div className="park-grid">
          {loading
            ? // Loading skeleton — same card shape
              Array.from({ length: 6 }).map((_, i) => (
                <article
                  key={i}
                  className="park-card"
                  style={{ '--park-color': '#8ea7b4' } as React.CSSProperties}
                >
                  <div className="park-card-top">
                    <div>
                      <h3 style={{ opacity: 0.3 }}>Loading…</h3>
                      <p style={{ opacity: 0.2 }}>—</p>
                    </div>
                    <span className="park-pin">+</span>
                  </div>
                  <div className="park-score-row" style={{ marginTop: 37 }}>
                    <span className="park-score" style={{ opacity: 0.2 }}>—</span>
                  </div>
                </article>
              ))
            : filteredParks.map((park) => (
                <article
                  key={park.name}
                  className="park-card"
                  style={{ '--park-color': park.color } as React.CSSProperties}
                >
                  <div className="park-card-top">
                    <div>
                      <h3>{park.name}</h3>
                      <p>{park.area}</p>
                    </div>
                    <span className="park-pin">+</span>
                  </div>
                  <div className="park-score-row">
                    <span className="park-score">{park.score.toFixed(2)}</span>
                    <span className="park-risk">{park.risk}</span>
                  </div>
                  <div className="park-meter">
                    <span style={{ width: `${((park.score - 3.12) / (7.07 - 3.12)) * 100}%` }} />
                  </div>
                  <div className="park-readings">
                    <span>
                      <small>PM2.5</small>
                      {park.pm25.toFixed(1)} <b>µg/m³</b>
                    </span>
                    <span>
                      <small>PM10</small>
                      {park.pm10.toFixed(1)} <b>µg/m³</b>
                    </span>
                    <span className="readings-time">Live</span>
                  </div>
                </article>
              ))}
        </div>
      </section>

      {/* ── Agent ─────────────────────────────────────────────────────────── */}
      <section id="agent" className="agent-section">
        <div className="agent-intro">
          <h2>
            Tell us how you
            <br />
            <em>want to feel.</em>
          </h2>
          <p>
            HawaGuide reads the air like a local. Ask where to go, when to leave, or how today looks
            for your personal health profile.
          </p>
        </div>
        <AgentPanel />
      </section>

      {/* ── Footer ────────────────────────────────────────────────────────── */}
      <footer className="site-footer">
        <span className="brand">
          <span className="brand-mark">∿</span>
          <span>HawaGuide</span>
        </span>
        <span>Air moves. We help you move with it.</span>
        <span>Made for Delhi NCR · 2026</span>
      </footer>
    </main>
  )
}
