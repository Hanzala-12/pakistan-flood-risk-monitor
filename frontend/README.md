# Frontend — Pakistan Flood Risk Monitor

Expo (React Native) app: a map screen colored by district risk level, and a
detail screen with the signal breakdown + 30-day trend. See
[`../files/IMPLEMENTATION_PLAN.md`](../files/IMPLEMENTATION_PLAN.md) section 8.

Scaffolded with `create-expo-app` (SDK 57, Expo Router, TypeScript). Primary
target is iOS/Android — `react-native-maps` is a native module with no real
web renderer (see "Web support" below).

## Running it

```bash
npm install
npx expo start
```

Then press `i` (iOS simulator), `a` (Android emulator), or scan the QR code
with Expo Go on a physical device.

**Point it at the backend** — the API base URL is read from
`EXPO_PUBLIC_API_URL` at build time (see `src/api/client.ts`), defaulting to
`http://localhost:8000`. That default only reaches the backend from:
- Web (same machine)
- iOS simulator (shares the host's network)

For anything else, create `frontend/.env`:

```
# Android emulator -> host machine loopback
EXPO_PUBLIC_API_URL=http://10.0.2.2:8000

# Physical device on the same Wi-Fi -> your machine's LAN IP
EXPO_PUBLIC_API_URL=http://192.168.1.23:8000
```

## Structure

```
src/
  app/                  Expo Router screens (file-based routing)
    index.tsx           Map screen
    district/[id].tsx   District detail screen
    _layout.tsx         Stack navigator
  api/client.ts         Typed fetch wrapper for the 3 backend endpoints
  types/district.ts     Mirrors backend/app/schemas.py — keep in sync
  components/
    risk-map.tsx         Native map (react-native-maps) — iOS/Android only
    risk-map.web.tsx      Web stub (see below)
    risk-badge.tsx, signal-bar.tsx, history-chart.tsx
  constants/risk.ts      Risk-level -> color, shared by map + badges
```

## Web support (best-effort, not the primary target)

`react-native-maps` has no working web renderer in this Expo SDK — even
importing it crashes a web bundle (`codegenNativeComponent is not a
function`). `risk-map.tsx` / `risk-map.web.tsx` is a platform-split pair:
Metro picks `risk-map.web.tsx` (a no-op stub) for the web build, so the
native module is never bundled there at all. `app/index.tsx` renders a
ranked district list on web instead of the map.

`app.json`'s web output is set to `"single"` (client-rendered SPA) rather
than `"static"` (server-side prerendering): `"static"` tries to
server-render every route in Node, and `react-native-svg` (used by
`history-chart.tsx`) hits the same native-codegen problem in that
environment. `"single"` avoids SSR entirely, which is enough for this app's
web fallback to work.

## Known harmless lint warning

`npx expo lint` flags `src/hooks/use-color-scheme.web.ts` (a file from the
Expo template, not written for this project) for calling `setState`
synchronously inside a `useEffect`. That's the standard hydration pattern
for that hook and matches the same pattern used deliberately elsewhere in
this app (fetch-on-mount in `index.tsx` / `district/[id].tsx`, both with an
explaining comment) — left as-is rather than reworking Expo's own generated
file for a lint nitpick.

## Maps API key (production Android builds only)

Expo Go / dev builds render Google Maps on Android using a shared testing
key. A production build needs your own key added via the `react-native-maps`
config plugin in `app.json`:

```json
"plugins": [["react-native-maps", { "androidGoogleMapsApiKey": "YOUR_KEY" }]]
```

iOS uses Apple Maps by default and needs no key.
