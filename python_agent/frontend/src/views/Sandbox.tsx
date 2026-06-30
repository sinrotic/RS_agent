import { useState } from 'react';
import { DEBUG_PANEL_ENABLED, runSimulationScene } from '../api';
import { SimulationSceneResponse } from '../types';
import { AgentTimeline } from '../components/sandbox/AgentTimeline';
import { PersonaSprite, personaVisual } from '../components/sandbox/PersonaSprite';
import { Brain, Sparkles, Play, RefreshCw, Plus, Cpu, Trophy } from 'lucide-react';

const roleStaticInfo: Record<string, { goal: string; persona: string; style: string; preferred: string; negative: string }> = {
  commuter_practical: {
    goal: "需要高性价比且性能可靠的日常通勤音频设备，偏好蓝牙、无线。",
    persona: "注重性价比与简单实用的解释，对复杂和昂贵的品类有顾虑。",
    style: "谨慎决策 / 直接反馈",
    preferred: "蓝牙, 无线, 通勤",
    negative: "笨重, 有线"
  },
  gift_buyer: {
    goal: "需要选购一份容易让人满意且实用、体面的礼物。",
    persona: "注重礼品的体面，在决策前喜欢对比多种不同方向的备选品。",
    style: "均衡决策 / 探索式反馈",
    preferred: "流行, 礼物, 易用",
    negative: "复杂"
  },
  price_sensitive: {
    goal: "寻找低价实用、性价比极高的产品。",
    persona: "对价格极其敏感，对溢价过高或推荐不精准的品类具有很高的排斥度。",
    style: "快速拦截 / 批判性反馈",
    preferred: "折扣, 预算, 实惠",
    negative: "高档, 昂贵"
  }
};

