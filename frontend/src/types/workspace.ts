/**
 * ATHER application-level information architecture (UI restructure).
 *
 * Exactly one workspace is rendered as the main content area at a time.
 * 'station' is reached only by clicking a station on the Map or an
 * anomaly in the Anomalies workspace — it has no standalone top-nav tab,
 * matching the target architecture (Station Intelligence is a child of
 * Map/Anomalies, not a sibling top-level section).
 */
export type Workspace = 'overview' | 'map' | 'station' | 'anomalies' | 'health' | 'testlab';
