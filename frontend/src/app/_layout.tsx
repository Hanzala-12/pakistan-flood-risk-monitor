import { DarkTheme, DefaultTheme, Stack, ThemeProvider } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useColorScheme } from 'react-native';

export default function RootLayout() {
  const colorScheme = useColorScheme();
  return (
    <ThemeProvider value={colorScheme === 'dark' ? DarkTheme : DefaultTheme}>
      <Stack screenOptions={{ headerShadowVisible: false }}>
        <Stack.Screen name="index" options={{ title: 'Flood Risk Monitor' }} />
        <Stack.Screen name="district/[id]" options={{ title: 'District detail' }} />
      </Stack>
      <StatusBar style="auto" />
    </ThemeProvider>
  );
}
