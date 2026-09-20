import React, { useState, useEffect, useRef } from 'react';
import {
  ArrowRight,
  ShieldCheck,
  Activity,
  Layers,
  Cpu,
  Radio,
  Zap,
  CheckCircle2,
  ChevronRight,
  Compass,
  AlertTriangle,
  Flame,
  Search,
  Sliders,
  TrendingUp,
  MapPin,
  ExternalLink,
  Info,
  Server,
  CloudRain,
  Wind,
  Gauge,
  Thermometer,
  Eye,
  Terminal,
  ShieldAlert,
  SlidersHorizontal,
  Check,
  Layers2,
  Database,
  Menu,
  X
} from 'lucide-react';
import { Workspace } from '../types/workspace';
import { AnomaliesSummary } from '../types/weather';
import './HomePage.css';

interface HomePageProps {
  onLaunchPlatform: (targetWorkspace?: Workspace) => void;
  summary: AnomaliesSummary | null;
}

type SectionKey = 'home' | 'problem' | 'how-it-works' | 'intelligence' | 'technology' | 'live-demo';

export const HomePage: React.FC<HomePageProps> = ({ onLaunchPlatform, summary }) => {
  const [activePipelineStep, setActivePipelineStep] = useState<number>(3); // Default to ECOD Multivariate
  const [activeSection, setActiveSection] = useState<SectionKey>('home');
  const [isScrolled, setIsScrolled] = useState<boolean>(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState<boolean>(false);

  // Keep a ref to avoid infinite updates during scroll
  const isNavClickRef = useRef<boolean>(false);

  // 1. Intersection Observer for Active Section Tracking & URL Hash Sync
  useEffect(() => {
    const sectionIds: SectionKey[] = ['home', 'problem', 'how-it-works', 'intelligence', 'technology', 'live-demo'];

    // Scroll state for navbar background opacity & border strength
    const handleScroll = () => {
      const scrollY = window.scrollY || document.documentElement.scrollTop;
      setIsScrolled(scrollY > 20);
    };
    window.addEventListener('scroll', handleScroll, { passive: true });
    handleScroll();

    // IntersectionObserver with balanced rootMargin
    const observerCallback: IntersectionObserverCallback = (entries) => {
      if (isNavClickRef.current) return;

      // Find the most visible intersecting entry
      const visibleEntries = entries.filter((e) => e.isIntersecting);
      if (visibleEntries.length === 0) return;

      // Sort by intersection ratio or proximity to viewport top
      visibleEntries.sort((a, b) => {
        const topA = Math.abs(a.boundingClientRect.top);
        const topB = Math.abs(b.boundingClientRect.top);
        return topA - topB;
      });

      const current = visibleEntries[0];
      const targetId = current.target.id as SectionKey;

      if (targetId && sectionIds.includes(targetId)) {
        setActiveSection(targetId);

        // Synchronize URL Hash without polluting history entries
        const targetHash = targetId === 'home' ? '' : `#${targetId}`;
        const currentHash = window.location.hash;
        if (targetHash !== currentHash) {
          const newUrl = targetHash ? `${window.location.pathname}${targetHash}` : window.location.pathname;
          window.history.replaceState(null, '', newUrl);
        }
      }
    };

    const observer = new IntersectionObserver(observerCallback, {
      root: null,
      rootMargin: '-15% 0px -55% 0px',
      threshold: [0.05, 0.2, 0.5],
    });

    sectionIds.forEach((id) => {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    });

    // Check direct hash URL on mount (e.g. localhost:3000/#problem)
    if (window.location.hash) {
      const initialId = window.location.hash.replace('#', '') as SectionKey;
      if (sectionIds.includes(initialId)) {
        setActiveSection(initialId);
        setTimeout(() => {
          const targetEl = document.getElementById(initialId);
          if (targetEl) {
            targetEl.scrollIntoView({ behavior: 'smooth' });
          }
        }, 100);
      }
    }

    return () => {
      window.removeEventListener('scroll', handleScroll);
      observer.disconnect();
    };
  }, []);

  // Smooth scroll handler with reliable offset
  const scrollToSection = (sectionId: SectionKey) => {
    isNavClickRef.current = true;
    setActiveSection(sectionId);
    setMobileMenuOpen(false);

    const targetHash = sectionId === 'home' ? '' : `#${sectionId}`;
    const newUrl = targetHash ? `${window.location.pathname}${targetHash}` : window.location.pathname;
    window.history.pushState(null, '', newUrl);

    if (sectionId === 'home') {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } else {
      const el = document.getElementById(sectionId);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth' });
      }
    }

    // Release click guard after animation settles
    setTimeout(() => {
      isNavClickRef.current = false;
    }, 850);
  };

  const pipelineSteps = [
    {
      id: 0,
      code: 'L-01',
      number: '01',
      name: 'DATA SOURCES & QUALITY',
      tag: 'PRE-FILTERING',
      layerType: 'INGESTION LAYER',
      desc: 'Ingests physical Indian AWS telemetry and regional Open-Meteo context with rigorous packet and boundary checks.',
      details: 'Continuously validates timestamps, GPS positions, and physical atmospheric limits (-10°C to 55°C, 0–100% RH, 850–1080 hPa). Discards corrupted packets before multi-layer inference.',
      features: ['Automated AWS Polling', 'Boundary Guardrails', 'Packet CRC Validation'],
    },
    {
      id: 1,
      code: 'L-02',
      number: '02',
      name: 'PHYSICS INTELLIGENCE',
      tag: 'THERMODYNAMICS',
      layerType: 'FIRST PRINCIPLES',
      desc: 'Enforces fundamental thermodynamic laws across temperature, vapor pressure deficit, and barometric lapse rates.',
      details: 'Evaluates empirical saturation curves using the Magnus-Tetens formula. Rejects mathematically impossible states like dew points exceeding ambient dry-bulb temperature.',
      features: ['Magnus-Tetens Formula', 'Barometric Lapse Rate', 'Vapour Pressure Deficit'],
    },
    {
      id: 2,
      code: 'L-03',
      number: '03',
      name: 'TEMPORAL DYNAMICS',
      tag: 'TIME-SERIES',
      layerType: 'RESIDUAL ANALYSIS',
      desc: 'Differentiates true atmospheric squall lines and cold fronts from electrical sensor step-spikes and flatlines.',
      details: 'Tracks rolling rate-of-change (dT/dt, dP/dt), diurnal heating cycles, and zero-variance stuck values to isolate electrical noise from real meteorology.',
      features: ['Rolling Delta Tracking', 'Zero-Variance Isolation', 'Diurnal Curve Matching'],
    },
    {
      id: 3,
      code: 'L-04',
      number: '04',
      name: 'MULTIVARIATE ECOD',
      tag: 'STATISTICAL LEARNING',
      layerType: 'PyOD / ECOD',
      desc: 'Empirical Cumulative Distribution Functions evaluate high-dimensional weather vectors without Gaussian assumptions.',
      details: 'Computes tail probabilities across joint temperature, relative humidity, pressure, and wind dimensions. Uncovers subtle multivariate anomalies that pass 1D scalar bounds.',
      features: ['Non-Parametric Tail Probabilities', 'Multi-Variable Vector Outliers', 'Sub-millisecond Scoring'],
    },
    {
      id: 4,
      code: 'L-05',
      number: '05',
      name: 'SPATIAL CONSISTENCY',
      tag: 'NEIGHBOR CORRELATION',
      layerType: 'k-NN GEOSPATIAL',
      desc: 'Cross-examines target station telemetry against nearest regional AWS nodes within topographic buffers.',
      details: 'Uses inverse-distance weighting and elevation lapse adjustments. If 4 nearby stations report 28°C and one reports 41°C, spatial divergence is flagged immediately.',
      features: ['Elevation-Adjusted IDW', 'Topographic Buffer Consensus', 'Microclimate Heat Island Filtering'],
    },
    {
      id: 5,
      code: 'L-06',
      number: '06',
      name: 'SENSOR HARDWARE HEALTH',
      tag: 'DIAGNOSTICS',
      layerType: 'HARDWARE TELEMETRY',
      desc: 'Monitors channel availability, stuck analog-to-digital voltages, and long-term calibration drift.',
      details: 'Produces a dedicated hardware integrity score (0–100%). Ensures operational engineers know whether to dispatch a physical repair crew or alert forecasters.',
      features: ['Hardware Diagnostic Index', 'Stuck-Value Voltage Check', 'Channel Degradation Tagging'],
    },
    {
      id: 6,
      code: 'L-07',
      number: '07',
      name: 'CONFORMAL EVIDENCE FUSION',
      tag: 'SYNTHESIS',
      layerType: 'CONFIDENCE CALIBRATION',
      desc: 'Aggregates signals from Physics, Temporal, Multivariate, Spatial, and Hardware layers into calibrated confidence.',
      details: 'Combines multi-layer evidence vectors into an interpretable anomaly probability and calibrated severity classification (HIGH / MEDIUM / LOW) with zero black-box opacity.',
      features: ['Multi-Layer Agreement Weighting', 'Calibrated Confidence (0-100%)', 'Uncertainty Estimation'],
    },
    {
      id: 7,
      code: 'L-08',
      number: '08',
      name: 'ROOT CAUSE & ACTION',
      tag: 'OPERATIONAL AI',
      layerType: 'EXPLAINABLE INTELLIGENCE',
      desc: 'Generates human-readable attribution, pinpointing culprit sensors and routing incidents to field dispatch.',
      details: 'Produces operational hypotheses like "Thermodynamic Inconsistency (High Temp + High RH)" with automated lifecycle tracking (New → Investigating → Escalated → Resolved).',
      features: ['Dominant Culprit Attribution', 'Automated Diagnostic Hypothesis', 'One-Click Incident Workflow'],
    },
  ];

  return (
    <div className="ather-home-page">
      {/* ========================================================================= */}
      {/* 00. EDITORIAL TOP NAVIGATION (Always Sticky, Z-Index 1000+, Dynamic State) */}
      {/* ========================================================================= */}
      <header className={`home-top-nav ${isScrolled ? 'scrolled' : 'top-state'}`} aria-label="ATHER Sticky Navigation">
        <div className="home-nav-container">
          {/* Brand Left */}
          <div
            className="home-nav-brand"
            onClick={() => scrollToSection('home')}
            title="ATHER Meteorological Intelligence"
          >
            <div className="home-nav-logo-mark">
              <span className="home-logo-pulse" />
              <Radio className="w-3.5 h-3.5 text-amber-500" />
            </div>
            <div className="home-brand-titles">
              <span className="home-brand-main">ATHER</span>
              <span className="home-brand-sub">WEATHER INTELLIGENCE</span>
            </div>
          </div>

          {/* Center Navigation Pill Container (Desktop) */}
          <nav className="home-nav-pill-wrapper" aria-label="Page Sections">
            <div className="home-nav-pill">
              <button
                type="button"
                className={`home-nav-link ${activeSection === 'home' ? 'active' : ''}`}
                onClick={() => scrollToSection('home')}
              >
                HOME
              </button>
              <button
                type="button"
                className={`home-nav-link ${activeSection === 'problem' ? 'active' : ''}`}
                onClick={() => scrollToSection('problem')}
              >
                PROBLEM
              </button>
              <button
                type="button"
                className={`home-nav-link ${activeSection === 'how-it-works' ? 'active' : ''}`}
                onClick={() => scrollToSection('how-it-works')}
              >
                HOW IT WORKS
              </button>
              <button
                type="button"
                className={`home-nav-link ${activeSection === 'intelligence' ? 'active' : ''}`}
                onClick={() => scrollToSection('intelligence')}
              >
                INTELLIGENCE
              </button>
              <button
                type="button"
                className={`home-nav-link ${activeSection === 'technology' ? 'active' : ''}`}
                onClick={() => scrollToSection('technology')}
              >
                TECHNOLOGY
              </button>
              <button
                type="button"
                className={`home-nav-link home-nav-link-demo ${activeSection === 'live-demo' ? 'active' : ''}`}
                onClick={() => scrollToSection('live-demo')}
              >
                LIVE DEMO
              </button>
            </div>
          </nav>

          {/* Right Action + Mobile Toggle */}
          <div className="home-nav-actions">
            <button
              className="home-cta-button primary nav-cta-btn"
              onClick={() => onLaunchPlatform('map')}
              title="Launch the operational ATHER weather map"
            >
              <span>LAUNCH ATHER</span>
              <ArrowRight className="cta-gold-arrow w-3.5 h-3.5" />
            </button>

            {/* Mobile Hamburger Button */}
            <button
              type="button"
              className="mobile-menu-toggle-btn"
              onClick={() => setMobileMenuOpen((v) => !v)}
              aria-label={mobileMenuOpen ? 'Close Menu' : 'Open Menu'}
            >
              {mobileMenuOpen ? <X className="w-5 h-5 text-dark" /> : <Menu className="w-5 h-5 text-dark" />}
            </button>
          </div>
        </div>

        {/* Mobile Dropdown Navigation Menu */}
        {mobileMenuOpen && (
          <div className="mobile-nav-drawer" aria-label="Mobile Navigation">
            <button
              type="button"
              className={`mobile-nav-item ${activeSection === 'home' ? 'active' : ''}`}
              onClick={() => scrollToSection('home')}
            >
              HOME
            </button>
            <button
              type="button"
              className={`mobile-nav-item ${activeSection === 'problem' ? 'active' : ''}`}
              onClick={() => scrollToSection('problem')}
            >
              PROBLEM
            </button>
            <button
              type="button"
              className={`mobile-nav-item ${activeSection === 'how-it-works' ? 'active' : ''}`}
              onClick={() => scrollToSection('how-it-works')}
            >
              HOW IT WORKS
            </button>
            <button
              type="button"
              className={`mobile-nav-item ${activeSection === 'intelligence' ? 'active' : ''}`}
              onClick={() => scrollToSection('intelligence')}
            >
              INTELLIGENCE
            </button>
            <button
              type="button"
              className={`mobile-nav-item ${activeSection === 'technology' ? 'active' : ''}`}
              onClick={() => scrollToSection('technology')}
            >
              TECHNOLOGY
            </button>
            <button
              type="button"
              className={`mobile-nav-item demo-item ${activeSection === 'live-demo' ? 'active' : ''}`}
              onClick={() => scrollToSection('live-demo')}
            >
              LIVE DEMO
            </button>
            <div className="mobile-drawer-cta">
              <button
                className="home-cta-button primary full-width"
                onClick={() => {
                  setMobileMenuOpen(false);
                  onLaunchPlatform('map');
                }}
              >
                <span>LAUNCH ATHER</span>
                <ArrowRight className="cta-gold-arrow w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        )}
      </header>

      {/* ========================================================================= */}
      {/* 01. SECTION 01 — HERO (#home)                                             */}
      {/* ========================================================================= */}
      <section id="home" className="home-section hero-section">
        <div className="home-container">
          <div className="hero-grid">
            {/* Left Content (48–50%) */}
            <div className="hero-content">
              <div className="editorial-eyebrow">
                <span className="eyebrow-dot" />
                <span>THE INTELLIGENCE LAYER FOR WEATHER STATIONS</span>
              </div>

              <h1 className="hero-headline">
                DETECT WEATHER<br />
                ANOMALIES
                <span className="hero-subline-italic">
                  before they become operational surprises.
                </span>
              </h1>

              <p className="hero-body-text">
                ATHER transforms weather-station observations into explainable anomaly
                intelligence by combining physical consistency, temporal behavior,
                multivariate relationships, spatial context, and sensor health.
              </p>

              <div className="hero-cta-group">
                <button
                  className="home-cta-button primary large hero-primary-cta"
                  onClick={() => onLaunchPlatform('map')}
                  title="Launch the operational ATHER weather map"
                >
                  <span>LAUNCH ATHER</span>
                  <ArrowRight className="cta-gold-arrow w-4 h-4" />
                </button>
                <button
                  type="button"
                  className="home-cta-button secondary large hero-secondary-cta"
                  onClick={() => scrollToSection('how-it-works')}
                  title="Explore the system architecture and intelligence layers"
                >
                  <span>EXPLORE THE SYSTEM</span>
                </button>
              </div>

              {/* Capability Check Labels Under CTA */}
              <div className="hero-capability-row">
                <span className="cap-item">
                  <Check className="w-3.5 h-3.5 text-amber-500" />
                  <span>PHYSICS-AWARE</span>
                </span>
                <span className="cap-item">
                  <Check className="w-3.5 h-3.5 text-amber-500" />
                  <span>MULTI-LAYER DETECTION</span>
                </span>
                <span className="cap-item">
                  <Check className="w-3.5 h-3.5 text-amber-500" />
                  <span>ROOT CAUSE ANALYSIS</span>
                </span>
                <span className="cap-item">
                  <Check className="w-3.5 h-3.5 text-amber-500" />
                  <span>SENSOR HEALTH</span>
                </span>
              </div>
            </div>

            {/* Right Product Visualization Console (50–52%) */}
            <div className="hero-visual">
              <div className="observability-console-card">
                {/* Console Header Bar */}
                <div className="console-header">
                  <div className="console-window-dots">
                    <span className="dot" />
                    <span className="dot" />
                    <span className="dot" />
                  </div>
                  <div className="console-title">
                    <span className="mono-sub">ATHER / STATION INTELLIGENCE</span>
                  </div>
                  <div className="console-status-live demo-badge">
                    <span className="demo-beacon" />
                    <span>DEMO ANALYSIS</span>
                  </div>
                </div>

                {/* Console Body Grid */}
                <div className="console-body">
                  {/* South India Station Network Topology Preview */}
                  <div className="console-network-diagram">
                    <div className="network-grid-layer" />
                    <div className="network-label">SOUTH INDIA AWS MONITORING</div>

                    {/* Nodes (Geographically Coherent with Coimbatore AWS-178) */}
                    <div className="station-node normal n1" title="CBE-101 Coimbatore North (Normal)">
                      <span className="node-dot" />
                      <span className="node-tag">CBE-101</span>
                    </div>

                    <div className="station-node normal n2" title="PLK-042 Palakkad (Normal)">
                      <span className="node-dot" />
                      <span className="node-tag">PLK-042</span>
                    </div>

                    <div className="station-node warning n3" title="TIR-089 Tiruppur (Warning)">
                      <span className="node-dot" />
                      <span className="node-tag">TIR-089</span>
                    </div>

                    <div className="station-node anomaly-active n4" title="AWS-178 Coimbatore South (Active Anomaly)">
                      <span className="node-ping" />
                      <span className="node-dot" />
                      <span className="node-tag">AWS-178 [ANOMALY]</span>
                    </div>

                    {/* Vector Signal Path linking Anomaly to Evidence Panel */}
                    <svg className="node-signal-line" viewBox="0 0 280 120" preserveAspectRatio="none">
                      <path
                        d="M 175 55 C 215 55, 235 75, 275 95"
                        fill="none"
                        stroke="rgba(245, 158, 11, 0.65)"
                        strokeWidth="1.5"
                        strokeDasharray="4 4"
                      />
                    </svg>
                  </div>

                  {/* Active Station Analysis Banner */}
                  <div className="console-station-strip">
                    <div className="console-station-identity">
                      <span className="stn-id-tag">AWS-178</span>
                      <span className="stn-location-tag">Coimbatore South, TN</span>
                    </div>
                    <div className="console-anomaly-pill">
                      <span className="anomaly-pulse-dot" />
                      <span>ANOMALY · 94% CONFIDENCE</span>
                    </div>
                  </div>

                  {/* Telemetry Metrics Row (4 Equal Cards with Derived Mathematically-Consistent Values) */}
                  <div className="console-metrics-row">
                    <div className="metric-box">
                      <div className="metric-label">TEMPERATURE</div>
                      <div className="metric-val">34.8<span className="unit">°C</span></div>
                      <div className="metric-note text-amber-400">+6.2°C vs baseline</div>
                    </div>

                    <div className="metric-box">
                      <div className="metric-label">PRESSURE</div>
                      <div className="metric-val">1001<span className="unit">hPa</span></div>
                      <div className="metric-note text-red-400">−8 hPa vs baseline</div>
                    </div>

                    <div className="metric-box">
                      <div className="metric-label">HUMIDITY</div>
                      <div className="metric-val">91<span className="unit">%</span></div>
                      <div className="metric-note text-red-400">High Vapour</div>
                    </div>

                    <div className="metric-box score-box">
                      <div className="metric-label">CONFIDENCE</div>
                      <div className="metric-val text-red-400">94<span className="unit">%</span></div>
                      <div className="metric-note text-red-300">High Severity</div>
                    </div>
                  </div>

                  {/* Model Evidence Indicators Strip */}
                  <div className="console-mini-evidence-strip">
                    <div className="mini-evi-item">
                      <span className="lbl">PHYSICS</span>
                      <span className="val text-amber-400">82</span>
                    </div>
                    <div className="mini-evi-sep">|</div>
                    <div className="mini-evi-item">
                      <span className="lbl">TEMPORAL</span>
                      <span className="val text-red-400">91</span>
                    </div>
                    <div className="mini-evi-sep">|</div>
                    <div className="mini-evi-item">
                      <span className="lbl">ECOD</span>
                      <span className="val text-red-400">96</span>
                    </div>
                    <div className="mini-evi-sep">|</div>
                    <div className="mini-evi-item">
                      <span className="lbl">SPATIAL</span>
                      <span className="val text-amber-400">73</span>
                    </div>
                  </div>

                  {/* Root Cause Conclusion Box */}
                  <div className="console-root-cause-banner">
                    <div className="root-cause-title">
                      <Zap className="w-3.5 h-3.5 text-amber-400" />
                      <span>DIAGNOSIS: Thermodynamic / Barometric Inconsistency</span>
                    </div>
                    <p className="root-cause-desc">
                      Observed temperature and humidity diverge from the station's expected relationship while pressure also deviates from the local baseline.
                    </p>
                  </div>

                  {/* Console Action Footer */}
                  <div className="console-action-row">
                    <div className="console-meta-text">
                      DEMO SCENARIO · AWS-178
                    </div>
                    <button
                      type="button"
                      className="console-launch-btn"
                      onClick={() => onLaunchPlatform('map')}
                      title="Open station in operational ATHER map console"
                    >
                      <span>OPEN MAP CONSOLE</span>
                      <ArrowRight className="w-3 h-3 text-amber-400" />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ========================================================================= */}
      {/* 02. SECTION 02 — THE PROBLEM (#problem / S-01)                             */}
      {/* ========================================================================= */}
      <section id="problem" className="home-section problem-section">
        <div className="home-container">
          <div className="section-header-left">
            <div className="section-system-label">
              <span>S-01 / THE PROBLEM</span>
            </div>
            <h2 className="section-headline">
              WEATHER DATA<br />
              ISN’T ALWAYS<br />
              TRUSTWORTHY.
            </h2>
            <p className="section-subline-italic">
              Raw observations need intelligence.
            </p>
            <p className="section-lead-body">
              Weather stations continuously produce measurements, but missing values,
              sensor faults, sudden spikes, physical inconsistencies, and local deviations
              can make raw observations difficult to trust without multi-layer evaluation.
            </p>
          </div>

          {/* Large White Rounded Container with Horizontal Instrumentation Chain */}
          <div className="workflow-card-container">
            <div className="workflow-card-header">
              <span className="mono-title">OBSERVATIONAL FLOW / INSTRUMENTATION CHAIN</span>
              <span className="mono-subtitle">STATION METADATA: TEMP · PRES · HUM · WIND · PRECIP</span>
            </div>

            <div className="workflow-stages-grid">
              <div className="stage-box">
                <div className="stage-step-num">01</div>
                <div className="stage-name">STATION</div>
                <div className="stage-desc">In-situ AWS node recording telemetry.</div>
              </div>
              <div className="stage-arrow">→</div>

              <div className="stage-box">
                <div className="stage-step-num">02</div>
                <div className="stage-name">OBSERVATION</div>
                <div className="stage-desc">Digitized packets streamed via GSM / satellite.</div>
              </div>
              <div className="stage-arrow">→</div>

              <div className="stage-box">
                <div className="stage-step-num">03</div>
                <div className="stage-name">DATA QUALITY</div>
                <div className="stage-desc">Boundary range & packet validation.</div>
              </div>
              <div className="stage-arrow">→</div>

              <div className="stage-box highlight">
                <div className="stage-step-num">04</div>
                <div className="stage-name">ANOMALY</div>
                <div className="stage-desc">Multi-layer engines isolate outliers.</div>
              </div>
              <div className="stage-arrow">→</div>

              <div className="stage-box highlight">
                <div className="stage-step-num">05</div>
                <div className="stage-name">EXPLANATION</div>
                <div className="stage-desc">First-principles root cause attribution.</div>
              </div>
              <div className="stage-arrow">→</div>

              <div className="stage-box active">
                <div className="stage-step-num">06</div>
                <div className="stage-name">ACTION</div>
                <div className="stage-desc">Field engineering alert & escalation.</div>
              </div>
            </div>

            {/* Micro-metadata strip under chain */}
            <div className="chain-metadata-strip">
              <span>TEMPERATURE (°C)</span>
              <span>•</span>
              <span>PRESSURE (hPa)</span>
              <span>•</span>
              <span>HUMIDITY (% RH)</span>
              <span>•</span>
              <span>WIND SPEED (m/s)</span>
              <span>•</span>
              <span>PRECIPITATION (mm)</span>
            </div>

            {/* 3 Editorial Columns at Bottom - Refined Density */}
            <div className="problem-analysis-grid">
              <div className="analysis-col">
                <div className="col-tag">THE PROBLEM</div>
                <h3 className="col-headline">Raw station readings contain noise.</h3>
                <p className="col-body">
                  Raw station readings can contain noise, missing values, sensor drift and communication faults.
                </p>
              </div>

              <div className="analysis-col">
                <div className="col-tag">THE RISK</div>
                <h3 className="col-headline">A bad reading looks like extreme weather.</h3>
                <p className="col-body">
                  A faulty observation can resemble an extreme weather event and distort downstream analysis.
                </p>
              </div>

              <div className="analysis-col ather-col">
                <div className="col-tag accent">ATHER RESPONSE</div>
                <h3 className="col-headline">Decoupled multi-layer verification.</h3>
                <p className="col-body">
                  ATHER evaluates observations across multiple intelligence layers to separate physical anomalies, unusual behavior and potential sensor faults.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ========================================================================= */}
      {/* 03. SECTION 03 — TODAY VS ATHER (#how-it-works / S-02 & S-03)              */}
      {/* ========================================================================= */}
      <section id="how-it-works" className="home-section why-section">
        <div className="home-container">
          <div className="section-header-left">
            <div className="section-system-label">
              <span>S-02 / WHY ATHER</span>
            </div>
            <h2 className="section-headline">
              THE FUTURE OF WEATHER<br />
              INTELLIGENCE
            </h2>
            <p className="section-subline-italic">
              isn’t more data. It’s better interpretation.
            </p>
            <p className="section-lead-body">
              Legacy weather observation pipelines blindly ingest and store telemetry, relying on reactive inspection.
              ATHER introduces physics-informed, multivariate, and spatial evaluation before an anomaly is asserted.
            </p>
          </div>

          {/* Two Contrasting Cards: Today vs ATHER */}
          <div className="comparison-cards-grid">
            {/* Left Card: Raw Observations (White Card) */}
            <div className="contrast-card raw-pipeline">
              <div className="contrast-card-header">
                <span className="contrast-tag">TODAY</span>
                <h3 className="contrast-title">RAW OBSERVATIONS</h3>
              </div>

              <div className="contrast-steps-list">
                <div className="contrast-step-item">
                  <span className="step-num">01</span>
                  <div className="step-text">
                    <strong>Raw Data Streams:</strong> High-volume unvalidated telemetry ingested blindly.
                  </div>
                </div>
                <div className="contrast-step-item">
                  <span className="step-num">02</span>
                  <div className="step-text">
                    <strong>Missing Values:</strong> Sensor dropouts ignored or zero-filled by default.
                  </div>
                </div>
                <div className="contrast-step-item">
                  <span className="step-num">03</span>
                  <div className="step-text">
                    <strong>Manual Inspection:</strong> Engineers visually reviewing erratic charts after complaints.
                  </div>
                </div>
                <div className="contrast-step-item">
                  <span className="step-num">04</span>
                  <div className="step-text">
                    <strong>Isolated Checks:</strong> Rigid 3-sigma thresholds that miss multivariate interactions.
                  </div>
                </div>
                <div className="contrast-step-item">
                  <span className="step-num">05</span>
                  <div className="step-text">
                    <strong>Reactive Response:</strong> Identified only after downstream operational failures.
                  </div>
                </div>
              </div>

              <div className="contrast-banner warning-banner">
                <AlertTriangle className="w-4 h-4 text-amber-700 flex-shrink-0" />
                <span>Raw data alone cannot explain whether a reading is unusual, uncalibrated, or physically impossible.</span>
              </div>
            </div>

            {/* Right Card: ATHER Intelligence (Dark Obsidian Card) */}
            <div className="contrast-card ather-intelligent">
              <div className="contrast-card-header">
                <span className="contrast-tag accent">ATHER</span>
                <h3 className="contrast-title">INTELLIGENT OBSERVATION</h3>
              </div>

              <div className="contrast-steps-list">
                <div className="contrast-step-item">
                  <span className="step-num accent">01</span>
                  <div className="step-text">
                    <strong>Physics Consistency:</strong> Thermodynamic laws (Magnus-Tetens, lapse rates) validated first.
                  </div>
                </div>
                <div className="contrast-step-item">
                  <span className="step-num accent">02</span>
                  <div className="step-text">
                    <strong>Temporal Dynamics:</strong> Rapid step jumps and flatlines isolated from genuine squall fronts.
                  </div>
                </div>
                <div className="contrast-step-item">
                  <span className="step-num accent">03</span>
                  <div className="step-text">
                    <strong>Multivariate ECOD:</strong> Non-parametric joint distribution anomaly scoring across vectors.
                  </div>
                </div>
                <div className="contrast-step-item">
                  <span className="step-num accent">04</span>
                  <div className="step-text">
                    <strong>Spatial Consensus:</strong> Real-time regional correlation against neighboring AWS stations.
                  </div>
                </div>
                <div className="contrast-step-item">
                  <span className="step-num accent">05</span>
                  <div className="step-text">
                    <strong>Sensor Hardware Health:</strong> Dedicated hardware diagnostic indexing and zero-variance detection.
                  </div>
                </div>
                <div className="contrast-step-item">
                  <span className="step-num accent">06</span>
                  <div className="step-text">
                    <strong>Evidence Fusion:</strong> Calibrated confidence scoring with transparent root cause attribution.
                  </div>
                </div>
              </div>

              <div className="contrast-banner ather-banner">
                <CheckCircle2 className="w-4 h-4 text-amber-500 flex-shrink-0" />
                <span>ATHER turns raw observations into explainable, mathematically sound anomaly intelligence.</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ========================================================================= */}
      {/* 04. SECTION 04 — INTELLIGENCE LAYERS & PIPELINE (#intelligence / S-03-S-06)*/}
      {/* ========================================================================= */}
      <section id="intelligence" className="home-section how-section">
        <div className="home-container">
          <div className="section-header-left">
            <div className="section-system-label">
              <span>S-03 / HOW ATHER THINKS</span>
            </div>
            <h2 className="section-headline">
              FROM OBSERVATION<br />
              TO <span className="hero-subline-italic">INTELLIGENCE.</span>
            </h2>
            <p className="section-lead-body">
              ATHER evaluates each observation through multiple complementary intelligence
              layers instead of relying on a single brittle anomaly detector.
            </p>
          </div>

          {/* Editorial Cards Grid */}
          <div className="intelligence-cards-grid">
            {/* Card 01 */}
            <div className="intel-card">
              <div className="card-top-meta">
                <span className="card-layer-num">01</span>
                <span className="card-cat-label">THERMODYNAMICS</span>
              </div>
              <h3 className="card-title">PHYSICS INTELLIGENCE</h3>
              <p className="card-body">
                Evaluates physical relationships between ambient temperature, barometric pressure,
                relative humidity, and vapor pressure deficit.
              </p>
              <div className="card-bottom-tech">
                <span className="tech-label">MODEL</span>
                <span className="tech-val">FIRST PRINCIPLES / MAGNUS-TETENS</span>
              </div>
            </div>

            {/* Card 02 */}
            <div className="intel-card">
              <div className="card-top-meta">
                <span className="card-layer-num">02</span>
                <span className="card-cat-label">TIME-SERIES</span>
              </div>
              <h3 className="card-title">TEMPORAL DYNAMICS</h3>
              <p className="card-body">
                Tracks rate of change, diurnal temperature curves, and historical time-series
                residuals. Flags sudden unphysical leaps and frozen flatlines.
              </p>
              <div className="card-bottom-tech">
                <span className="tech-label">MODEL</span>
                <span className="tech-val">RESIDUAL & DELTA CHECK</span>
              </div>
            </div>

            {/* Card 03 */}
            <div className="intel-card highlight-card">
              <div className="card-top-meta">
                <span className="card-layer-num accent">03</span>
                <span className="card-cat-label accent">MULTIVARIATE</span>
              </div>
              <h3 className="card-title">ECOD ANOMALY ENGINE</h3>
              <p className="card-body">
                Identify unusual relationships across available weather variables using Empirical
                Cumulative Distribution Functions without Gaussian assumptions.
              </p>
              <div className="card-bottom-tech">
                <span className="tech-label">MODEL</span>
                <span className="tech-val accent">PyOD / ECOD ENGINE</span>
              </div>
            </div>

            {/* Card 04 */}
            <div className="intel-card">
              <div className="card-top-meta">
                <span className="card-layer-num">04</span>
                <span className="card-cat-label">GEOSPATIAL</span>
              </div>
              <h3 className="card-title">SPATIAL CONSENSUS</h3>
              <p className="card-body">
                Compares target station against regional AWS neighbors using inverse-distance
                weighting and topographical elevation adjustments.
              </p>
              <div className="card-bottom-tech">
                <span className="tech-label">MODEL</span>
                <span className="tech-val">k-NN REGIONAL CORRELATION</span>
              </div>
            </div>

            {/* Card 05 */}
            <div className="intel-card">
              <div className="card-top-meta">
                <span className="card-layer-num">05</span>
                <span className="card-cat-label">HARDWARE</span>
              </div>
              <h3 className="card-title">SENSOR HEALTH</h3>
              <p className="card-body">
                Monitors packet freshness, frozen telemetric values, missing communication
                cycles, and long-term calibration degradation.
              </p>
              <div className="card-bottom-tech">
                <span className="tech-label">MODEL</span>
                <span className="tech-val">HARDWARE INTEGRITY INDEX</span>
              </div>
            </div>

            {/* Card 06 */}
            <div className="intel-card highlight-card">
              <div className="card-top-meta">
                <span className="card-layer-num accent">06</span>
                <span className="card-cat-label accent">SYNTHESIS</span>
              </div>
              <h3 className="card-title">EVIDENCE FUSION</h3>
              <p className="card-body">
                Aggregates signals from all diagnostic layers with conformal uncertainty
                weighting into a single calibrated confidence rating.
              </p>
              <div className="card-bottom-tech">
                <span className="tech-label">MODEL</span>
                <span className="tech-val accent">CONFORMAL AGGREGATION</span>
              </div>
            </div>
          </div>

          {/* Interactive Pipeline Sub-Section */}
          <div className="pipeline-container-wrapper" style={{ marginTop: '80px' }}>
            <div className="section-header-left">
              <div className="section-system-label">
                <span>S-04 / ARCHITECTURE</span>
              </div>
              <h2 className="section-headline">
                ONE OBSERVATION.<br />
                MULTIPLE SIGNALS.
              </h2>
              <p className="section-lead-body">
                Hover over or click any node in the ATHER intelligence pipeline to inspect its
                evaluation criteria, algorithmic execution, and operational output.
              </p>
            </div>

            <div className="pipeline-interactive-layout">
              {/* Left Steps Rail with Technical Grid */}
              <div className="pipeline-steps-rail">
                {pipelineSteps.map((step, idx) => (
                  <div
                    key={step.id}
                    className={`pipeline-step-pill ${activePipelineStep === idx ? 'active' : ''}`}
                    onMouseEnter={() => setActivePipelineStep(idx)}
                    onClick={() => setActivePipelineStep(idx)}
                  >
                    <span className="step-idx">{step.code}</span>
                    <div className="step-meta">
                      <span className="step-name">{step.name}</span>
                      <span className="step-tag">{step.tag}</span>
                    </div>
                    <ChevronRight className="w-4 h-4 step-chevron" />
                  </div>
                ))}
              </div>

              {/* Right Detailed Inspector Card */}
              <div className="pipeline-inspector-card">
                <div className="inspector-card-header">
                  <div className="inspector-layer-number">
                    {pipelineSteps[activePipelineStep].code} / {pipelineSteps[activePipelineStep].tag}
                  </div>
                  <div className="inspector-badge">{pipelineSteps[activePipelineStep].layerType}</div>
                </div>

                <h3 className="inspector-title">{pipelineSteps[activePipelineStep].name}</h3>
                <p className="inspector-lead">{pipelineSteps[activePipelineStep].desc}</p>

                <div className="inspector-divider" />

                <div className="inspector-deep-dive">
                  <span className="section-tiny-title">EVALUATION LOGIC</span>
                  <p className="inspector-body">{pipelineSteps[activePipelineStep].details}</p>
                </div>

                <div className="inspector-features-list">
                  <span className="section-tiny-title">CORE CAPABILITIES</span>
                  <div className="features-chips">
                    {pipelineSteps[activePipelineStep].features.map((feat, i) => (
                      <span key={i} className="feature-chip">
                        <Check className="w-3.5 h-3.5 text-amber-500" />
                        {feat}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="inspector-footer">
                  <span className="inspector-note">Operational in ATHER Backend Engine</span>
                  <button
                    className="inspector-action-btn"
                    onClick={() => onLaunchPlatform('map')}
                  >
                    <span>SEE IN MAP</span>
                    <ArrowRight className="w-3 h-3 text-amber-400" />
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* Degraded Mode Data Quality Sub-Section */}
          <div className="degraded-container-wrapper" style={{ marginTop: '100px' }}>
            <div className="degraded-grid">
              <div className="degraded-content">
                <div className="section-system-label">
                  <span>S-05 / DATA QUALITY</span>
                </div>
                <h2 className="section-headline">
                  REAL WEATHER DATA<br />
                  IS NEVER PERFECT.
                </h2>
                <p className="section-subline-italic">ATHER adapts.</p>

                <p className="section-lead-body">
                  Weather stations frequently suffer from broken communication lines, dead sensors,
                  or partial channel dropouts. While conventional models crash or hallucinate zeros,
                  ATHER operates with whatever evidence is available, adjusting uncertainty rather
                  than pretending missing signals are normal.
                </p>

                <div className="resilience-points-list">
                  <div className="resilience-item">
                    <div className="res-icon-box">
                      <Check className="w-4 h-4 text-amber-500" />
                    </div>
                    <div>
                      <strong>Graceful Partial Degradation:</strong> If wind or rainfall is offline, thermodynamic and pressure models continue without crashing.
                    </div>
                  </div>

                  <div className="resilience-item">
                    <div className="res-icon-box">
                      <Check className="w-4 h-4 text-amber-500" />
                    </div>
                    <div>
                      <strong>Calibrated Uncertainty:</strong> Reduced channels dynamically expand the confidence interval and lower the maximum assertion score.
                    </div>
                  </div>

                  <div className="resilience-item">
                    <div className="res-icon-box">
                      <Check className="w-4 h-4 text-amber-500" />
                    </div>
                    <div>
                      <strong>Explicit Health Flagging:</strong> Field engineers see exactly which sensors need maintenance without mistaking data loss for an anomaly.
                    </div>
                  </div>
                </div>
              </div>

              {/* Technical Station Card */}
              <div className="degraded-station-card">
                <div className="stn-card-top">
                  <div className="stn-header-left">
                    <span className="stn-badge-mono">AWS-178</span>
                    <span className="stn-state-loc">CHANNEL AVAILABILITY INSPECTOR</span>
                  </div>
                  <div className="mode-badge degraded">
                    <span>MODE: DEGRADED</span>
                  </div>
                </div>

                {/* Channels Status Table */}
                <div className="channels-table">
                  <div className="channel-row active">
                    <span className="ch-name">TEMPERATURE</span>
                    <span className="ch-val">34.8 °C</span>
                    <span className="ch-status ok">ACTIVE</span>
                  </div>

                  <div className="channel-row active">
                    <span className="ch-name">PRESSURE</span>
                    <span className="ch-val">1001 hPa</span>
                    <span className="ch-status ok">ACTIVE</span>
                  </div>

                  <div className="channel-row active">
                    <span className="ch-name">HUMIDITY</span>
                    <span className="ch-val">91 %</span>
                    <span className="ch-status ok">ACTIVE</span>
                  </div>

                  <div className="channel-row offline">
                    <span className="ch-name">WIND SPEED / DIR</span>
                    <span className="ch-val">—</span>
                    <span className="ch-status error">MISSING</span>
                  </div>

                  <div className="channel-row offline">
                    <span className="ch-name">RAIN ACCUMULATION</span>
                    <span className="ch-val">—</span>
                    <span className="ch-status error">MISSING</span>
                  </div>
                </div>

                {/* Metrics Summary Strip */}
                <div className="degraded-summary-strip">
                  <div className="summary-block">
                    <span className="sub-label">AVAILABLE CHANNELS</span>
                    <span className="sub-val text-amber-400">2 / 5</span>
                  </div>

                  <div className="summary-block">
                    <span className="sub-label">DETECTION MODE</span>
                    <span className="sub-val text-amber-400">DEGRADED</span>
                  </div>

                  <div className="summary-block">
                    <span className="sub-label">CONFIDENCE</span>
                    <span className="sub-val text-slate-200">78%</span>
                  </div>
                </div>

                <div className="degraded-card-explanation">
                  <Info className="w-4 h-4 text-amber-500 flex-shrink-0" />
                  <p>
                    ATHER acknowledges uncertainty. When sensor channels drop, the system communicates
                    reduced confidence rather than pretending missing inputs are complete.
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* Dark Investigation Sub-Section */}
          <div className="dark-investigation-wrapper" style={{ marginTop: '100px' }}>
            <div className="investigation-mock-console">
              <div className="mock-console-header">
                <div className="station-meta-left">
                  <span className="section-system-label dark" style={{ marginBottom: '6px' }}>S-06 / INVESTIGATION</span>
                  <span className="station-code">AWS-178 ANOMALY DIAGNOSTIC</span>
                  <span className="station-sub">LAT 15.82°N · LON 78.03°E · ELEV 273m</span>
                </div>
                <div className="status-tag-anomaly">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  <span>ANOMALY DETECTED</span>
                </div>
              </div>

              <div className="mock-console-main-grid">
                {/* Left Observations Column */}
                <div className="console-column observations">
                  <div className="col-sub-title">STATION DETAILS</div>
                  <div className="reading-card">
                    <span className="param-label">Temperature</span>
                    <span className="param-reading">34.8 °C</span>
                  </div>
                  <div className="reading-card">
                    <span className="param-label">Pressure</span>
                    <span className="param-reading">1001 hPa</span>
                  </div>
                  <div className="reading-card">
                    <span className="param-label">Humidity</span>
                    <span className="param-reading">91% RH</span>
                  </div>
                  <div className="overall-confidence-box">
                    <span className="conf-label">ANOMALY CONFIDENCE</span>
                    <span className="conf-number">94%</span>
                    <span className="conf-badge">HIGH SEVERITY</span>
                  </div>
                </div>

                {/* Center Multi-Layer Diagnostics */}
                <div className="console-column diagnostics">
                  <div className="col-sub-title">EVIDENCE SCORES</div>

                  <div className="diagnostic-meter">
                    <div className="meter-label-row">
                      <span>PHYSICS</span>
                      <span className="meter-score text-amber-400">82%</span>
                    </div>
                    <div className="meter-bar">
                      <div className="meter-fill bg-amber" style={{ width: '82%' }} />
                    </div>
                    <div className="meter-hint">Magnus-Tetens saturation boundary violation</div>
                  </div>

                  <div className="diagnostic-meter">
                    <div className="meter-label-row">
                      <span>TEMPORAL</span>
                      <span className="meter-score text-red-400">91%</span>
                    </div>
                    <div className="meter-bar">
                      <div className="meter-fill bg-red" style={{ width: '91%' }} />
                    </div>
                    <div className="meter-hint">Delta spike dT/dt exceeds coastal baseline</div>
                  </div>

                  <div className="diagnostic-meter">
                    <div className="meter-label-row">
                      <span>ECOD</span>
                      <span className="meter-score text-red-500">96%</span>
                    </div>
                    <div className="meter-bar">
                      <div className="meter-fill bg-red" style={{ width: '96%' }} />
                    </div>
                    <div className="meter-hint">Joint vector outlier in top 0.4% empirical tail</div>
                  </div>

                  <div className="diagnostic-meter">
                    <div className="meter-label-row">
                      <span>SPATIAL</span>
                      <span className="meter-score text-amber-400">73%</span>
                    </div>
                    <div className="meter-bar">
                      <div className="meter-fill bg-amber" style={{ width: '73%' }} />
                    </div>
                    <div className="meter-hint">Disagrees with 4 surrounding AWS stations</div>
                  </div>
                </div>

                {/* Right Root Cause & Evidence */}
                <div className="console-column explanation">
                  <div className="col-sub-title">ROOT CAUSE</div>
                  <div className="root-cause-card">
                    <div className="cause-heading">
                      <Zap className="w-4 h-4 text-amber-400" />
                      <span>Temperature / humidity inconsistency</span>
                    </div>
                    <p className="cause-text">
                      Ambient temperature of 34.8°C coexisting with 91% RH creates an implausible
                      heat index (54.2°C) unsupported by regional barometric gradients.
                    </p>
                  </div>

                  <div className="col-sub-title" style={{ marginTop: '16px' }}>SUPPORTING SIGNALS</div>
                  <div className="evidence-checklist">
                    <div className="evidence-item">
                      <Check className="w-3.5 h-3.5 text-amber-400" />
                      <span>Vapour pressure deficit violation</span>
                    </div>
                    <div className="evidence-item">
                      <Check className="w-3.5 h-3.5 text-amber-400" />
                      <span>ECOD multivariate tail score: 96%</span>
                    </div>
                    <div className="evidence-item">
                      <Check className="w-3.5 h-3.5 text-amber-400" />
                      <span>Neighboring stations avg 27.5°C</span>
                    </div>
                  </div>

                  <button
                    className="investigate-cta-btn"
                    onClick={() => onLaunchPlatform('map')}
                  >
                    <span>INVESTIGATE IN ATHER →</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ========================================================================= */}
      {/* 05. SECTION 05 — TECHNOLOGY (#technology / S-07 & S-08)                   */}
      {/* ========================================================================= */}
      <section id="technology" className="home-section tech-section">
        <div className="home-container">
          <div className="section-header-left">
            <div className="section-system-label">
              <span>S-07 / TECHNOLOGY</span>
            </div>
            <h2 className="section-headline">
              BUILT FOR<br />
              WEATHER-SCALE
              <span className="hero-subline-italic"> INTELLIGENCE.</span>
            </h2>
            <p className="section-lead-body">
              Engineered with a high-throughput Python anomaly engine, rigorous statistical methods,
              first-principles physics, and a hardware-accelerated geospatial canvas.
            </p>
          </div>

          <div className="tech-cards-grid">
            <div className="tech-card">
              <div className="tech-id-badge">T-01</div>
              <h3 className="tech-title">ECOD</h3>
              <p className="tech-tag-category">MULTIVARIATE DETECTION</p>
              <p className="tech-desc">
                Non-parametric joint distribution outlier detection via Empirical Cumulative Distribution Functions.
              </p>
              <div className="tech-bottom-pill">PyOD / Python</div>
            </div>

            <div className="tech-card">
              <div className="tech-id-badge">T-02</div>
              <h3 className="tech-title">TEMPORAL DYNAMICS</h3>
              <p className="tech-tag-category">TIME-SERIES INTELLIGENCE</p>
              <p className="tech-desc">
                Rolling rate-of-change and residual analysis isolating squalls from electrical sensor jumps.
              </p>
              <div className="tech-bottom-pill">Residual Analytics</div>
            </div>

            <div className="tech-card">
              <div className="tech-id-badge">T-03</div>
              <h3 className="tech-title">PHYSICS INTELLIGENCE</h3>
              <p className="tech-tag-category">FIRST-PRINCIPLES</p>
              <p className="tech-desc">
                Thermodynamic equations including Magnus-Tetens, barometric lapse rates, and saturation limits.
              </p>
              <div className="tech-bottom-pill">Physical Modeling</div>
            </div>

            <div className="tech-card">
              <div className="tech-id-badge">T-04</div>
              <h3 className="tech-title">FASTAPI</h3>
              <p className="tech-tag-category">SERVICE LAYER</p>
              <p className="tech-desc">
                Asynchronous ASGI backend providing real-time GeoJSON streaming, station search, and ML inference.
              </p>
              <div className="tech-bottom-pill">FastAPI / Python 3.11</div>
            </div>

            <div className="tech-card">
              <div className="tech-id-badge">T-05</div>
              <h3 className="tech-title">MAPLIBRE GL</h3>
              <p className="tech-tag-category">STATION VISUALIZATION</p>
              <p className="tech-desc">
                Hardware-accelerated 2D mapping engine with real-time station clustering and wind vector animations.
              </p>
              <div className="tech-bottom-pill">MapLibre / WebGL</div>
            </div>

            <div className="tech-card">
              <div className="tech-id-badge">T-06</div>
              <h3 className="tech-title">CONFORMAL FUSION</h3>
              <p className="tech-tag-category">CONFIDENCE SYNTHESIS</p>
              <p className="tech-desc">
                Multi-layer evidence synthesis delivering calibrated confidence and uncertainty metrics.
              </p>
              <div className="tech-bottom-pill">Statistical Synthesis</div>
            </div>
          </div>

          {/* Test Lab Teaser Box */}
          <div className="testlab-teaser-wrapper" style={{ marginTop: '80px' }}>
            <div className="test-case-showcase-box">
              <div className="case-id-tag">S-08 / TEST LAB CASE-07</div>
              <h3 className="case-title">TEMPERATURE SENSOR FAILURE SIMULATION</h3>

              <div className="case-metrics-comparison">
                <div className="case-metric-block">
                  <span className="lbl">Expected Value</span>
                  <span className="val text-slate-300">34.2°C</span>
                </div>
                <div className="case-metric-arrow">→</div>
                <div className="case-metric-block injected">
                  <span className="lbl">Injected Telemetry Fault</span>
                  <span className="val text-amber-400">52.0°C</span>
                </div>
                <div className="case-metric-arrow">→</div>
                <div className="case-metric-block result">
                  <span className="lbl">Engine Verification</span>
                  <span className="val text-red-400">ANOMALY DETECTED</span>
                  <span className="sub-conf">Confidence: 98%</span>
                </div>
              </div>

              <div className="case-cta-bar">
                <span className="case-cta-desc">Select any AWS station to simulate custom environmental faults in the operational Test Lab.</span>
                <button
                  className="home-cta-button primary"
                  onClick={() => onLaunchPlatform('testlab')}
                >
                  <span>OPEN TEST LAB</span>
                  <ArrowRight className="cta-gold-arrow w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ========================================================================= */}
      {/* 06. SECTION 06 — LIVE DEMO & CONSOLE PREVIEW (#live-demo / S-09)          */}
      {/* ========================================================================= */}
      <section id="live-demo" className="home-section platform-preview-section">
        <div className="home-container">
          <div className="section-header-left">
            <div className="section-system-label">
              <span>S-09 / PLATFORM CONSOLE</span>
            </div>
            <h2 className="section-headline">
              THE ATHER<br />
              PLATFORM CONSOLE
            </h2>
            <p className="section-lead-body">
              Explore station locations, current observations, anomaly states, sensor health,
              and investigation signals from a single operational interface.
            </p>
          </div>

          {/* Large Dashboard Container Preview (OpenRelay Console Style) */}
          <div className="platform-mock-container" onClick={() => onLaunchPlatform('map')}>
            <div className="mock-top-bar">
              <div className="mock-brand">
                <Radio className="w-3.5 h-3.5 text-amber-500" />
                <span>ATHER_OPERATIONAL_CONSOLE</span>
              </div>
              <div className="mock-nav-tabs">
                <span className="mock-tab active">2D Map</span>
                <span className="mock-tab">Anomalies ({summary?.anomalyCount ?? 12})</span>
                <span className="mock-tab">Sensor Health</span>
                <span className="mock-tab">Test Lab</span>
              </div>
              <div className="mock-live-badge">
                <span className="live-dot-pulse" />
                <span>LIVE PLATFORM</span>
              </div>
            </div>

            <div className="mock-dashboard-content">
              {/* Left Side: Mock Map */}
              <div className="mock-map-area">
                <div className="mock-map-bg-grid" />
                <div className="mock-cluster-pin p1">
                  <span className="pin-pulse red" />
                  <span className="pin-label">AWS-178 (ANOMALY)</span>
                </div>
                <div className="mock-cluster-pin p2">
                  <span className="pin-pulse green" />
                  <span className="pin-label">BLR-001 (NORMAL)</span>
                </div>
                <div className="mock-cluster-pin p3">
                  <span className="pin-pulse amber" />
                  <span className="pin-label">HYD-042 (WARNING)</span>
                </div>
                <div className="mock-cluster-pin p4">
                  <span className="pin-pulse green" />
                  <span className="pin-label">MUM-112 (NORMAL)</span>
                </div>

                <div className="mock-map-overlay-card">
                  <div className="overlay-title">SELECTED: AWS-178</div>
                  <div className="overlay-metric">34.8°C · 1001 hPa · 91% RH</div>
                  <div className="overlay-alert">Anomaly Severity: HIGH (94%)</div>
                </div>
              </div>

              {/* Right Side: Activity Feed */}
              <div className="mock-feed-area">
                <div className="feed-title">REAL-TIME ANOMALY FEED</div>
                <div className="feed-items-list">
                  <div className="feed-item unread">
                    <div className="feed-badge red">CRITICAL</div>
                    <div className="feed-info">
                      <div className="feed-stn">AWS-178</div>
                      <div className="feed-desc">Thermodynamic & Barometric Clash</div>
                    </div>
                  </div>

                  <div className="feed-item">
                    <div className="feed-badge amber">WARNING</div>
                    <div className="feed-info">
                      <div className="feed-stn">HYD-042</div>
                      <div className="feed-desc">Spatial Temperature Residual (+4.8°C)</div>
                    </div>
                  </div>

                  <div className="feed-item">
                    <div className="feed-badge red">ANOMALY</div>
                    <div className="feed-info">
                      <div className="feed-stn">DEL-204</div>
                      <div className="feed-desc">Rate-of-Change Pressure Step (12 hPa/hr)</div>
                    </div>
                  </div>
                </div>

                <div className="feed-metrics-bottom">
                  <div className="feed-stat">
                    <span className="num">{summary?.totalStations ?? 150}</span>
                    <span className="lbl">Stations</span>
                  </div>
                  <div className="feed-stat">
                    <span className="num text-green-500">{summary?.normalCount ?? 134}</span>
                    <span className="lbl">Normal</span>
                  </div>
                  <div className="feed-stat">
                    <span className="num text-amber-500">{summary?.warningCount ?? 8}</span>
                    <span className="lbl">Warning</span>
                  </div>
                  <div className="feed-stat">
                    <span className="num text-red-500">{summary?.anomalyCount ?? 8}</span>
                    <span className="lbl">Anomaly</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Click Overlay */}
            <div className="mock-overlay-hover-cue">
              <div className="cue-content">
                <ExternalLink className="w-4 h-4 text-amber-400" />
                <span>CLICK TO ENTER LIVE OPERATIONAL PLATFORM</span>
              </div>
            </div>
          </div>

          <div style={{ textAlign: 'center', marginTop: '36px' }}>
            <button
              className="home-cta-button primary large"
              onClick={() => onLaunchPlatform('map')}
            >
              <span>OPEN LIVE ATHER</span>
              <ArrowRight className="cta-gold-arrow w-4 h-4" />
            </button>
          </div>
        </div>
      </section>

      {/* ========================================================================= */}
      {/* 07. FINAL CTA                                                             */}
      {/* ========================================================================= */}
      <section className="home-section final-cta-section">
        <div className="home-container">
          <div className="final-cta-content">
            <h2 className="final-cta-headline">
              FROM RAW OBSERVATIONS<br />
              <span className="hero-subline-italic text-amber-400">
                TO WEATHER INTELLIGENCE.
              </span>
            </h2>
            <p className="final-cta-body">
              ATHER turns complex station observations into verifiable anomaly signals that can be
              investigated, explained, and acted upon by meteorological engineers and automated systems.
            </p>
            <div className="final-cta-buttons">
              <button
                className="home-cta-button primary large"
                onClick={() => onLaunchPlatform('map')}
              >
                <span>LAUNCH ATHER</span>
                <ArrowRight className="cta-gold-arrow w-4 h-4" />
              </button>
              <button
                type="button"
                className="home-cta-button secondary large"
                onClick={() => scrollToSection('intelligence')}
              >
                <span>EXPLORE THE SYSTEM</span>
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* ========================================================================= */}
      {/* 08. FOOTER                                                                */}
      {/* ========================================================================= */}
      <footer className="home-footer">
        <div className="home-container">
          <div className="footer-top-row">
            <div className="footer-brand">
              <div className="footer-logo">
                <Radio className="w-4 h-4 text-amber-500" />
                <span>ATHER</span>
              </div>
              <p className="footer-tagline">WEATHER INTELLIGENCE PLATFORM</p>
              <p className="footer-desc">
                Advanced meteorological anomaly detection, in-situ sensor health diagnostics,
                and physical-statistical evidence fusion.
              </p>
            </div>

            <div className="footer-nav-columns">
              <div className="footer-nav-col">
                <span className="col-title">NAVIGATION</span>
                <button type="button" className="footer-link-btn" onClick={() => scrollToSection('home')}>Home</button>
                <button type="button" className="footer-link-btn" onClick={() => scrollToSection('problem')}>Problem</button>
                <button type="button" className="footer-link-btn" onClick={() => scrollToSection('how-it-works')}>How It Works</button>
                <button type="button" className="footer-link-btn" onClick={() => scrollToSection('intelligence')}>Intelligence</button>
                <button type="button" className="footer-link-btn" onClick={() => scrollToSection('technology')}>Technology</button>
              </div>

              <div className="footer-nav-col">
                <span className="col-title">PLATFORM</span>
                <a
                  href="#live-map"
                  onClick={(e) => {
                    e.preventDefault();
                    onLaunchPlatform('map');
                  }}
                >
                  2D Weather Map
                </a>
                <a
                  href="#anomalies"
                  onClick={(e) => {
                    e.preventDefault();
                    onLaunchPlatform('anomalies');
                  }}
                >
                  Active Incidents
                </a>
                <a
                  href="#health"
                  onClick={(e) => {
                    e.preventDefault();
                    onLaunchPlatform('health');
                  }}
                >
                  Sensor Health
                </a>
                <a
                  href="#testlab"
                  onClick={(e) => {
                    e.preventDefault();
                    onLaunchPlatform('testlab');
                  }}
                >
                  Test Lab
                </a>
              </div>

              <div className="footer-nav-col">
                <span className="col-title">SYSTEM</span>
                <span>FastAPI v0.115</span>
                <span>MapLibre GL v5.6</span>
                <span>ECOD Anomaly Engine</span>
                <span>Python 3.11</span>
              </div>
            </div>
          </div>

          <div className="footer-bottom-row">
            <span className="footer-copyright">
              © {new Date().getFullYear()} ATHER Meteorological Intelligence. All operational rights reserved.
            </span>
            <div className="footer-status-pill">
              <span className="dot green" />
              <span>SYSTEM NOMINAL · 150+ AWS NODES CONNECTED</span>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
};
