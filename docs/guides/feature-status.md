# Feature Status

This page is the high-level feature readiness snapshot for Spindrel.

It is meant to answer questions like:

- What are the core product features?
- Which ones are solid today?
- Which ones are still rough, partial, or advanced-user territory?
- Which ones are tested heavily in real use versus only "seem to work"?

**Snapshot date:** 2026-04-21

## Status meanings

| Status | Meaning |
|---|---|
| `working` | Core flow is in real use and expected to hold up |
| `working (beta)` | Usable now, but still fresh or carrying notable caveats |
| `partial` | Important value is there, but the surface is incomplete or still uneven |
| `advanced` | Works, but expects more operator competence or setup effort |
| `experimental` | Real code exists, but not yet a feature to broadly promise |
| `deprecated` | Kept for compatibility or history, but no longer the recommended path |

## Confidence meanings

| Confidence | Meaning |
|---|---|
| `high` | Used regularly in real life; confidence comes from repeated use, not just tests |
| `medium` | Working in practice, but with meaningful caveats, limited soak time, or open uncertainty |
| `low` | Present and promising, but not exercised enough to trust broadly yet |

## Core agent experience

| Feature | Status | Confidence | What it means today |
|---|---|---|---|
| Multi-bot server | `working` | `high` | You can run multiple bots with different models, system prompts, tool policies, and capabilities. |
| Channels by topic/project | `working` | `high` | Each topic lives in its own persistent channel with its own bot binding, files, state, and history. |
| Multi-user support | `working (beta)` | `medium` | Multi-user support exists and is suitable for close friends/family style use, but this is not pitched as full multi-tenant SaaS isolation. |
| Auto-discovery of tools/skills/capabilities | `working` | `medium` | Core product bet and actively working, but still likely to benefit from model/retrieval tuning. |
| Capability gating / approval-aware discovery | `working` | `medium` | Tool/capability discovery respects availability and approval constraints instead of blindly exposing everything. |
| Tool approval flow | `working` | `medium` | Approval queues, inline approval states, and integration-aware approval handling are real parts of the product, even if some policy UX is still rough. |
| Parallel tool execution / sub-agents | `working` | `medium` | Parallel sub-agent execution exists and the sub-agent system is a completed track. |
| LLM fallbacks + retries | `working` | `high` | Retry, cooldown skip, fallback model routing, and rate-limit waits are part of the normal stack and are believed to be working well. |
| Temporal context awareness | `working` | `medium` | The system intentionally feeds date/time context into reasoning so agents can anchor work to when things happened, not just what happened. |
| Prompt caching respect | `working` | `medium` | The system is designed to preserve provider-side prompt caching wins rather than casually defeating them. |

## Skills, learning, and discovery

| Feature | Status | Confidence | What it means today |
|---|---|---|---|
| Skill discovery / retrieval | `working` | `medium` | Skills are ranked and retrieved at runtime as part of the same discovery story as tools/capabilities. |
| Agent self-authored skills | `working` | `medium` | Bots can create skills for themselves via `manage_bot_skill`. |
| Automatic dreaming / skill review | `working (beta)` | `low` | Maintenance + Skill Review jobs are real and seem to be working, but there has not been enough evaluation time or long-run evidence yet to call them well-proven. |
| Learning from corrections / repeated lookup / reflection | `working` | `medium` | The learning nudges are real and wired into the self-improving-agent loop. |
| Skill quality analytics / learning center | `working (beta)` | `medium` | There is visibility into skills and surfacing analytics, though parts of the UI are still being polished. |

## Memory, files, and history

| Feature | Status | Confidence | What it means today |
|---|---|---|---|
| Markdown memory on disk | `working` | `high` | Memory lives as files (`MEMORY.md`, logs, reference docs), not as an opaque vector-only store. |
| Channel knowledge base | `working` | `high` | Every channel gets a knowledge-base convention with automatic indexing/retrieval. |
| Workspace/file search mechanisms | `working` | `high` | The system uses multiple retrieval/search paths: workspace retrieval, channel archive search, bot knowledge search, and hybrid retrieval/reranking. |
| Archived conversation history with sectioned index | `working` | `high` | Conversation history is archived into numbered/topic-tagged sections and can be searched/read back with `read_conversation_history`. |
| Raw-message grep / tool-output recall from history | `working` | `high` | History tooling supports section reads, topic search, raw-message grep across history, and retrieval of summarized tool outputs by tool-call id. |
| Scratch / side-thread sessions | `working` | `medium` | Scratch sessions and other sub-sessions are first-class conversation surfaces now, including current-session pointers and archived history. |
| Chat state rehydration | `working` | `medium` | Reloads, reconnects, approvals, and active turns survive much better than the earlier streaming-only model. |

