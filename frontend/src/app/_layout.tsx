import { DarkTheme, DefaultTheme, Stack, ThemeProvider } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useColorScheme } from 'react-native';

export default function RootLayout() {
  const colorScheme = useColorScheme();
  return (
    <ThemeProvider value={colorScheme === 'dark' ? DarkTheme : DefaultTheme}>
      {/* headerShown: false — every screen renders its own <AppHeader />
          (components/app-header.tsx) instead of the native Stack header, so
          the mark/back-button/title styling is fully custom. */}
      <Stack screenOptions={{ headerShown: false }}>
        <Stack.Screen name="index" />
        <Stack.Screen name="district/[id]" />
      </Stack>
      <StatusBar style="auto" />
    </ThemeProvider>
  );
}
