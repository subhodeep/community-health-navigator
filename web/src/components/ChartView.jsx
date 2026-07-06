import React, { useEffect, useRef, useState } from 'react';
import embed from 'vega-embed';

export default function ChartView({ chartSpec }) {
  const containerRef = useRef(null);
  const [showSql, setShowSql] = useState(false);
  const [renderError, setRenderError] = useState(null);

  useEffect(() => {
    let view = null;
    let cancelled = false;
    if (containerRef.current && chartSpec && chartSpec.vega_lite) {
      embed(containerRef.current, chartSpec.vega_lite, { actions: false })
        .then((result) => {
          if (cancelled) {
            result.view.finalize();
          } else {
            view = result.view;
          }
        })
        .catch((err) => {
          if (!cancelled) setRenderError(err.message || 'Chart failed to render.');
        });
    }
    return () => {
      cancelled = true;
      if (view) view.finalize();
    };
  }, [chartSpec]);

  return (
    <div className="chart-view">
      {renderError ? (
        <p className="chart-error">Could not render chart: {renderError}</p>
      ) : (
        <div className="chart-container" ref={containerRef} />
      )}
      {chartSpec.sql && (
        <div className="sql-panel">
          <button
            type="button"
            className="sql-toggle"
            aria-expanded={showSql}
            onClick={() => setShowSql((s) => !s)}
          >
            {showSql ? 'Hide SQL' : 'Show SQL'}
          </button>
          {showSql && <pre className="sql-pre">{chartSpec.sql}</pre>}
        </div>
      )}
    </div>
  );
}
