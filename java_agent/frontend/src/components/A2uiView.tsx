import { ReactNode } from 'react';
import { ProductCard, ProductFeedbackAction } from './ProductCard';
import { DisplayProduct } from '../utils/displayViewModel';
import { UiComponent, UiState, resolveUiValue, updateUiData } from '../utils/a2ui';

interface Props {
  state: UiState;
  products: DisplayProduct[];
  disabled: boolean;
  feedbackDisabled?: boolean;
  onStateChange: (state: UiState) => void;
  onSubmit: (query: string) => void;
  onOpen: (product: DisplayProduct) => void;
  onFeedback: (action: ProductFeedbackAction, itemId: string) => void;
}

/** Native shopping components render only the application catalog, never model-generated code. */
export function A2uiView({ state, products, disabled, feedbackDisabled = false, onStateChange, onSubmit, onOpen, onFeedback }: Props) {
  return <div className="space-y-4">
    {Array.from(state.values(), surface => {
      function render(id: string, ancestors = new Set<string>()): ReactNode {
        const component: UiComponent | undefined = surface.components.get(id);
        if (!component || ancestors.has(id) || ancestors.size > 32) return null;
        const next = new Set(ancestors).add(id);
        switch (component.component) {
          case 'Text': return <p key={id} className="text-sm whitespace-pre-wrap">{resolveUiValue(component.text, surface.data)}</p>;
          case 'Column': case 'Row': return <div key={id} className={component.component === 'Row'
            ? 'flex flex-wrap items-start gap-3' : 'flex flex-col gap-3'}>
            {component.children.map(child => render(child, next))}
          </div>;
          case 'Card': return <div key={id} className="rounded-xl border border-slate-700 p-4">{render(component.child, next)}</div>;
          case 'ProductCards': {
            const cards = Array.from(new Set(component.itemIds)).flatMap(itemId => {
              const item = products.find(product => product.itemId === itemId);
              return item ? [<ProductCard key={itemId} item={item} onFeedback={onFeedback} onOpen={onOpen}
                disabled={disabled || feedbackDisabled} position={products.indexOf(item) + 1} />] : [];
            });
            return cards.length ? <div key={id} className={component.layout === 'grid'
              ? 'grid grid-cols-1 md:grid-cols-2 gap-3' : 'grid grid-cols-1 gap-3'}>{cards}</div> : null;
          }
          case 'TextField': return <label key={id} className="flex flex-col gap-1 text-xs">
            {component.label}
            <input type={component.textFieldType === 'number' ? 'number' : 'text'} disabled={disabled}
              value={resolveUiValue(component.value, surface.data)} maxLength={4000}
              onChange={event => {
                const updated = new Map(state);
                updated.set(surface.surfaceId, { ...surface,
                  data: updateUiData(surface.data, component.value.path, event.target.value) });
                onStateChange(updated);
              }}
              className="rounded-lg border border-slate-600 bg-slate-950 px-3 py-2 text-white" />
          </label>;
          case 'Button': {
            const event = component.action.event;
            const query = resolveUiValue(event.context.query, surface.data).trim();
            return <button key={id} type="button" disabled={disabled || !query}
              onClick={() => { if (event.name === 'submit_query' && query) onSubmit(query); }}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-white disabled:opacity-50">
              {render(component.child, next)}
            </button>;
          }
        }
      }
      const content = render('root');
      return content == null ? null : <section key={surface.surfaceId} data-a2ui-surface-id={surface.surfaceId}
        aria-label="交互推荐界面">{content}</section>;
    })}
  </div>;
}
