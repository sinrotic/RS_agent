import type { DemoRoundtripRequest, DemoRoundtripResponse, SimulationBatchRequest, SimulationBatchResponse, SimulationSceneRequest, SimulationSceneResponse } from '../types';
import { postJson } from './shared';

export async function runSimulationScene(request: SimulationSceneRequest): Promise<SimulationSceneResponse> {
  return postJson<SimulationSceneResponse>('/simulation/scene', request);
}

export async function runSimulationBatch(request: SimulationBatchRequest): Promise<SimulationBatchResponse> {
  return postJson<SimulationBatchResponse>('/simulation/batch', request);
}

export async function runDemoRoundtrip(request: DemoRoundtripRequest): Promise<DemoRoundtripResponse> {
  return postJson<DemoRoundtripResponse>('/demo/e2e', request);
}
