import React, { useState } from 'react';

export default function BlockCard({ title, children, defaultExpanded = false }) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  return (
    <div style={{ border: '1px solid #ccc', borderRadius: 4, marginBottom: 8 }}>
      <div
        onClick={() => setExpanded(e => !e)}
        style={{ padding: '8px 12px', cursor: 'pointer', fontWeight: 'bold' }}
      >
        {title} {expanded ? '▲' : '▼'}
      </div>
      {expanded && (
        <div style={{ padding: '8px 12px', borderTop: '1px solid #eee' }}>
          {children}
        </div>
      )}
    </div>
  );
}
