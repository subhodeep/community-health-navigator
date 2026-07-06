import React, { useState } from 'react';

export default function Citations({ citations }) {
  const [openN, setOpenN] = useState(null);

  return (
    <div className="citations">
      <span className="citations-label">Sources</span>
      <ol className="citations-list">
        {citations.map((c) => {
          const open = openN === c.n;
          return (
            <li key={c.n}>
              <button
                type="button"
                className="citation-toggle"
                aria-expanded={open}
                onClick={() => setOpenN(open ? null : c.n)}
              >
                [{c.n}] {c.title || c.uri || 'Source'}
              </button>
              {open && (
                <div className="citation-detail">
                  {c.snippet && <p className="citation-snippet">{c.snippet}</p>}
                  {c.uri && (
                    <a href={c.uri} target="_blank" rel="noopener noreferrer">
                      {c.uri}
                    </a>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
