# ADR-0016: Recommendation Feedback Contract and Idempotency

- Status: Accepted
- Date: 2026-08-09

## Context

The Java recommendation service receives feedback from the product surface. Exposure, positive/negative preference, and explanation requests must not be conflated. Retries from browsers or gateways must also avoid counting the same event more than once.

## Decision

- `POST /api/recommend/feedback/exposure` accepts a request/session pair and a distinct non-empty `item_ids` list.
- `POST /api/recommend/feedback/event` accepts a request/session/item tuple and only the event types `click`, `like`, `dislike`, and `why`.
- `why` is an explanation request. The recommendation feedback service acknowledges it but does not mutate preference state or invoke reranking.
- A non-blank `request_id` is the idempotency key within the feedback kind and session. A retry returns `duplicate=true` and `accepted_count=0`.
- The acknowledgement keeps the original four fields and adds `duplicate` as an additive wire field.

The current implementation is an in-memory sink. A durable event consumer may replace it later while preserving this HTTP contract and idempotency behavior.

## Consequences

Clients can retry safely and distinguish an accepted event from a duplicate. Invalid event types and incomplete tuples are rejected without changing recommendation state. Persistence and cross-instance idempotency remain follow-up deployment work.
