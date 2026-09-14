import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';

import { api, ApiError } from '@/api/client';
import { RiskMap } from '@/components/risk-map';
import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { riskColor } from '@/constants/risk';
import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import type { DistrictSummary } from '@/types/district';

export default function MapScreen() {
  const [districts, setDistricts] = useState<DistrictSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const data = await api.listDistricts();
      setDistricts(data);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    // Fetch-on-mount (see the same note in district/[id].tsx).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  if (districts === null && !error) {
    return (
      <ThemedView style={styles.center}>
        <ActivityIndicator size="large" />
        <ThemedText type="small" themeColor="textSecondary" style={{ marginTop: Spacing.two }}>
          Loading districts…
        </ThemedText>
      </ThemedView>
    );
  }

  if (error) {
    return (
      <ThemedView style={styles.center}>
        <ThemedText type="subtitle">Can’t reach the backend</ThemedText>
        <ThemedText type="small" themeColor="textSecondary" style={styles.errorText}>
          {error}
        </ThemedText>
        <ThemedText type="small" themeColor="textSecondary" style={styles.errorText}>
          Is the FastAPI server running? See frontend/README.md for how to point the app at it.
        </ThemedText>
      </ThemedView>
    );
  }

  // Same component on every platform now — Metro resolves risk-map.web.tsx
  // (Leaflet) on web and risk-map.tsx (react-native-maps) on iOS/Android.
  return (
    <View style={styles.flex}>
      <RiskMap districts={districts!} />
      <Legend />
    </View>
  );
}

function Legend() {
  const theme = useTheme();
  const levels: ('Low' | 'Moderate' | 'High' | 'Severe')[] = ['Low', 'Moderate', 'High', 'Severe'];
  return (
    <View style={[styles.legend, { backgroundColor: theme.background }]}>
      {levels.map((level) => (
        <View key={level} style={styles.legendRow}>
          <View style={[styles.legendDot, { backgroundColor: riskColor(level) }]} />
          <ThemedText type="small">{level}</ThemedText>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: Spacing.four },
  errorText: { textAlign: 'center', marginTop: Spacing.two },
  legend: {
    position: 'absolute',
    bottom: Spacing.three,
    left: Spacing.three,
    borderRadius: 12,
    padding: Spacing.three,
    gap: 6,
    shadowColor: '#000',
    shadowOpacity: 0.15,
    shadowRadius: 6,
    elevation: 3,
  },
  legendRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  legendDot: { width: 10, height: 10, borderRadius: 5 },
});
