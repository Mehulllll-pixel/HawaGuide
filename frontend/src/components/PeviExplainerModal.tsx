/**
 * PeviExplainerModal
 *
 * Liquid-glass modal explaining "Why PEVI, not just AQI?"
 * Opens via the (i) trigger next to the PEVI label in the green spaces section.
 *
 * Features:
 * - Click-outside-to-close (backdrop click)
 * - Escape key to close
 * - Focus trap on open (focus moves to close button)
 * - Fraunces headline, Inter body (project's loaded fonts)
 * - Liquid-glass aesthetic matching the hero widgets
 */

import { useEffect, useRef } from 'react'

interface PeviExplainerModalProps {
  isOpen: boolean
  onClose: () => void
}

export function PeviExplainerModal({ isOpen, onClose }: PeviExplainerModalProps) {
  const closeRef = useRef<HTMLButtonElement>(null)

  // Close on Escape
  useEffect(() => {
    if (!isOpen) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [isOpen, onClose])

  // Move focus to close button when opened
  useEffect(() => {
    if (isOpen) {
      // Small delay so the element is visible before focus
      setTimeout(() => closeRef.current?.focus(), 30)
    }
  }, [isOpen])

  if (!isOpen) return null

  return (
    <>
      <style>{`
        /* ── PEVI explainer modal ── */
        .pevi-modal-backdrop {
          position: fixed;
          inset: 0;
          z-index: 200;
          background: rgba(180, 210, 220, 0.38);
          backdrop-filter: blur(12px) saturate(1.2);
          -webkit-backdrop-filter: blur(12px) saturate(1.2);
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 20px;
          animation: modal-fade-in 0.22s cubic-bezier(.2,.8,.2,1) both;
        }

        @keyframes modal-fade-in {
          from { opacity: 0; }
          to   { opacity: 1; }
        }

        .pevi-modal {
          position: relative;
          isolation: isolate;
          overflow: hidden;
          width: 100%;
          max-width: 600px;
          max-height: 88vh;
          overflow-y: auto;
          border-radius: 22px;
          border: 1px solid rgba(255,255,255,.70);
          background: rgba(255,255,255,.82);
          backdrop-filter: blur(28px) saturate(1.7);
          -webkit-backdrop-filter: blur(28px) saturate(1.7);
          box-shadow:
            0 32px 80px rgba(50,90,110,.14),
            0 8px 20px rgba(50,90,110,.08),
            inset 0 1px 0 rgba(255,255,255,.95),
            inset 0 2px 16px rgba(255,255,255,.22);
          animation: modal-slide-up 0.28s cubic-bezier(.2,.8,.2,1) both;
          scrollbar-width: thin;
          scrollbar-color: rgba(66,207,192,.25) transparent;
        }

        @keyframes modal-slide-up {
          from { opacity: 0; transform: translateY(18px) scale(.98); }
          to   { opacity: 1; transform: translateY(0)    scale(1);   }
        }

        /* Glass highlight sheen */
        .pevi-modal::before {
          content: '';
          position: absolute;
          inset: 0;
          z-index: 0;
          pointer-events: none;
          border-radius: inherit;
          background: linear-gradient(
            120deg,
            rgba(255,255,255,.52) 0%,
            rgba(255,255,255,.14) 26%,
            transparent 54%
          );
          mix-blend-mode: screen;
        }

        .pevi-modal > * { position: relative; z-index: 1; }

        /* Modal inner layout */
        .pevi-modal-inner {
          padding: 36px 40px 40px;
        }

        /* Header row */
        .pevi-modal-header {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 16px;
          margin-bottom: 26px;
        }

        .pevi-modal-title {
          font-family: 'Fraunces', serif;
          font-size: 28px;
          font-weight: 500;
          letter-spacing: -.045em;
          line-height: 1.1;
          color: #17324d;
          margin: 0;
        }

        .pevi-modal-close {
          flex-shrink: 0;
          width: 32px;
          height: 32px;
          border-radius: 50%;
          border: 1px solid rgba(129,160,174,.30);
          background: rgba(255,255,255,.60);
          color: #5d778c;
          font-size: 16px;
          line-height: 1;
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          transition: background .18s, border-color .18s, color .18s;
          margin-top: 4px;
        }

        .pevi-modal-close:hover {
          background: rgba(255,255,255,.95);
          border-color: rgba(129,160,174,.55);
          color: #17324d;
        }

        .pevi-modal-close:focus-visible {
          outline: 2px solid #42cfc0;
          outline-offset: 3px;
        }

        /* Body text */
        .pevi-modal-body {
          display: flex;
          flex-direction: column;
          gap: 16px;
        }

        .pevi-modal-body p {
          margin: 0;
          font-family: 'Inter', sans-serif;
          font-size: 14px;
          line-height: 1.72;
          color: #2e4f62;
        }

        .pevi-modal-section-head {
          font-family: 'Fraunces', serif;
          font-size: 15px;
          font-weight: 600;
          letter-spacing: -.02em;
          color: #17324d;
          margin: 8px 0 0;
        }

        /* Divider */
        .pevi-modal-divider {
          height: 1px;
          background: rgba(129,160,174,.18);
          margin: 4px 0;
        }

        /* Disclaimer */
        .pevi-modal-disclaimer {
          font-family: 'Inter', sans-serif;
          font-size: 11.5px;
          line-height: 1.6;
          color: #7190a1;
          border-top: 1px solid rgba(129,160,174,.18);
          padding-top: 16px;
          margin-top: 4px;
        }

        @media (max-width: 640px) {
          .pevi-modal-inner { padding: 24px 22px 28px; }
          .pevi-modal-title { font-size: 22px; }
          .pevi-modal-body p { font-size: 13.5px; }
        }

        /* ── Inline (i) trigger used next to PEVI labels ── */
        .pevi-why-link {
          display: inline-flex;
          align-items: center;
          gap: 3px;
          background: none;
          border: none;
          padding: 0;
          cursor: pointer;
          color: #7190a1;
          font-size: 10px;
          font-weight: 500;
          font-family: 'Inter', sans-serif;
          text-decoration: underline;
          text-underline-offset: 2px;
          text-decoration-color: rgba(113,144,161,.4);
          letter-spacing: .01em;
          transition: color .15s, text-decoration-color .15s;
          line-height: 1;
          vertical-align: middle;
        }

        .pevi-why-link:hover {
          color: #42cfc0;
          text-decoration-color: rgba(66,207,192,.6);
        }

        .pevi-why-link:focus-visible {
          outline: 2px solid #42cfc0;
          outline-offset: 3px;
          border-radius: 3px;
        }
      `}</style>

      {/* Backdrop — clicking it closes the modal */}
      <div
        className="pevi-modal-backdrop"
        role="dialog"
        aria-modal="true"
        aria-label="Why PEVI, not just AQI?"
        onClick={(e) => {
          // Only close if the backdrop itself was clicked (not the card)
          if (e.target === e.currentTarget) onClose()
        }}
      >
        <div className="pevi-modal">
          <div className="pevi-modal-inner">
            {/* Header */}
            <div className="pevi-modal-header">
              <h2 className="pevi-modal-title">Why PEVI, not just AQI?</h2>
              <button
                ref={closeRef}
                className="pevi-modal-close"
                onClick={onClose}
                aria-label="Close explainer"
              >
                ✕
              </button>
            </div>

            {/* Body */}
            <div className="pevi-modal-body">
              <p>
                Standard AQI looks at your air's pollutants and reports whichever single one is
                worst that day — everything else gets ignored, even if several pollutants are all
                moderately elevated at once.
              </p>

              <p>
                PEVI (Personalized Exposure Vulnerability Index) instead adds up a real
                health-risk contribution from all 6 measured pollutants together. A location with
                several moderately-bad pollutants can genuinely be riskier to breathe than one with
                a single very bad pollutant — PEVI reflects that; AQI can't.
              </p>

              <div className="pevi-modal-divider" />

              <p className="pevi-modal-section-head">How it's calculated</p>

              <p>
                PEVI is built on Canada's published Air Quality Health Index (AQHI) methodology —
                real coefficients derived from studies linking short-term health risk to O₃, NO₂,
                and PM₂.₅ levels. We extended this (as our own addition, documented separately from
                the original research) to include PM₁₀, SO₂, and CO, using coefficients scaled from
                WHO Air Quality Guideline thresholds.
              </p>

              <p>
                The personalized version further adjusts for age, existing health conditions, and
                how long you plan to be outside.
              </p>

              <p className="pevi-modal-disclaimer">
                This is a comparative environmental risk score, not a medical diagnosis — always
                consult a healthcare provider for personal health decisions.
              </p>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

/**
 * PeviWhyLink — the tiny understated (i) trigger placed next to PEVI labels.
 * Accepts an onClick that opens the modal.
 */
export function PeviWhyLink({ onClick }: { onClick: () => void }) {
  return (
    <button
      className="pevi-why-link"
      onClick={onClick}
      aria-label="Why PEVI? Learn more"
      title="Why PEVI, not just AQI?"
    >
      Why PEVI?
    </button>
  )
}
