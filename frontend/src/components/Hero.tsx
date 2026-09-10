import React, { useEffect, useRef } from 'react';
import { getPeviColor, getPeviRgb } from '../utils/peviColor';

interface HeroProps {
  avgPevi: number | null;
  totalLocations: number;
  loading: boolean;
  onAskAgentClick?: () => void;
  onSeeLocationsClick?: () => void;
}

interface Particle {
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
  alpha: number;
  baseAlpha: number;
  phase: number;
}

export const Hero: React.FC<HeroProps> = ({
  avgPevi,
  totalLocations,
  loading,
  onAskAgentClick,
  onSeeLocationsClick,
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  // Dynamic particle speed & density based on real PEVI score
  const effectivePevi = avgPevi ?? 4.8;
  const peviThemeColor = getPeviColor(avgPevi, 3.12, 7.07);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animationFrameId: number;
    let width = (canvas.width = canvas.parentElement?.clientWidth || window.innerWidth);
    let height = (canvas.height = canvas.parentElement?.clientHeight || 640);

    const handleResize = () => {
      if (!canvas || !canvas.parentElement) return;
      width = canvas.width = canvas.parentElement.clientWidth;
      height = canvas.height = canvas.parentElement.clientHeight;
    };

    window.addEventListener('resize', handleResize);

    // Particle calculation
    // Lower PEVI = gentle laminar drift; Higher PEVI = faster turbulent agitation
    const speedMultiplier = 0.35 + ((effectivePevi - 3.12) / (7.07 - 3.12)) * 0.75;
    const count = Math.min(85, Math.floor((width * height) / 14000));

    const particles: Particle[] = [];
    const rgb = getPeviRgb(avgPevi, 3.12, 7.07);

    for (let i = 0; i < count; i++) {
      particles.push({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.45) * speedMultiplier * 0.8,
        vy: -(Math.random() * 0.4 + 0.15) * speedMultiplier,
        radius: Math.random() * 2.2 + 0.8,
        alpha: Math.random() * 0.5 + 0.2,
        baseAlpha: Math.random() * 0.4 + 0.2,
        phase: Math.random() * Math.PI * 2,
      });
    }

    let time = 0;

    const render = () => {
      time += 0.02;
      ctx.clearRect(0, 0, width, height);

      // Render individual particulate aerosols — pure independent drifting dots, no network lines
      for (let i = 0; i < particles.length; i++) {
        const p = particles[i];

        // Update positions with subtle wavy motion
        p.x += p.vx + Math.sin(time + p.phase) * 0.2;
        p.y += p.vy;

        // Wrap around boundaries smoothly
        if (p.x < -10) p.x = width + 10;
        if (p.x > width + 10) p.x = -10;
        if (p.y < -10) p.y = height + 10;
        if (p.y > height + 10) p.y = -10;

        // Breathing alpha oscillation
        const currentAlpha = p.baseAlpha + Math.sin(time * 1.5 + p.phase) * 0.15;
        const safeAlpha = Math.max(0.05, Math.min(0.85, currentAlpha));

        ctx.fillStyle = `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${safeAlpha})`;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
        ctx.fill();
      }

      animationFrameId = requestAnimationFrame(render);
    };

    render();

    return () => {
      window.removeEventListener('resize', handleResize);
      cancelAnimationFrame(animationFrameId);
    };
  }, [avgPevi, effectivePevi]);

  const handleScrollToLocations = () => {
    if (onSeeLocationsClick) {
      onSeeLocationsClick();
    } else {
      const el = document.getElementById('locations-section');
      if (el) {
        el.scrollIntoView({ behavior: 'smooth' });
      }
    }
  };

  return (
    <section className="hero-container">
      {/* Full-bleed atmospheric gradient background */}
      <div className="hero-atmosphere-backdrop" />
      
      {/* Canvas particle visualization */}
      <canvas ref={canvasRef} className="hero-particle-canvas" />

      {/* Hero content container */}
      <div className="container hero-content-wrapper">
        <div className="hero-main-column">
          
          {/* Breathing Live Average Indicator */}
          <div className="hero-pulse-badge">
            <span
              className="hero-pulse-dot"
              style={{
                backgroundColor: peviThemeColor,
                boxShadow: `0 0 12px ${peviThemeColor}`,
              }}
            >
              <span
                className="hero-pulse-ring"
                style={{ borderColor: peviThemeColor }}
              />
            </span>
            <span className="hero-pulse-text">
              {loading ? (
                'Connecting to Delhi NCR PostGIS network...'
              ) : avgPevi !== null ? (
                <>
                  Live Network Average:{' '}
                  <strong style={{ color: peviThemeColor }}>
                    {avgPevi.toFixed(2)} PEVI
                  </strong>{' '}
                  across {totalLocations} parks
                </>
              ) : (
                'Delhi NCR 40 Green Space Sensor Network'
              )}
            </span>
          </div>

          {/* Left-Aligned Fraunces Display Headline */}
          <h1 className="hero-headline">
            Know the air before you breathe it
          </h1>

          {/* Subtext */}
          <p className="hero-subtext">
            Find cleaner air near you — hours before you go. See live air quality across
            40 Delhi NCR green spaces, ranked so you can choose the healthiest park
            for a walk, run, or family outing today.
          </p>

          {/* Action Buttons — No trailing arrows */}
          <div className="hero-button-group">
            <button
              type="button"
              className="hero-btn-primary"
              onClick={onAskAgentClick}
            >
              Ask the agent
            </button>
            <button
              type="button"
              className="hero-btn-secondary"
              onClick={handleScrollToLocations}
            >
              See live conditions
            </button>
          </div>
        </div>
      </div>

      <style>{`
        .hero-container {
          position: relative;
          width: 100%;
          min-height: 560px;
          padding: 80px 0 64px 0;
          display: flex;
          align-items: center;
          background-color: var(--bg-space);
          overflow: hidden;
        }

        .hero-atmosphere-backdrop {
          position: absolute;
          inset: 0;
          pointer-events: none;
          background: 
            radial-gradient(circle at 18% 25%, #1e2a4a 0%, rgba(30, 42, 74, 0.4) 40%, transparent 70%),
            radial-gradient(circle at 85% 75%, #131b33 0%, rgba(19, 27, 51, 0.5) 50%, transparent 80%),
            linear-gradient(180deg, #0a0e1f 0%, #0d1326 50%, #0a0e1f 100%);
          z-index: 1;
        }

        .hero-particle-canvas {
          position: absolute;
          inset: 0;
          width: 100%;
          height: 100%;
          pointer-events: none;
          z-index: 2;
        }

        .hero-content-wrapper {
          position: relative;
          z-index: 3;
        }

        .hero-main-column {
          max-width: 780px;
          text-align: left;
        }

        .hero-pulse-badge {
          display: inline-flex;
          align-items: center;
          gap: 10px;
          padding: 6px 14px;
          background: rgba(19, 27, 51, 0.85);
          border: 1px solid var(--border-subtle);
          border-radius: var(--radius-full);
          backdrop-filter: blur(12px);
          margin-bottom: 28px;
        }

        .hero-pulse-dot {
          position: relative;
          width: 9px;
          height: 9px;
          border-radius: 50%;
          display: inline-block;
        }

        .hero-pulse-ring {
          position: absolute;
          inset: -4px;
          border: 1.5px solid;
          border-radius: 50%;
          animation: hero-breathe 2.4s cubic-bezier(0.4, 0, 0.6, 1) infinite;
          opacity: 0.8;
        }

        @keyframes hero-breathe {
          0% {
            transform: scale(0.85);
            opacity: 0.9;
          }
          50% {
            transform: scale(1.65);
            opacity: 0;
          }
          100% {
            transform: scale(0.85);
            opacity: 0;
          }
        }

        .hero-pulse-text {
          font-size: 13.5px;
          font-weight: 500;
          color: var(--text-secondary);
          letter-spacing: 0.2px;
        }

        .hero-headline {
          font-family: var(--font-serif);
          font-size: 58px;
          font-weight: 600;
          line-height: 1.12;
          letter-spacing: -1.2px;
          color: var(--text-primary);
          margin-bottom: 22px;
          text-wrap: balance;
        }

        @media (max-width: 900px) {
          .hero-headline {
            font-size: 42px;
            letter-spacing: -0.8px;
          }
        }

        @media (max-width: 600px) {
          .hero-headline {
            font-size: 34px;
            letter-spacing: -0.5px;
          }
        }

        .hero-subtext {
          font-size: 17.5px;
          line-height: 1.62;
          color: var(--text-secondary);
          max-width: 660px;
          margin-bottom: 36px;
          font-weight: 400;
        }

        @media (max-width: 600px) {
          .hero-subtext {
            font-size: 15.5px;
          }
        }

        .hero-button-group {
          display: flex;
          align-items: center;
          gap: 16px;
          flex-wrap: wrap;
        }

        .hero-btn-primary {
          background-color: rgba(110, 231, 216, 0.12);
          color: var(--accent-teal);
          border: 1px solid rgba(110, 231, 216, 0.35);
          font-size: 15.5px;
          font-weight: 600;
          padding: 13px 26px;
          border-radius: var(--radius-full);
          transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
          letter-spacing: 0.1px;
        }

        .hero-btn-primary:hover {
          background-color: rgba(110, 231, 216, 0.22);
          border-color: var(--accent-teal);
          transform: translateY(-2px);
        }

        .hero-btn-secondary {
          background-color: rgba(255, 255, 255, 0.05);
          color: var(--text-primary);
          border: 1px solid var(--border-subtle);
          font-size: 15.5px;
          font-weight: 500;
          padding: 13px 24px;
          border-radius: var(--radius-md);
          backdrop-filter: blur(8px);
          transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
        }

        .hero-btn-secondary:hover {
          background-color: rgba(255, 255, 255, 0.1);
          border-color: var(--border-active);
          transform: translateY(-2px);
        }
      `}</style>
    </section>
  );
};
