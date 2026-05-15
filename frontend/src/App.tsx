import { useState } from 'react';
import { LiveDemo } from './views/LiveDemo';
import { Sandbox } from './views/Sandbox';
import { MessageSquare, LayoutDashboard } from 'lucide-react';

export default function App() {
  const [view, setView] = useState<'demo' | 'sandbox'>('demo');

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      <header className="bg-white border-b border-gray-200 sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center gap-2">
              <div className="bg-indigo-600 text-white p-1.5 rounded-lg">
                <MessageSquare size={20} />
              </div>
              <span className="font-bold text-xl text-gray-900 tracking-tight">RS Agent Frontend</span>
            </div>
            <nav className="flex gap-1">
              <button
                onClick={() => setView('demo')}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${view === 'demo' ? 'bg-indigo-50 text-indigo-700' : 'text-gray-600 hover:bg-gray-100'}`}
              >
                Live Demo
              </button>
              <button
                onClick={() => setView('sandbox')}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2 ${view === 'sandbox' ? 'bg-purple-50 text-purple-700' : 'text-gray-600 hover:bg-gray-100'}`}
              >
                <LayoutDashboard size={16} />
                Agent Sandbox
              </button>
            </nav>
          </div>
        </div>
      </header>

      <main className="flex-1 py-8 px-4 sm:px-6 lg:px-8 max-w-6xl mx-auto w-full">
        {view === 'demo' ? <LiveDemo /> : <Sandbox />}
      </main>
    </div>
  );
}
