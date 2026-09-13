import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Platform, Pressable, RefreshControl, ScrollView, StyleSheet, View } from 'react-native';
import { useRouter } from 'expo-router';

import { api, ApiError } from '@/api/client';
import { RiskBadge } from '@/components/risk-badge';
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
  const [refreshing, setRefreshing] = useState(false);

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

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
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

  // react-native-maps has no usable web renderer in this SDK — show a simple
  // ranked list there instead (see components/risk-map.web.tsx).
  if (Platform.OS === 'web') {
    return <DistrictListFallback districts={districts!} refreshing={refreshing} onRefresh={onRefresh} />;
  }

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

function DistrictListFallback({
  districts,
  refreshing,
  onRefresh,
}: {
  districts: DistrictSummary[];
  refreshing: boolean;
  onRefresh: () => void;
}) {
  const router = useRouter();
  return (
    <ScrollView
      style={styles.flex}
      contentContainerStyle={styles.listContent}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
    >
      <ThemedText type="small" themeColor="textSecondary" style={{ marginBottom: Spacing.three }}>
        Map polygons need a native build (react-native-maps has no web renderer) — showing districts ranked by risk
        instead. Run this on iOS/Android to see the map.
      </ThemedText>
      {[...districts]
        .sort((a, b) => b.risk_score - a.risk_score)
        .map((d) => (
          <Pressable key={d.id} onPress={() => router.push(`/district/${d.id}`)}>
            <ThemedView type="backgroundElement" style={styles.listRow}>
              <ThemedText type="default">{d.name}</ThemedText>
              <RiskBadge level={d.risk_level} />
            </ThemedView>
          </Pressable>
        ))}
    </ScrollView>
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
  listContent: { padding: Spacing.three },
  listRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: Spacing.three,
    borderRadius: 10,
    marginBottom: Spacing.two,
  },
});
