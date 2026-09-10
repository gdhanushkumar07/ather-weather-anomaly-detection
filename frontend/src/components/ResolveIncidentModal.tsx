import React, { useState } from 'react';
import { X, CheckCircle2 } from 'lucide-react';

interface ResolveIncidentModalProps {
  incidentId: string;
  onClose: () => void;
  onResolve: (notes: string, resolutionType: string) => Promise<void>;
}

const RESOLUTION_TYPES = [
  'Sensor repaired',
  'Sensor recalibrated',
  'Communication restored',
  'False positive',
  'Genuine weather event',
  'Other',
];

/**
 * Resolution requires explicit operator input (Phase 18) — the backend
 * rejects a resolve request with empty notes/type, so this is never a
 * silent one-click action.
 */
export const ResolveIncidentModal: React.FC<ResolveIncidentModalProps> = ({ incidentId, onClose, onResolve }) => {
  const [notes, setNotes] = useState('');
  const [resolutionType, setResolutionType] = useState(RESOLUTION_TYPES[0]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async () => {
    if (!notes.trim()) {
      setError('Resolution notes are required.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await onResolve(notes.trim(), resolutionType);
      onClose();
    } catch (e: any) {
      setError(e.message || 'Failed to resolve incident.');
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
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            <span>RESOLVE INCIDENT</span>
          </div>
          <button className="btn-close-panel" onClick={onClose}><X className="w-4 h-4" /></button>
        </div>
        <div className="escalation-preview-note">{incidentId}</div>

        <div className="test-lab-field-row">
          <label className="test-lab-field-label">Resolution Outcome</label>
          <select className="test-lab-select" value={resolutionType} onChange={(e) => setResolutionType(e.target.value)}>
            {RESOLUTION_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>

        <div className="test-lab-field-row">
          <label className="test-lab-field-label">Resolution Notes (required)</label>
          <textarea
            className="test-lab-select"
            style={{ minHeight: 80, resize: 'vertical', fontFamily: 'inherit' }}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="What was done to resolve this incident?"
          />
        </div>

        {error && <div className="test-lab-error">{error}</div>}

        <div className="escalation-modal-footer">
          <button className="btn-close-test-lab" onClick={onClose}>CANCEL</button>
          <button className="btn-run-simulation" onClick={handleSubmit} disabled={submitting}>
            {submitting ? 'RESOLVING...' : 'RESOLVE'}
          </button>
        </div>
      </div>
    </div>
  );
};
