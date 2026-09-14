import { StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { riskColor } from '@/constants/risk';
import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import type { DistrictSummary, RiskLevel } from '@/types/district';

const LEVELS: RiskLevel[] = ['Low', 'Moderate', 'High', 'Severe'];

/** District-count-by-risk-level strip shown across the top of the map
 * screen — doubles as the map's color legend (each stat's accent dot is
 * the same color as its polygon fill) so a separate floating legend isn't
 * needed. */
export function RiskStatsStrip({ districts }: { districts: DistrictSummary[] }) {
  const theme = useTheme();
  const counts: Record<string, number> = { Low: 0, Moderate: 0, High: 0, Severe: 0 };
  for (const d of districts) {
    if (d.risk_level in counts) counts[d.risk_level] += 1;
  }

  return (
    <View style={[styles.strip, { backgroundColor: theme.surface, borderColor: theme.border }]}>
      {LEVELS.map((level) => (
        <View key={level} style={styles.stat}>
          <View style={styles.labelRow}>
            <View style={[styles.dot, { backgroundColor: riskColor(level) }]} />
            <ThemedText type="small" themeColor="textSecondary" style={styles.label}>
              {level}
            </ThemedText>
          </View>
          <ThemedText type="title" style={[styles.count, { color: riskColor(level) }]}>
            {counts[level]}
          </ThemedText>
        </View>
      ))}
      <View style={styles.stat}>
        <ThemedText type="small" themeColor="textSecondary" style={styles.label}>
          Districts monitored
        </ThemedText>
        <ThemedText type="title" style={styles.count}>
          {districts.length}
        </ThemedText>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  strip: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    borderRadius: 14,
    borderWidth: 1,
    paddingVertical: Spacing.two,
    paddingHorizontal: Spacing.three,
    gap: Spacing.five,
    shadowColor: '#0B1220',
    shadowOpacity: 0.06,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 4 },
    elevation: 2,
  },
  stat: { gap: 2, minWidth: 64 },
  labelRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  label: { fontSize: 12 },
  count: { fontSize: 26, lineHeight: 30 },
});
