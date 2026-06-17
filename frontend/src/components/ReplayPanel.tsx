import { SessionExportResponse, SanitizedTimelineEvent } from '../types';

function eventLabel(event: SanitizedTimelineEvent) {
  if (event.event_type === 'chat') return '用户对话';
  if (event.event_type === 'feedback') return '用户反馈';
  return event.event_type.toUpperCase();
}

export function ReplayPanel({ data, onClose, error }: { data: SessionExportResponse | null; onClose: () => void; error: string }) {
  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 text-red-600 rounded-lg p-4 mt-8 text-sm">
        {error}
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 flex flex-col gap-4 mt-8">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold text-gray-900">会话交互历史重放</h2>
        <button onClick={onClose} className="text-sm text-indigo-600 hover:text-indigo-800 font-semibold focus:outline-none">关闭</button>
      </div>
      {data.public_timeline.events.length === 0 ? (
        <div className="text-center text-gray-500 py-4">此会话未发现任何交互事件。</div>
      ) : (
        <div className="space-y-8 mt-4">
          {data.public_timeline.events.map((event) => {
            const displayInfo = data.display_responses[event.display_response_index];
            return (
              <div key={event.public_event_id} className="border border-indigo-100 rounded-lg p-4 bg-indigo-50/30 text-left">
                <div className="flex justify-between items-start mb-3">
                  <span className="text-xs font-semibold text-indigo-800 bg-indigo-100 px-2 py-1 rounded">第 {event.turn_index} 轮 - {eventLabel(event)}</span>
                </div>

                <div className="mb-2 text-sm text-gray-800">
                  <span className="font-semibold text-purple-700">用户 Agent: </span>
                  <span>{event.user_message}</span>
                </div>

                <div className="mb-4 text-sm text-gray-800">
                  <span className="font-semibold text-indigo-700">推荐系统: </span>
                  <span>{event.assistant_message}</span>
                </div>

                {displayInfo?.items && displayInfo.items.length > 0 ? (
                  <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3 mt-4 pt-4 border-t border-indigo-100">
                    {displayInfo.items.map(item => (
                      <div key={item.parent_asin} className="bg-white border border-gray-200 rounded-lg p-2 text-xs flex flex-col gap-1 justify-between">
                         <div className="font-medium text-gray-800 truncate" title={item.title || item.parent_asin}>{item.title || item.parent_asin}</div>
                         {item.price && <div className="text-gray-900 font-semibold mt-1">{typeof item.price === 'number' ? `$${item.price.toFixed(2)}` : item.price}</div>}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="mt-4 pt-4 border-t border-indigo-100 text-xs text-gray-500 italic">
                    未展示任何推荐商品。
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
