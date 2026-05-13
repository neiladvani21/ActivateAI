import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import ReactMarkdown from 'react-markdown';
import GeofenceMap from './GeofenceMap';

const TOOL_META = {
  get_weather: { label: 'Weather', color: 'bg-sky-100 text-sky-700', icon: '🌤' },
  geocode_location: { label: 'Geocode', color: 'bg-violet-100 text-violet-700', icon: '📍' },
  search_pois: { label: 'POI Search', color: 'bg-emerald-100 text-emerald-700', icon: '🗺' },
  suggest_geofence: { label: 'Geofence', color: 'bg-amber-100 text-amber-700', icon: '⬡' },
  generate_image: { label: 'Banner', color: 'bg-pink-100 text-pink-700', icon: '🖼' },
};

function ToolBadge({ tool }) {
  const meta = TOOL_META[tool] || { label: tool, color: 'bg-slate-100 text-slate-600', icon: '⚙' };
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium ${meta.color}`}>
      <span>{meta.icon}</span>
      {meta.label}
    </span>
  );
}

function ToolsUsed({ tools }) {
  const [open, setOpen] = useState(false);
  if (!tools?.length) return null;
  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-600 transition"
      >
        <span className={`transition-transform ${open ? 'rotate-90' : ''}`}>▶</span>
        Tools used ({tools.length})
      </button>
      {open && (
        <div className="mt-2 flex flex-wrap gap-2">
          {tools.map((tool) => <ToolBadge key={tool} tool={tool} />)}
        </div>
      )}
    </div>
  );
}

const LOADING_HINTS = [
  'Checking location data…',
  'Fetching weather conditions…',
  'Searching nearby POIs…',
  'Calculating geofence…',
  'Building your campaign…',
];

function ThinkingIndicator() {
  const [hintIdx, setHintIdx] = useState(0);

  useEffect(() => {
    const t = setInterval(() => setHintIdx((i) => (i + 1) % LOADING_HINTS.length), 2000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="flex justify-start">
      <div className="flex items-center gap-3 rounded-xl bg-white px-4 py-3 text-sm text-slate-600 shadow-sm">
        <span className="flex gap-1">
          {[0, 1, 2].map((i) => (
            <span
              key={i}
              className="h-2 w-2 rounded-full bg-slate-400"
              style={{ animation: `bounce 1.2s ease-in-out ${i * 0.2}s infinite` }}
            />
          ))}
        </span>
        <span className="text-slate-500 transition-all">{LOADING_HINTS[hintIdx]}</span>
      </div>
    </div>
  );
}

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8001';

function generateSessionId() {
  return 'sess_' + Math.random().toString(36).slice(2) + Date.now().toString(36);
}

function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState(() => {
    return sessionStorage.getItem('session_id') || generateSessionId();
  });

  const messagesEndRef = useRef(null);

  useEffect(() => {
    sessionStorage.setItem('session_id', sessionId);
  }, [sessionId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const suggestedPrompts = useMemo(
    () => [
      {
        icon: '☕',
        title: 'Coffee Campaign',
        description: 'Cold weather activation near Jersey City',
        prompt: 'Find coffee shops near Jersey City NJ and suggest a cold weather activation',
      },
      {
        icon: '🏙',
        title: 'Grocery Push',
        description: 'Weather-based campaign in New York',
        prompt: 'Check New York weather and suggest a marketing campaign for nearby grocery stores',
      },
      {
        icon: '💪',
        title: 'Gym Activation',
        description: 'Morning workout push near Austin TX',
        prompt: 'Find gyms near Austin TX and suggest a morning workout activation',
      },
      {
        icon: '🍔',
        title: 'Fast Food Drive',
        description: 'Lunch hour campaign near Chicago',
        prompt: 'Find fast food restaurants near Chicago IL and suggest a lunch hour activation campaign',
      },
    ],
    []
  );

  const sendMessage = useCallback(async (text) => {
    const trimmed = (text || input).trim();
    if (!trimmed || loading) return;

    setMessages((prev) => [...prev, { role: 'user', content: trimmed }]);
    setInput('');
    setLoading(true);

    // Placeholder agent message we'll update token by token
    const placeholderIdx = (prev) => prev.length;
    setMessages((prev) => [...prev, { role: 'agent', content: '', toolsUsed: [], pois: [], geofenceRadiusM: null, mapCenter: null, imageUrl: null }]);

    try {
      const local_time = new Date().toLocaleTimeString('en-US', {
        hour: '2-digit', minute: '2-digit', hour12: true, weekday: 'short'
      });

      const response = await fetch(`${API_BASE_URL}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: trimmed, session_id: sessionId, local_time }),
      });

      if (!response.ok) throw new Error(`Server error: ${response.status}`);

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop(); // keep incomplete line in buffer

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const chunk = JSON.parse(line.slice(6));

            if (chunk.type === 'token') {
              setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                updated[updated.length - 1] = { ...last, content: last.content + chunk.content };
                return updated;
              });
            } else if (chunk.type === 'done') {
              setLoading(false);
              setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                updated[updated.length - 1] = {
                  ...last,
                  toolsUsed: chunk.tools_used || [],
                  pois: chunk.pois || [],
                  geofenceRadiusM: chunk.geofence_radius_m || null,
                  mapCenter: chunk.map_center || null,
                  imageUrl: chunk.image_url || null,
                };
                return updated;
              });
            } else if (chunk.type === 'error') {
              setLoading(false);
              setMessages((prev) => {
                const updated = [...prev];
                updated[updated.length - 1] = {
                  role: 'agent', content: chunk.content, toolsUsed: [], isError: true,
                };
                return updated;
              });
            }
          } catch (_) {}
        }
      }
    } catch (error) {
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          role: 'agent',
          content: `Unable to process your request right now.\n\n${error.message}`,
          toolsUsed: [],
          isError: true,
        };
        return updated;
      });
    } finally {
      setLoading(false);
    }
  }, [input, loading, sessionId]);

  const onInputKeyDown = (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  };

  const startNewChat = async () => {
    try {
      await axios.delete(`${API_BASE_URL}/session/${sessionId}`);
    } catch (_) {
      // best-effort clear on server
    }
    const newId = generateSessionId();
    setSessionId(newId);
    setMessages([]);
    setInput('');
  };

  return (
    <div className="min-h-screen text-slate-100" style={{background: 'linear-gradient(135deg, #0a0a0f 0%, #0d0d1a 50%, #0a0a0f 100%)'}}>
      <div className="mx-auto flex h-screen w-full max-w-5xl flex-col px-4 py-4 sm:px-6 sm:py-6">
        <header className="mb-4 flex items-center justify-between rounded-2xl p-4 sm:mb-5 sm:p-5" style={{background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(139,92,246,0.25)', boxShadow: '0 0 30px rgba(139,92,246,0.08)'}}>
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl text-xl shadow-lg" style={{background: 'linear-gradient(135deg, #7c3aed, #2563eb)', boxShadow: '0 0 20px rgba(124,58,237,0.5)'}}>
              ⚡
            </div>
            <div>
              <h1 className="text-xl font-black tracking-tight sm:text-2xl" style={{background: 'linear-gradient(90deg, #a78bfa, #60a5fa)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent'}}>
                ActivateAI
              </h1>
              <p className="mt-0.5 text-xs font-medium sm:text-sm" style={{color: 'rgba(148,163,184,0.7)'}}>
                AI-Powered Marketing Activation Platform
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={startNewChat}
            disabled={loading}
            className="rounded-xl px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50"
            style={{background: 'rgba(139,92,246,0.15)', border: '1px solid rgba(139,92,246,0.35)', color: '#c4b5fd'}}
            onMouseEnter={e => { e.currentTarget.style.background = 'rgba(139,92,246,0.25)'; e.currentTarget.style.borderColor = 'rgba(139,92,246,0.6)'; }}
            onMouseLeave={e => { e.currentTarget.style.background = 'rgba(139,92,246,0.15)'; e.currentTarget.style.borderColor = 'rgba(139,92,246,0.35)'; }}
          >
            New Chat
          </button>
        </header>

        <main className="flex min-h-0 flex-1 flex-col rounded-2xl" style={{background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(139,92,246,0.15)'}}>
          <section className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 sm:p-5">
            {messages.length === 0 && (
              <div className="flex flex-col items-center justify-center h-full py-8 px-2">
                <div className="relative mb-2 flex h-16 w-16 items-center justify-center rounded-2xl text-3xl" style={{background: 'linear-gradient(135deg, #7c3aed, #2563eb)', boxShadow: '0 0 40px rgba(124,58,237,0.6), 0 0 80px rgba(124,58,237,0.2)'}}>
                  ⚡
                </div>
                <h2 className="mt-4 text-2xl font-black text-white tracking-tight">Welcome to ActivateAI</h2>
                <p className="mt-2 text-sm text-center max-w-sm" style={{color: 'rgba(148,163,184,0.8)'}}>
                  Describe a location and brand — get a ready-to-launch marketing activation in seconds.
                </p>

                <p className="mt-8 mb-4 text-xs font-bold uppercase tracking-widest" style={{color: 'rgba(139,92,246,0.7)'}}>
                  Try a prompt
                </p>

                <div className="grid grid-cols-1 gap-3 w-full max-w-2xl sm:grid-cols-2">
                  {suggestedPrompts.map((item) => (
                    <button
                      key={item.prompt}
                      type="button"
                      onClick={() => sendMessage(item.prompt)}
                      disabled={loading}
                      className="group flex items-start gap-3 rounded-xl p-4 text-left transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-50"
                      style={{background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)'}}
                      onMouseEnter={e => { e.currentTarget.style.background = 'rgba(139,92,246,0.1)'; e.currentTarget.style.borderColor = 'rgba(139,92,246,0.4)'; e.currentTarget.style.boxShadow = '0 0 20px rgba(139,92,246,0.1)'; }}
                      onMouseLeave={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.03)'; e.currentTarget.style.borderColor = 'rgba(255,255,255,0.07)'; e.currentTarget.style.boxShadow = 'none'; }}
                    >
                      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-xl transition-all" style={{background: 'rgba(139,92,246,0.15)', border: '1px solid rgba(139,92,246,0.25)'}}>
                        {item.icon}
                      </span>
                      <div className="pt-0.5">
                        <p className="text-sm font-bold text-white">{item.title}</p>
                        <p className="mt-0.5 text-xs" style={{color: 'rgba(148,163,184,0.7)'}}>{item.description}</p>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((message, index) => {
              const isStreaming = loading && message.role === 'agent' && index === messages.length - 1;
              return (
              <div
                key={`${message.role}-${index}`}
                className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-[90%] rounded-xl sm:max-w-[80%] ${!message.content && isStreaming ? '' : 'px-4 py-3'}`}
                  style={
                    !message.content && isStreaming
                      ? {}
                      : message.role === 'user'
                        ? { background: 'linear-gradient(135deg, rgba(124,58,237,0.3), rgba(37,99,235,0.2))', border: '1px solid rgba(139,92,246,0.35)', color: 'white' }
                        : message.isError
                          ? { background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', color: '#fca5a5' }
                          : { background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.1)', color: '#e2e8f0' }
                  }
                >
                  {message.role === 'agent' ? (
                    <div className="prose prose-sm prose-invert max-w-none prose-p:my-1 prose-strong:text-white prose-li:my-0.5 prose-headings:text-white prose-code:text-violet-300">
                      <ReactMarkdown>{message.content}</ReactMarkdown>
                      {isStreaming && (
                        <div className="mt-3 inline-flex items-center gap-2 rounded-full px-3 py-1.5" style={{background: 'rgba(139,92,246,0.12)', border: '1px solid rgba(139,92,246,0.3)'}}>
                          <span className="flex gap-[3px] items-center">
                            {[0,1,2].map(i => (
                              <span key={i} className="inline-block w-1 h-1 rounded-full" style={{background: '#a78bfa', animation: `bounce 1s ease-in-out ${i * 0.15}s infinite`}} />
                            ))}
                          </span>
                          <span className="text-xs font-semibold tracking-wide" style={{color: '#a78bfa'}}>ActivateAI is working</span>
                        </div>
                      )}
                    </div>
                  ) : (
                    <p className="m-0 whitespace-pre-wrap text-sm sm:text-base">{message.content}</p>
                  )}

                  {message.role === 'agent' && message.pois?.length > 0 && (
                    <GeofenceMap
                      pois={message.pois}
                      geofenceRadiusM={message.geofenceRadiusM}
                      mapCenter={message.mapCenter}
                    />
                  )}

                  {message.role === 'agent' && message.imageUrl && (
                    <div className="mt-4">
                      <p className="mb-2 text-xs font-medium text-slate-400 uppercase tracking-wide">Generated Campaign Banner</p>
                      <div className="relative w-full rounded-xl border border-slate-200 overflow-hidden bg-slate-100" style={{minHeight: '200px'}}>
                        <p className="absolute inset-0 flex items-center justify-center text-xs text-slate-400">Generating image...</p>
                        <img
                          src={message.imageUrl}
                          alt="Generated marketing banner"
                          className="relative w-full rounded-xl"
                          style={{display: 'block'}}
                          onLoad={(e) => { e.target.previousSibling.style.display = 'none'; }}
                          onError={(e) => { e.target.previousSibling.textContent = 'Image unavailable. '; e.target.style.display = 'none'; }}
                        />
                      </div>
                      <p className="mt-1 text-xs text-slate-400">
                        <a href={message.imageUrl} target="_blank" rel="noreferrer" className="underline">Open image in new tab</a>
                      </p>
                    </div>
                  )}

                  <ToolsUsed tools={message.toolsUsed} />
                </div>
              </div>
              );
            })}


            <div ref={messagesEndRef} />
          </section>

          <section className="p-4 sm:p-5" style={{borderTop: '1px solid rgba(139,92,246,0.15)'}}>
            <div className="flex items-end gap-3">
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={onInputKeyDown}
                placeholder="Type your request... (Shift+Enter for new line)"
                rows={2}
                disabled={loading}
                className="min-h-[52px] flex-1 resize-none rounded-xl px-4 py-3 text-sm text-white outline-none transition disabled:cursor-not-allowed disabled:opacity-70"
                style={{background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(139,92,246,0.2)', color: 'white'}}
                onFocus={e => { e.currentTarget.style.borderColor = 'rgba(139,92,246,0.6)'; e.currentTarget.style.boxShadow = '0 0 0 3px rgba(139,92,246,0.1)'; }}
                onBlur={e => { e.currentTarget.style.borderColor = 'rgba(139,92,246,0.2)'; e.currentTarget.style.boxShadow = 'none'; }}
              />
              <button
                type="button"
                onClick={() => sendMessage()}
                disabled={loading || !input.trim()}
                className="h-[52px] rounded-xl px-5 text-sm font-bold transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-40"
                style={{background: 'linear-gradient(135deg, #7c3aed, #2563eb)', color: 'white', boxShadow: '0 0 20px rgba(124,58,237,0.4)'}}
                onMouseEnter={e => { if (!e.currentTarget.disabled) e.currentTarget.style.boxShadow = '0 0 30px rgba(124,58,237,0.7)'; }}
                onMouseLeave={e => { e.currentTarget.style.boxShadow = '0 0 20px rgba(124,58,237,0.4)'; }}
              >
                Send
              </button>
            </div>
          </section>
        </main>
      </div>
    </div>
  );
}

export default App;