## Automation and orchestration

| Feature | Status | Confidence | What it means today |
|---|---|---|---|
| Scheduled tasks | `working` | `high` | One-off and recurring tasks are established product features. |
| Pipelines | `working` | `medium` | Pipelines work, but the UI still feels clunky and the surface has not been exercised as heavily as simpler task scheduling. |
| Pipeline sub-sessions | `working` | `medium` | Pipeline runs render as chat-native transcripts instead of invisible background jobs. |
| Heartbeats | `working` | `high` | Scheduled autonomous check-ins are a real, supported mechanism. |
| Event-triggered automation | `working (beta)` | `low` | Any event an integration brings in can be used to fire a task automatically, but this surface has not been tested deeply enough yet to claim broad reliability. |
| Push notifications | `working` | `medium` | Bots can intentionally send browser push notifications, and push delivery is part of the product rather than an external bolt-on. |
| Friendly setup/orchestration wizard | `working (beta)` | `medium` | Setup is straightforward and the orchestrator helps guide onboarding, but the overall polish is still evolving. |

## Models, providers, and cost controls

| Feature | Status | Confidence | What it means today |
|---|---|---|---|
| Multiple provider support | `working` | `high` | OpenAI, Anthropic, Ollama, LiteLLM, OpenAI-compatible, Anthropic-compatible, and ChatGPT Subscription are all in the typed provider system. |
| Ollama / local model path | `working` | `high` | Local-model support is a first-class use case, not an afterthought. |
| Usage tracking | `working` | `medium` | Token tracking appears solid; cost tracking is best-effort and may not perfectly match provider-side billing in every case. |
| Usage caps / budgets | `working (beta)` | `low` | Budget limits exist, but current confidence is lower because this surface has not been tested heavily in recent use. |
| Rate limiting / retry handling | `working` | `high` | Rate-limit backoff and retry behavior are part of the core request pipeline and are believed to be working well. |
| Provider-dialect prompt tuning | `working (beta)` | `low` | Prompt-style adaptation by provider/model exists, but is still early and explicitly treated as something to validate with experiments. |

### Operator-tested provider/model snapshot

This is not a theoretical compatibility list. It is the set of provider/model paths that have actually been used enough to say something concrete.

| Model / family | Provider path | Confidence | Notes |
|---|---|---|---|
| `minimax-m2.7` | `anthropic-compatible` | `high` | Extensively tested and known to work well. |
| Claude Haiku 4.5 | `litellm` | `high` | Used through the LiteLLM provider path. |
| Claude Sonnet 4.6 | `litellm` | `high` | Used through the LiteLLM provider path. |
| Gemini 2.5 family | `litellm` | `high` | Extensively used through the LiteLLM provider path. |
| GPT-5.4 | `litellm` | `high` | Tested and working through LiteLLM. |
| GPT-5.4 | `openai-subscription` | `high` | Tested and working through the ChatGPT-subscription provider path. |
| `gemini-2.5-flash-image` | `litellm` | `high` | Tested image generation path. |
| `gpt-image-1-mini` | `litellm` | `high` | Tested image generation path. |
| `gemma4:e4b` | `ollama` | `medium` | Local model path works, but not tested heavily. |
| `gemma4:e2b` | `ollama` | `medium` | Local model path works, but not tested heavily. |
| `gemma4:31b` | `ollama` | `medium` | Local model path works, but not tested heavily. |
| `qwen2.5-coder:7b` | `ollama` | `medium` | Local model path works, but not tested heavily. |

### Tool calls, vision, and image generation

| Capability | Status | Confidence | Notes |
|---|---|---|---|
| Tool calls on supported models | `working` | `high` | Working on the tested model/provider paths above where the model itself supports tool use. |
| Vision on supported models | `working` | `high` | Working on the tested model/provider paths above where the model itself supports vision. |
| Image generation | `working` | `high` | Confirmed on `gemini-2.5-flash-image` and `gpt-image-1-mini`, both via LiteLLM. |
| Local-model general path | `working (beta)` | `medium` | Local models generally work, but confidence is lower because the soak time is much lighter than the hosted-model paths. |

### Embeddings

| Capability | Status | Confidence | Notes |
|---|---|---|---|
| Local embedding model path | `working` | `medium` | You can use a local embedding model path built into the Docker/self-hosted setup. |
| Provider-backed embedding model path | `working` | `medium` | You can also select embeddings from a configured provider instead of forcing a local-only path. |

## Widgets, dashboards, and UI

