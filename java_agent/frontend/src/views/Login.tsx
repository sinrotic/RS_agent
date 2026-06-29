import React, { useState } from 'react';
import { ShieldCheck, UserPlus, KeyRound, Sparkles } from 'lucide-react';
import { register, login } from '../api/authClient';

interface LoginProps {
  onLoginSuccess: () => void;
}

export function Login({ onLoginSuccess }: LoginProps) {
  const [isRegister, setIsRegister] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [nickname, setNickname] = useState('');
  const [bindStrategy, setBindStrategy] = useState<'random' | 'manual' | 'segment'>('random');
  const [profileUserId, setProfileUserId] = useState('');
  const [segment, setSegment] = useState('Smart Tech Commuters');
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccessMsg('');
    setLoading(true);

    try {
      if (isRegister) {
        await register({
          username,
          password,
          nickname: nickname || undefined,
          bindStrategy,
          profileUserId: bindStrategy === 'manual' ? profileUserId : undefined,
          segment: bindStrategy === 'segment' ? segment : undefined
        });
        setSuccessMsg('注册成功！正在进入推荐系统...');
      } else {
        await login({ username, password });
        setSuccessMsg('登录成功！正在加载个性化商城...');
      }

      setTimeout(() => {
        onLoginSuccess();
      }, 1000);
    } catch (err: any) {
      setError(err.message || '操作失败，请检查后端服务');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex-1 flex items-center justify-center min-h-[70vh] px-4 py-8">
      <div className="relative w-full max-w-md bg-slate-800/90 border border-slate-700/80 rounded-3xl p-8 shadow-2xl overflow-hidden glass-panel">
        {/* Glow decoration */}
        <div className="absolute -top-24 -left-24 w-48 h-48 bg-indigo-500/20 rounded-full blur-3xl"></div>
        <div className="absolute -bottom-24 -right-24 w-48 h-48 bg-purple-500/20 rounded-full blur-3xl"></div>

        <div className="relative z-10 flex flex-col items-center">
          {/* Header Icon */}
          <div className="bg-gradient-to-tr from-indigo-500 to-purple-500 p-3.5 rounded-2xl text-white shadow-lg shadow-indigo-500/20 mb-6">
            {isRegister ? <UserPlus size={28} /> : <KeyRound size={28} />}
          </div>

          <h2 className="text-2xl font-extrabold tracking-tight text-white mb-2">
            {isRegister ? '注册推荐 Agent 账户' : '登录推荐系统'}
          </h2>
          <p className="text-slate-400 text-xs text-center mb-8 max-w-[280px]">
            {isRegister 
              ? '创建一个新账户，并自动绑定电商画像数据集中的虚拟用户画像'
              : '连接 Java 统一网关，加载您专属的个性化推荐与对话能力'}
          </p>

          {error && (
            <div className="w-full bg-rose-500/10 border border-rose-500/20 text-rose-450 px-4 py-2.5 rounded-xl text-xs font-semibold mb-4 text-center">
              ⚠️ {error}
            </div>
          )}

          {successMsg && (
            <div className="w-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 px-4 py-2.5 rounded-xl text-xs font-semibold mb-4 text-center animate-pulse">
              ✓ {successMsg}
            </div>
          )}

          <form onSubmit={handleSubmit} className="w-full space-y-4 text-left">
            <div>
              <label className="block text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1.5 pl-1">
                用户名
              </label>
              <input
                type="text"
                required
                value={username}
                onChange={e => setUsername(e.target.value)}
                placeholder="输入用户名"
                className="w-full rounded-xl bg-slate-950/60 border border-slate-700/60 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 px-4 py-3 text-xs text-white transition-all pl-4 placeholder-slate-600"
              />
            </div>

            <div>
              <label className="block text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1.5 pl-1">
                密码
              </label>
              <input
                type="password"
                required
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="输入账户密码"
                className="w-full rounded-xl bg-slate-950/60 border border-slate-700/60 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 px-4 py-3 text-xs text-white transition-all pl-4 placeholder-slate-600"
              />
            </div>

            {isRegister && (
              <>
                <div>
                  <label className="block text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1.5 pl-1">
                    昵称
                  </label>
                  <input
                    type="text"
                    value={nickname}
                    onChange={e => setNickname(e.target.value)}
                    placeholder="选填，默认同用户名"
                    className="w-full rounded-xl bg-slate-950/60 border border-slate-700/60 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 px-4 py-3 text-xs text-white transition-all pl-4 placeholder-slate-600"
                  />
                </div>

                <div>
                  <label className="block text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1.5 pl-1">
                    画像绑定策略
                  </label>
                  <select
                    value={bindStrategy}
                    onChange={e => setBindStrategy(e.target.value as any)}
                    className="w-full rounded-xl bg-slate-950/60 border border-slate-700/60 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 px-4 py-3 text-xs text-white transition-all cursor-pointer"
                  >
                    <option value="random">随机画像绑定 (推荐)</option>
                    <option value="manual">手动指定画像 ID (profileUserId)</option>
                    <option value="segment">按特定特征人群划分 (Segment)</option>
                  </select>
                </div>

                {bindStrategy === 'manual' && (
                  <div>
                    <label className="block text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1.5 pl-1">
                      画像用户 ID (profile_user_id)
                    </label>
                    <input
                      type="text"
                      required
                      value={profileUserId}
                      onChange={e => setProfileUserId(e.target.value)}
                      placeholder="例如: user_12345"
                      className="w-full rounded-xl bg-slate-950/60 border border-slate-700/60 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 px-4 py-3 text-xs text-white transition-all pl-4 placeholder-slate-600"
                    />
                  </div>
                )}

                {bindStrategy === 'segment' && (
                  <div>
                    <label className="block text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-1.5 pl-1">
                      人群特征组 (Segment)
                    </label>
                    <select
                      value={segment}
                      onChange={e => setSegment(e.target.value)}
                      className="w-full rounded-xl bg-slate-950/60 border border-slate-700/60 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 px-4 py-3 text-xs text-white transition-all cursor-pointer"
                    >
                      <option value="Smart Tech Commuters">智能数码通勤族</option>
                      <option value="Home Comfort Seekers">居家舒适乐享派</option>
                      <option value="Outdoor Sports Enthusiasts">户外运动达人</option>
                      <option value="Budget Accessory Finders">低价性价比配件型</option>
                    </select>
                  </div>
                )}
              </>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-gradient-to-r from-indigo-500 to-purple-500 hover:from-indigo-600 hover:to-purple-600 text-white font-bold rounded-xl py-3.5 text-xs transition-all shadow-lg shadow-indigo-500/25 flex items-center justify-center gap-1.5 disabled:opacity-50 cursor-pointer mt-4"
            >
              {loading ? (
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
              ) : isRegister ? (
                <>
                  <Sparkles size={14} />
                  绑定画像并注册
                </>
              ) : (
                <>
                  <ShieldCheck size={14} />
                  安全登录
                </>
              )}
            </button>
          </form>

          <div className="mt-6 border-t border-slate-700/50 w-full pt-4 text-center">
            <button
              type="button"
              onClick={() => {
                setIsRegister(!isRegister);
                setError('');
                setSuccessMsg('');
              }}
              className="text-xs text-indigo-400 hover:text-indigo-300 font-semibold transition-colors cursor-pointer"
            >
              {isRegister ? '已有账户？立即登录' : '没有账户？创建画像账户'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
