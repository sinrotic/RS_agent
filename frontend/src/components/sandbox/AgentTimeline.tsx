export function AgentTimeline({ simScene }: { simScene: any }) {
  if (!simScene) return null;

  return (
    <div className="mt-6 flex flex-col gap-6">
      <div className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
        <h3 className="font-bold text-gray-900 mb-4 border-b border-gray-100 pb-2">Actions Timeline (Agent-to-Agent)</h3>
        <div className="space-y-4">
          {simScene.actions.map((action: any, i: number) => (
            <div key={i} className="flex gap-3 text-sm">
              <div className="flex flex-col items-center">
                <div className="w-6 h-6 rounded-full bg-gray-100 border border-gray-300 flex items-center justify-center text-xs font-bold text-gray-600">{action.turn_index}</div>
                {i < simScene.actions.length - 1 && <div className="w-px h-full bg-gray-200 my-1"></div>}
              </div>
              <div className="flex-1 pb-2">
                <div className="font-semibold text-gray-800 uppercase text-xs tracking-wider mb-1">
                  {action.type} {action.action_type ? `• ${action.action_type}` : ''}
                </div>
                {action.message && <div className="text-gray-700 bg-gray-50 p-2 rounded border border-gray-100">"{action.message}"</div>}
                {action.comment && <div className="text-gray-600 mt-1 italic text-xs">Comment: "{action.comment}"</div>}
                {action.item_id && <div className="text-gray-500 mt-1 text-xs">Item: {action.item_id}</div>}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
        <h3 className="font-bold text-gray-900 mb-4 border-b border-gray-100 pb-2">Session Summary</h3>
        <div className="space-y-4">
          {simScene.session.events.map((event: any, i: number) => {
            const displayInfo = simScene.session.display_responses[event.display_response_index];
            return (
              <div key={i} className="border border-indigo-100 rounded-lg bg-indigo-50/30 p-4 text-sm">
                <div className="flex justify-between items-start mb-2">
                  <span className="text-xs font-semibold text-indigo-800 bg-indigo-100 px-2 py-1 rounded">Turn {event.turn_index} - {event.type.toUpperCase()}</span>
                </div>
                <div className="mb-2">
                  <span className="font-semibold text-gray-800">User Agent: </span>
                  <span className="text-gray-700">
                    {event.type === 'chat' ? event.user_input : `Feedback [${event.action_type}]`}
                    {event.item_id && ` on item ${event.item_id}`}
                    {event.comment && ` - "${event.comment}"`}
                  </span>
                </div>
                <div className="mb-3">
                  <span className="font-semibold text-indigo-700">RS Agent: </span>
                  <span className="text-gray-700">{event.assistant_message}</span>
                </div>
                {displayInfo?.items && displayInfo.items.length > 0 && (
                  <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2 mt-3 pt-3 border-t border-indigo-100">
                    {displayInfo.items.map((item: any) => (
                      <div key={item.parent_asin} className="bg-white border border-gray-200 rounded p-1.5 text-xs">
                         <div className="font-medium text-gray-800 truncate" title={item.title || item.parent_asin}>{item.title || item.parent_asin}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
