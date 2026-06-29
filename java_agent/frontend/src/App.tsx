import { useState, useEffect } from 'react';
import { MallHome } from './views/MallHome';
import { AgentChat } from './views/AgentChat';
import { Login } from './views/Login';
import { ObserveConsole } from './views/ObserveConsole';
import { getAccessToken, getStoredProfileUserId, isMockMode, setMockMode, logout, clearTokens } from './api';
import { Activity, ShoppingBag, MessageSquare, LogOut, ShieldCheck, ToggleLeft, ToggleRight, Wifi, WifiOff } from 'lucide-react';
import { getMe } from './api/authClient';

export default function App() {
  const [view, setView] = useState<'login' | 'mall' | 'chat'>('login');
  const [username, setUsername] = useState<string>('');
  const [profileUserId, setProfileUserId] = useState<string>('');
  const [isMock, setIsMock] = useState<boolean>(isMockMode());
  const [backendStatus, setBackendStatus] = useState<'checking' | 'online' | 'offline'>('checking');
  const isObserveRoute = window.location.pathname.startsWith('/observe') || window.location.pathname.startsWith('/ops');

  // Check auth state and backend connectivity on mount
  useEffect(() => {
    const token = getAccessToken();
    if (token) {
      getMe()
        .then(user => {
          setUsername(user.nickname || user.username);
          setProfileUserId(user.profileUserId);
          setView('mall');
        })
        .catch(() => {
          // Token expired or invalid
          clearTokens();
          setView('login');
        });
    } else {
      setView('login');
    }

    // Ping check backend
    checkBackend();
  }, []);

  const checkBackend = async () => {
    setBackendStatus('checking');
    try {
      const controller = new AbortController();
      const id = setTimeout(() => controller.abort(), 2000);
      const res = await fetch('/api/auth/me', { signal: controller.signal });
      clearTimeout(id);
      if (res.status === 404 || res.status === 401 || res.status === 200) {
        setBackendStatus('online');
      } else {
        setBackendStatus('offline');
      }
    } catch {
      setBackendStatus('offline');
    }
  };

  const handleLoginSuccess = () => {
    const pUserId = getStoredProfileUserId() || 'guest_user';
    setProfileUserId(pUserId);
    getMe().then(user => {
      setUsername(user.nickname || user.username);
    }).catch(() => {
      setUsername('已登录账户');
    });
    setView('mall');
  };

  const handleLogout = async () => {
    try {
      await logout();
    } catch (e) {
      console.error('Logout failed', e);
    }
    setView('login');
    setUsername('');
    setProfileUserId('');
  };

  const toggleMockMode = () => {
    const target = !isMock;
    setMockMode(target);
    setIsMock(target);
    // Reload active view
    if (view !== 'login') {
      window.location.reload();
    }
  };

  return (
    <div className="xl:h-screen min-h-screen bg-slate-950 text-slate-100 flex flex-col xl:overflow-hidden font-sans">
      <header className="bg-slate-900 border-b border-slate-800 flex-shrink-0 z-10">
        <div className="w-full px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center gap-2">
              <div className="bg-indigo-600 text-white p-2 rounded-xl flex-shrink-0 shadow-lg shadow-indigo-600/30">
                {isObserveRoute ? <Activity size={18} /> : <ShoppingBag size={18} />}
              </div>
              <span className="font-extrabold text-base tracking-tight gradient-text">
                {isObserveRoute ? 'JavaAgent 平台观测控制台' : 'JavaAgent 推荐底座系统'}
              </span>
            </div>

            {/* Middle Nav - Only visible if logged in */}
            {!isObserveRoute && view !== 'login' && (
              <nav className="flex gap-2">
                <button
                  onClick={() => setView('mall')}
                  className={`px-4 py-2 rounded-xl text-xs font-bold transition-all flex items-center gap-2 cursor-pointer ${
                    view === 'mall' 
                      ? 'bg-indigo-600 text-white shadow-md shadow-indigo-600/20' 
                      : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
                  }`}
                >
                  <ShoppingBag size={14} />
                  智能推荐商城
                </button>
                <button
                  onClick={() => setView('chat')}
                  className={`px-4 py-2 rounded-xl text-xs font-bold transition-all flex items-center gap-2 cursor-pointer ${
                    view === 'chat' 
                      ? 'bg-indigo-600 text-white shadow-md shadow-indigo-600/20' 
                      : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
                  }`}
                >
                  <MessageSquare size={14} />
                  Agent 对话助手
                </button>
              </nav>
            )}

            {/* Right Controls */}
            <div className="flex items-center gap-4">
              {/* Mock Status Toggler */}
              <div className="flex items-center gap-1.5 bg-slate-950 border border-slate-800 rounded-full px-3 py-1 text-[10px] font-bold">
                <span className="text-slate-400 font-sans">本地Mock模式</span>
                <button 
                  onClick={toggleMockMode}
                  className="text-indigo-400 hover:text-indigo-300 transition-colors flex items-center cursor-pointer"
                >
                  {isMock ? (
                    <ToggleRight size={18} className="text-indigo-400" />
                  ) : (
                    <ToggleLeft size={18} className="text-slate-500" />
                  )}
                </button>
              </div>

              {/* Gateway Connection Tagger */}
              <div className="flex items-center gap-1 bg-slate-950 border border-slate-800 rounded-full px-3 py-1 text-[10px] font-bold">
                {backendStatus === 'online' ? (
                  <>
                    <Wifi size={12} className="text-emerald-400 animate-pulse" />
                    <span className="text-emerald-400">Gateway 在线</span>
                  </>
                ) : backendStatus === 'offline' ? (
                  <>
                    <WifiOff size={12} className="text-rose-450" />
                    <span className="text-rose-450">Gateway 离线</span>
                  </>
                ) : (
                  <span className="text-slate-400">检测网关...</span>
                )}
              </div>

              {/* User Profiling info & Logout */}
              {!isObserveRoute && view !== 'login' && (
                <div className="flex items-center gap-3 border-l border-slate-850 pl-4">
                  <div className="text-right">
                    <div className="text-xs font-bold text-slate-200 flex items-center gap-1">
                      <ShieldCheck size={12} className="text-indigo-400" />
                      {username}
                    </div>
                    <div className="text-[9px] text-slate-500 font-mono">ID: {profileUserId}</div>
                  </div>
                  <button
                    onClick={handleLogout}
                    className="p-2 rounded-lg bg-slate-800 text-slate-400 hover:text-rose-450 hover:bg-slate-700/60 transition-all cursor-pointer"
                    title="退出登录"
                  >
                    <LogOut size={14} />
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      </header>

      <main className="flex-1 py-6 px-6 lg:px-8 w-full mx-auto flex flex-col min-h-0 xl:overflow-hidden bg-slate-950">
        {isObserveRoute && <ObserveConsole />}
        {!isObserveRoute && view === 'login' && <Login onLoginSuccess={handleLoginSuccess} />}
        {!isObserveRoute && view === 'mall' && <MallHome />}
        {!isObserveRoute && view === 'chat' && <AgentChat />}
      </main>
    </div>
  );
}
