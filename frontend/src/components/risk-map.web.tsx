import type { DistrictSummary } from '@/types/district';

// Web stub — index.tsx renders DistrictListFallback instead of <RiskMap> on
// web, so this never actually mounts. It exists only so Metro's
// platform-extension resolution picks this file (not risk-map.tsx) for the
// web bundle, keeping react-native-maps — which crashes on web in this SDK
// — out of the web build entirely.
export function RiskMap(_props: { districts: DistrictSummary[] }) {
  return null;
}
