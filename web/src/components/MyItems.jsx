import React, { useEffect, useState } from 'react';
import { getMyItems } from '../api.js';

export default function MyItems({ persona, refreshKey }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState(null); // {referrals, subscriptions}
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getMyItems(persona)
      .then((data) => {
        if (!cancelled) setItems(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Could not load your items.');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, refreshKey, persona]);

  const referrals = (items && items.referrals) || [];
  const subscriptions = (items && items.subscriptions) || [];

  return (
    <section className="my-items">
      <button
        type="button"
        className="my-items-toggle"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        {open ? '▾' : '▸'} My referrals &amp; alerts
      </button>
      {open && (
        <div className="my-items-body">
          {loading && <p className="muted">Loading…</p>}
          {error && <p className="my-items-error">{error}</p>}
          {!loading && !error && (
            <>
              <h3>Referrals</h3>
              {referrals.length === 0 ? (
                <p className="muted">No referrals yet.</p>
              ) : (
                <ul>
                  {referrals.map((r, i) => (
                    <li key={r.referral_id || i}>
                      <strong>{r.specialty || 'Referral'}</strong>
                      {r.facility_id ? ` — facility ${r.facility_id}` : ''}
                      {r.status ? ` · ${r.status}` : ''}
                    </li>
                  ))}
                </ul>
              )}
              <h3>Alert subscriptions</h3>
              {subscriptions.length === 0 ? (
                <p className="muted">No alert subscriptions yet.</p>
              ) : (
                <ul>
                  {subscriptions.map((s, i) => (
                    <li key={s.sub_id || i}>
                      <strong>{s.signal || 'Alert'}</strong>
                      {s.threshold != null ? ` > ${s.threshold}` : ''}
                      {s.channel ? ` · via ${s.channel}` : ''}
                      {s.active === false ? ' · inactive' : ''}
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}
