/**
 * Standard spherical-to-cartesian conversion for placing a lat/lng coordinate
 * on the surface of a three.js sphere. Longitude offset by 180deg to match
 * the equirectangular UV convention used by the earth.glb texture.
 */
export function latLngToVector3(lat: number, lng: number, radius: number): [number, number, number] {
  const phi = (90 - lat) * (Math.PI / 180);
  const theta = (lng + 180) * (Math.PI / 180);

  const x = -(radius * Math.sin(phi) * Math.cos(theta));
  const z = radius * Math.sin(phi) * Math.sin(theta);
  const y = radius * Math.cos(phi);

  return [x, y, z];
}
