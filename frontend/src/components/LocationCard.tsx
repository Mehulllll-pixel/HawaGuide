import React from 'react';
import type { LocationItem } from '../api/types';
import { getPeviColor, getPeviNormalized } from '../utils/peviColor';

interface LocationCardProps {
  location: LocationItem;
  rank: number;           // 1-indexed position in the currently filtered+sorted list
  totalVisible: number;   // total cards visible in the current view
  onClick?: (location: LocationItem) => void;
}

export const LocationCard: React.FC<LocationCardProps> = ({
  location,
  rank,
  totalVisible,
  onClick,
}) => {
  const hasData = location.data_available && location.current_pevi !== null;
  const peviVal = location.current_pevi;

  // Perceptually-eased ambient background wash
  const ambientBgWash = hasData
    ? getPeviColor(peviVal, 3.12, 7.07, 0.22)
    : 'rgba(255, 255, 255, 0.02)';

  const accentColor = hasData
    ? getPeviColor(peviVal, 3.12, 7.07)
    : 'var(--text-muted)';

  const cardBorderColor = hasData
    ? getPeviColor(peviVal, 3.12, 7.07, 0.28)
    : 'var(--border-subtle)';

  // Exposure bar — normalized position in the full PEVI range
  const exposureBarPct = hasData
    ? Math.round(getPeviNormalized(peviVal, 3.12, 7.07) * 100)
    : 0;

  // Rank-based visual hierarchy — cleanest (#1) and worst (last) get elevated weight
  const isBest = rank === 1;
  const isWorst = rank === totalVisible;
  const isAnchor = isBest || isWorst;

  const borderWidth = isAnchor ? '2px' : '1px';
  const peviTextSize = isBest ? '44px' : isWorst ? '42px' : '38px';

  return (
    <div
      className={`location-card ${!hasData ? 'unavailable' : ''} ${isAnchor ? 'anchor-card' : ''}`}
      style={{
        backgroundColor: ambientBgWash,
        borderColor: cardBorderColor,
        borderWidth,
      }}
      onClick={() => onClick?.(location)}
    >
      {/* Best/Worst anchor label */}
      {hasData && isAnchor && (
        <div
          className="card-anchor-label"
          style={{ color: accentColor, borderColor: getPeviColor(peviVal, 3.12, 7.07, 0.35) }}
        >
          {isBest ? 'Cleanest in view' : 'Highest exposure'}
        </div>
      )}

      {/* Top row: Name and Zone */}
      <div className="card-header">
        <div>
          <h3 className="card-title">{location.name}</h3>
          {location.zone && <p className="card-zone">{location.zone}</p>}
        </div>
      </div>

      {/* Main Metric Section */}
      {hasData ? (
        <div className="card-metric-container">
          <div className="card-pevi-display">
            <span className="pevi-number" style={{ color: accentColor, fontSize: peviTextSize }}>
              {peviVal?.toFixed(2)}
            </span>
            <span className="pevi-unit">PEVI</span>
          </div>

          {/* Quiet Plain-Text Risk Band Label */}
          <div className="card-risk-band-plain">
            {location.personalized_risk_band || 'Relative Risk'}
          </div>

          {/* Key Pollutants Summary */}
          {location.pollutants && (
            <div className="card-pollutants-row">
              <div className="pollutant-mini-stat">
                <span className="stat-label">PM2.5</span>
                <span className="stat-value">{location.pollutants.pm25.toFixed(1)} µg/m³</span>
              </div>
              <div className="pollutant-mini-stat">
                <span className="stat-label">PM10</span>
                <span className="stat-value">{location.pollutants.pm10.toFixed(1)} µg/m³</span>
              </div>
            </div>
          )}

          {/* Exposure Bar — shows where this park sits in the full PEVI range */}
          <div className="exposure-bar-track" title={`PEVI ${peviVal?.toFixed(2)} — ${exposureBarPct}% of full range`}>
            <div
              className="exposure-bar-fill"
              style={{
                width: `${exposureBarPct}%`,
                background: `linear-gradient(90deg, ${getPeviColor(peviVal, 3.12, 7.07, 0.55)}, ${accentColor})`,
              }}
            />
            <div
              className="exposure-bar-tip"
              style={{ left: `${exposureBarPct}%`, backgroundColor: accentColor }}
            />
          </div>
        </div>
      ) : (
        <div className="card-unavailable-container">
          <span className="unavailable-title">Data Unavailable</span>
          <p className="unavailable-desc">
            Spatial kriging interpolation will resume on the next scheduled data cycle.
          </p>
        </div>
      )}

      <style>{`
        .location-card {
          position: relative;
          display: flex;
          flex-direction: column;
          justify-content: space-between;
          padding: 22px 24px 18px 24px;
          border-radius: var(--radius-lg);
          border: 1px solid var(--border-subtle);
          background: var(--bg-card);
          backdrop-filter: blur(12px);
          transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
          text-align: left;
          min-height: 200px;
          cursor: pointer;
        }

        .location-card.anchor-card {
          box-shadow: 0 0 0 1px rgba(255,255,255,0.06) inset;
        }

        .location-card:hover {
          transform: translateY(-3px);
          box-shadow: 0 12px 30px -8px rgba(0, 0, 0, 0.45);
          background-color: rgba(30, 42, 74, 0.65);
          border-color: var(--border-active);
        }

        .location-card.unavailable {
          opacity: 0.6;
          cursor: default;
        }

        .location-card.unavailable:hover {
          transform: none;
          box-shadow: none;
        }

        .card-anchor-label {
          display: inline-block;
          font-size: 11px;
          font-weight: 700;
          letter-spacing: 0.6px;
          text-transform: uppercase;
          padding: 3px 8px;
          border: 1px solid;
          border-radius: var(--radius-sm);
          margin-bottom: 10px;
          background: rgba(0,0,0,0.15);
        }

        .card-header {
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          margin-bottom: 12px;
        }

        .card-title {
          font-family: var(--font-sans);
          font-size: 17px;
          font-weight: 600;
          color: var(--text-primary);
          line-height: 1.3;
          margin-bottom: 3px;
        }

        .card-zone {
          font-size: 13px;
          color: var(--text-secondary);
          font-weight: 400;
        }

        .card-metric-container {
          display: flex;
          flex-direction: column;
          gap: 5px;
        }

        .card-pevi-display {
          display: flex;
          align-items: baseline;
          gap: 6px;
        }

        .pevi-number {
          font-family: var(--font-serif);
          font-weight: 600;
          line-height: 1;
          letter-spacing: -0.5px;
          transition: font-size 0.2s;
        }

        .pevi-unit {
          font-size: 12px;
          font-weight: 600;
          color: var(--text-muted);
          letter-spacing: 0.5px;
        }

        .card-risk-band-plain {
          font-size: 13.5px;
          font-weight: 400;
          color: var(--text-secondary);
          letter-spacing: 0.1px;
        }

        .card-pollutants-row {
          display: flex;
          gap: 16px;
          margin-top: 8px;
          padding-top: 8px;
          border-top: 1px solid rgba(255, 255, 255, 0.05);
        }

        .pollutant-mini-stat {
          display: flex;
          gap: 6px;
          align-items: center;
          font-size: 12px;
        }

        .stat-label {
          color: var(--text-muted);
          font-weight: 500;
        }

        .stat-value {
          color: var(--text-secondary);
          font-weight: 600;
        }

        /* ── Exposure Bar ─────────────────────────────────────── */
        .exposure-bar-track {
          position: relative;
          margin-top: 14px;
          height: 4px;
          background: rgba(255, 255, 255, 0.07);
          border-radius: 99px;
          overflow: visible;
        }

        .exposure-bar-fill {
          height: 100%;
          border-radius: 99px;
          transition: width 0.6s cubic-bezier(0.16, 1, 0.3, 1);
          min-width: 4px;
        }

        .exposure-bar-tip {
          position: absolute;
          top: 50%;
          transform: translate(-50%, -50%);
          width: 8px;
          height: 8px;
          border-radius: 50%;
          box-shadow: 0 0 6px currentColor;
          transition: left 0.6s cubic-bezier(0.16, 1, 0.3, 1);
        }

        /* ── Unavailable state ───────────────────────────────── */
        .card-unavailable-container {
          display: flex;
          flex-direction: column;
          gap: 6px;
          padding: 12px 0 4px 0;
        }

        .unavailable-title {
          font-size: 14px;
          font-weight: 600;
          color: var(--text-muted);
        }

        .unavailable-desc {
          font-size: 12.5px;
          color: var(--text-dim);
          line-height: 1.4;
        }
      `}</style>
    </div>
  );
};
