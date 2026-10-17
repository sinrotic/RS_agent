export const SHOPPING_CATALOG_ID = 'urn:rs-agent:a2ui:shopping:v1';
export type UiValue = string | { path: string };
export type UiComponent =
  | { id: string; component: 'Text'; text: UiValue }
  | { id: string; component: 'Column' | 'Row'; children: string[] }
  | { id: string; component: 'Card'; child: string }
  | { id: string; component: 'ProductCards'; itemIds: string[]; layout?: 'grid' | 'list' }
  | { id: string; component: 'TextField'; label: string; value: { path: string }; textFieldType?: 'shortText' | 'number' }
  | { id: string; component: 'Button'; child: string; action: { event: { name: 'submit_query'; context: { query: UiValue } } } };
export type A2uiMessage = { version: 'v0.9' } & (
  | { createSurface: { surfaceId: string; catalogId: string } }
  | { updateComponents: { surfaceId: string; components: UiComponent[] } }
  | { updateDataModel: { surfaceId: string; path?: string; value?: unknown } }
  | { deleteSurface: { surfaceId: string } }
);
export interface UiSurface {
  surfaceId: string;
  components: Map<string, UiComponent>;
  data: unknown;
}
export type UiState = Map<string, UiSurface>;
const UNSAFE_KEYS = new Set(['__proto__', 'prototype', 'constructor']);
const INTERNAL_DATA_KEYS = new Set(['trace', 'diagnostics', 'raw_path', 'ranking_evidence',
  'retrieval_evidence', 'tool_calls', 'tool_results', 'system_prompt', 'available_tools']);
const COMPONENT_NAMES = new Set(['Text', 'Column', 'Row', 'Card', 'ProductCards', 'TextField', 'Button']);

function pointerParts(path: string): string[] {
  if (path === '' || path === '/') return [];
  if (!/^\/([^~/]|~[01]|\/)*$/.test(path) || path.length > 256) throw new Error('无效的界面数据路径');
  const parts = path.slice(1).split('/').map(part => part.replace(/~1/g, '/').replace(/~0/g, '~'));
  if (parts.some(part => UNSAFE_KEYS.has(part))) throw new Error('无效的界面数据路径');
  return parts;
}

function validateJson(value: unknown, depth = 0): void {
  if (depth > 8) throw new Error('界面数据层级过深');
  if (value === null || typeof value === 'boolean' || typeof value === 'string' && value.length <= 4000
    || typeof value === 'number' && Number.isFinite(value)) return;
  if (Array.isArray(value) && value.length <= 64) {
    value.forEach(item => validateJson(item, depth + 1));
    return;
  }
  if (typeof value === 'object' && value !== null && Object.keys(value).length <= 64) {
    Object.entries(value).forEach(([key, item]) => {
      if (UNSAFE_KEYS.has(key) || INTERNAL_DATA_KEYS.has(key) || key.length > 128) throw new Error('无效的界面数据字段');
      validateJson(item, depth + 1);
    });
    return;
  }
  throw new Error('无效的界面数据');
}

export function updateUiData(data: unknown, path: string, value: unknown, remove = false): unknown {
  const parts = pointerParts(path);
  if (!remove) validateJson(value);
  if (parts.length === 0) return remove ? {} : JSON.parse(JSON.stringify(value));
  const result = data && typeof data === 'object' ? JSON.parse(JSON.stringify(data)) : {};
  let target = result;
  for (const part of parts.slice(0, -1)) {
    if (target[part] == null) {
      if (remove) return result;
      target[part] = {};
    }
    if (typeof target[part] !== 'object') throw new Error('界面数据路径无法写入');
    target = target[part];
  }
  const key = parts[parts.length - 1];
  if (Array.isArray(target)) {
    if (!/^(0|[1-9]\d*)$/.test(key) || Number(key) >= target.length) throw new Error('无效的界面数组索引');
    if (remove) target.splice(Number(key), 1);
    else target[Number(key)] = value;
  } else if (remove) delete target[key];
  else target[key] = value;
  validateJson(result);
  return result;
}

export function resolveUiValue(value: UiValue, data: unknown): string {
  if (typeof value === 'string') return value;
  let resolved = data;
  for (const part of pointerParts(value.path)) {
    resolved = resolved && typeof resolved === 'object' && Object.prototype.hasOwnProperty.call(resolved, part)
      ? (resolved as Record<string, unknown>)[part] : undefined;
  }
  if (resolved == null) return '';
  return typeof resolved === 'object' ? JSON.stringify(resolved) : String(resolved);
}

export function uiChildren(component: UiComponent): string[] {
  if ('children' in component) return component.children;
  if ('child' in component) return [component.child];
  return [];
}

export function visibleUiProductIds(state: UiState): string[] {
  const ids = new Set<string>();
  for (const surface of state.values()) {
    const visited = new Set<string>();
    const visit = (id: string) => {
      if (visited.has(id)) return;
      visited.add(id);
      const component = surface.components.get(id);
      if (!component) return;
      if (component.component === 'ProductCards') component.itemIds.forEach(itemId => ids.add(itemId));
      uiChildren(component).forEach(visit);
    };
    visit('root');
  }
  return Array.from(ids);
}

