/**
 * HealthProfileBanner
 *
 * A sticky-below-hero banner that lets users configure their health profile
 * (age group, condition, duration) to personalize PEVI scores across all cards.
 *
 * Persists to localStorage via peviPersonalize helpers.
 * Emits onProfileChange whenever the profile changes.
 */

import type { AgeGroup, Condition, HealthProfile } from '../utils/peviPersonalize'
import {
  DEFAULT_PROFILE,
  clearProfile,
  isDefaultProfile,
  profileLabel,
  saveProfile,
} from '../utils/peviPersonalize'

interface HealthProfileBannerProps {
  profile: HealthProfile
  onProfileChange: (profile: HealthProfile) => void
}

// No emojis — plain text labels only
const AGE_OPTIONS: { value: AgeGroup; label: string }[] = [
  { value: 'child', label: 'Child' },
  { value: 'adult', label: 'Adult' },
  { value: 'elderly', label: 'Elderly' },
]

const CONDITION_OPTIONS: { value: Condition; label: string }[] = [
  { value: 'none', label: 'None' },
  { value: 'respiratory', label: 'Respiratory' },
  { value: 'cardiac', label: 'Cardiac' },
]

const DURATION_OPTIONS: { value: number; label: string }[] = [
  { value: 0.5, label: '30 min' },
  { value: 1, label: '1 hour' },
  { value: 2, label: '2 hours' },
  { value: 3, label: '3 hours' },
]

function handleUpdate(
  profile: HealthProfile,
  patch: Partial<HealthProfile>,
  onChange: (p: HealthProfile) => void,
) {
  const updated = { ...profile, ...patch }
  saveProfile(updated)
  onChange(updated)
}

