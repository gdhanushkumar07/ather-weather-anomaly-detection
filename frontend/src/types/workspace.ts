/**
 * SkyGuard AI information architecture.
 *
 * 'home'      public landing page
 * 'overview'  what is happening across the network right now
 * 'map'       live map — where is it happening
 * 'incidents' operational incident queue: lifecycle, work orders, reports
 * 'anomalies' investigations — technical deep dive (URL /investigations)
 * 'testlab'   validation environment, separate from operations
 * 'station'   focused station context (entered from the product)
 * 'system'    pipeline and data-source health (entered from the live indicator)
 */
export type Workspace = 'home' | 'overview' | 'map' | 'station' | 'incidents' | 'anomalies' | 'testlab' | 'system';
