const EARTH_RADIUS_MI = 3958.8;

/** Polygon ring approximating a circle of radiusMi miles around [lon, lat]. */
export function circlePolygon([lon, lat], radiusMi, steps = 64) {
  const d = radiusMi / EARTH_RADIUS_MI;
  const lat1 = (lat * Math.PI) / 180;
  const lon1 = (lon * Math.PI) / 180;
  const ring = [];
  for (let i = 0; i <= steps; i++) {
    const brng = (2 * Math.PI * i) / steps;
    const lat2 = Math.asin(Math.sin(lat1) * Math.cos(d) + Math.cos(lat1) * Math.sin(d) * Math.cos(brng));
    const lon2 = lon1 + Math.atan2(
      Math.sin(brng) * Math.sin(d) * Math.cos(lat1),
      Math.cos(d) - Math.sin(lat1) * Math.sin(lat2)
    );
    ring.push([(lon2 * 180) / Math.PI, (lat2 * 180) / Math.PI]);
  }
  return ring;
}

/** Coverage rings for each recommended site, as a FeatureCollection. */
export function coverageRings(candidates, radiusMi) {
  return {
    type: "FeatureCollection",
    features: candidates.features.map((f) => ({
      type: "Feature",
      properties: { rank: f.properties.rank },
      geometry: { type: "Polygon", coordinates: [circlePolygon(f.geometry.coordinates, radiusMi)] },
    })),
  };
}
