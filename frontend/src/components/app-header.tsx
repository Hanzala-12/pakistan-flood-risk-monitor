import { Pressable, StyleSheet, View } from 'react-native';
import { router } from 'expo-router';

import { ThemedText } from '@/components/themed-text';
import { Spacing } from '@/constants/theme';
import { useTheme } from '@/hooks/use-theme';

/** Branded top bar, used on every screen instead of Expo Router's default
 * native header (headerShown: false in _layout.tsx) — gives full control
 * over the mark/title/back-button styling instead of the plain system bar. */
export function AppHeader({
  title,
  subtitle,
  showBack,
  right,
}: {
  title: string;
  subtitle?: string;
  showBack?: boolean;
  right?: React.ReactNode;
}) {
  const theme = useTheme();
  return (
    <View style={[styles.bar, { backgroundColor: theme.surface, borderBottomColor: theme.border }]}>
      <View style={styles.left}>
        {showBack ? (
          <Pressable
            onPress={() => router.back()}
            hitSlop={10}
            style={({ pressed }) => [styles.backButton, { backgroundColor: pressed ? theme.backgroundElement : 'transparent' }]}
          >
            <ThemedText type="subtitle" style={styles.backChevron}>
              ‹
            </ThemedText>
          </Pressable>
        ) : (
          <View style={[styles.mark, { backgroundColor: theme.primary }]}>
            <ThemedText style={styles.markGlyph}>🌊</ThemedText>
          </View>
        )}
        <View>
          <ThemedText type="smallBold" style={styles.title} numberOfLines={1}>
            {title}
          </ThemedText>
          {subtitle ? (
            <ThemedText type="small" themeColor="textSecondary" style={styles.subtitle} numberOfLines={1}>
              {subtitle}
            </ThemedText>
          ) : null}
        </View>
      </View>
      {right}
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: Spacing.three,
    paddingVertical: Spacing.two,
    borderBottomWidth: 1,
    gap: Spacing.two,
  },
  left: { flexDirection: 'row', alignItems: 'center', gap: Spacing.two, flexShrink: 1 },
  mark: {
    width: 34,
    height: 34,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  markGlyph: { fontSize: 17, lineHeight: 20 },
  backButton: {
    width: 34,
    height: 34,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  backChevron: { fontSize: 24, lineHeight: 26, marginTop: -2 },
  title: { fontSize: 16, letterSpacing: -0.1 },
  subtitle: { fontSize: 12, marginTop: 1 },
});
