import React, { useEffect, useRef, useState } from 'react';
import { streamChat } from '../api.js';
import Citations from './Citations.jsx';
import ChartView from './ChartView.jsx';
import ActionConfirm from './ActionConfirm.jsx';
import UploadButton from './UploadButton.jsx';

let nextId = 1;
const newId = () => nextId++;

export default function Chat({ persona, onActionConfirmed }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [pendingImage, setPendingImage] = useState(null); // {gcsUri, name}
  const sessionIdRef = useRef(null);
  const scrollRef = useRef(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const updateMessage = (id, updater) => {
    setMessages((msgs) => msgs.map((m) => (m.id === id ? updater(m) : m)));
  };

  const send = async (text, { isConfirmReply = false } = {}) => {
    const message = text.trim();
    if (!message || streaming) return;

    const imageUri = pendingImage ? pendingImage.gcsUri : null;
    const imageName = pendingImage ? pendingImage.name : null;
    setPendingImage(null);
    setInput('');
    setStreaming(true);

    const userMsg = { id: newId(), role: 'user', text: message, imageName };
    const assistantId = newId();
    const assistantMsg = {
      id: assistantId,
      role: 'assistant',
      text: '',
      citations: null,
      chartSpec: null,
      actionRequest: null,
      streaming: true,
    };
    setMessages((msgs) => [...msgs, userMsg, assistantMsg]);

    try {
      await streamChat(
        { sessionId: sessionIdRef.current, message, imageUri, persona },
        (event, data) => {
          switch (event) {
            case 'session':
              sessionIdRef.current = data.session_id;
              break;
            case 'token':
              updateMessage(assistantId, (m) => ({ ...m, text: m.text + data.text }));
              break;
            case 'citations':
              updateMessage(assistantId, (m) => ({ ...m, citations: data }));
              break;
            case 'chart_spec':
              updateMessage(assistantId, (m) => ({ ...m, chartSpec: data }));
              break;
            case 'action_request':
              updateMessage(assistantId, (m) => ({
                ...m,
                actionRequest: { ...data, resolved: false },
              }));
              break;
            case 'error':
              setMessages((msgs) => [
                ...msgs,
                {
                  id: newId(),
                  role: 'system-error',
                  text: `${data.message}${data.code ? ` (${data.code})` : ''}`,
                },
              ]);
              break;
            case 'done':
              break;
            default:
              break;
          }
        }
      );
      if (isConfirmReply && onActionConfirmed) {
        onActionConfirmed();
      }
    } catch (err) {
      setMessages((msgs) => [
        ...msgs,
        { id: newId(), role: 'system-error', text: err.message || 'Request failed.' },
      ]);
    } finally {
      updateMessage(assistantId, (m) => ({ ...m, streaming: false }));
      setStreaming(false);
    }
  };

  const handleActionResponse = (messageId, confirmed) => {
    updateMessage(messageId, (m) => ({
      ...m,
      actionRequest: { ...m.actionRequest, resolved: true, confirmed },
    }));
    // The agent holds pending state server-side; a literal yes/no resolves it.
    send(confirmed ? 'yes' : 'no', { isConfirmReply: confirmed });
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    send(input);
  };

  return (
    <div className="chat">
      <div className="messages" ref={scrollRef} aria-live="polite">
        {messages.length === 0 && (
          <p className="empty-hint">
            {persona === 'analyst'
              ? 'Ask about utilization, trends, or forecasts — answers come with charts and the SQL behind them.'
              : 'Ask about nearby care, programs, and eligibility — or upload a referral letter photo.'}
          </p>
        )}
        {messages.map((m) => (
          <div key={m.id} className={`bubble-row ${m.role}`}>
            <div className={`bubble ${m.role}`}>
              {m.imageName && <span className="image-chip">📎 {m.imageName}</span>}
              {m.text && <div className="bubble-text">{m.text}</div>}
              {m.streaming && !m.text && <span className="typing">…</span>}
              {m.citations && m.citations.length > 0 && <Citations citations={m.citations} />}
              {m.chartSpec && <ChartView chartSpec={m.chartSpec} />}
              {m.actionRequest && (
                <ActionConfirm
                  actionRequest={m.actionRequest}
                  disabled={streaming}
                  onRespond={(confirmed) => handleActionResponse(m.id, confirmed)}
                />
              )}
            </div>
          </div>
        ))}
      </div>

      <form className="composer" onSubmit={handleSubmit}>
        {pendingImage && (
          <span className="image-chip pending">
            📎 {pendingImage.name}
            <button
              type="button"
              className="chip-remove"
              aria-label="Remove attachment"
              onClick={() => setPendingImage(null)}
            >
              ×
            </button>
          </span>
        )}
        <div className="composer-row">
          <UploadButton
            persona={persona}
            disabled={streaming}
            onUploaded={(gcsUri, name) => setPendingImage({ gcsUri, name })}
            onError={(msg) =>
              setMessages((msgs) => [...msgs, { id: newId(), role: 'system-error', text: msg }])
            }
          />
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={streaming ? 'Waiting for response…' : 'Type your message'}
            aria-label="Message"
            disabled={streaming}
          />
          <button type="submit" disabled={streaming || !input.trim()}>
            Send
          </button>
        </div>
      </form>

      <p className="disclaimer" role="note">
        Informational only — not medical advice. In an emergency call your local emergency
        number.
      </p>
    </div>
  );
}
