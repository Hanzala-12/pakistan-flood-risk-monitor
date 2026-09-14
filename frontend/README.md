# Frontend — Pakistan Flood Risk Monitor

Expo (React Native) app: a map screen colored by district risk level, and a
detail screen with the signal breakdown + 30-day trend. See
[`../files/IMPLEMENTATION_PLAN.md`](../files/IMPLEMENTATION_PLAN.md) section 8.

Scaffolded with `create-expo-app` (SDK 57, Expo Router, TypeScript). **Web is
the primary target** — the map on web is a real interactive Leaflet map
(district polygons, click-through to detail, zoom/pan), not a fallback. The
same codebase still builds for iOS/Android via `react-native-maps` (Metro
picks whichever `risk-map.*` file matches the platform — see "Structure"
below); that native path hasn't been run on a device or emulator.

## Running it

```bash
npm install
npx expo start
```

Press `w` for web (the primary target — opens in your default browser), or
`i`/`a` for iOS/Android if you want to try the native map (untested on a
real device so far, see below).

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
    risk-map.tsx         Native map (react-native-maps) — iOS/Android only, unverified
    risk-map.web.tsx      Web map (Leaflet, driven imperatively — not react-leaflet)
    risk-badge.tsx, signal-bar.tsx, history-chart.tsx
  constants/risk.ts      Risk-level -> color, shared by map + badges
```

## The web map (`risk-map.web.tsx`)

Built with Leaflet directly — imported dynamically and driven via a plain
DOM ref, not through `react-leaflet` (avoids coupling to whatever React
version `react-leaflet` happens to support; Leaflet itself is
framework-agnostic). `react-native-maps` has no web renderer at all in this
Expo SDK (importing it crashes a web bundle outright), so this is a
genuinely different implementation per platform, not the same map ported —
Metro's platform-extension resolution (`risk-map.tsx` vs. `risk-map.web.tsx`)
picks the right one per build target.

Two real bugs worth knowing about if you touch this file, both only
reproduce with a live map, not in a type-check:

1. **Every polygon collapsing to a single point.** React Native Web's flex
   layout resolves the container's true size *after* mount, so Leaflet
   initializes against a stale/zero-size box and caches that in its pixel
   projection — coordinates going in are fine, everything rendered comes out
   degenerate. Fixed with a debounced `ResizeObserver` calling
   `invalidateSize()`. A naive (non-debounced) version of this fix creates a
   *second* bug: flex layout can settle through several sizes in one mount,
   and calling `invalidateSize()` on each one — before the previous call
   finishes — scatters tiles across a canvas several times larger than the
   actual container.
2. **Tiles load correctly but visually spill outside the map container.**
   `leaflet/dist/leaflet.css` was never imported. Without it,
   `.leaflet-container` has no `overflow: hidden` and Leaflet's panes have
   no positioning rules, so correctly-placed tiles aren't clipped to the
   box — this looks exactly like a layout bug (and isn't one).

`app.json`'s web output is set to `"single"` (client-rendered SPA) rather
than `"static"` (server-side prerendering): `"static"` tries to
server-render every route in Node, and `react-native-svg` (used by
`history-chart.tsx`) hits a native-codegen problem in that environment.
`"single"` avoids SSR entirely.

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
