import { useMemo } from 'react';
import { StyleSheet, View } from 'react-native';
import Svg, { Circle, Line, Path } from 'react-native-svg';

import { ThemedText } from '@/components/themed-text';
import { riskColor } from '@/constants/risk';
import { useTheme } from '@/hooks/use-theme';
import type { HistoryPoint } from '@/types/district';

const HEIGHT = 140;
const H_PADDING = 12;
const V_PADDING = 16;

/** Minimal hand-rolled line chart (no charting library) — the plan only
 * asks for "a simple line chart of the last 30 days," and react-native-svg
 * (already needed for map tooling) is enough to draw one without adding
 * another dependency. */
export function HistoryChart({ points, width }: { points: HistoryPoint[]; width: number }) {
  const theme = useTheme();

  const { path, dots, gridY } = useMemo(() => {
    if (points.length === 0) return { path: '', dots: [], gridY: [] as number[] };

    const innerWidth = width - H_PADDING * 2;
    const innerHeight = HEIGHT - V_PADDING * 2;
    const stepX = points.length > 1 ? innerWidth / (points.length - 1) : 0;

    const toXY = (p: HistoryPoint, i: number) => {
      const x = H_PADDING + i * stepX;
      const y = V_PADDING + (1 - Math.max(0, Math.min(1, p.risk_score))) * innerHeight;
      return { x, y };
    };

    const coords = points.map(toXY);
    const d = coords.map((c, i) => `${i === 0 ? 'M' : 'L'} ${c.x.toFixed(1)} ${c.y.toFixed(1)}`).join(' ');
    const dotsOut = coords.map((c, i) => ({ ...c, level: points[i].risk_level }));
    const gridLevels = [0, 0.25, 0.5, 0.75, 1.0].map((v) => V_PADDING + (1 - v) * innerHeight);

    return { path: d, dots: dotsOut, gridY: gridLevels };
  }, [points, width]);

  if (points.length === 0) {
    return (
      <View style={[styles.empty, { height: HEIGHT }]}>
        <ThemedText type="small" themeColor="textSecondary">
          No history yet — trigger a refresh, or run scripts/seed_history.py.
        </ThemedText>
      </View>
    );
  }

  const last = points[points.length - 1];

  return (
    <View>
      <Svg width={width} height={HEIGHT}>
        {gridY.map((y, i) => (
          <Line key={i} x1={H_PADDING} y1={y} x2={width - H_PADDING} y2={y} stroke={theme.backgroundElement} strokeWidth={1} />
        ))}
        <Path d={path} stroke="#3c87f7" strokeWidth={2} fill="none" />
        {dots.map((d, i) => (
          <Circle key={i} cx={d.x} cy={d.y} r={i === dots.length - 1 ? 4 : 2.5} fill={riskColor(d.level)} />
        ))}
      </Svg>
      <ThemedText type="small" themeColor="textSecondary">
        Latest: {last.risk_level} ({Math.round(last.risk_score * 100)}%) on {new Date(last.date).toLocaleDateString()}
      </ThemedText>
    </View>
  );
}

const styles = StyleSheet.create({
  empty: { justifyContent: 'center', alignItems: 'center' },
});
