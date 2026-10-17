import type { AgentAnswerBlock } from '../types/agent';
import type { DisplayProduct } from './displayViewModel';
import { SHOPPING_CATALOG_ID, UiComponent, UiState, applyA2uiMessages, visibleUiProductIds } from './a2ui';

interface AgentDisplay {
  products: DisplayProduct[];
  answerBlocks?: AgentAnswerBlock[];
  cardSetId?: string;
}

/**
 * All structured Agent displays use A2UI, including business-generated defaults.
 * This is a disposable display projection, not model state or Session history.
 * Product facts always come from hydrated business results; messages contain only IDs.
 */
export function projectAgentUi(modelState: UiState, display: AgentDisplay): UiState {
  const currentTurnHasUi = (display.answerBlocks || []).some(block => block.type === 'a2ui');
  // Persistent model forms remain usable, but a previous Turn's card selection
  // must not hide a new business delivery when this Turn emits no UI.
  const displayModelState: UiState = currentTurnHasUi ? modelState : new Map(Array.from(modelState,
    ([id, surface]) => {
      const components = new Map(surface.components);
      let changed = false;
      for (const component of components.values()) {
        if (component.component === 'ProductCards' && component.itemIds.length > 0) {
          components.set(component.id, { ...component, itemIds: [] });
          changed = true;
        }
      }
      return [id, changed ? { ...surface, components } : surface] as const;
    }));
  const productIds = Array.from(new Set(display.products.map(product => product.itemId)));
  const knownIds = new Set(productIds);
  const modelShowsProducts = visibleUiProductIds(displayModelState).some(id => knownIds.has(id));
  const components: UiComponent[] = [];
  const children: string[] = [];
  const shownIds = new Set<string>();

  const add = (component: UiComponent) => {
    if (children.length >= 32) return;
    components.push(component);
    children.push(component.id);
  };
  const addCards = (ids: string[], layout: 'grid' | 'list') => {
    const accepted = Array.from(new Set(ids)).filter(id => knownIds.has(id) && !shownIds.has(id));
    for (let offset = 0; offset < accepted.length && children.length < 32; offset += 20) {
      const itemIds = accepted.slice(offset, offset + 20);
      add({ id: `products-${components.length}`, component: 'ProductCards', itemIds, layout });
      itemIds.forEach(id => shownIds.add(id));
    }
  };

  // Old public answer blocks are adapted, rather than rendered by a second UI path.
  for (const block of (display.answerBlocks || []).slice(0, 12)) {
    if (block.type === 'followup_question' || block.type === 'comparison_table' && block.content) {
      if (block.content?.trim()) add({ id: `content-${components.length}`, component: 'Text',
        text: block.content.slice(0, 4000) });
    } else if (!modelShowsProducts && (block.type === 'product_cards' || block.type === 'comparison_table')) {
      if (block.card_set_id && block.card_set_id !== display.cardSetId) continue;
      const ids = block.item_ids ?? (block.type === 'product_cards' ? productIds : []);
      addCards(ids, block.type === 'comparison_table' || block.layout === 'grid' ? 'grid' : 'list');
    }
  }

  // No UI, a form-only UI, unknown/stale product IDs and legacy history all get a
  // deterministic A2UI product display without relying on another model invocation.
  if (!modelShowsProducts && shownIds.size === 0) addCards(productIds, 'list');
  if (productIds.length === 0) add({ id: `empty-${components.length}`, component: 'Text',
    text: '暂无对话推荐商品，请在左侧发送您的意向诉求。' });
  if (children.length === 0) return displayModelState;

  let surfaceId = 'rs-business-display';
  for (let suffix = 1; displayModelState.has(surfaceId); suffix += 1) surfaceId = `rs-business-display-${suffix}`;
  const generated = applyA2uiMessages(new Map(), [
    { version: 'v0.9', createSurface: { surfaceId, catalogId: SHOPPING_CATALOG_ID } },
    { version: 'v0.9', updateComponents: { surfaceId, components: [
      { id: 'root', component: 'Column', children }, ...components,
    ] } },
  ]);
  return new Map([...displayModelState, ...generated]);
}
