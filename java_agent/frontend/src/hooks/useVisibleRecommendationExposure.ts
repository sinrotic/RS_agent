import { RefObject, useEffect } from 'react';
import { recordExposure } from '../api/interactionClient';
import { AuthSessionChangedError, captureAuthSession, isCurrentAuthSession } from '../api/shared';
import { RecommendExposureFeedbackRequest } from '../types/interaction';

const MIN_VISIBLE_RATIO = 0.5;
const MIN_VISIBLE_MS = 1000;
const MAX_ATTEMPTS = 3;

interface ExposureState {
  payload: RecommendExposureFeedbackRequest;
  attempts: number;
  inFlight: boolean;
  confirmed: boolean;
  blocked: boolean;
  retryTimer?: number;
}

export function useVisibleRecommendationExposure(
  rootRef: RefObject<HTMLElement>,
  requestId: string,
  sessionId: string,
  refreshKey: unknown,
) {
  useEffect(() => {
    const root = rootRef.current;
    if (!root || !requestId || !sessionId || typeof IntersectionObserver === 'undefined') return;

    const session = captureAuthSession();
    let disposed = false;
    const current = () => !disposed && isCurrentAuthSession(session);
    const timers = new Map<Element, number>();
    const states = new Map<string, ExposureState>();
    const elements = Array.from(root.querySelectorAll<HTMLElement>('[data-recommend-item-id]'));

    const send = async (itemId: string, state: ExposureState) => {
      if (!current() || state.inFlight || state.confirmed || state.blocked) return;
      state.inFlight = true;
      state.attempts += 1;
      try {
        const ack = await recordExposure(state.payload);
        if (!current()) return;
        if (!ack.accepted) { state.blocked = true; return; }
        state.confirmed = true;
        elements.filter(element => element.dataset.recommendItemId === itemId)
          .forEach(element => observer.unobserve(element));
      } catch (error) {
        if (!current() || error instanceof AuthSessionChangedError) return;
        const status = (error as { status?: number } | null)?.status;
        if (status !== undefined && status < 500 && status !== 408 && status !== 429) {
          state.blocked = true;
          return;
        }
        if (state.attempts < MAX_ATTEMPTS) {
          state.retryTimer = window.setTimeout(() => {
            state.retryTimer = undefined;
            void send(itemId, state);
          }, 1000 * 2 ** (state.attempts - 1));
        }
      } finally {
        state.inFlight = false;
      }
    };

    const observer = new IntersectionObserver((entries) => {
      if (!current()) return;
      for (const entry of entries) {
        const element = entry.target as HTMLElement;
        const itemId = element.dataset.recommendItemId;
        if (!itemId) continue;
        const previous = states.get(itemId);
        if (previous?.confirmed || previous?.blocked || previous?.inFlight || previous?.retryTimer !== undefined) continue;

        if (entry.isIntersecting && entry.intersectionRatio >= MIN_VISIBLE_RATIO) {
          if (timers.has(element)) continue;
          const startedAt = Date.now();
          const timer = window.setTimeout(() => {
            timers.delete(element);
            if (!current()) return;
            let state = states.get(itemId);
            if (state?.confirmed || state?.blocked || state?.inFlight || state?.retryTimer !== undefined) return;
            if (!state) {
              state = {
                attempts: 0, inFlight: false, confirmed: false, blocked: false,
                payload: {
                  request_id: requestId,
                  session_id: sessionId,
                  items: [{
                    item_id: itemId,
                    position: Number(element.dataset.recommendPosition || 0),
                    visible_ratio: entry.intersectionRatio,
                    visible_duration_ms: Date.now() - startedAt,
                  }],
                  exposed_at: Date.now(),
                },
              };
              states.set(itemId, state);
            }
            // 自动尝试耗尽后，重新进入视口可再次补报原始事实。
            state.attempts = 0;
            void send(itemId, state);
          }, MIN_VISIBLE_MS);
          timers.set(element, timer);
        } else {
          const timer = timers.get(element);
          if (timer !== undefined) window.clearTimeout(timer);
          timers.delete(element);
        }
      }
    }, { threshold: [MIN_VISIBLE_RATIO] });

    elements.forEach(element => observer.observe(element));
    return () => {
      disposed = true;
      timers.forEach(timer => window.clearTimeout(timer));
      states.forEach(state => {
        if (state.retryTimer !== undefined) window.clearTimeout(state.retryTimer);
      });
      observer.disconnect();
    };
  }, [rootRef, requestId, sessionId, refreshKey]);
}
