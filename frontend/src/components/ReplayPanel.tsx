import { SessionExportResponse } from '../types';

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
        <h2 className="text-xl font-bold text-gray-900">Session Replay</h2>
        <button onClick={onClose} className="text-sm text-gray-500 hover:text-gray-700">Close</button>
      </div>
      {data.events.length === 0 ? (
        <div className="text-center text-gray-500 py-4">No events found in this session.</div>
      ) : (
        <div className="space-y-8 mt-4">
          {data.events.map((event, i) => {
            const displayInfo = data.display_responses[event.display_response_index];
            return (
              <div key={i} className="border border-indigo-100 rounded-lg p-4 bg-indigo-50/30">
                <div className="flex justify-between items-start mb-3">
                  <span className="text-xs font-semibold text-indigo-800 bg-indigo-100 px-2 py-1 rounded">Turn {event.turn_index} - {event.type.toUpperCase()}</span>
                </div>
                
                <div className="mb-2">
                  <span className="font-semibold text-gray-800">User: </span>
                  <span className="text-gray-700">
                    {event.type === 'chat' ? event.user_input : `Feedback [${event.action_type}]`}
                    {event.item_id && ` on item ${event.item_id}`}
                    {event.comment && ` - "${event.comment}"`}
                  </span>
                </div>
                
                <div className="mb-4">
                  <span className="font-semibold text-indigo-700">Agent: </span>
                  <span className="text-gray-700">{event.assistant_message}</span>
                </div>
                
                {displayInfo?.items && displayInfo.items.length > 0 ? (
                  <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3 mt-4 pt-4 border-t border-indigo-100">
                    {displayInfo.items.map(item => (
                      <div key={item.parent_asin} className="bg-white border border-gray-200 rounded-lg p-2 text-xs flex flex-col gap-1">
                         <div className="font-medium text-gray-800 truncate" title={item.title || item.parent_asin}>{item.title || item.parent_asin}</div>
                         {item.price && <div className="text-gray-900 font-semibold">{typeof item.price === 'number' ? `$${item.price.toFixed(2)}` : item.price}</div>}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="mt-4 pt-4 border-t border-indigo-100 text-xs text-gray-500 italic">
                    No items displayed.
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
