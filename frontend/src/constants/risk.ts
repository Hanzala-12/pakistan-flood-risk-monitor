import type { RiskLevel } from '@/types/district';

// One color scale, used for both the map polygon fill and the risk badges,
// so a district reads the same way wherever it appears in the app.
export const RISK_COLORS: Record<RiskLevel, string> = {
  Low: '#2E9E4F',
  Moderate: '#E0A800',
  High: '#E0632E',
  Severe: '#C62828',
  Unknown: '#8A8F98',
};

export function riskColor(level: RiskLevel): string {
  return RISK_COLORS[level] ?? RISK_COLORS.Unknown;
}
