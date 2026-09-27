/**
 * ATHER information architecture.
 *
 * 'home'      public landing page
 * 'overview'  what is happening across the network right now
 * 'map'       live map — where is it happening
 * 'anomalies' investigations (URL /investigations)
 * 'testlab'   validation environment, separate from operations
 * 'station'   focused station context (entered from the product)
 * 'system'    pipeline and data-source health (entered from the live indicator)
 */
export type Workspace = 'home' | 'overview' | 'map' | 'station' | 'anomalies' | 'testlab' | 'system';