| Feature | Status | Confidence | What it means today |
|---|---|---|---|
| Rich widgeting system | `working (beta)` | `medium` | This is a major focus area and already very usable, but it is still new, still being tuned, and still likely to reveal more bugs under wider use. |
| HTML widgets authored by bots | `working (beta)` | `medium` | Bot-authored interactive HTML widgets are real and useful, with bot-scoped auth. |
| Widget templates / component widgets | `working` | `medium` | Declarative widget templates and state polling are a real platform surface. |
| Customizable widget dashboards | `working (beta)` | `medium` | Named dashboards, channel dashboards, panel mode, and chat-zone placement are workable today, but the surface is still fresh, not yet super robust, and needs tuning plus more bug-finding. |
| Chat panels / HUD / channel widget zones | `working (beta)` | `medium` | Left rail, center dashboard, right rail, and top-center chips are real, but layout polish is still ongoing. |
| Developer panel / widget authoring workbench | `working (beta)` | `medium` | `/widgets/dev` is useful and real, but still under active polish. |
| Quick navigation with Ctrl/Cmd-K | `working` | `high` | Command palette is a first-class navigation surface and is heavily used in practice. |
| Mobile-friendly UI | `working (beta)` | `high` | The app is meaningfully mobile-capable and used regularly on mobile, though some editing surfaces remain desktop-only. |
| PWA-ready | `working` | `high` | PWA installability and push are shipped. |
| Web voice controls (chat mic + settings screen) | `experimental` | `low` | The microphone button and voice settings exist in the UI, but they are currently untested and should not be presented as a trusted product surface. |

## Tools, extensibility, and integrations

| Feature | Status | Confidence | What it means today |
|---|---|---|---|
| Build your own tools | `working` | `high` | Local tool authoring is straightforward and documented. |
| Build your own integrations | `working (beta)` | `medium` | The integration framework is real and capable, though “easy” still depends on technical comfort. |
| Programmatic tool orchestration (`run_script`) | `working (beta)` | `medium` | Bots can script many tool calls in one turn instead of forcing everything through long chat loops, but this is still a power-user surface. |
| Remote client / voice assistant path | `partial` | `low` | The separate client still exists, but it has not been exercised recently enough to promote as a current flagship surface. |
| Raw shell / exec command path | `working` | `high` | Host-side subprocess execution is part of the current product. |
| Docker sidecars / integration processes | `working` | `medium` | Docker deployment and sidecar-style service patterns are part of the system design. |
| Channel integration bindings / outbound delivery | `working` | `medium` | Channels can bind integrations and deliver events/results outward, but the depth and polish still vary by integration. |
| Webhooks | `working (beta)` | `low` | Outgoing lifecycle webhooks are supported and documented, but current confidence is lower because this surface has not been exercised much recently. |
| API keys + documented API | `working` | `high` | Scoped API keys and documented HTTP APIs are established features and are used constantly by the web UI and bot integrations. |
| Endpoint catalog / API discoverability | `working` | `medium` | The server builds an endpoint catalog from the actual app routes, which is useful and real even if it is not a flashy headline feature. |
| Tool policies | `partial` | `medium` | Tool policies work, but the current experience is not yet well-optimized enough to call polished. |

## Security, operations, and admin

| Feature | Status | Confidence | What it means today |
|---|---|---|---|
| Secret key storage | `working` | `medium` | Secret paste blocking/redirection into secure storage is confirmed working; less recent confidence on every downstream retrieval path. |
| Security posture / good practices | `working (beta)` | `low` | Reasonable best-practice hardening for LAN/self-hosted use, but not tested enough to present as broadly battle-tested or ready for hostile/public multi-user exposure. |
| Backup script included | `working` | `high` | Backup/restore tooling is documented and backup is known to work on demand in real use. |
| Easy command-line setup | `working` | `high` | `setup.sh` + Docker-based bootstrap are real strengths. |
| Docker-first hosting story | `working` | `high` | Running in Docker is the normal path. |

## Explicitly deprecated

| Feature | Status | Confidence | What it means today |
|---|---|---|---|
| Workflows | `deprecated` | `high` | Superseded by task pipelines. Retained only for compatibility/history. |

## Notes

- This page is intentionally high-level. It is the product-feature companion to [Integration Status](integration-status.md).
- Confidence here is based primarily on real operator use, not just whether code and tests exist.
- If a feature sits between two labels, it should usually get the less flattering one.
- Some rows bundle multiple implementation details under one user-visible feature because that is how people actually evaluate the product.

## See also

- [Integration Status](integration-status.md)
- [How Spindrel Works](how-spindrel-works.md)
- [Setup Guide](../setup.md)
- [Developer API](api.md)
