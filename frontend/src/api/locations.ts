import type { LocationsResponse } from './types';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

/**
 * Fetches all 40 Delhi NCR urban green spaces with their current
 * Personalized Exposure Vulnerability Index (PEVI) scores and 6 criteria pollutant levels.
 *
 * @returns Promise<LocationsResponse>
 */
export async function getLocations(): Promise<LocationsResponse> {
  const url = `${API_BASE_URL}/locations`;
  const response = await fetch(url, {
    method: 'GET',
    headers: {
      'Accept': 'application/json',
    },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch locations: ${response.status} ${response.statusText}`);
  }

  const data: LocationsResponse = await response.json();
  return data;
}
