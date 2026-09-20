/**
 * ATHER application-level information architecture (UI restructure).
 *
 * 'home' is the marketing / product landing page.
 * 'map', 'overview', 'anomalies', 'health', 'testlab' are operational workspaces.
 * 'station' is the deep diagnostic view for a selected station.
 */
export type Workspace = 'home' | 'overview' | 'map' | 'station' | 'anomalies' | 'health' | 'testlab';
