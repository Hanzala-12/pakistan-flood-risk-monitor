import { StyleSheet, View } from 'react-native';
import MapView, { Polygon } from 'react-native-maps';
import { useRouter } from 'expo-router';

import { riskColor } from '@/constants/risk';
import type { DistrictSummary, GeoJSONGeometry } from '@/types/district';

// Native-only (react-native-maps has no usable web renderer in this SDK —
// importing it at all crashes the web bundle, which is why this file has a
// risk-map.web.tsx sibling; Metro picks whichever matches the platform, so
// react-native-maps is never even bundled for web).

const INITIAL_REGION = {
  latitude: 27.2,
  longitude: 68.5,
  latitudeDelta: 6.5,
  longitudeDelta: 6.5,
};

/** GeoJSON coordinates are [lon, lat]; react-native-maps wants
 * {latitude, longitude}. Returns one ring per polygon part (exterior rings
 * only — interior holes aren't relevant at district-outline scale). */
function geometryToRings(geometry: GeoJSONGeometry): { latitude: number; longitude: number }[][] {
  const polygons = geometry.type === 'MultiPolygon' ? (geometry.coordinates as number[][][][]) : [geometry.coordinates as number[][][]];
  return polygons.map((poly) => poly[0].map(([lon, lat]) => ({ latitude: lat, longitude: lon })));
}

export function RiskMap({ districts }: { districts: DistrictSummary[] }) {
  const router = useRouter();

  return (
    <View style={styles.flex}>
      <MapView style={styles.flex} initialRegion={INITIAL_REGION}>
        {districts.map((d) =>
          geometryToRings(d.geometry).map((ring, i) => (
            <Polygon
              key={`${d.id}-${i}`}
              coordinates={ring}
              fillColor={riskColor(d.risk_level) + '55'}
              strokeColor={riskColor(d.risk_level)}
              strokeWidth={2}
              tappable
              onPress={() => router.push(`/district/${d.id}`)}
            />
          )),
        )}
      </MapView>
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
});