export function Sandbox() {
  const [simLoading, setSimLoading] = useState(false);
  const [simError, setSimError] = useState('');
  const [simScene, setSimScene] = useState<SimulationSceneResponse | null>(null);
  const [simRole, setSimRole] = useState('commuter_practical');
  const [simMaxTurns, setSimMaxTurns] = useState(4);
  const [agents, setAgents] = useState<string[]>(['commuter_practical', 'gift_buyer']);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [selectedTurnIndex, setSelectedTurnIndex] = useState<number | null>(null);

  async function handleRunSimulation() {
    setSimLoading(true);
    setSimError('');
    setSimScene(null);
    setSelectedTurnIndex(null);
    try {
      const response = await runSimulationScene({ role_id: simRole, max_turns: simMaxTurns });
      setSimScene(response);
      if (response.session.public_timeline.events.length > 0) {
        setSelectedTurnIndex(response.session.public_timeline.events[response.session.public_timeline.events.length - 1].turn_index);
      }
    } catch (error) {
      setSimError(error instanceof Error ? error.message : 'Unknown error');
    } finally {
      setSimLoading(false);
    }
  }

  return (
    <div className="xl:h-full flex flex-col gap-3 min-h-0 xl:overflow-hidden">
      <div className="flex-shrink-0">
        <h1 className="text-2xl font-bold text-gray-900 mb-1">智能体沙盒</h1>
        <p className="text-gray-600 text-sm">模拟与评估基于 Persona 画像的多智能体交互，探索大模型与推荐底座协同决策轨迹。</p>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-12 gap-4 xl:gap-6 items-stretch flex-grow min-h-0">
        {/* Left Column (xl:col-span-3): Recommender Thoughts Panel */}
        <div className="xl:col-span-3 bg-white rounded-xl shadow-sm border border-gray-200 p-4 h-[550px] xl:h-full flex flex-col gap-3 overflow-hidden">
          <div className="flex items-center gap-2 border-b border-gray-150 pb-2.5 flex-shrink-0">
            <Cpu className="text-indigo-600" size={18} />
            <h2 className="font-bold text-gray-900 text-sm">{DEBUG_PANEL_ENABLED ? '推荐系统内部思考' : '仿真公开摘要'}</h2>
          </div>

          <div className="flex-grow overflow-y-auto pr-1 text-xs font-mono space-y-3 min-h-0">
            {!DEBUG_PANEL_ENABLED ? (
              <div className="h-full flex flex-col items-center justify-center text-gray-500 gap-3 text-center p-4 font-sans">
                <Brain size={32} className="opacity-30 text-indigo-600" />
                <span className="text-xs font-bold text-gray-700">公开试用模式</span>
                <p className="text-[11px] text-gray-500 leading-relaxed">仿真页面默认只展示 persona、对话轨迹和用户动作摘要；内部推荐工具链路与评估指标需开启 debug 面板后查看。</p>
              </div>
            ) : !simScene ? (
              <div className="h-full flex flex-col items-center justify-center text-gray-400 gap-2 text-center p-4">
                <Brain size={32} className="opacity-30 text-indigo-600" />
                <span className="text-xs">等待运行仿真...</span>
                <p className="text-[10px] text-gray-400 leading-normal">启动仿真后，点击对应对话气泡可在此查看该轮次推荐决策的详细轨迹。</p>
              </div>
            ) : !selectedTurnIndex ? (
              <div className="h-full flex flex-col items-center justify-center text-gray-400 text-center p-4">
                <span>请点击对话中的气泡来查看对应轮次的思考轨迹。</span>
              </div>
            ) : (() => {
              const event = simScene.session.public_timeline.events.find(e => e.turn_index === selectedTurnIndex);
              const displayResponse = event ? simScene.session.display_responses[event.display_response_index] : undefined;
              if (!event) {
                return (
                  <div className="h-full flex items-center justify-center text-gray-400 text-center">
                    <span>第 {selectedTurnIndex} 轮暂无公开交互摘要。</span>
                  </div>
                );
              }
              return (
                <div className="space-y-4 font-sans">
                  <div className="flex justify-between items-center bg-indigo-50 border border-indigo-100 p-2 rounded-lg flex-shrink-0">
                    <span className="font-bold text-indigo-800">公开交互摘要 (第 {selectedTurnIndex} 轮)</span>
                  </div>
                  <div className="bg-gray-50 border border-gray-150 p-2 rounded space-y-2 text-[11px]">
                    <div>
                      <div className="text-gray-400 text-[10px] font-semibold">用户动作</div>
                      <div className="text-gray-800">{event.user_message || '无用户输入'}</div>
                    </div>
                    <div>
                      <div className="text-gray-400 text-[10px] font-semibold">系统回复</div>
                      <div className="text-gray-800">{event.assistant_message}</div>
                    </div>
                    <div className="text-gray-500 text-[10px]">公开展示商品数：{displayResponse?.items.length || 0}</div>
                  </div>
                  <div className="text-[10px] text-gray-400 leading-relaxed">
                    仿真页面只读取 public_timeline 与 display_responses；内部工具链路、RAG 原始证据、奖励分和诊断不进入公开导出。
                  </div>
                </div>
              );
            })()}
          </div>
        </div>

        {/* Middle Column (xl:col-span-6): Chat Timeline Panel */}
        <div className="xl:col-span-6 h-[650px] xl:h-full flex flex-col min-h-0">
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 flex flex-col gap-4 h-full overflow-hidden">
            {/* Timeline Header */}
            <div className="flex items-center justify-between border-b border-gray-100 pb-3 flex-shrink-0">
              <div className="flex items-center gap-3">
                <PersonaSprite roleId={simRole} size="md" />
                <div>
                  <h2 className="font-bold text-gray-900 text-sm md:text-base leading-tight">
                    {roleStaticInfo[simRole]?.goal}
                  </h2>
                  <p className="text-xs text-gray-400">画像人设: {roleStaticInfo[simRole]?.persona}</p>
                </div>
              </div>
              <span className="text-[10px] bg-purple-100 text-purple-800 font-bold px-2 py-1 rounded-full whitespace-nowrap">
                多智能体交互中 (仿真引擎)
              </span>
            </div>

            {/* Conversation Flow */}
            <div className="flex-grow rounded-xl bg-gray-50 border border-gray-200 p-4 overflow-y-auto flex flex-col min-h-0">
              {simLoading && (
                <div className="flex-grow flex flex-col items-center justify-center text-gray-400 gap-3">
                  <RefreshCw className="animate-spin text-indigo-600" size={32} />
                  <span className="text-sm font-semibold">正在运行多智能体交互仿真，请稍候...</span>
                </div>
              )}

              {simError && (
                <div className="bg-red-50 border border-red-200 text-red-600 rounded-lg p-4 text-sm font-medium">
                  仿真运行失败：{simError}
                </div>
              )}

              {!simLoading && !simScene && !simError && (
                <div className="flex-grow flex flex-col items-center justify-center text-gray-400 gap-2">
                  <Brain size={48} className="opacity-40 text-indigo-600" />
                  <span className="text-sm text-center">点击下方按钮运行仿真，查看用户智能体与推荐系统智能体的多轮对话及推荐过程。</span>
                </div>
              )}

              {!simLoading && simScene && (
                <AgentTimeline 
                  simScene={simScene} 
                  selectedTurnIndex={selectedTurnIndex}
                  setSelectedTurnIndex={setSelectedTurnIndex}
                />
              )}
            </div>

            {/* Simulation controls row */}
            <div className="flex items-center gap-4 justify-between border-t border-gray-100 pt-4 flex-shrink-0">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold text-gray-500">最大对话轮数:</span>
                <input
                  type="number"
                  min="1"
                  max="8"
                  value={simMaxTurns}
                  onChange={e => setSimMaxTurns(parseInt(e.target.value))}
                  className="border border-gray-300 rounded-lg px-2.5 py-1 text-xs w-16 text-center focus:ring-indigo-500 focus:border-indigo-500 focus:outline-none"
                  disabled={simLoading}
                />
              </div>

              <button
                onClick={handleRunSimulation}
                disabled={simLoading}
                className="rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white px-5 py-2 text-xs font-bold shadow-sm transition-colors flex items-center gap-1.5 disabled:bg-gray-300 focus:outline-none"
              >
                {simLoading ? <RefreshCw size={14} className="animate-spin" /> : <Play size={14} />}
                {simLoading ? '正在生成仿真数据...' : '启动多智能体交互仿真'}
              </button>
            </div>
          </div>
        </div>

        {/* Right Column (xl:col-span-3): Sidebar & user agent controls */}
        <div className="xl:col-span-3 flex flex-col gap-4 h-[650px] xl:h-full overflow-hidden">
          {/* Agent list panel */}
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4 flex flex-col gap-4 flex-grow min-h-0">
            <div className="flex items-center justify-between border-b border-gray-100 pb-2 flex-shrink-0">
              <span className="font-bold text-gray-900 text-sm">可用智能体 (Agents)</span>
              <button
                onClick={() => setIsModalOpen(true)}
                className="p-1 rounded-md bg-indigo-50 border border-indigo-200 text-indigo-700 hover:bg-indigo-100 transition-colors flex items-center justify-center focus:outline-none"
                title="添加新智能体"
              >
                <Plus size={16} />
              </button>
            </div>

            <div className="space-y-2 flex-grow overflow-y-auto pr-1">
              {agents.map(roleId => {
                const visual = personaVisual(roleId);
                const isSelected = simRole === roleId;
                return (
                  <button
                    key={roleId}
                    onClick={() => {
                      setSimRole(roleId);
                      setSimScene(null);
                      setSimError('');
                      setSelectedTurnIndex(null);
                    }}
                    className={`w-full flex items-center gap-3 p-3 rounded-lg border text-left transition-all focus:outline-none ${
                      isSelected
                        ? 'bg-indigo-50 border-indigo-300 shadow-sm ring-1 ring-indigo-300'
                        : 'bg-white border-gray-200 hover:bg-gray-50'
                    }`}
                  >
                    <PersonaSprite roleId={roleId} size="sm" />
                    <div className="min-w-0 flex-1">
                      <div className="font-bold text-xs text-gray-900 truncate">{visual.display_name}</div>
                      <div className="text-[10px] text-gray-400 font-mono truncate">{roleId}</div>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Active Agent Configuration Summary Card */}
          <div className="bg-gradient-to-br from-indigo-900 to-slate-900 text-white rounded-xl p-4 shadow-sm space-y-2.5 flex-shrink-0">
            <div className="flex items-center gap-3 border-b border-indigo-800 pb-2 flex-shrink-0">
              <PersonaSprite roleId={simRole} size="md" />
              <div>
                <h3 className="font-bold text-sm leading-tight">{personaVisual(simRole).display_name}</h3>
                <span className="text-[9px] bg-indigo-800 text-indigo-200 px-1.5 py-0.5 rounded font-mono uppercase">{simRole}</span>
              </div>
            </div>
            
            <div className="grid grid-cols-2 gap-2 text-[11px] leading-snug text-indigo-100 flex-shrink-0">
              <div className="col-span-2">
                <span className="font-bold text-indigo-300 block mb-0.5">性格与特点:</span>
                <p className="text-gray-300 line-clamp-1" title={roleStaticInfo[simRole]?.persona}>{roleStaticInfo[simRole]?.persona}</p>
              </div>
              <div>
                <span className="font-bold text-indigo-300 block mb-0.5">反馈风格:</span>
                <p className="text-gray-300 truncate" title={roleStaticInfo[simRole]?.style}>{roleStaticInfo[simRole]?.style}</p>
              </div>
              <div>
                <span className="font-bold text-indigo-300 block mb-0.5">偏好标签:</span>
                <p className="text-gray-300 truncate" title={roleStaticInfo[simRole]?.preferred}>{roleStaticInfo[simRole]?.preferred}</p>
              </div>
              {roleStaticInfo[simRole]?.negative && (
                <div className="col-span-2">
                  <span className="font-bold text-rose-300 block mb-0.5">屏蔽关键词:</span>
                  <p className="text-rose-200 truncate">{roleStaticInfo[simRole]?.negative}</p>
                </div>
              )}
            </div>
          </div>

          {/* User Agent Thoughts Card (Dedicated White Box) */}
          {DEBUG_PANEL_ENABLED && (
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4 h-[200px] flex flex-col gap-2 flex-shrink-0 overflow-hidden">
            <div className="flex items-center gap-2 border-b border-gray-150 pb-2 flex-shrink-0">
              <Brain className="text-purple-600" size={16} />
              <h2 className="font-bold text-gray-900 text-sm">用户智能体内部思考</h2>
            </div>
            <div className="flex-grow overflow-y-auto pr-1 text-xs font-mono space-y-2 min-h-0 text-left">
              {!simScene ? (
                <div className="h-full flex flex-col items-center justify-center text-gray-400 gap-1 text-center p-2">
                  <span className="text-[11px] font-sans">等待运行仿真...</span>
                </div>
              ) : !selectedTurnIndex ? (
                <div className="h-full flex items-center justify-center text-gray-400 text-center p-2 font-sans">
                  <span>请点击气泡查看该轮决策。</span>
                </div>
              ) : (() => {
                const action = simScene.actions.find(act => act.turn_index === selectedTurnIndex);
                if (!action) {
                  return <p className="text-gray-400 italic font-sans text-center mt-4">此轮无具体决策数据。</p>;
                }

                let actionLabel = '发送需求 (CHAT)';
                const actType = (action.action_type || action.type) as string;
                if (actType === 'like') actionLabel = '商品点赞 (LIKE)';
                else if (actType === 'dislike') actionLabel = '商品踩/不喜欢 (DISLIKE)';
                else if (actType === 'show_different') actionLabel = '换一批 (SHOW_DIFFERENT)';
                else if (actType === 'why') actionLabel = '追问推荐原因 (WHY)';
                else if (actType === 'accept') actionLabel = '接受并购买 (ACCEPT)';
                else if (actType === 'stop') actionLabel = '终止对话 (STOP)';

                return (
                  <div className="space-y-3 font-sans">
                    <div className="flex justify-between items-center bg-purple-50 border border-purple-100 p-2 rounded-lg flex-shrink-0 font-sans">
                      <span className="font-bold text-purple-800">用户决策 (第 {selectedTurnIndex} 轮)</span>
                    </div>

                    {/* Section 1: Action Planning */}
                    <div className="space-y-1">
                      <div className="font-bold text-gray-800 flex items-center gap-1 text-[11px]">
                        <Sparkles size={11} className="text-purple-500" />
                        决策动作规划
                      </div>
                      <div className="bg-gray-50 border border-gray-150 p-2 rounded text-[10px] space-y-1 font-mono">
                        <div>
                          <span className="text-gray-450 font-sans">决策行为:</span>{' '}
                          <span className="font-bold text-purple-700 bg-purple-55 px-1.5 py-0.5 rounded">{actionLabel}</span>
                        </div>
                        {action.item_id && (
                          <div>
                            <span className="text-gray-455 font-sans">评估商品 ASIN:</span>{' '}
                            <span className="font-bold text-gray-800">{action.item_id}</span>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Section 2: Motivation & Comments */}
                    {action.comment && (
                      <div className="space-y-1">
                        <div className="font-bold text-gray-800 flex items-center gap-1 text-[11px]">
                          <Brain size={11} className="text-purple-500" />
                          反馈动机与理由
                        </div>
                        <div className="bg-white border border-gray-150 p-2 rounded text-[10px]">
                          <p className="italic text-gray-650 leading-relaxed font-sans">"{action.comment}"</p>
                        </div>
                      </div>
                    )}

                    {/* Section 3: Heartbeat Flow State */}
                    <div className="space-y-1">
                      <div className="font-bold text-gray-800 flex items-center gap-1 text-[11px]">
                        <Trophy size={11} className="text-yellow-500" />
                        智能体心流状态
                      </div>
                      <div className="bg-white border border-gray-150 p-2 rounded text-[10px] space-y-1">
                        <div className="flex justify-between items-center">
                          <span className="text-gray-400">当前满意度:</span>
                          <span className="font-bold text-purple-700">{simScene.state.satisfaction.toFixed(1)} / 5.0</span>
                        </div>
                        <div className="flex justify-between items-center">
                          <span className="text-gray-400">是否购买达成:</span>
                          <span className={`font-semibold ${simScene.state.ready_to_accept ? 'text-emerald-600' : 'text-amber-600'}`}>
                            {simScene.state.ready_to_accept ? '已购入 (READY)' : '对比选择中 (EXPLORING)'}
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })()}
            </div>
          </div>
          )}
        </div>
      </div>

      {/* 4. Pop-up Modal to Create/Add Agent */}
      {isModalOpen && (
        <div className="fixed inset-0 bg-gray-900/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl max-w-md w-full border border-gray-100 overflow-hidden flex flex-col">
            <div className="p-5 border-b border-gray-100 flex items-center justify-between">
              <h3 className="font-bold text-gray-900 text-base flex items-center gap-1.5">
                <Sparkles className="text-indigo-600" size={18} />
                选择并添加智能体人设
              </h3>
              <button
                type="button"
                onClick={() => setIsModalOpen(false)}
                className="text-gray-400 hover:text-gray-600 text-sm focus:outline-none"
              >
                ✕
              </button>
            </div>
            <div className="p-5 space-y-3 flex-grow overflow-y-auto max-h-[360px]">
              {['commuter_practical', 'gift_buyer', 'price_sensitive'].map(roleId => {
                const staticInfo = roleStaticInfo[roleId];
                const isAlreadyAdded = agents.includes(roleId);
                return (
                  <div
                    key={roleId}
                    className={`p-3 rounded-lg border flex gap-3 items-center ${
                      isAlreadyAdded ? 'bg-gray-50 border-gray-200 opacity-60' : 'bg-white border-gray-200 hover:border-indigo-300'
                    }`}
                  >
                    <PersonaSprite roleId={roleId} size="md" />
                    <div className="flex-grow min-w-0">
                      <div className="flex justify-between items-center mb-0.5">
                        <span className="font-bold text-xs text-gray-900">{personaVisual(roleId).display_name}</span>
                        {isAlreadyAdded && (
                          <span className="text-[9px] bg-gray-200 text-gray-600 px-1.5 py-0.5 rounded-full font-bold font-sans">已添加</span>
                        )}
                      </div>
                      <p className="text-[10px] text-gray-500 truncate">{staticInfo.goal}</p>
                      <div className="text-[9px] text-indigo-600 font-semibold font-mono mt-0.5">{staticInfo.style}</div>
                    </div>
                    {!isAlreadyAdded && (
                      <button
                        type="button"
                        onClick={() => {
                          setAgents(prev => [...prev, roleId]);
                          setSimRole(roleId);
                          setSimScene(null);
                          setSimError('');
                          setIsModalOpen(false);
                        }}
                        className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded text-[10px] font-bold focus:outline-none"
                      >
                        添加
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
