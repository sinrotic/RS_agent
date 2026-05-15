import { useState } from 'react';
import { runSimulationScene } from '../api';
import { SimulationSceneResponse } from '../types';
import { PersonaStatePanel } from '../components/sandbox/PersonaStatePanel';
import { AgentTimeline } from '../components/sandbox/AgentTimeline';
import { BatchSimulationPanel } from '../components/sandbox/BatchSimulationPanel';

export function Sandbox() {
  const [simLoading, setSimLoading] = useState(false);
  const [simError, setSimError] = useState('');
  const [simScene, setSimScene] = useState<SimulationSceneResponse | null>(null);
  const [simRole, setSimRole] = useState('commuter_practical');
  const [simMaxTurns, setSimMaxTurns] = useState(4);

  async function handleRunSimulation() {
    setSimLoading(true);
    setSimError('');
    setSimScene(null);
    try {
      const response = await runSimulationScene({ role_id: simRole, max_turns: simMaxTurns });
      setSimScene(response);
    } catch (error) {
      setSimError(error instanceof Error ? error.message : 'Unknown error');
    } finally {
      setSimLoading(false);
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 mb-2">Agent Sandbox</h1>
        <p className="text-gray-600">Simulate and evaluate persona-based multi-agent interactions.</p>
      </div>
      
      <PersonaStatePanel
        simScene={simScene}
        simRole={simRole}
        setSimRole={setSimRole}
        simMaxTurns={simMaxTurns}
        setSimMaxTurns={setSimMaxTurns}
        onRunSimulation={handleRunSimulation}
        simLoading={simLoading}
        simError={simError}
      />
      
      <AgentTimeline simScene={simScene} />
      
      <BatchSimulationPanel />
    </div>
  );
}
