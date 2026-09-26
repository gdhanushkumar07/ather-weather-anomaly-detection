import React from 'react';

interface Props {
  fallback: React.ReactNode;
  children: React.ReactNode;
}

interface State {
  hasError: boolean;
}

/**
 * The AWS model itself is procedural (no async GLB load, so there's no
 * "model failed to load" case) -- but WebGL context creation can still fail
 * (browser without WebGL, context limit reached, etc). This keeps that
 * failure contained to the small station overlay instead of crashing the app.
 */
export class AWSErrorBoundary extends React.Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: unknown) {
    // eslint-disable-next-line no-console
    console.error('AWS 3D model failed to load. Using fallback station marker.', error);
  }

  render() {
    if (this.state.hasError) return this.props.fallback;
    return this.props.children;
  }
}
