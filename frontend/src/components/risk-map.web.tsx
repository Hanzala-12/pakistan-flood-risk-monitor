import { useEffect, useRef } from 'react';
import { StyleSheet, View } from 'react-native';
import { useRouter } from 'expo-router';
import type { Map as LeafletMap, GeoJSON as LeafletGeoJSON } from 'leaflet';
// Leaflet's own stylesheet — without it, .leaflet-container has no
// `overflow: hidden` / pane-positioning rules, so correctly-positioned
// tiles visually spill outside the container instead of being clipped to
// it. This is a plain CSS import, safe here since this file only ever
// loads on web (Metro's platform resolution), same pattern as global.css
// in constants/theme.ts.
import 'leaflet/dist/leaflet.css';

import { riskColor } from '@/constants/risk';
import type { DistrictSummary } from '@/types/district';

// Web map, built with Leaflet directly (not react-leaflet) so this has no
// coupling to react-leaflet's own React-version support — Leaflet itself is
// framework-agnostic, we just drive its imperative API from a plain DOM node
// via refs. This is the real map for web (see index.tsx: same <RiskMap>
// component is used on every platform now); risk-map.tsx (react-native-maps)
// is the native counterpart Metro picks for iOS/Android builds.

const INITIAL_CENTER: [number, number] = [27.2, 68.5];
const INITIAL_ZOOM = 7;

export function RiskMap({ districts }: { districts: DistrictSummary[] }) {
  const router = useRouter();
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<LeafletMap | null>(null);
  const layerGroupRef = useRef<LeafletGeoJSON | null>(null);
  const resizeObserverRef = useRef<ResizeObserver | null>(null);

  // Create the map once.
  useEffect(() => {
    let cancelled = false;
    let map: LeafletMap | undefined;

    // Leaflet touches `window`/`document` at import time, so it must be a
    // dynamic import here rather than a top-level one — this file is only
    // ever loaded on web (Metro's platform resolution), but a top-level
    // `import 'leaflet'` still runs during any server-side render pass.
    import('leaflet').then((L) => {
      if (cancelled || !containerRef.current || mapRef.current) return;

      // Marker icon URLs Leaflet's CSS expects aren't bundled by Metro's
      // asset pipeline the way a plain webpack/CRA app would; district
      // polygons don't need markers, so point icon URLs at Leaflet's own
      // CDN copy rather than fighting the bundler over unused assets.
      delete (L.Icon.Default.prototype as any)._getIconUrl;
      L.Icon.Default.mergeOptions({
        iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
        iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
        shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
      });

      map = L.map(containerRef.current, {
        center: INITIAL_CENTER,
        zoom: INITIAL_ZOOM,
      });
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        maxZoom: 18,
      }).addTo(map);
      mapRef.current = map;

      // React Native Web's flex layout resolves the container's real size
      // asynchronously after mount, so Leaflet often initializes against a
      // 0x0 (or stale) box and caches that in its internal pixel projection
      // — every polygon then renders collapsed to a single point, even
      // though the GeoJSON coordinates going in are completely correct.
      //
      // A naive `new ResizeObserver(() => map.invalidateSize())` looks like
      // the fix but isn't: flex layout can settle through several
      // intermediate sizes in one mount, firing the observer several times
      // in quick succession. Each invalidateSize() recomputes Leaflet's tile
      // grid for whatever size was current *then*; overlapping that with the
      // next call's grid — without waiting for the first to finish — left
      // tiles scattered across a ~1800x2300px area for a 902x614 container
      // (verified via getBoundingClientRect on the actual <img> tiles).
      // Debouncing to the last resize in a burst fixes it.
      let debounce: ReturnType<typeof setTimeout> | undefined;
      const resizeObserver = new ResizeObserver(() => {
        clearTimeout(debounce);
        debounce = setTimeout(() => map?.invalidateSize({ animate: false, pan: false }), 100);
      });
      resizeObserver.observe(containerRef.current);
      resizeObserverRef.current = resizeObserver;
    });

    return () => {
      cancelled = true;
      resizeObserverRef.current?.disconnect();
      resizeObserverRef.current = null;
      map?.remove();
      mapRef.current = null;
    };
  }, []);

  // Keep district polygons in sync with the latest data, without rebuilding the map itself.
  useEffect(() => {
    let cancelled = false;

    import('leaflet').then((L) => {
      const map = mapRef.current;
      if (cancelled || !map) return;

      layerGroupRef.current?.remove();

      const featureCollection = {
        type: 'FeatureCollection' as const,
        features: districts.map((d) => ({
          type: 'Feature' as const,
          properties: { id: d.id, name: d.name, risk_level: d.risk_level },
          geometry: d.geometry as GeoJSON.Geometry,
        })),
      };

      const layer = L.geoJSON(featureCollection, {
        style: (feature) => {
          const color = riskColor(feature?.properties.risk_level);
          return { color, weight: 2, fillColor: color, fillOpacity: 0.35 };
        },
        onEachFeature: (feature, geoLayer) => {
          geoLayer.bindTooltip(feature.properties.name);
          geoLayer.on('click', () => router.push(`/district/${feature.properties.id}`));
          geoLayer.on('mouseover', () => (geoLayer as L.Path).setStyle({ fillOpacity: 0.6 }));
          geoLayer.on('mouseout', () => (geoLayer as L.Path).setStyle({ fillOpacity: 0.35 }));
        },
      }).addTo(map);

      layerGroupRef.current = layer;
    });

    return () => {
      cancelled = true;
    };
  }, [districts, router]);

  return (
    <View style={styles.flex}>
      <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
});
