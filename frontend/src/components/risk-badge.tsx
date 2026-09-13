import { StyleSheet, View } from 'react-native';

import { ThemedText } from '@/components/themed-text';
import { riskColor } from '@/constants/risk';
import type { RiskLevel } from '@/types/district';

export function RiskBadge({ level }: { level: RiskLevel }) {
  const color = riskColor(level);
  return (
    <View style={[styles.badge, { backgroundColor: color + '22', borderColor: color }]}>
      <View style={[styles.dot, { backgroundColor: color }]} />
      <ThemedText type="smallBold" style={{ color }}>
        {level}
      </ThemedText>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 999,
    borderWidth: 1,
    gap: 6,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
});
