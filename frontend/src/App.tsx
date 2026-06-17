import { useState } from 'react';
import { LiveDemo } from './views/LiveDemo';
import { Sandbox } from './views/Sandbox';
import { MallHome } from './views/MallHome';
import { MessageSquare, LayoutDashboard, ShoppingBag } from 'lucide-react';

export default function App() {
  const [view, setView] = useState<'demo' | 'sandbox' | 'mall'>('mall');

  return (
    <div className="xl:h-screen min-h-screen bg-gray-50 flex flex-col xl:overflow-hidden">
      <header className="bg-white border-b border-gray-200 flex-shrink-0 z-10">
        <div className="w-full px-6 lg:px-8">
          <div className="flex justify-between items-center h-14">
            <div className="flex items-center gap-2">
              <div className="bg-indigo-600 text-white p-1.5 rounded-lg flex-shrink-0">
                <ShoppingBag size={18} />
              </div>
              <span className="font-bold text-lg text-gray-900 tracking-tight">推荐智能体交互系统</span>
            </div>
            <nav className="flex gap-1">
              <button
                onClick={() => setView('mall')}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors flex items-center gap-1.5 ${view === 'mall' ? 'bg-indigo-50 text-indigo-700' : 'text-gray-600 hover:bg-gray-100'}`}
              >
                <ShoppingBag size={14} />
                推荐商城
              </button>
              <button
                onClick={() => setView('demo')}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors flex items-center gap-1.5 ${view === 'demo' ? 'bg-indigo-50 text-indigo-700' : 'text-gray-600 hover:bg-gray-100'}`}
              >
                <MessageSquare size={14} />
                实时演示
              </button>
              <button
                onClick={() => setView('sandbox')}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors flex items-center gap-1.5 ${view === 'sandbox' ? 'bg-purple-50 text-purple-700' : 'text-gray-600 hover:bg-gray-100'}`}
              >
                <LayoutDashboard size={14} />
                智能体沙盒
              </button>
            </nav>
          </div>
        </div>
      </header>

      <main className="flex-1 py-4 py-6 px-4 lg:px-8 w-full mx-auto flex flex-col min-h-0 xl:overflow-hidden">
        {view === 'mall' ? <MallHome /> : view === 'demo' ? <LiveDemo /> : <Sandbox />}
      </main>
    </div>
  );
}
