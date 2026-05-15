import { Play, RefreshCw } from 'lucide-react';
import { PersonaSprite } from './PersonaSprite';

interface PersonaStatePanelProps {
  simScene: any;
  simRole: string;
  setSimRole: (val: string) => void;
  simMaxTurns: number;
  setSimMaxTurns: (val: number) => void;
  onRunSimulation: () => void;
  simLoading: boolean;
  simError: string;
}

export function PersonaStatePanel({
  simScene, simRole, setSimRole, simMaxTurns, setSimMaxTurns, onRunSimulation, simLoading, simError
}: PersonaStatePanelProps) {
  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 flex flex-col gap-4 mt-8">
      <div className="flex items-center justify-between border-b border-gray-100 pb-4">
        <h2 className="text-xl font-bold text-gray-900 flex items-center gap-2">
          <Play size={20} className="text-indigo-600" />
          Multi-role Persona Agent Sandbox
        </h2>
      </div>
      <div className="flex flex-wrap gap-4 items-end">
        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium text-gray-700">Role Preset</label>
          <select 
            value={simRole} 
            onChange={e => setSimRole(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-indigo-500 focus:border-indigo-500 bg-white"
            disabled={simLoading}
          >
            <option value="commuter_practical">Commuter Practical</option>
            <option value="gift_buyer">Gift Buyer</option>
            <option value="price_sensitive">Price Sensitive</option>
            <option value="brand_loyalist">Brand Loyalist</option>
            <option value="tech_enthusiast">Tech Enthusiast</option>
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium text-gray-700">Max Turns</label>
          <input 
            type="number" 
            min="1" 
            max="8"
            value={simMaxTurns}
            onChange={e => setSimMaxTurns(parseInt(e.target.value))}
            className="border border-gray-300 rounded-lg px-3 py-2 text-sm w-24 focus:ring-indigo-500 focus:border-indigo-500"
            disabled={simLoading}
          />
        </div>
        <button
          onClick={onRunSimulation}
          disabled={simLoading}
          className="rounded-lg bg-indigo-600 px-5 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:bg-gray-300 whitespace-nowrap h-10 flex items-center gap-2"
        >
          {simLoading && <RefreshCw size={16} className="animate-spin" />}
          {simLoading ? 'Running...' : 'Run Simulation'}
        </button>
      </div>

      {simError && (
        <div className="bg-red-50 border border-red-200 text-red-600 rounded-lg p-4 text-sm mt-2">
          {simError}
        </div>
      )}

      {simScene && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 text-sm">
            <div className="flex items-center gap-3 mb-2 border-b border-blue-200 pb-2">
               <PersonaSprite roleId={simScene.role.role_id} size="lg" />
               <h3 className="font-bold text-blue-900">Role: {simScene.role.role_id}</h3>
            </div>
            <div className="space-y-1 text-blue-800">
              <div><span className="font-semibold">Persona:</span> {simScene.role.persona}</div>
              <div><span className="font-semibold">Goal:</span> {simScene.role.shopping_goal}</div>
              <div><span className="font-semibold">Style:</span> {simScene.role.decision_style} / {simScene.role.feedback_style}</div>
              <div><span className="font-semibold">Categories:</span> {simScene.role.category_preferences?.join(', ')}</div>
              <div><span className="font-semibold">Keywords:</span> {simScene.role.keyword_preferences?.join(', ')}</div>
              <div><span className="font-semibold">Negative:</span> {simScene.role.negative_preferences?.join(', ')}</div>
            </div>
          </div>
          <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-sm">
            <h3 className="font-bold text-green-900 mb-2 border-b border-green-200 pb-2">Final State</h3>
            <div className="space-y-1 text-green-800">
              <div><span className="font-semibold">Satisfaction:</span> {simScene.state.satisfaction} / 5.0</div>
              <div><span className="font-semibold">Final Action:</span> {simScene.state.final_action}</div>
              <div><span className="font-semibold">Accepted Item:</span> {simScene.state.accepted_item_id || 'None'}</div>
              <div><span className="font-semibold">Turns Observed:</span> {simScene.state.turns_observed}</div>
              <div><span className="font-semibold">Seen Items:</span> {simScene.state.seen_item_ids?.length}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
