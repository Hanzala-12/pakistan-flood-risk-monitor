import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, ScrollView, StyleSheet, View, useWindowDimensions } from 'react-native';
import { useLocalSearchParams } from 'expo-router';

import { api, ApiError } from '@/api/client';
import { AppHeader } from '@/components/app-header';
import { HistoryChart } from '@/components/history-chart';
import { RiskBadge } from '@/components/risk-badge';
import { SignalBar } from '@/components/signal-bar';
import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { MaxContentWidth, Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';
import type { DistrictDetail, HistoryPoint } from '@/types/district';

const CONTENT_PADDING = Spacing.three * 2;
const CARD_PADDING = Spacing.four * 2;

export default function DistrictDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { width } = useWindowDimensions();
  const theme = useTheme();
  // Content is capped at MaxContentWidth and centered on wide screens (see
  // styles.content below) — the chart's own width has to match that capped
  // width, not the full window width, or it overflows/underfills its card.
  const chartWidth = Math.min(width, MaxContentWidth) - CONTENT_PADDING - CARD_PADDING;
  const [detail, setDetail] = useState<DistrictDetail | null>(null);
  const [history, setHistory] = useState<HistoryPoint[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      setError(null);
      const [d, h] = await Promise.all([api.getDistrict(id), api.getDistrictHistory(id, 30)]);
      setDetail(d);
      setHistory(h);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, [id]);

  useEffect(() => {
    // Fetch-on-mount is exactly what this effect is for; the project
    // intentionally uses plain useEffect + fetch instead of a data library
    // (see IMPLEMENTATION_PLAN.md section 8) so the state update below is
    // expected, not an accidental synchronous setState.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  if (error) {
    return (
      <ThemedView style={styles.flex}>
        <AppHeader title="District detail" showBack />
        <ThemedView style={styles.center}>
          <ThemedText type="subtitle">Couldn’t load this district</ThemedText>
          <ThemedText type="small" themeColor="textSecondary" style={styles.errorText}>
            {error}
          </ThemedText>
        </ThemedView>
      </ThemedView>
    );
  }

  if (!detail || !history) {
    return (
      <ThemedView style={styles.flex}>
        <AppHeader title="District detail" showBack />
        <ThemedView style={styles.center}>
          <ActivityIndicator size="large" />
        </ThemedView>
      </ThemedView>
    );
  }

  const s = detail.signals;

  return (
    <ThemedView style={styles.flex}>
      <AppHeader title={detail.name} subtitle={detail.province} showBack />
      <ScrollView contentContainerStyle={styles.content}>
        <View style={[styles.heroCard, { backgroundColor: theme.surface, borderColor: theme.border }]}>
          <View style={styles.heroTop}>
            <View>
              <ThemedText type="small" themeColor="textSecondary">
                Risk score
              </ThemedText>
              <ThemedText type="title" style={styles.heroScore}>
                {Math.round(detail.risk_score * 100)}
                <ThemedText type="subtitle" themeColor="textSecondary">
                  /100
                </ThemedText>
              </ThemedText>
            </View>
            <RiskBadge level={detail.risk_level} />
          </View>
          <ThemedText type="small" themeColor="textSecondary">
            {detail.area_sqkm.toLocaleString()} km² · updated{' '}
            {detail.last_updated ? new Date(detail.last_updated).toLocaleString() : 'never'}
          </ThemedText>
        </View>

        <Section title="Why this score — signal breakdown" theme={theme}>
          <SignalBar
            label="Satellite water anomaly"
            value={s.water_anomaly}
            accent="#2f7bd1"
            caption={
              s.water_source === 'mock'
                ? 'Synthetic demo value — no live satellite pass processed yet (see README).'
                : `From ${s.water_source}${detail.last_satellite_pass ? `, last pass ${new Date(detail.last_satellite_pass).toLocaleDateString()}` : ''}`
            }
          />
          <SignalBar
            label="Rainfall anomaly"
            value={s.rainfall_anomaly}
            accent="#2f9dd1"
            caption={
              s.rainfall_7d_mm != null
                ? `${s.rainfall_7d_mm}mm in the last 7 days vs. a ${s.rainfall_baseline_7d_mm}mm seasonal baseline`
                : undefined
            }
          />
          <SignalBar
            label="Terrain susceptibility"
            value={s.terrain_susceptibility}
            accent="#7a5cc7"
            caption="Static — from elevation, relief, and distance to a major river, computed once (see scripts/compute_terrain_susceptibility.py + compute_river_proximity.py)"
          />
          <SignalBar
            label="Soil moisture anomaly"
            value={s.soil_moisture_anomaly}
            accent="#8a6a3f"
            caption={
              s.soil_moisture_m3m3 != null
                ? `${s.soil_moisture_m3m3} m³/m³ vs. a ${s.soil_moisture_baseline_m3m3} m³/m³ seasonal baseline — how saturated the ground already is, independent of this week's rain`
                : undefined
            }
          />
          <SignalBar
            label="River discharge anomaly"
            value={s.river_discharge_anomaly}
            accent="#1f8fa3"
            caption={
              s.river_discharge_cms != null
                ? `${s.river_discharge_cms} m³/s vs. a ${s.river_discharge_baseline_cms} m³/s seasonal baseline — actual modeled river flow (GloFAS), the most direct signal in this breakdown`
                : undefined
            }
          />
        </Section>

        <Section title="30-day trend" theme={theme}>
          <HistoryChart points={history} width={chartWidth} />
        </Section>
      </ScrollView>
    </ThemedView>
  );
}

function Section({ title, children, theme }: { title: string; children: React.ReactNode; theme: ReturnType<typeof useTheme> }) {
  return (
    <View style={[styles.section, { backgroundColor: theme.surface, borderColor: theme.border }]}>
      <ThemedText type="smallBold" themeColor="textSecondary" style={styles.sectionTitle}>
        {title.toUpperCase()}
      </ThemedText>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: Spacing.four },
  errorText: { textAlign: 'center', marginTop: Spacing.two },
  content: { padding: Spacing.three, gap: Spacing.three, maxWidth: MaxContentWidth, width: '100%', alignSelf: 'center' },
  heroCard: {
    borderRadius: 16,
    borderWidth: 1,
    padding: Spacing.four,
    gap: Spacing.two,
    shadowColor: '#0B1220',
    shadowOpacity: 0.05,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 4 },
    elevation: 1,
  },
  heroTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start' },
  heroScore: { fontSize: 40, lineHeight: 44 },
  section: {
    borderRadius: 16,
    borderWidth: 1,
    padding: Spacing.four,
    gap: Spacing.three,
  },
  sectionTitle: { letterSpacing: 0.6 },
});
