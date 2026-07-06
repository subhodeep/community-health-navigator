import React from 'react';

const INTENT_LABELS = {
  referral: 'Create referral',
  alert_subscription: 'Create alert subscription',
};

export default function ActionConfirm({ actionRequest, disabled, onRespond }) {
  const { intent, params, resolved, confirmed } = actionRequest;
  const label = INTENT_LABELS[intent] || intent;

  return (
    <div className="action-confirm" role="group" aria-label="Action confirmation">
      <p className="action-title">{label}</p>
      <dl className="action-params">
        {Object.entries(params || {}).map(([key, value]) => (
          <div key={key} className="action-param">
            <dt>{key.replace(/_/g, ' ')}</dt>
            <dd>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd>
          </div>
        ))}
      </dl>
      {resolved ? (
        <p className="action-resolved">{confirmed ? 'Confirmed' : 'Cancelled'}</p>
      ) : (
        <div className="action-buttons">
          <button
            type="button"
            className="btn-confirm"
            disabled={disabled}
            onClick={() => onRespond(true)}
          >
            Confirm
          </button>
          <button
            type="button"
            className="btn-cancel"
            disabled={disabled}
            onClick={() => onRespond(false)}
          >
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}
