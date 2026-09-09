/**
 * Types representing the HawaGuide API responses and data shapes.
 */

export interface PollutantBreakdown {
  pm25: number;
  pm10: number;
  no2: number;
  so2: number;
  o3: number;
  co: number;
}

export interface LocationItem {
  id?: number | null;
  name: string;
  zone?: string | null;
  lat: number;
  lon: number;
  data_available: boolean;
  current_pevi: number | null;
  personalized_risk_band: string | null;
  advisory_guidance: string;
  pollutants: PollutantBreakdown | null;
  last_updated?: string | null;
}

export interface LocationsResponse {
  status: string;
  disclaimer: string;
  total_locations: number;
  locations: LocationItem[];
}
