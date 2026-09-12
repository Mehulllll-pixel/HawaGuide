/**
 * peviPersonalize.ts
 *
 * Client-side mirror of the optimizer.py Personalized PEVI formula.
 * Keeps multipliers and band thresholds in exact sync with the Python backend.
 *
 * Formula:
 *   Personalized_PEVI = base_pevi × age_mult × cond_mult × dur_mult
 *
 * Multipliers (from optimizer.py):
 *   age_mult : child | elderly → 1.3 ;  adult → 1.0
 *   cond_mult: respiratory | cardiac → 1.5 ; none → 1.0
 *   dur_mult : 1 + 0.15 × duration_hours
 *
 * Personalized band thresholds (NOT the base quartile thresholds):
 *   Low      ≤ 6.00
 *   Moderate ≤ 7.70
 *   High     ≤ 10.30
 *   Extreme  > 10.30
 */

export type AgeGroup = 'child' | 'adult' | 'elderly'
export type Condition = 'none' | 'respiratory' | 'cardiac'

export interface HealthProfile {
  ageGroup: AgeGroup
  condition: Condition
  durationHours: number
}

export const DEFAULT_PROFILE: HealthProfile = {
  ageGroup: 'adult',
  condition: 'none',
  durationHours: 1,
}

export function isDefaultProfile(p: HealthProfile): boolean {
  return (
    p.ageGroup === DEFAULT_PROFILE.ageGroup &&
    p.condition === DEFAULT_PROFILE.condition &&
    p.durationHours === DEFAULT_PROFILE.durationHours
  )
}

// ── Multipliers (mirror optimizer.py exactly) ─────────────────────────────
export function getAgeMultiplier(ageGroup: AgeGroup): number {
  return ageGroup === 'child' || ageGroup === 'elderly' ? 1.3 : 1.0
}

export function getConditionMultiplier(condition: Condition): number {
  return condition === 'respiratory' || condition === 'cardiac' ? 1.5 : 1.0
}

export function getDurationMultiplier(hours: number): number {
  return 1.0 + 0.15 * Math.max(0, hours)
}

// ── Core calculation ──────────────────────────────────────────────────────
export function calculatePersonalizedPevi(
  basePevi: number,
  profile: HealthProfile,
): number {
  const ageMult = getAgeMultiplier(profile.ageGroup)
  const condMult = getConditionMultiplier(profile.condition)
  const durMult = getDurationMultiplier(profile.durationHours)
  return Math.round(basePevi * ageMult * condMult * durMult * 10000) / 10000
}

// ── Personalized band (uses personalized thresholds, NOT base quartiles) ──
export function getPersonalizedBand(persPevi: number): string {
  if (persPevi <= 6.0) return 'Low'
  if (persPevi <= 7.7) return 'Moderate'
  if (persPevi <= 10.3) return 'High'
  return 'Extreme'
}

// ── Advisory guidance (mirrors get_personalized_guidance in optimizer.py) ─
export function getPersonalizedGuidance(persPevi: number): string {
  if (persPevi <= 6.0) {
    return 'Great conditions for outdoor activities and exercise.'
  }
  if (persPevi <= 7.7) {
    return 'Acceptable for most outdoor activities; sensitive groups may want shorter outdoor sessions.'
  }
  if (persPevi <= 10.3) {
    return 'Higher air pollution exposure; sensitive groups may want to reduce strenuous outdoor activity.'
  }
  return 'Significantly elevated exposure; consider indoor activities or choosing a lower-risk nearby location.'
}

// ── localStorage persistence ──────────────────────────────────────────────
const LS_KEY = 'hawaguide_health_profile'

export function loadProfile(): HealthProfile {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (!raw) return { ...DEFAULT_PROFILE }
    const parsed = JSON.parse(raw) as Partial<HealthProfile>
    return {
      ageGroup: (['child', 'adult', 'elderly'] as AgeGroup[]).includes(
        parsed.ageGroup as AgeGroup,
      )
        ? (parsed.ageGroup as AgeGroup)
        : DEFAULT_PROFILE.ageGroup,
      condition: (['none', 'respiratory', 'cardiac'] as Condition[]).includes(
        parsed.condition as Condition,
      )
        ? (parsed.condition as Condition)
        : DEFAULT_PROFILE.condition,
      durationHours:
        typeof parsed.durationHours === 'number' && parsed.durationHours >= 0
          ? parsed.durationHours
          : DEFAULT_PROFILE.durationHours,
    }
  } catch {
    return { ...DEFAULT_PROFILE }
  }
}

export function saveProfile(profile: HealthProfile): void {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(profile))
  } catch {
    // ignore — storage might be unavailable in private mode
  }
}

export function clearProfile(): void {
  try {
    localStorage.removeItem(LS_KEY)
  } catch {
    // ignore
  }
}

// ── Human-readable profile label ─────────────────────────────────────────
export function profileLabel(profile: HealthProfile): string {
  const age = profile.ageGroup.charAt(0).toUpperCase() + profile.ageGroup.slice(1)
  const cond =
    profile.condition === 'none'
      ? 'No condition'
      : profile.condition.charAt(0).toUpperCase() + profile.condition.slice(1)
  const dur = `${profile.durationHours}h`
  return `${age} · ${cond} · ${dur}`
}