export function HealthProfileBanner({ profile, onProfileChange }: HealthProfileBannerProps) {
  const personalized = !isDefaultProfile(profile)

  function reset() {
    clearProfile()
    onProfileChange({ ...DEFAULT_PROFILE })
  }

  return (
    <>
      <style>{`
        /* ── Health profile banner — liquid glass ── */
        .hp-banner {
          max-width: 1240px;
          margin-left: auto;
          margin-right: auto;
          margin-bottom: 24px;
          padding: 18px 24px;
          border-radius: 18px;

          /* Liquid glass base */
          position: relative;
          isolation: isolate;
          background: rgba(255,255,255,.68);
          backdrop-filter: blur(18px) saturate(1.55);
          -webkit-backdrop-filter: blur(18px) saturate(1.55);
          border: 1px solid rgba(255,255,255,.60);
          box-shadow:
            0 8px 28px rgba(65,126,151,.09),
            0 2px 6px rgba(65,126,151,.05),
            inset 0 1px 0 rgba(255,255,255,.82),
            inset 0 -1px 0 rgba(129,160,174,.06);
          transition: border-color .28s, box-shadow .28s;
          overflow: hidden;
        }

        /* Frosted glass highlight sheen */
        .hp-banner::after {
          content: '';
          position: absolute;
          inset: 0;
          z-index: 0;
          pointer-events: none;
          border-radius: inherit;
          background: linear-gradient(
            118deg,
            rgba(255,255,255,.38) 0%,
            rgba(255,255,255,.10) 22%,
            transparent 52%
          );
          mix-blend-mode: screen;
        }

        .hp-banner > * { position: relative; z-index: 1; }

        .hp-banner.is-personalized {
          border-color: rgba(66,207,192,.42);
          background: rgba(240,252,250,.70);
          box-shadow:
            0 8px 28px rgba(65,126,151,.09),
            0 2px 6px rgba(65,126,151,.05),
            0 0 0 1px rgba(66,207,192,.12),
            inset 0 1px 0 rgba(255,255,255,.82);
        }

        .hp-banner-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          flex-wrap: wrap;
          gap: 10px;
          margin-bottom: 14px;
        }

        .hp-banner-title {
          display: flex;
          align-items: center;
          gap: 0;
          font-size: 13px;
          font-weight: 600;
          color: #17324d;
          letter-spacing: -.01em;
        }

        .hp-banner-subtitle {
          font-size: 11px;
          color: #7190a1;
          font-weight: 400;
          margin-left: 4px;
        }

        .hp-active-label {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 4px 11px;
          border-radius: 100px;
          background: rgba(66,207,192,.14);
          border: 1px solid rgba(66,207,192,.38);
          color: #1a7b72;
          font-size: 10.5px;
          font-weight: 600;
          letter-spacing: .02em;
          animation: badge-pop 0.28s cubic-bezier(.2,.8,.2,1) both;
        }

        @keyframes badge-pop {
          from { opacity: 0; transform: scale(.88); }
          to   { opacity: 1; transform: scale(1); }
        }

        .hp-active-label::before {
          content: '✦';
          font-size: 8px;
          color: #42cfc0;
        }

        .hp-reset-btn {
          padding: 4px 13px;
          border-radius: 100px;
          border: 1px solid rgba(129,160,174,.30);
          background: rgba(255,255,255,.46);
          backdrop-filter: blur(8px);
          -webkit-backdrop-filter: blur(8px);
          color: #7190a1;
          font-size: 10.5px;
          font-weight: 500;
          cursor: pointer;
          transition: border-color .18s, color .18s, background .18s;
          white-space: nowrap;
        }

        .hp-reset-btn:hover {
          border-color: #a9c7d3;
          color: #17324d;
          background: rgba(255,255,255,.72);
        }

        /* ── Chip rows ── */
        .hp-rows {
          display: flex;
          flex-wrap: wrap;
          gap: 16px;
          align-items: flex-start;
        }

        .hp-group {
          display: flex;
          flex-direction: column;
          gap: 6px;
          flex: 1;
          min-width: 130px;
        }

        .hp-group-label {
          font-size: 9.5px;
          font-weight: 700;
          letter-spacing: .08em;
          text-transform: uppercase;
          color: #7190a1;
          padding-left: 2px;
        }

        .hp-chips {
          display: flex;
          flex-wrap: wrap;
          gap: 5px;
        }

        .hp-chip {
          padding: 5px 13px;
          border-radius: 100px;
          border: 1px solid rgba(129,160,174,.26);
          background: rgba(255,255,255,.52);
          backdrop-filter: blur(8px);
          -webkit-backdrop-filter: blur(8px);
          color: #3d5f74;
          font-size: 11.5px;
          font-weight: 500;
          cursor: pointer;
          transition:
            background .16s,
            border-color .16s,
            transform .12s,
            color .16s,
            box-shadow .16s;
          white-space: nowrap;
          display: flex;
          align-items: center;
          gap: 4px;
        }

        .hp-chip:hover {
          background: rgba(255,255,255,.80);
          border-color: rgba(129,160,174,.50);
          color: #17324d;
        }

        /* Selected: teal glow border + very light teal fill — no flat solid background */
        .hp-chip.selected {
          background: rgba(66,207,192,.09);
          border-color: #42cfc0;
          color: #1a7b72;
          font-weight: 600;
          box-shadow:
            0 0 0 2.5px rgba(66,207,192,.18),
            inset 0 1px 0 rgba(255,255,255,.6);
        }

        .hp-chip:active {
          transform: scale(.96);
        }

        /* ── Tooltip for PEVI explanation ── */
        .pevi-info-wrap {
          position: relative;
          display: inline-flex;
          align-items: center;
        }

        .pevi-info-btn {
          width: 16px;
          height: 16px;
          border-radius: 50%;
          border: 1px solid rgba(66,207,192,.5);
          background: rgba(66,207,192,.1);
          color: #42cfc0;
          font-size: 9px;
          font-weight: 700;
          display: inline-flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          line-height: 1;
          padding: 0;
          margin-left: 6px;
          transition: background .18s;
          flex-shrink: 0;
        }

        .pevi-info-btn:hover {
          background: rgba(66,207,192,.22);
        }

        .pevi-tooltip {
          position: absolute;
          bottom: calc(100% + 8px);
          left: 50%;
          transform: translateX(-50%);
          min-width: 240px;
          max-width: 290px;
          padding: 10px 13px;
          border-radius: 10px;
          background: rgba(23, 50, 77, 0.93);
          color: #e8eef3;
          font-size: 11px;
          line-height: 1.55;
          font-style: normal;
          box-shadow: 0 8px 24px rgba(0,0,0,.18);
          z-index: 50;
          pointer-events: none;
          opacity: 0;
          transition: opacity .18s;
          white-space: normal;
        }

        .pevi-info-wrap:hover .pevi-tooltip,
        .pevi-info-btn:focus + .pevi-tooltip {
          opacity: 1;
        }

        .pevi-tooltip::after {
          content: '';
          position: absolute;
          top: 100%;
          left: 50%;
          transform: translateX(-50%);
          border: 5px solid transparent;
          border-top-color: rgba(23,50,77,.93);
        }

        @media (max-width: 760px) {
          .hp-banner { margin: 0 22px 20px; }
          .hp-group { min-width: 100px; }
        }
      `}</style>

      <div
        className={`hp-banner ${personalized ? 'is-personalized' : ''}`}
        role="region"
        aria-label="Health profile for personalized air quality"
      >
        {/* Header row */}
        <div className="hp-banner-header">
          <div className="hp-banner-title">
            Personalize for your health profile
            <span className="hp-banner-subtitle">— PEVI scores update for all parks</span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {personalized && (
              <span className="hp-active-label" aria-live="polite">
                Personalized for: {profileLabel(profile)}
              </span>
            )}
            {personalized && (
              <button
                className="hp-reset-btn"
                onClick={reset}
                aria-label="Reset to general (default) PEVI view"
              >
                Reset to general view
              </button>
            )}
          </div>
        </div>

        {/* Chip rows */}
        <div className="hp-rows">
          {/* Age group */}
          <div className="hp-group">
            <span className="hp-group-label">Age group</span>
            <div className="hp-chips" role="radiogroup" aria-label="Age group">
              {AGE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  id={`hp-age-${opt.value}`}
                  role="radio"
                  aria-checked={profile.ageGroup === opt.value}
                  className={`hp-chip ${profile.ageGroup === opt.value ? 'selected' : ''}`}
                  onClick={() =>
                    handleUpdate(profile, { ageGroup: opt.value }, onProfileChange)
                  }
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Health condition */}
          <div className="hp-group">
            <span className="hp-group-label">Health condition</span>
            <div className="hp-chips" role="radiogroup" aria-label="Health condition">
              {CONDITION_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  id={`hp-cond-${opt.value}`}
                  role="radio"
                  aria-checked={profile.condition === opt.value}
                  className={`hp-chip ${profile.condition === opt.value ? 'selected' : ''}`}
                  onClick={() =>
                    handleUpdate(profile, { condition: opt.value }, onProfileChange)
                  }
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* Duration */}
          <div className="hp-group">
            <span className="hp-group-label">Outdoor duration</span>
            <div className="hp-chips" role="radiogroup" aria-label="Outdoor duration">
              {DURATION_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  id={`hp-dur-${opt.value}`}
                  role="radio"
                  aria-checked={profile.durationHours === opt.value}
                  className={`hp-chip ${profile.durationHours === opt.value ? 'selected' : ''}`}
                  onClick={() =>
                    handleUpdate(profile, { durationHours: opt.value }, onProfileChange)
                  }
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* PEVI info tooltip */}
          <div className="hp-group" style={{ flex: '0 0 auto', alignSelf: 'flex-end', minWidth: 0 }}>
            <div className="pevi-info-wrap" aria-describedby="pevi-tooltip-text">
              <button
                className="pevi-info-btn"
                aria-label="What is PEVI?"
                tabIndex={0}
              >
                i
              </button>
              <div className="pevi-tooltip" id="pevi-tooltip-text" role="tooltip">
                <strong>PEVI</strong> — Personalized Exposure Vulnerability Index
                <br /><br />
                A health-weighted air quality score combining 6 pollutants (PM2.5, PM10, NO₂, SO₂, O₃, CO).{' '}
                <strong>Lower is better.</strong> When a profile is set, your PEVI is multiplied by vulnerability
                factors for age, health condition, and time spent outside.
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
