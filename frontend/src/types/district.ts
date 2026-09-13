// Mirrors backend/app/schemas.py — keep in sync with the API.

export type RiskLevel = 'Low' | 'Moderate' | 'High' | 'Severe' | 'Unknown';

export interface DistrictSummary {
  id: string;
  name: string;
  risk_level: RiskLevel;
  risk_score: number;
  last_updated: string | null;
  geometry: GeoJSONGeometry;
  centroid: [number, number]; // [lon, lat]
}

export interface SignalBreakdown {
  water_anomaly: number;
  rainfall_anomaly: number;
  terrain_susceptibility: number;
  water_source: string;
  rainfall_source: string;
  rainfall_3d_mm: number | null;
  rainfall_7d_mm: number | null;
  rainfall_baseline_7d_mm: number | null;
}

export interface GeoJSONGeometry {
  type: 'Polygon' | 'MultiPolygon';
  coordinates: number[][][] | number[][][][];
}

export interface DistrictDetail {
  id: string;
  name: string;
  province: string;
  risk_level: RiskLevel;
  risk_score: number;
  signals: SignalBreakdown;
  last_satellite_pass: string | null;
  last_updated: string | null;
  geometry: GeoJSONGeometry;
  centroid: [number, number]; // [lon, lat]
  area_sqkm: number;
}

export interface HistoryPoint {
  date: string;
  risk_score: number;
  risk_level: RiskLevel;
}
