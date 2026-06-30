# Agent Session Storage Design

## Decision

Agent session storage is split by temperature and query pattern:

```text
MySQL
  session index and user-facing metadata

Redis
  hot AgentSessionState
  mark-after events
  active tool states
  large temporary tool results

ScyllaDB
  mark-before stable event log
  context snapshots
  cold reload source
```

The agent session is modeled as append-only events, not as one mutable row.

## Event Flow

During active conversation, the agent writes hot events to Redis. When context compaction is triggered, the system inserts a compaction mark. Events before the mark are stable and can be archived to ScyllaDB. The compaction also creates a context snapshot.

```text
evt_001 USER_MESSAGE
evt_002 TOOL_USE
evt_003 TOOL_RESULT
evt_004 ASSISTANT_MESSAGE
evt_005 COMPACTION_MARK
evt_006 USER_MESSAGE
```

After compaction:

```text
ScyllaDB:
  evt_001..evt_004
  CONTEXT_SNAPSHOT

Redis:
  latest CONTEXT_SNAPSHOT
  evt_006 and later hot events
```

## Current Java Interfaces

The first implementation is an in-memory adapter set inside `rs-service-agent`.

```text
AgentHotSessionStore
  Current Redis-shaped interface.

AgentColdSessionArchiveStore
  Current ScyllaDB-shaped interface.

AgentSessionCompactionService
  Archives mark-before events and writes snapshot.

AgentSessionColdLoadService
  Restores latest snapshot plus events after snapshot boundary into hot storage.
```

Current implementations:

```text
InMemoryAgentHotSessionStore
InMemoryAgentColdSessionArchiveStore
DefaultAgentSessionCompactionService
DefaultAgentSessionColdLoadService
InMemoryAgentToolResultStore
```

## Large Tool Result Access

Large tool results should not be copied into the model context. Store the result body itself as line text, and keep only metadata in the original tool result event.

The original `TOOL_RESULT` event should carry only:

```text
tool_call_id
status
summary
result_ref
truncated
total_lines
preview
```

The full result body is stored under `result_ref` as ordered result lines. The model can request a bounded line range with:

```text
read_tool_result_lines
```

Tool arguments:

```json
{
  "result_ref": "agent:result:sess_001:toolu_001",
  "offset": 0,
  "limit": 20
}
```

Tool response:

```json
{
  "status": "SUCCESS",
  "tool_type": "tool_result_lines",
  "result_ref": "agent:result:sess_001:toolu_001",
  "offset": 0,
  "limit": 20,
  "total_lines": 120,
  "has_more": true,
  "lines": []
}
```

The current implementations are:

```text
InMemoryAgentToolResultStore
RedisAgentToolResultStore
```

The default is in-memory. Enable Redis with:

```yaml
rs:
  agent:
    result-store:
      type: redis
      block-line-count: 50
      ttl: 1h
```

Both implementations store the original result lines in fixed-size line blocks. This keeps the public API line-oriented while reducing per-line storage overhead.

The Redis implementation uses this block-list shape:

```text
agent:result:{session_id}:{tool_call_id}:lines
  Redis List, where each element stores a fixed number of original result lines, such as 50 lines.

  To read offset+limit:
    1. compute first/last block index
    2. LRANGE only those blocks
    3. split the returned blocks into original lines
    4. return the requested line range

agent:result:{session_id}:{tool_call_id}:meta
  Redis Hash for summary, total_lines, block_line_count, created_at, ttl, source tool
```

## Replacement Path

The in-memory stores are intentionally thin. Replace them later with:

```text
RedisAgentHotSessionStore
RedisAgentToolResultStore
ScyllaAgentColdSessionArchiveStore
MysqlAgentSessionIndexStore
```

`AgentLoop` and agent profiles should depend on the interfaces, not on Redis or Scylla clients directly.

## Important Rule

ScyllaDB should receive append-only stable data. It should not be used for every hot context mutation.

Use this split:

```text
frequent mutation -> Redis
stable event range -> ScyllaDB
session list/search -> MySQL
```