function validateGraph(components: Map<string, UiComponent>): void {
  const visited = new Set<string>();
  const active = new Set<string>();
  function visit(id: string, depth: number) {
    if (active.has(id) || depth > 32) throw new Error('界面组件存在循环或层级过深');
    if (visited.has(id)) return;
    const component = components.get(id);
    if (!component) return; // References may arrive in subsequent stream messages.
    active.add(id);
    uiChildren(component).forEach(child => visit(child, depth + 1));
    active.delete(id);
    visited.add(id);
  }
  components.forEach(component => visit(component.id, 0));
}

function validateComponent(component: UiComponent): void {
  const definitions: Record<string, { required: string[]; optional?: string[] }> = {
    Text: { required: ['text'] }, Column: { required: ['children'] }, Row: { required: ['children'] },
    Card: { required: ['child'] }, ProductCards: { required: ['itemIds'], optional: ['layout'] },
    TextField: { required: ['label', 'value'], optional: ['textFieldType'] }, Button: { required: ['child', 'action'] },
  };
  const definition = definitions[component.component];
  if (!definition) throw new Error('不支持的界面组件');
  const fields = ['id', 'component', ...definition.required, ...definition.optional || []];
  if (Object.keys(component).some(key => !fields.includes(key))
    || definition.required.some(key => !Object.prototype.hasOwnProperty.call(component, key))) {
    throw new Error('无效的界面组件参数');
  }
  const identifier = (value: unknown) => {
    if (typeof value !== 'string' || !/^[A-Za-z0-9_:.-]{1,128}$/.test(value)) throw new Error('无效的组件标识');
  };
  const binding = (value: UiValue) => {
    if (typeof value === 'string' && value.length <= 4000) return;
    if (typeof value !== 'object' || !value || typeof value.path !== 'string' || Object.keys(value).length !== 1) {
      throw new Error('无效的界面绑定');
    }
    pointerParts(value.path);
  };
  identifier(component.id);
  if ('children' in component) {
    if (!Array.isArray(component.children) || component.children.length > 32) throw new Error('无效的子组件');
    component.children.forEach(identifier);
  }
  if ('child' in component) identifier(component.child);
  if (component.component === 'Text') binding(component.text);
  if (component.component === 'TextField') {
    if (typeof component.label !== 'string' || component.label.length > 4000 || typeof component.value !== 'object'
      || typeof component.value?.path !== 'string' || component.textFieldType !== undefined
      && !['shortText', 'number'].includes(component.textFieldType)) throw new Error('无效的输入组件');
    binding(component.value);
  }
  if (component.component === 'ProductCards') {
    if (!Array.isArray(component.itemIds) || component.itemIds.length > 20 || component.layout !== undefined
      && !['grid', 'list'].includes(component.layout)) throw new Error('无效的商品组件');
    component.itemIds.forEach(identifier);
  }
  if (component.component === 'Button') {
    if (component.action?.event?.name !== 'submit_query') throw new Error('不支持的界面操作');
    binding(component.action.event.context?.query);
  }
}

/** Applies complete messages atomically. Transport chunks must never be passed as partial JSON. */
export function applyA2uiMessages(state: UiState, messages: A2uiMessage[]): UiState {
  if (!Array.isArray(messages) || messages.length === 0 || messages.length > 32) throw new Error('界面消息数量超限');
  const next = new Map(state);
  for (const message of messages) {
    if (message.version !== 'v0.9') throw new Error('不支持的界面协议版本');
    const operations = ['createSurface', 'updateComponents', 'updateDataModel', 'deleteSurface']
      .filter(key => Object.prototype.hasOwnProperty.call(message, key));
    if (operations.length !== 1 || Object.keys(message).length !== 2) throw new Error('无效的界面消息');
    const operation = operations[0];
    const payload = (message as unknown as Record<string, { surfaceId: string }>)[operation];
    const id = payload.surfaceId;
    if (typeof id !== 'string' || !/^[A-Za-z0-9_:.-]{1,128}$/.test(id)) throw new Error('无效的界面标识');
    if ('createSurface' in message) {
      if (message.createSurface.catalogId !== SHOPPING_CATALOG_ID) throw new Error('不支持的组件目录');
      if (next.has(id)) throw new Error('界面标识已存在');
      if (next.size >= 8) throw new Error('界面数量超限');
      next.set(id, { surfaceId: id, components: new Map(), data: {} });
      continue;
    }
    if (!next.has(id)) throw new Error('界面尚未创建');
    if ('deleteSurface' in message) { next.delete(id); continue; }
    const surface = next.get(id)!;
    if ('updateComponents' in message) {
      const components = new Map(surface.components);
      const batch = message.updateComponents.components;
      if (!Array.isArray(batch) || batch.length > 64) throw new Error('界面组件数量超限');
      for (const component of batch) {
        if (!/^[A-Za-z0-9_:.-]{1,128}$/.test(component.id) || !COMPONENT_NAMES.has(component.component)) {
          throw new Error('不支持的界面组件');
        }
        validateComponent(component);
        components.set(component.id, component);
      }
      if (components.size > 64) throw new Error('界面组件数量超限');
      validateGraph(components);
      next.set(id, { ...surface, components });
    } else if ('updateDataModel' in message) {
      const update = message.updateDataModel;
      next.set(id, { ...surface, data: updateUiData(surface.data, update.path ?? '/', update.value,
        !Object.prototype.hasOwnProperty.call(update, 'value')) });
    }
  }
  return next;
}

export function uiStateContext(state: UiState): unknown[] {
  return Array.from(state.values(), surface => ({
    surfaceId: surface.surfaceId,
    catalogId: SHOPPING_CATALOG_ID,
    components: Array.from(surface.components.values()),
    data: surface.data,
  }));
}
