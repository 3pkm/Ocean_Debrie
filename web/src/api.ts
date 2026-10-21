import type { Feature, FeatureCollection, Geometry } from 'geojson'

export type PatchStatus = 'active' | 'occluded' | 'lost' | 'split' | 'merged' | 'stranded' | 'expired'

export interface Patch {
  patch_id: string
  parent_id?: string
  status: PatchStatus
  first_seen?: string
  last_seen?: string
  clear_evidence?: number
  latest_obs?: {
    centroid?: { type: 'Point'; coordinates: [number, number] }
    geom?: Geometry
    area_m2?: number
    confidence?: number
    mean_fdi?: number
  }
  geom?: Geometry
  centroid?: { type: 'Point'; coordinates: [number, number] }
}

export interface Zone {
  id?: string | number
  zone_id?: number
  name: string
  geom?: Geometry
  geometry?: Geometry
  risk_tier?: string
  alert_tier?: string
  advisory_threshold?: number
  warning_threshold?: number
  threshold_advisory?: number
  threshold_warning?: number
  properties?: Record<string, unknown>
}

export interface VerificationRecord {
  lead_h: number
  error_km: number
  in_p50?: boolean
  in_p90?: boolean
  persistence_error_km?: number
  currents_only_error_km?: number
  created_at?: string
}

export interface Verification {
  summary?: {
    total_matched?: number
    in_p50_pct?: number
    in_p90_pct?: number
    mean_error_km?: number
    mean_persistence_error_km?: number
    mean_currents_only_error_km?: number
  }
  records?: VerificationRecord[]
}

export interface Freshness {
  last_scene_utc?: string
  last_scene_age_hours?: number
  wind_forecast_updated_utc?: string
  currents_forecast_updated_utc?: string
  last_risk_refresh_utc?: string
  active_patches_count?: number
  occluded_patches_count?: number
  pending_alerts_count?: number
}

export interface Forecast {
  p50?: Geometry
  p90?: Geometry
  centroid?: { type: 'Point'; coordinates: [number, number] }
}

export interface PatchDetail {
  patch?: Patch
  timeline?: Array<{ event?: string; type?: string; description?: string; created_at?: string; timestamp?: string; details?: string }>
  events?: Array<{ event?: string; type?: string; description?: string; created_at?: string; timestamp?: string; details?: string }>
}

const apiBase = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    ...init,
    headers: { Accept: 'application/json', ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...init?.headers },
  })
  const text = await response.text()
  let body: unknown
  try {
    body = text ? JSON.parse(text) : undefined
  } catch {
    body = text
  }
  if (!response.ok) {
    const message = typeof body === 'object' && body !== null && 'error' in body
      ? String((body as { error: unknown }).error)
      : `${response.status} ${response.statusText}`
    throw new Error(message)
  }
  return body as T
}

export function collectionFrom<T>(input: unknown, key: string): T[] {
  if (Array.isArray(input)) return input as T[]
  if (typeof input !== 'object' || input === null) return []
  const record = input as Record<string, unknown>
  if (Array.isArray(record[key])) return record[key] as T[]
  if (record.type === 'FeatureCollection' && Array.isArray(record.features)) {
    return record.features.map((feature) => {
      const item = feature as Feature<Geometry, Record<string, unknown>>
      return { ...item.properties, geom: item.geometry } as T
    })
  }
  return []
}

export function featureCollection(features: Feature<Geometry, Record<string, unknown>>[]): FeatureCollection<Geometry, Record<string, unknown>> {
  return { type: 'FeatureCollection', features }
}
