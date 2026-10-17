import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { clearTokens, saveAccountId, commerceStorageKey, subscribeAccount } from './shared';

function storage() {
  const values = new Map<string, string>();
  return { get length() { return values.size; }, key: (i: number) => [...values.keys()][i] ?? null,
    getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => { values.delete(key); } };
}
beforeEach(() => { vi.stubGlobal('sessionStorage', storage()); vi.stubGlobal('localStorage', storage()); clearTokens(); });
afterEach(() => { clearTokens(); vi.unstubAllGlobals(); });

it('账号变化通知交易组件重置内存，同账号刷新不重置', () => {
  const listener = vi.fn(); const unsubscribe = subscribeAccount(listener);
  try {
    saveAccountId('a'); saveAccountId('a'); expect(listener).toHaveBeenCalledTimes(1);
    saveAccountId('b'); expect(listener).toHaveBeenCalledTimes(2);
    clearTokens(); expect(listener).toHaveBeenCalledTimes(3);
    unsubscribe(); saveAccountId('c'); expect(listener).toHaveBeenCalledTimes(3);
  } finally { unsubscribe(); }
});

it('退出和账号切换阻止读取前一账号的待确认交易，同时保留无关存储', () => {
  saveAccountId('account-a');
  const checkout = commerceStorageKey('checkout', 'item')!;
  const seckill = commerceStorageKey('seckill', 'item')!;
  sessionStorage.setItem(checkout, 'original-order'); sessionStorage.setItem(seckill, 'original-seckill');
  sessionStorage.setItem('session-ui', 'keep');
  saveAccountId('account-a');
  expect(sessionStorage.getItem(checkout)).toBe('original-order');
  saveAccountId('account-b');
  expect(commerceStorageKey('checkout', 'item')).not.toBe(checkout);
  expect(sessionStorage.getItem(checkout)).toBeNull(); expect(sessionStorage.getItem(seckill)).toBeNull();
  sessionStorage.setItem(commerceStorageKey('checkout', 'item')!, 'b-order');
  clearTokens();
  expect(commerceStorageKey('checkout', 'item')).toBeNull();
  expect(sessionStorage.getItem('checkout-pending:account-b:item')).toBeNull();
  expect(sessionStorage.getItem('session-ui')).toBe('keep');
});

it('刷新同一账号保留原键，弃用旧无账号键，并避免账号和商品分隔符冲突', () => {
  sessionStorage.setItem('checkout-pending:item', 'unsafe-legacy');
  sessionStorage.setItem('seckill-pending:item', 'unsafe-legacy');
  saveAccountId('a:b');
  const key = commerceStorageKey('checkout', 'c');
  sessionStorage.setItem(key!, 'stable');
  saveAccountId('a:b');
  expect(sessionStorage.getItem(key!)).toBe('stable');
  expect(sessionStorage.getItem('checkout-pending:item')).toBeNull();
  expect(sessionStorage.getItem('seckill-pending:item')).toBeNull();
  saveAccountId('a');
  expect(commerceStorageKey('checkout', 'b:c')).not.toBe(key);
});
