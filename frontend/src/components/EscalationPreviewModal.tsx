import React, { useEffect, useState } from 'react';
import { X, Copy, CheckCheck, ShieldAlert } from 'lucide-react';
import { fetchEscalationPreview, markEscalated } from '../services/api';

interface EscalationPreviewModalProps {
  stationId: string;
  onClose: () => void;
  onEscalated?: () => void;
}

export const EscalationPreviewModal: React.FC<EscalationPreviewModalProps> = ({ stationId, onClose, onEscalated }) => {
  const [preview, setPreview] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [marking, setMarking] = useState(false);

  useEffect(() => {
    fetchEscalationPreview(stationId).then(setPreview).catch((e) => setError(e.message));
  }, [stationId]);

  const alertText = preview
    ? `ESCALATION PREVIEW\n\n` +
      `Recipient: ${preview.recipient}\n` +
      `Subject: ${preview.subject}\n\n` +
      `Station: ${preview.station_id} (${preview.station_name || ''})\n` +
      `Location: ${preview.location}\n` +
      `Affected Parameter: ${preview.affected_parameter}\n` +
      `Observed: ${preview.observed}\n` +
      `Expected: ${preview.expected}\n` +
      `Severity: ${preview.severity}\n` +
      `Confidence: ${preview.confidence_pct}%\n` +
      `Root Cause: ${preview.root_cause}\n` +
      `Evidence: ${(preview.evidence || []).join('; ')}\n\n` +
      `Recommended Action: ${preview.recommended_action}`
    : '';

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(alertText);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard unavailable — non-fatal */
    }
  };

  const handleMarkEscalated = async () => {
    setMarking(true);
    try {
      await markEscalated(stationId);
      onEscalated?.();
      onClose();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setMarking(false);
    }
  };

  return (
    <div className="escalation-modal-overlay">
      <div className="escalation-modal-scrim" onClick={onClose} />
      <div className="escalation-modal-card">
        <div className="escalation-modal-header">
          <div className="escalation-modal-title-group">
            <ShieldAlert className="w-4 h-4 text-amber-400" />
            <span>ESCALATION PREVIEW</span>
          </div>
          <button className="btn-close-panel" onClick={onClose}><X className="w-4 h-4" /></button>
        </div>
        <div className="escalation-preview-note">
          This is a preview only. ATHER has not contacted any external recipient.
        </div>
        {error && <div className="test-lab-error">{error}</div>}
        {preview && (
          <div className="escalation-preview-body">
            <Row label="Recipient" value={preview.recipient} />
            <Row label="Subject" value={preview.subject} />
            <Row label="Station" value={`${preview.station_id} — ${preview.station_name || ''}`} />
            <Row label="Location" value={preview.location} />
            <Row label="Affected Parameter" value={preview.affected_parameter} />
            <Row label="Observed" value={preview.observed} />
            <Row label="Expected" value={preview.expected} />
            <Row label="Severity" value={preview.severity} />
            <Row label="Confidence" value={`${preview.confidence_pct}%`} />
            <Row label="Root Cause" value={String(preview.root_cause).replace(/_/g, ' ')} />
            {preview.evidence?.length > 0 && (
              <div className="escalation-row">
                <span className="escalation-row-label">Evidence</span>
                <ul className="test-lab-evidence-list">
                  {preview.evidence.slice(0, 4).map((e: string, i: number) => <li key={i}>{e}</li>)}
                </ul>
              </div>
            )}
            <Row label="Recommended Action" value={preview.recommended_action} />
          </div>
        )}
        <div className="escalation-modal-footer">
          <button className="btn-reset-simulation" onClick={handleCopy}>
            {copied ? <CheckCheck className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
            {copied ? 'COPIED' : 'COPY ALERT'}
          </button>
          <button className="btn-run-simulation" onClick={handleMarkEscalated} disabled={marking || !preview}>
            {marking ? 'MARKING...' : 'MARK AS ESCALATED'}
          </button>
          <button className="btn-close-test-lab" onClick={onClose}>CANCEL</button>
        </div>
      </div>
    </div>
  );
};

const Row: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div className="escalation-row">
    <span className="escalation-row-label">{label}</span>
    <span className="escalation-row-value">{value}</span>
  </div>
);
