// API client: auth bootstrap, SSE chat streaming, uploads, my-items.
//
// SSE contract (each stream line is `data: {"event": <name>, "data": <payload>}`):
//   session        {session_id}
//   token          {text}
//   citations      [{n, title, uri, snippet}]
//   chart_spec     {vega_lite, sql}
//   action_request {intent, params, confirm_token}
//   error          {message, code}
//   done           {latency_ms, agents_used}

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8080';
const FIREBASE_CONFIG = import.meta.env.VITE_FIREBASE_CONFIG || '';

const DEMO_USER = 'demo-user';

let authReady = null; // Promise resolving to { mode: 'firebase'|'demo', getToken? }

function bootstrapAuth() {
  if (authReady) return authReady;
  authReady = (async () => {
    if (!FIREBASE_CONFIG) {
      return { mode: 'demo' };
    }
    const config = JSON.parse(FIREBASE_CONFIG);
    const { initializeApp } = await import('firebase/app');
    const { getAuth, signInAnonymously } = await import('firebase/auth');
    const app = initializeApp(config);
    const auth = getAuth(app);
    const cred = await signInAnonymously(auth);
    return {
      mode: 'firebase',
      getToken: () => cred.user.getIdToken(),
    };
  })();
  return authReady;
}

async function authHeaders(persona) {
  const auth = await bootstrapAuth();
  if (auth.mode === 'firebase') {
    const token = await auth.getToken();
    return { Authorization: `Bearer ${token}` };
  }
  return { 'X-Demo-User': DEMO_USER, 'X-Persona': persona };
}

/**
 * POST /api/v1/chat and stream SSE events.
 * onEvent(eventName, payload) is called for each parsed event.
 * Returns when the stream closes. Throws on network/HTTP failure.
 */
export async function streamChat({ sessionId, message, imageUri, persona }, onEvent) {
  const headers = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
    ...(await authHeaders(persona)),
  };
  const body = { message, persona };
  if (sessionId) body.session_id = sessionId;
  if (imageUri) body.image_uri = imageUri;

  const res = await fetch(`${API_URL}/api/v1/chat`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    throw new Error(`Chat request failed (${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const handleLine = (line) => {
    const trimmed = line.trim();
    if (!trimmed.startsWith('data:')) return;
    const json = trimmed.slice(5).trim();
    if (!json) return;
    let frame;
    try {
      frame = JSON.parse(json);
    } catch {
      return; // skip malformed frames
    }
    if (frame && frame.event) onEvent(frame.event, frame.data);
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf('\n')) >= 0) {
      handleLine(buffer.slice(0, idx));
      buffer = buffer.slice(idx + 1);
    }
  }
  if (buffer) handleLine(buffer);
}

/**
 * Upload an image: get a signed URL, PUT the bytes, return the gs:// URI.
 */
export async function uploadImage(file, persona) {
  const headers = await authHeaders(persona);
  const url = `${API_URL}/api/v1/uploads/signed-url?content_type=${encodeURIComponent(file.type)}`;
  const res = await fetch(url, { headers });
  if (!res.ok) throw new Error(`Signed URL request failed (${res.status})`);
  const { put_url: putUrl, gcs_uri: gcsUri } = await res.json();

  const put = await fetch(putUrl, {
    method: 'PUT',
    headers: { 'Content-Type': file.type },
    body: file,
  });
  if (!put.ok) throw new Error(`Upload failed (${put.status})`);
  return gcsUri;
}

/**
 * GET /api/v1/me/items → {referrals, subscriptions}
 */
export async function getMyItems(persona) {
  const headers = await authHeaders(persona);
  const res = await fetch(`${API_URL}/api/v1/me/items`, { headers });
  if (!res.ok) throw new Error(`My items request failed (${res.status})`);
  return res.json();
}
