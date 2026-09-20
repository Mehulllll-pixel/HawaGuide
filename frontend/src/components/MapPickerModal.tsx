import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

interface MapPickerModalProps {
  isOpen: boolean
  onClose: () => void
  onSelectLocation: (locationText: string) => void
}

function MapPinIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" />
      <circle cx="12" cy="10" r="3" />
    </svg>
  )
}

function CloseIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  )
}

// ─── Nominatim Reverse Geocoding Helper ────────────────────────────────────
export async function reverseGeocodeNominatim(lat: number, lon: number): Promise<string> {
  try {
    const res = await fetch(
      `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=json&addressdetails=1`,
      {
        headers: {
          'User-Agent': 'HawaGuide-Delhi/1.0 (air-quality advisory app)',
        },
      },
    )
    if (res.ok) {
      const data = await res.json()
      const addr = data.address || {}
      const localPart =
        addr.suburb ||
        addr.neighbourhood ||
        addr.residential ||
        addr.quarter ||
        addr.city_district ||
        addr.road ||
        ''
      const cityPart =
        addr.city ||
        addr.town ||
        addr.village ||
        addr.municipality ||
        addr.county ||
        ''
      const statePart = addr.state || ''

      if (localPart && cityPart && localPart.toLowerCase() !== cityPart.toLowerCase()) {
        return `${localPart}, ${cityPart}`
      }
      if (cityPart && statePart && cityPart.toLowerCase() !== statePart.toLowerCase()) {
        return `${cityPart}, ${statePart}`
      }
      if (localPart && statePart) {
        return `${localPart}, ${statePart}`
      }
      if (cityPart) return cityPart
      if (data.display_name) {
        const parts = data.display_name
          .split(',')
          .map((s: string) => s.trim())
          .filter(Boolean)
        if (parts.length >= 2) {
          return `${parts[0]}, ${parts[1]}`
        }
        return parts[0] || ''
      }
    }
  } catch {
    // Network / offline fallback
  }
  return `${lat.toFixed(4)}, ${lon.toFixed(4)}`
}

