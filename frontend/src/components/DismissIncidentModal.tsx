import React, { useState } from 'react';
import { X, XCircle } from 'lucide-react';

interface DismissIncidentModalProps {
  incidentId: string;
  onClose: () => void;
  onDismiss: (reason: string) => Promise<void>;
}

const DISMISSAL_REASONS = ['False Positive', 'Duplicate', 'Expected Event', 'Test/Simulation', 'Other'];

/**
 * Dismissal requires an explicit reason (Phase 19). Test/Simulation is
 * listed as a valid reason for a rare edge case where a real incident
 * turns out to correspond to a known test artifact — it does NOT mean
 * simulation incidents ever reach this dialog (they never enter the
 * production incident list at all, see app/incidents/service.py).
 */
export const DismissIncidentModal: React.FC<DismissIncidentModalProps> = ({ incidentId, onClose, onDismiss }) => {
  const [reason, setReason] = useState(DISMISSAL_REASONS[0]);
  const [customReason, setCustomReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async () => {
    const finalReason = reason === 'Other' ? customReason.trim() : reason;
    if (!finalReason) {
      setError('A dismissal reason is required.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await onDismiss(finalReason);
      onClose();
    } catch (e: any) {
      setError(e.message || 'Failed to dismiss incident.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="escalation-modal-overlay">
      <div className="escalation-modal-scrim" onClick={onClose} />
      <div className="escalation-modal-card">
        <div className="escalation-modal-header">
          <div className="escalation-modal-title-group">
            <XCircle className="w-4 h-4 text-slate-400" />
            <span>DISMISS INCIDENT</span>
          </div>
          <button className="btn-close-panel" onClick={onClose}><X className="w-4 h-4" /></button>
        </div>
        <div className="escalation-preview-note">{incidentId}</div>

        <div className="test-lab-field-row">
          <label className="test-lab-field-label">Reason (required)</label>
          <select className="test-lab-select" value={reason} onChange={(e) => setReason(e.target.value)}>
            {DISMISSAL_REASONS.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>

        {reason === 'Other' && (
          <div className="test-lab-field-row">
            <label className="test-lab-field-label">Specify reason</label>
            <input
              className="test-lab-select"
              value={customReason}
              onChange={(e) => setCustomReason(e.target.value)}
              placeholder="Describe why this incident is being dismissed"
            />
          </div>
        )}

        {error && <div className="test-lab-error">{error}</div>}

        <div className="escalation-modal-footer">
          <button className="btn-close-test-lab" onClick={onClose}>CANCEL</button>
          <button className="btn-run-simulation" onClick={handleSubmit} disabled={submitting}>
            {submitting ? 'DISMISSING...' : 'DISMISS'}
          </button>
        </div>
      </div>
    </div>
  );
};
