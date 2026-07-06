import React, { useCallback, useState } from 'react';
import Chat from './components/Chat.jsx';
import MyItems from './components/MyItems.jsx';

const TABS = [
  { id: 'navigator', label: 'Navigator', persona: 'citizen' },
  { id: 'analyst', label: 'Analyst', persona: 'analyst' },
];

export default function App() {
  const [activeTab, setActiveTab] = useState('navigator');
  const [itemsRefreshKey, setItemsRefreshKey] = useState(0);

  const handleActionConfirmed = useCallback(() => {
    setItemsRefreshKey((k) => k + 1);
  }, []);

  const activePersona = TABS.find((t) => t.id === activeTab).persona;

  return (
    <div className="app">
      <header className="app-header">
        <h1>Community Health Navigator</h1>
        <nav className="tabs" role="tablist" aria-label="Personas">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              role="tab"
              aria-selected={activeTab === tab.id}
              className={activeTab === tab.id ? 'tab active' : 'tab'}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </header>

      <MyItems persona={activePersona} refreshKey={itemsRefreshKey} />

      {/* Both chats stay mounted so each tab keeps its session and history. */}
      {TABS.map((tab) => (
        <div
          key={tab.id}
          role="tabpanel"
          hidden={activeTab !== tab.id}
          className="tab-panel"
        >
          <Chat persona={tab.persona} onActionConfirmed={handleActionConfirmed} />
        </div>
      ))}
    </div>
  );
}
