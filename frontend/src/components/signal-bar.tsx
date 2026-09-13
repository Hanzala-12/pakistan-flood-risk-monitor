import { StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { useTheme } from '@/hooks/use-theme';

export function SignalBar({ label, value, accent, caption }: { label: string; value: number; accent: string; caption?: string }) {
  const theme = useTheme();
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);

  return (
    <View style={styles.row}>
      <View style={styles.labelRow}>
        <ThemedText type="small">{label}</ThemedText>
        <ThemedText type="smallBold">{pct}%</ThemedText>
      </View>
      <View style={[styles.track, { backgroundColor: theme.backgroundElement }]}>
        <View style={[styles.fill, { width: `${pct}%`, backgroundColor: accent }]} />
      </View>
      {caption ? (
        <ThemedText type="small" themeColor="textSecondary" style={styles.caption}>
          {caption}
        </ThemedText>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { gap: 6 },
  labelRow: { flexDirection: 'row', justifyContent: 'space-between' },
  track: { height: 8, borderRadius: 4, overflow: 'hidden' },
  fill: { height: '100%', borderRadius: 4 },
  caption: { marginTop: 2 },
});