export function MapPickerModal({
  isOpen,
  onClose,
  onSelectLocation,
}: MapPickerModalProps) {
  const mapContainerRef = useRef<HTMLDivElement>(null)
  const mapInstanceRef = useRef<L.Map | null>(null)
  const markerRef = useRef<L.Marker | null>(null)

  const [selectedPoint, setSelectedPoint] = useState<{ lat: number; lon: number } | null>(null)
  const [resolvedName, setResolvedName] = useState<string>('')
  const [isResolving, setIsResolving] = useState<boolean>(false)

  // Initialize or teardown Leaflet map
  useEffect(() => {
    if (!isOpen) return
    if (!mapContainerRef.current) return
    if (mapInstanceRef.current) return // already initialized

    // Center on Delhi (Connaught Place)
    const defaultCenter: [number, number] = [28.6328, 77.2197]
    const defaultZoom = 11

    const map = L.map(mapContainerRef.current, {
      center: defaultCenter,
      zoom: defaultZoom,
      zoomControl: true,
      minZoom: 8,
      maxZoom: 18,
    })
    mapInstanceRef.current = map

    // OpenStreetMap tile layer
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 19,
    }).addTo(map)

    // Liquid Glass custom marker icon
    const customIcon = L.divIcon({
      className: 'map-custom-pin',
      html: `
        <div class="custom-glass-pin">
          <div class="pin-ring"></div>
          <div class="pin-core"></div>
        </div>
      `,
      iconSize: [36, 46],
      iconAnchor: [18, 44],
      popupAnchor: [0, -44],
    })

    // Click handler on map
    map.on('click', async (e: L.LeafletMouseEvent) => {
      const { lat, lng } = e.latlng
      setSelectedPoint({ lat, lon: lng })

      if (markerRef.current) {
        markerRef.current.setLatLng(e.latlng)
      } else {
        markerRef.current = L.marker(e.latlng, { icon: customIcon }).addTo(map)
      }

      // Reverse geocode via Nominatim
      setIsResolving(true)
      setResolvedName('')
      try {
        const name = await reverseGeocodeNominatim(lat, lng)
        setResolvedName(name)
      } finally {
        setIsResolving(false)
      }
    })

    // Invalidate size to ensure proper tile rendering inside modal
    const timer = setTimeout(() => {
      map.invalidateSize()
    }, 120)

    // Keyboard ESC listener
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)

    return () => {
      clearTimeout(timer)
      window.removeEventListener('keydown', handleKeyDown)
      map.remove()
      mapInstanceRef.current = null
      markerRef.current = null
    }
  }, [isOpen, onClose])

  if (!isOpen) return null

  const handleConfirm = async () => {
    if (!selectedPoint) return
    let text = resolvedName
    if (!text) {
      setIsResolving(true)
      text = await reverseGeocodeNominatim(selectedPoint.lat, selectedPoint.lon)
      setIsResolving(false)
    }
    onSelectLocation(text)
    onClose()
  }

  return (
    <div className="map-modal-backdrop" onClick={onClose} role="dialog" aria-modal="true">
      <div
        className="map-modal-card"
        onClick={(e) => e.stopPropagation()}
        role="document"
      >
        {/* Header */}
        <div className="map-modal-header">
          <div className="map-modal-title-group">
            <span className="map-modal-badge">Interactive Map</span>
            <h3>Pick your location in Delhi NCR</h3>
            <p className="map-modal-subtitle">
              Click anywhere on the map to drop a pin and set your location
            </p>
          </div>
          <button
            className="map-modal-close-btn"
            onClick={onClose}
            aria-label="Close map"
          >
            <CloseIcon />
          </button>
        </div>

        {/* Map Container */}
        <div className="map-modal-body">
          <div ref={mapContainerRef} className="map-leaflet-wrapper" />
        </div>

        {/* Footer info & confirm */}
        <div className="map-modal-footer">
          <div className="map-selection-info">
            {selectedPoint ? (
              <div className="map-selected-tag">
                <span className="map-selected-icon">
                  <MapPinIcon />
                </span>
                <span className="map-selected-text">
                  {isResolving ? (
                    <span className="map-resolving-pulse">Resolving location…</span>
                  ) : resolvedName ? (
                    <strong>{resolvedName}</strong>
                  ) : (
                    <span>Coordinates selected</span>
                  )}
                  <small className="map-selected-coords">
                    {selectedPoint.lat.toFixed(4)}, {selectedPoint.lon.toFixed(4)}
                  </small>
                </span>
              </div>
            ) : (
              <span className="map-selection-hint">
                Click any point on the map to place a pin (Connaught Place, Saket, Dwarka, Noida, etc.)
              </span>
            )}
          </div>

          <div className="map-modal-actions">
            <button className="map-btn-secondary" onClick={onClose}>
              Cancel
            </button>
            <button
              className="map-btn-primary"
              disabled={!selectedPoint}
              onClick={handleConfirm}
            >
              Use Selected Location
            </button>
          </div>
        </div>
      </div>

      <style>{`
        /* ══════════════════════════════════════════════════════════════
           MAP PICKER MODAL — LIQUID GLASS
        ══════════════════════════════════════════════════════════════ */
        .map-modal-backdrop {
          position: fixed;
          inset: 0;
          z-index: 9999;
          background: rgba(15, 32, 48, 0.45);
          backdrop-filter: blur(14px) saturate(1.2);
          -webkit-backdrop-filter: blur(14px) saturate(1.2);
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 20px;
          animation: map-fade-in 0.24s cubic-bezier(0.16, 1, 0.3, 1) both;
        }

        @keyframes map-fade-in {
          from { opacity: 0; }
          to   { opacity: 1; }
        }

        .map-modal-card {
          position: relative;
          width: 100%;
          max-width: 680px;
          border-radius: 24px;
          background: rgba(255, 255, 255, 0.88);
          backdrop-filter: blur(28px) saturate(1.7);
          -webkit-backdrop-filter: blur(28px) saturate(1.7);
          border: 1px solid rgba(255, 255, 255, 0.95);
          box-shadow:
            0 32px 72px rgba(18, 48, 68, 0.22),
            0 12px 28px rgba(18, 48, 68, 0.12),
            inset 0 1px 0 rgba(255, 255, 255, 0.98),
            inset 0 2px 16px rgba(255, 255, 255, 0.4);
          overflow: hidden;
          animation: map-scale-up 0.28s cubic-bezier(0.16, 1, 0.3, 1) both;
          display: flex;
          flex-direction: column;
        }

        @keyframes map-scale-up {
          from { opacity: 0; transform: translateY(16px) scale(0.96); }
          to   { opacity: 1; transform: translateY(0) scale(1); }
        }

        /* Top catchlight */
        .map-modal-card::before {
          content: '';
          position: absolute;
          inset: 0;
          pointer-events: none;
          z-index: 1;
          border-radius: inherit;
          background: radial-gradient(ellipse 80% 30% at 50% 0%, rgba(255, 255, 255, 0.75) 0%, transparent 70%);
        }

        .map-modal-header {
          position: relative;
          z-index: 2;
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          padding: 24px 28px 16px;
          border-bottom: 1px solid rgba(129, 160, 174, 0.18);
        }

        .map-modal-title-group h3 {
          margin: 4px 0 2px;
          font-size: 20px;
          font-weight: 700;
          color: #17324d;
          letter-spacing: -0.02em;
        }

        .map-modal-badge {
          display: inline-block;
          font-size: 10.5px;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.08em;
          color: #138578;
          background: rgba(66, 207, 192, 0.16);
          padding: 3px 9px;
          border-radius: 100px;
          border: 1px solid rgba(66, 207, 192, 0.35);
        }

        .map-modal-subtitle {
          margin: 2px 0 0;
          font-size: 13.5px;
          color: #648194;
        }

        .map-modal-close-btn {
          width: 34px;
          height: 34px;
          border-radius: 50%;
          border: 1px solid rgba(129, 160, 174, 0.25);
          background: rgba(255, 255, 255, 0.65);
          backdrop-filter: blur(8px);
          color: #4a677a;
          font-size: 14px;
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          transition: all 0.18s ease;
        }

        .map-modal-close-btn:hover {
          background: rgba(255, 255, 255, 0.95);
          color: #17324d;
          transform: scale(1.06);
        }

        .map-modal-body {
          position: relative;
          z-index: 2;
          padding: 16px 28px;
        }

        .map-leaflet-wrapper {
          width: 100%;
          height: 320px;
          border-radius: 18px;
          overflow: hidden;
          border: 1.5px solid rgba(66, 207, 192, 0.35);
          box-shadow:
            0 8px 24px rgba(18, 48, 68, 0.08),
            inset 0 0 0 1px rgba(255, 255, 255, 0.6);
        }

        /* Footer */
        .map-modal-footer {
          position: relative;
          z-index: 2;
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 16px 28px 22px;
          border-top: 1px solid rgba(129, 160, 174, 0.18);
          gap: 16px;
          flex-wrap: wrap;
        }

        .map-selection-info {
          flex: 1;
          min-width: 220px;
        }

        .map-selection-hint {
          font-size: 13px;
          color: #7190a1;
        }

        .map-selected-tag {
          display: inline-flex;
          align-items: center;
          gap: 9px;
          padding: 6px 14px;
          background: rgba(220, 248, 245, 0.7);
          border: 1px solid rgba(66, 207, 192, 0.4);
          border-radius: 100px;
          backdrop-filter: blur(8px);
        }

        .map-selected-icon {
          display: inline-flex;
          align-items: center;
          color: #138578;
        }

        .map-selected-text {
          display: flex;
          flex-direction: column;
          line-height: 1.25;
        }

        .map-selected-text strong {
          font-size: 13.5px;
          color: #124d45;
        }

        .map-selected-coords {
          font-size: 11px;
          color: #43827a;
          font-family: monospace;
        }

        .map-resolving-pulse {
          font-size: 12.5px;
          color: #1a6f64;
          font-style: italic;
          animation: pulse-text 1.2s ease-in-out infinite;
        }

        @keyframes pulse-text {
          0%, 100% { opacity: 0.6; }
          50% { opacity: 1; }
        }

        .map-modal-actions {
          display: flex;
          gap: 10px;
          align-items: center;
        }

        .map-btn-secondary {
          padding: 9px 18px;
          border-radius: 100px;
          border: 1px solid rgba(129, 160, 174, 0.32);
          background: rgba(255, 255, 255, 0.6);
          color: #4a677a;
          font-size: 14px;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.16s ease;
        }

        .map-btn-secondary:hover {
          background: rgba(255, 255, 255, 0.9);
          color: #17324d;
        }

        .map-btn-primary {
          padding: 9px 22px;
          border-radius: 100px;
          border: 0;
          background: linear-gradient(135deg, #42cfc0 0%, #2dbba9 100%);
          color: #0b2b27;
          font-size: 14px;
          font-weight: 600;
          cursor: pointer;
          box-shadow: 0 4px 14px rgba(66, 207, 192, 0.35);
          transition: all 0.18s cubic-bezier(0.16, 1, 0.3, 1);
        }

        .map-btn-primary:hover:not(:disabled) {
          transform: translateY(-1px) scale(1.02);
          box-shadow: 0 6px 20px rgba(66, 207, 192, 0.5);
          background: linear-gradient(135deg, #4ce0d0 0%, #32cbb8 100%);
        }

        .map-btn-primary:disabled {
          opacity: 0.45;
          cursor: not-allowed;
          box-shadow: none;
        }

        /* ── Leaflet Custom Glass Pin ── */
        .map-glass-pin-wrapper {
          background: transparent;
          border: none;
        }

        .map-glass-pin {
          position: relative;
          width: 36px;
          height: 44px;
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .map-glass-pin-head {
          position: relative;
          width: 30px;
          height: 30px;
          border-radius: 50% 50% 50% 0;
          transform: rotate(-45deg);
          background: linear-gradient(135deg, #42cfc0 0%, #158b7c 100%);
          border: 2px solid #ffffff;
          box-shadow:
            0 4px 12px rgba(18, 48, 68, 0.35),
            inset 0 1px 2px rgba(255, 255, 255, 0.6);
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .map-glass-pin-dot {
          width: 10px;
          height: 10px;
          border-radius: 50%;
          background: #ffffff;
          transform: rotate(45deg);
          box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
        }

        .map-glass-pin-pulse {
          position: absolute;
          bottom: 2px;
          left: 50%;
          transform: translateX(-50%);
          width: 20px;
          height: 8px;
          border-radius: 50%;
          background: rgba(66, 207, 192, 0.5);
          animation: pin-shadow-pulse 1.8s ease-in-out infinite;
        }

        @keyframes pin-shadow-pulse {
          0%, 100% { transform: translateX(-50%) scale(1); opacity: 0.6; }
          50%       { transform: translateX(-50%) scale(1.4); opacity: 0.2; }
        }
      `}</style>
    </div>
  )
}
