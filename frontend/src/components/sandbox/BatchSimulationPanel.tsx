import { useState } from 'react';
import { runSimulationBatch } from '../../api';
import { SimulationBatchResponse } from '../../types';
import { Layers, RefreshCw } from 'lucide-react';
import { PersonaSprite } from './PersonaSprite';

export function BatchSimulationPanel() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<SimulationBatchResponse | null>(null);
  const [repeats, setRepeats] = useState(2);
  const [maxTurns, setMaxTurns] = useState(4);
  const [selectedRoles, setSelectedRoles] = useState<string[]>(['commuter_practical', 'gift_buyer']);

  const allRoles = ['commuter_practical', 'gift_buyer', 'price_sensitive', 'brand_loyalist', 'tech_enthusiast'];

  function toggleRole(role: string) {
    setSelectedRoles(prev => 
      prev.includes(role) ? prev.filter(r => r !== role) : [...prev, role]
    );
  }

  async function handleRunBatch() {
    if (selectedRoles.length === 0) {
      setError('Please select at least one role.');
      return;
    }
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const res = await runSimulationBatch({
        role_ids: selectedRoles,
        max_turns: maxTurns,
        repeats: repeats
      });
      setResult(res);
    } catch (err: any) {
      setError(err.message || 'Error running batch simulation');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 flex flex-col gap-4 mt-8">
      <div className="flex items-center justify-between border-b border-gray-100 pb-4">
        <h2 className="text-xl font-bold text-gray-900 flex items-center gap-2">
          <Layers size={20} className="text-purple-600" />
          Batch Simulation Comparison
        </h2>
      </div>

      <div className="flex flex-col gap-4">
        <div>
          <label className="text-sm font-medium text-gray-700 block mb-2">Roles to Simulate</label>
          <div className="flex flex-wrap gap-2">
            {allRoles.map(role => (
              <button
                key={role}
                onClick={() => toggleRole(role)}
                disabled={loading}
                className={`px-3 py-1.5 text-xs rounded-full border transition-colors ${selectedRoles.includes(role) ? 'bg-purple-100 border-purple-300 text-purple-800' : 'bg-gray-50 border-gray-200 text-gray-600 hover:bg-gray-100'}`}
              >
                {role}
              </button>
            ))}
          </div>
        </div>

        <div className="flex gap-4">
          <div className="flex flex-col gap-1">
            <label className="text-sm font-medium text-gray-700">Repeats per Role</label>
            <input 
              type="number" min="1" max="5" value={repeats} onChange={e => setRepeats(parseInt(e.target.value))}
              className="border border-gray-300 rounded-lg px-3 py-2 text-sm w-24 focus:ring-purple-500 focus:border-purple-500" disabled={loading}
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-sm font-medium text-gray-700">Max Turns</label>
            <input 
              type="number" min="1" max="8" value={maxTurns} onChange={e => setMaxTurns(parseInt(e.target.value))}
              className="border border-gray-300 rounded-lg px-3 py-2 text-sm w-24 focus:ring-purple-500 focus:border-purple-500" disabled={loading}
            />
          </div>
          <div className="flex items-end">
            <button
              onClick={handleRunBatch} disabled={loading}
              className="rounded-lg bg-purple-600 px-5 py-2 text-sm font-semibold text-white hover:bg-purple-700 disabled:bg-gray-300 h-10 flex items-center gap-2"
            >
              {loading && <RefreshCw size={16} className="animate-spin" />}
              {loading ? 'Running Batch...' : 'Run Batch Simulation'}
            </button>
          </div>
        </div>
      </div>

      {error && <div className="bg-red-50 text-red-600 p-4 rounded-lg text-sm mt-2">{error}</div>}

      {result && (
        <div className="mt-6 space-y-6">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-gray-50 p-4 rounded-lg border border-gray-200">
              <div className="text-xs text-gray-500 uppercase font-semibold">Total Scenes</div>
              <div className="text-2xl font-bold text-gray-900">{result.summary.scene_count}</div>
            </div>
            <div className="bg-gray-50 p-4 rounded-lg border border-gray-200">
              <div className="text-xs text-gray-500 uppercase font-semibold">Accept Rate</div>
              <div className="text-2xl font-bold text-gray-900">{(result.summary.accept_rate * 100).toFixed(1)}%</div>
            </div>
            <div className="bg-gray-50 p-4 rounded-lg border border-gray-200">
              <div className="text-xs text-gray-500 uppercase font-semibold">Avg Satisfaction</div>
              <div className="text-2xl font-bold text-gray-900">{result.summary.avg_satisfaction.toFixed(2)}</div>
            </div>
            <div className="bg-gray-50 p-4 rounded-lg border border-gray-200">
              <div className="text-xs text-gray-500 uppercase font-semibold">Avg Turns</div>
              <div className="text-2xl font-bold text-gray-900">{result.summary.avg_turn_count.toFixed(1)}</div>
            </div>
          </div>

          <div>
            <h3 className="text-lg font-bold text-gray-900 mb-3">Role Comparison</h3>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 border border-gray-200 rounded-lg overflow-hidden text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-3 text-left font-medium text-gray-500">Role</th>
                    <th className="px-4 py-3 text-right font-medium text-gray-500">Scenes</th>
                    <th className="px-4 py-3 text-right font-medium text-gray-500">Accept Rate</th>
                    <th className="px-4 py-3 text-right font-medium text-gray-500">Avg Turns</th>
                    <th className="px-4 py-3 text-right font-medium text-gray-500">Satisfaction</th>
                    <th className="px-4 py-3 text-right font-medium text-gray-500">Feedback/Why</th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {Object.entries(result.summary.roles || {}).map(([role, stats]: [string, any]) => (
                    <tr key={role}>
                      <td className="px-4 py-3 font-medium text-gray-900 flex items-center gap-2">
                        <PersonaSprite roleId={role} size="sm" />
                        {role}
                      </td>
                      <td className="px-4 py-3 text-right text-gray-700">{stats.scene_count}</td>
                      <td className="px-4 py-3 text-right text-gray-700">{(stats.accept_rate * 100).toFixed(1)}%</td>
                      <td className="px-4 py-3 text-right text-gray-700">{stats.avg_turn_count.toFixed(1)}</td>
                      <td className="px-4 py-3 text-right text-gray-700">{stats.avg_satisfaction.toFixed(2)}</td>
                      <td className="px-4 py-3 text-right text-gray-700">{stats.feedback_count} / {stats.why_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
