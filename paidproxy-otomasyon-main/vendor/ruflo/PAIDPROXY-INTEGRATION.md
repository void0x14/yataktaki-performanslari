# PaidProxy Ruflo integration

This vendor tree is the upstream Ruflo orchestration runtime with the
standalone Security and Agent Federation packages removed. Swarm, agent,
memory, workflow, MCP, neural, and plugin sources remain available.

PaidProxy enters through `ruflo/bin/ruflo.js`. The Python adapter starts the
real Ruflo swarm and two registered roles, then sends model requests only
through `src/proxy_pipeline/agents/ai_havuz.py`:

- MiMo: `mimo-v2.5-pro` via the China Token Plan endpoint.
- Gemini Web2API: `gemini-3.5-flash-thinking-lite` via the local bridge.

Keys and endpoints are read from `~/.config/paidproxy/keys.txt`; no provider
key is read from environment variables.
