import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';

import { api, ApiError } from '@/api/client';
import { AppHeader } from '@/components/app-header';
import { RiskMap } from '@/components/risk-map';
import { RiskStatsStrip } from '@/components/risk-stats-strip';
import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { Spacing } from '@/constants/theme';
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

  return (
    <ThemedView style={styles.flex}>
      <AppHeader title="Flood Risk Monitor" subtitle="Pakistan · Indus Basin, 14 districts" />

      {districts === null && !error ? (
        <ThemedView style={styles.center}>
          <ActivityIndicator size="large" />
          <ThemedText type="small" themeColor="textSecondary" style={{ marginTop: Spacing.two }}>
            Loading districts…
          </ThemedText>
        </ThemedView>
      ) : error ? (
        <ThemedView style={styles.center}>
          <ThemedText type="subtitle">Can’t reach the backend</ThemedText>
          <ThemedText type="small" themeColor="textSecondary" style={styles.errorText}>
            {error}
          </ThemedText>
          <ThemedText type="small" themeColor="textSecondary" style={styles.errorText}>
            Is the FastAPI server running? See frontend/README.md for how to point the app at it.
          </ThemedText>
        </ThemedView>
      ) : (
        // Same map component on every platform — Metro resolves risk-map.web.tsx
        // (Leaflet) on web and risk-map.tsx (react-native-maps) on iOS/Android.
        <View style={styles.flex}>
          <RiskMap districts={districts!} />
          <View style={styles.statsOverlay}>
            <RiskStatsStrip districts={districts!} />
          </View>
        </View>
      )}
    </ThemedView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: Spacing.four },
  errorText: { textAlign: 'center', marginTop: Spacing.two },
  statsOverlay: {
    position: 'absolute',
    top: Spacing.three,
    left: Spacing.three,
    right: Spacing.three,
  },
});
