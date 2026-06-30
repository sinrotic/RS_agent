import { useEffect, useRef } from 'react';
import { SimulationSceneResponse } from '../../types';
import { Trophy, User, Cpu } from 'lucide-react';
import { ProductCard } from '../ProductCard';

interface AgentTimelineProps {
  simScene: SimulationSceneResponse | null;
  selectedTurnIndex: number | null;
  setSelectedTurnIndex: (turnIndex: number | null) => void;
}

export function AgentTimeline({ simScene, selectedTurnIndex, setSelectedTurnIndex }: AgentTimelineProps) {
  const timelineEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    timelineEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [simScene]);

  if (!simScene) return null;

  return (
    <div className="flex flex-col gap-4 w-full">
      {simScene.session.public_timeline.events.map((event) => {
        const displayInfo = simScene.session.display_responses[event.display_response_index];
        const isSelected = event.turn_index === selectedTurnIndex;

        return (
          <div key={event.public_event_id} className="flex flex-col gap-3 w-full">
            {/* User Agent message bubble (Purple, aligned to Right) */}
            <div 
              onClick={() => setSelectedTurnIndex(event.turn_index)}
              className={`flex flex-col gap-1 max-w-[85%] self-end items-end cursor-pointer transition-all duration-200 ${
                isSelected 
                  ? 'scale-[1.01] ring-2 ring-purple-400 ring-offset-2 ring-offset-gray-50 shadow-md' 
                  : 'hover:scale-[1.005]'
              }`}
            >
              <div className="text-[10px] text-gray-400 px-2 font-semibold uppercase flex items-center gap-1">
                <User size={10} className="text-purple-500" />
                用户智能体 (User Agent - {simScene.role.role_id})
              </div>
              <div className="rounded-2xl p-4 text-sm shadow-sm bg-purple-600 text-white rounded-tr-none text-left w-full">
                <p className="whitespace-pre-wrap leading-relaxed">{event.user_message}</p>
                <div className="mt-2 text-[9px] text-purple-200 border-t border-purple-500/30 pt-1.5 flex justify-between">
                  <span>第 {event.turn_index} 轮对话</span>
                  <span>点击查看决策轨迹</span>
                </div>
              </div>
            </div>

            {/* Recommendation Agent message bubble (White, aligned to Left) */}
            <div 
              onClick={() => setSelectedTurnIndex(event.turn_index)}
              className={`flex flex-col gap-1 max-w-[85%] self-start items-start w-full cursor-pointer transition-all duration-200 ${
                isSelected 
                  ? 'scale-[1.01] ring-2 ring-indigo-400 ring-offset-2 ring-offset-gray-50 shadow-md' 
                  : 'hover:scale-[1.005]'
              }`}
            >
              <div className="text-[10px] text-gray-400 px-2 font-semibold uppercase flex items-center gap-1">
                <Cpu size={10} className="text-indigo-500" />
                推荐系统智能体 (Recommendation Agent)
              </div>
              <div className="rounded-2xl p-4 text-sm shadow-sm bg-white text-gray-800 border border-gray-200 rounded-tl-none w-full text-left">
                <p className="whitespace-pre-wrap leading-relaxed">{event.assistant_message}</p>

                {/* Inline Recommended Items */}
                {displayInfo?.items && displayInfo.items.length > 0 && (
                  <div className="mt-4 pt-4 border-t border-gray-100">
                    <h4 className="font-semibold text-xs text-gray-500 uppercase tracking-wider mb-3">为您推荐以下商品：</h4>
                    <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
                      {displayInfo.items.map((item) => (
                        <div key={item.parent_asin} className="w-full">
                          <ProductCard
                            item={item}
                            onFeedback={() => {}}
                            disabled={true}
                          />
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                
                <div className="mt-3 text-[9px] text-gray-400 border-t border-gray-150 pt-1.5 flex justify-between">
                  <span>第 {event.turn_index} 轮推荐</span>
                  <span className="text-indigo-600 font-semibold">点击查看内部决策轨迹</span>
                </div>
              </div>
            </div>
          </div>
        );
      })}

      {/* 4. Terminal System Outcome Message */}
      {simScene.metrics && (
        <div className="self-center bg-emerald-50 border border-emerald-200 text-emerald-850 rounded-2xl px-5 py-4 text-xs font-medium my-3 max-w-[90%] shadow-sm flex flex-col gap-2 items-center text-center">
          <div className="font-bold flex items-center gap-1.5 text-sm text-emerald-850">
            <Trophy size={16} className="text-amber-500 animate-bounce" />
            仿真交互流程已闭环
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 font-mono text-[11px] text-emerald-700 mt-1.5 border-t border-emerald-100/60 pt-2.5 w-full">
            <div className="flex flex-col">
              <span className="text-emerald-555 font-sans">客户满意度</span>
              <span className="text-sm font-extrabold text-emerald-800">{simScene.state.satisfaction} / 5.0</span>
            </div>
            <div className="flex flex-col">
              <span className="text-emerald-555 font-sans">总对话轮数</span>
              <span className="text-sm font-extrabold text-emerald-800">{simScene.metrics.turn_count} / {simScene.actions.length}</span>
            </div>
            <div className="flex flex-col">
              <span className="text-emerald-555 font-sans">最终动作</span>
              <span className="text-sm font-extrabold text-purple-700 uppercase">{simScene.metrics.final_action}</span>
            </div>
            <div className="flex flex-col">
              <span className="text-emerald-555 font-sans">是否购买达成</span>
              <span className={`text-sm font-extrabold ${simScene.metrics.accepted ? 'text-emerald-600' : 'text-gray-500'}`}>
                {simScene.metrics.accepted ? 'YES' : 'NO'}
              </span>
            </div>
          </div>
          {simScene.metrics.accepted_item_id && (
            <div className="mt-2 text-[10px] bg-white border border-emerald-200 rounded px-2.5 py-1 text-emerald-800 font-mono">
              已购入 ASIN 商品: <span className="font-bold text-indigo-600">{simScene.metrics.accepted_item_id}</span>
            </div>
          )}
        </div>
      )}
      <div ref={timelineEndRef} />
    </div>
  );
}
