# LLM Providers

A **provider** is a configured endpoint that the agent loop can call for chat completions. Spindrel supports seven provider types, each backed by a typed driver that declares what it can do beyond basic chat (model listing, model pull/delete, live pricing, plan billing, etc.).

This guide covers the full catalog, the feature matrix, how to add a new provider, and the walkthroughs for the less-obvious flows (ChatGPT Subscription OAuth, Ollama, LiteLLM).

For `.env`-level bootstrapping and the setup wizard, see the [Setup Guide](../setup.md).

---

## Catalog

| Type | Auth | Local-only | Base URL | When to use |
|---|---|---|---|---|
| `openai` | API key | No | `https://api.openai.com` (default) | Direct OpenAI API |
| `openai-subscription` | ChatGPT OAuth device-code | No | Codex default | ChatGPT paid-subscription login, no API key, plan billing |
| `openai-compatible` | API key (often optional) | Your choice | Required | Any OpenAI-compatible endpoint (OpenRouter, vLLM, Gemini, self-hosted) |
| `anthropic` | API key | No | Anthropic default | Direct Anthropic API (native support, no proxy) |
| `anthropic-compatible` | API key | Your choice | Required | Anthropic-compatible proxies (Bedrock, custom gateways) |
| `ollama` | None | **Yes** | `http://localhost:11434` (default) | Local model runner |
| `litellm` | API key | No | Required | LiteLLM proxy (100+ providers via unified API) |

Drivers live in `app/services/provider_drivers/`. Each driver subclasses `ProviderDriver` and declares its `ProviderCapabilities`.

---

## Feature matrix

| Feature | `openai` | `openai-subscription` | `openai-compatible` | `anthropic` | `anthropic-compatible` | `ollama` | `litellm` |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| Chat completions | ✓ | ✓ (via `/responses` adapter) | ✓ | ✓ | ✓ | ✓ | ✓ |
| List models | ✓ | ✓ | ✓ | – | – | ✓ | ✓ |
| Pull model | – | – | – | – | – | ✓ | – |
| Delete model | – | – | – | – | – | ✓ | – |
| Model info | ✓ | – | – | – | – | ✓ | – |
| Running models | – | – | – | – | – | ✓ | – |
| Live pricing | ✓ | – | – | ✓ | – | – | ✓ |
| Requires API key | ✓ | – (OAuth) | user-configurable | ✓ | ✓ | – | ✓ |
| Requires base URL | – | – | ✓ | – | ✓ | ✓ | ✓ |
| Streaming | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Tool calls | ✓ | ✓ | ✓* | ✓ | ✓* | ✓* | ✓ |
| Plan billing | – | ✓ | – | – | – | – | – |

`*` = depends on the upstream model; basic chat works, but tool-call support varies (Ollama requires a tool-supporting model like `qwen2.5-coder`, etc.).

---

## Creating a provider

### From the Admin UI

**Admin → Providers → New provider**. Pick a type; the form adjusts to the driver's declared requirements (API key / base URL / OAuth button). On save, the server calls `driver.test_connection(...)` and shows the result. Models populate from `list_models()` into a table you can enable/disable per model.

### Managing models on a provider

The Models table on the provider edit page shows the **union** of the driver's live catalog (via `list_models()`) and any rows persisted in `provider_models` for this provider. That means a manually added row — e.g. a newer `gpt-5.5` you want to use before the driver fallback list catches up — shows up in bot dropdowns even if the driver itself doesn't list it yet.

Each row supports inline **edit / save / cancel**, toggling the per-model flags without deleting and recreating the row:

- `no_system_messages` — fold the system message into the first user message
- `supports_tools` — function-calling / tool use allowed
- `supports_vision` — image content parts allowed
- `supports_reasoning` — model takes an effort / thinking-budget knob (see [Reasoning / effort](#reasoning--effort))
- `prompt_style` — framework-prompt dialect (see [Prompt dialect](#prompt-dialect-prompt_style))

Any row mutation triggers a `load_providers()` reload so the in-memory capability caches refresh on the same request. No server restart needed.

### From first-boot seed

On first boot with an empty DB, the server looks for `provider-seed.yaml` (shipped by the `scripts/setup.py` wizard or hand-written). Example:

```yaml
provider:
  name: "OpenAI"
  type: "openai"
  api_key: "sk-..."
  default_model: "gpt-4o-mini"
```

The file is consumed once and then deleted — subsequent boots don't re-read it. Manage providers through the UI after that.

### Assigning to a bot

Set `model_provider_id` on the bot YAML or in the admin editor. Bots without an assignment fall through to the `.env` default (the typeless `LLM_BASE_URL` + `LLM_API_KEY` fallback, equivalent to a provider of type `openai-compatible`).

For cost tracking, budget limits, and spend forecasting, see the [Usage & Billing guide](usage-and-billing.md).

---

## ChatGPT Subscription (OAuth)

Use your existing ChatGPT paid-subscription login — no API key, no per-token billing. Requests are metered against your ChatGPT plan quota.

### Model allowlist

OAuth only authorizes a subset of OpenAI's public catalog. The live list is fetched from Codex's `/models` endpoint on boot and seeded into `provider_models`; a fallback list ships in the driver in case the endpoint is unreachable:

```
gpt-5, gpt-5-mini, gpt-5-codex, gpt-5.4, gpt-5.4-mini,
gpt-5.3-codex, gpt-5.3-codex-spark, gpt-5.2
```

The naming shifts across GPT-5 point releases; the driver re-syncs on each boot so stale entries don't linger.

### Connecting

1. **Admin → Providers → New provider**, pick type `openai-subscription`.
2. The edit page shows a **Connect ChatGPT** panel with a device-code flow.
3. Click **Start** — a short user code and a verification URL appear.
4. Open the URL, sign in with your ChatGPT account, paste the user code.
5. The panel polls until approval. On success it shows your email + plan.

Tokens persist encrypted on `ProviderConfig.config['oauth']`. Refreshes run automatically with a 10-minute leeway — long-running agents don't see auth blips.

### Billing

Creating an `openai-subscription` provider pre-fills `billing_type=plan`, `plan_cost=20`, `plan_period=monthly` so the plan-billing path reports $0 per call (the cost is your flat monthly subscription, not per-token). Override in the UI if your plan pricing differs. See [Usage & Billing](usage-and-billing.md).

### Responses API only

Tokens obtained through this path **only** work against Codex's `/responses` endpoint — *not* `/v1/chat/completions`. The `OpenAIResponsesAdapter` translates `chat.completions` ↔ `/responses` transparently, so the rest of the agent loop doesn't know the difference.

### Caveats

- **User-authenticated path.** OpenAI's ChatGPT subscription terms apply to requests through this flow. The Connect panel surfaces this in an amber disclaimer.
- **Public Codex CLI client_id.** There's no third-party OAuth app program — every self-hosted install uses the same client_id (`app_EMoamEEZ73f0CkXaXp7hrann`), stored as a module constant in the driver for easy audit if OpenAI rotates it.
- **Disconnect leaves the provider row.** Clicking Disconnect clears the OAuth block — the provider row stays, so reconnect doesn't require recreating it.

---

## Ollama

Local models, no API key, full driver support (list / pull / delete / info / running):

```
type: ollama
base_url: http://localhost:11434    # default
```

From Docker, point at the host via `http://host.docker.internal:11434` (or the Linux-compose equivalent) — see [Setup Guide → Web Search → Docker networking](../setup.md#docker-compose-port-binding) for the gory details.

Ollama capabilities in the Admin UI:

- **Pull model** — streams progress inline while Ollama downloads a new GGUF.
- **Delete model** — removes a local model and frees disk.
- **Get model info** — context length, parameter count, quantization.
- **Running models** — which models are loaded in Ollama's RAM right now.

For tool-call support, pick a model that explicitly supports function calling (`qwen2.5-coder`, `llama3-groq-tool-use`, etc.). Plain chat-only models will silently degrade tool calls to freeform text.

---

## LiteLLM proxy

The broadest compatibility — LiteLLM exposes 100+ upstream providers through a single OpenAI-compatible endpoint.

```
type: litellm
base_url: http://litellm:4000
api_key: <your proxy key>
```

LiteLLM's own `/model/info` endpoint supplies a live model catalog, and the driver's `fetch_pricing()` pulls per-model $/token for the Usage dashboard. If you want one place to configure Anthropic + OpenAI + Gemini + local Ollama + Together + Groq all at once, this is the shape.

Use `openai-compatible` if you have a simpler OpenAI-shaped endpoint that doesn't expose LiteLLM's management API.

---

## `openai-compatible` — the escape hatch

Anything that speaks OpenAI's `/v1/chat/completions` works here: OpenRouter, vLLM, Gemini via its OpenAI-compatible shim, self-hosted Llama endpoints, etc.

| Provider | `base_url` | Notes |
|---|---|---|
| OpenRouter | `https://openrouter.ai/api/v1` | Multi-provider (Anthropic, Google, Meta, …) — often the simplest Claude path |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | OpenAI-compatible shim |
| vLLM / TGI self-hosted | `http://your-host:port/v1` | Open-weights local serving |
| Ollama (as `openai-compatible`) | `http://localhost:11434/v1` | Works, but `ollama` type unlocks pull/delete/info |

API key is user-configurable — some endpoints require one, some are open.

---

## Anthropic (`anthropic` and `anthropic-compatible`)

Direct Anthropic API runs through the `AnthropicOpenAIAdapter` (translates `chat.completions` ↔ Anthropic's native `messages` API). No proxy required; just an API key.

`anthropic-compatible` adds a configurable `base_url` for Bedrock or a custom gateway.

If you only need occasional Claude access, `openai-compatible` with `base_url=https://openrouter.ai/api/v1` is often simpler than setting up a second provider.

---

## Reasoning / effort

Spindrel exposes a single user-facing reasoning knob: **`effort`**, an enum `off | low | medium | high`. It lives in three places with a strict resolution order:

| Layer | Storage | Set by |
|---|---|---|
| Turn override | `current_effort_override` ContextVar | Inherited from channel by `run_stream`; propagated to delegation/pipeline children |
| Channel override | `channel.config.effort_override` (JSONB) | `/effort <level>` slash command |
| Bot default | `bots.model_params.effort` (JSONB) | Bot editor UI |

Resolution order: **ContextVar > channel.config > bot.model_params**. `run_stream` reads `channel.config.effort_override` once at entry and sets the ContextVar so nested runs inherit via `snapshot_agent_context` / `restore_agent_context`.

The single source of truth for the wire shape is `translate_effort(model, effort, *, explicit_budget=None)` in `app/agent/model_params.py`. Call sites must not re-branch on provider family — if you're tempted to write `if family == "anthropic"` to build a request payload, add the case to `translate_effort` instead.

| Family | Wire shape |
|---|---|
| `anthropic` | `thinking_budget=<int>` kwarg (consumed by `AnthropicOpenAIAdapter`) |
| `gemini` / `google` | `extra_body.thinking_config.{thinking_budget, include_thoughts}` |
| `openai` / `xai` / `deepseek` chat.completions | `reasoning_effort="<level>"` kwarg |
| `openai` Responses API (Codex / gpt-5-*) | `body.reasoning.effort = "<level>"` (adapter translates the flat kwarg) |
| `mistral` / `groq` / `ollama` | Empty dict (reasoning not supported) |

Enum → default budget mapping for budget-shaped families: `off=0`, `low=2048`, `medium=8192`, `high=16384` tokens.

### Advanced: explicit `thinking_budget`

Power users can set a numeric `thinking_budget` under the Advanced disclosure in the bot editor. For budget-shaped families (Anthropic, Gemini) this wins over the enum-derived default — useful when you want a precise budget instead of the 2048 / 8192 / 16384 steps. For effort-shaped families (OpenAI / xAI / DeepSeek) the advanced field is ignored; the enum drives `reasoning_effort` directly.

### `/effort` slash command

```
/effort off       # clear the override; fall back to bot default
/effort low
/effort medium
/effort high
```

The command persists `channel.config.effort_override` (or removes the key on `off`). The channel header shows an `effort: <level>` pill while the override is active. The slash-command registry is backend-owned (`list_supported_slash_commands` in `app/services/slash_commands.py`); the frontend mirrors it at load. Each entry carries `accepts_args`, `arg_enum`, and `local_only` flags so both surfaces agree on the contract.

### Capability gating

`/effort <level>` (anything other than `off`) rejects with a 400 if the channel's primary bot runs a model that isn't marked as reasoning-capable. The bot editor greys out the Reasoning effort control under the same rule. Both checks consult the `supports_reasoning` column on `provider_models` — the single source of truth.

`filter_model_params` is the last-line defence: it strips `effort` / `reasoning_effort` / `thinking_budget` before the SDK call when the model isn't reasoning-capable. Callers never need to pre-check capability themselves.

Unknown models (no `provider_models` row) are treated as non-reasoning. If a legitimate reasoning model sneaks in without the flag, flip the checkbox in **Admin → Providers → [provider] → Models** and the cache picks up the change on next provider mutation (or bot/page reload). See [ProviderModel capability columns](#providermodel-capability-columns) below.

---

## ProviderModel capability columns

Per-model flags live on the `provider_models` table. Each row exposes the capability + cost metadata the admin UI edits:

| Column | Default | Purpose |
|---|:-:|---|
| `context_window` | `null` | Maximum input tokens (context size). Drives budget math, compaction thresholds. Replaces the ambiguous `max_tokens` for "how much input can I feed in." |
| `max_output_tokens` | `null` | Maximum output tokens the model will generate. Backfilled from `max_tokens` at migration 245; admin can split manually going forward. |
| `no_system_messages` | `false` | Fold `system` into the first user message (MiniMax-style APIs that reject `role: system`) |
| `supports_tools` | `true` | Whether function-calling / tool use is supported. Auto-learned on API rejection |
| `supports_vision` | `true` | Whether `image_url` content parts are accepted. Auto-learned on API rejection |
| `supports_reasoning` | `false` | Whether the model takes an effort / thinking-budget knob. Gates the `/effort` command and the bot editor control |
| `supports_prompt_caching` | `false` | Whether the model accepts `cache_control` breakpoints. Replaces the legacy `"claude" in model_id` string sniff in `app/agent/prompt_cache.py`. Backfilled true for Claude families, GPT-4o/5/Codex, Gemini 2.x. |
| `supports_structured_output` | `false` | Whether the model accepts `response_format={"type":"json_schema",...}`. Forward-looking gate — no consumer today, lets admin opt-in when a pipeline step needs it. |
| `input_cost_per_1m` | `null` | USD per 1M input tokens, e.g. `"$3.00"`. Used by `/admin/usage` cost math. |
| `output_cost_per_1m` | `null` | USD per 1M output tokens. |
| `cached_input_cost_per_1m` | `null` | USD per 1M **cached** input tokens, e.g. Anthropic's `"$0.30"` for Claude Sonnet. When set, the cost aggregator splits `(input - cached) * input_rate + cached * cached_rate` instead of applying a percent-discount heuristic. Stops `/admin/usage` from overstating Anthropic spend ~10× while prompt caching is active. |
| `prompt_style` | `'markdown'` | Framework-prompt dialect (`markdown` / `xml` / `structured`) — see [Prompt dialect](#prompt-dialect-prompt_style) |
| `extra_body` | `{}` | JSON merged into the outgoing request's `extra_body`. Primary use: Ollama's `options.num_ctx` (Ollama defaults to a **2048-token context** regardless of model file — set `{"options": {"num_ctx": 16384}}` to stop long prompts silently truncating). Also used for Mistral / Groq / Gemini-via-shim quirks. |

All are loaded into in-memory sets by `load_providers()` (`app/services/providers.py`). Prompt style, `extra_body`, and `cached_input_cost_per_1m` are cached by `(provider_id, model_id)` so duplicate model IDs can use different values on different providers. The cache auto-rebuilds whenever an admin adds, edits, or deletes a provider or model — no manual invalidation needed.

### Marking a new model as reasoning-capable

1. **Admin → Providers → [your provider] → Add model.**
2. In the row controls, tick the **Reasoning** checkbox.
3. Save. The `load_providers()` reload on the same request repopulates `_reasoning_capable_models`, the `/effort` validator and bot editor pick it up immediately.

Existing rows were backfilled by migration 242 for the known reasoning-capable families: Claude Opus / Sonnet / Haiku 4.5, gpt-5-*, o-series, codex-*, Gemini 2.5-*, DeepSeek Reasoner / R1, Grok 3. Anything else starts as `false`.

---

## Prompt dialect (`prompt_style`)

Framework prompts use a single `{% section "Title" %} ... {% endsection %}` marker. `app/services/prompt_dialect.py::render(canonical, style)` rewrites the markers based on the effective provider/model pair's `prompt_style` column on `provider_models`:

- `markdown` → `## Title\n...` (default — works everywhere OpenAI-shaped).
- `xml` → `<title>\n...\n</title>` (native Anthropic prefers XML framing).
- `structured` → currently aliased to markdown; reserved for a future JSON-sectioned variant.

Body content is preserved verbatim; only the envelope flips. Unknown styles fall through to markdown. Unmarked prompts pass through unchanged.

---

## Adapter architecture

Adapters exist to bridge an OpenAI-shaped call into a backend that isn't natively OpenAI-shaped. They expose the same chat-completion surface the rest of the codebase assumes (`.chat.completions.create(model=..., messages=..., tools=..., stream=...)`) and translate in both directions:

- **Outbound**: OpenAI-style messages + tools → provider-native request body.
- **Inbound**: provider-native stream events → OpenAI-style chunks (plus a `reasoning_content` channel for the UI's thinking panel).

Today two adapters exist: `AnthropicOpenAIAdapter` (`app/services/anthropic_adapter.py`) and `OpenAIResponsesAdapter` (`app/services/openai_responses_adapter.py`). Both re-implement tool-shape translation from scratch — the shared helpers will be extracted into `app/services/provider_translation.py` in Phase 3 of the Provider Refactor track so drift can't happen.

### Known limits and rough edges

- **Codex tool-call ID truncation** (`openai_responses_adapter.py::_normalize_call_id`): tool-call IDs longer than 64 chars are replaced with a deterministic hash. Logged as a warning; authors with long bot_id + tool_name combinations should keep identifiers short.
- **Codex OAuth `client_id`** (`openai_subscription_driver.py`): a public constant borrowed from OpenAI's own Codex CLI — not a secret.
- **Codex `reasoning.summary` default**: set unconditionally to `"auto"` so the thinking stream flows; callers can still override via model_params.
- **Anthropic `thinking` constraints**: when `thinking_budget > 0`, the adapter forces `temperature=1` and strips `top_p`/`top_k` (Anthropic SDK requires this for extended thinking).
- **Fallback model lists** in the Anthropic and OpenAI-subscription drivers are hardcoded today and will decay as new models ship. Phase 3 removes them in favor of the admin refresh flow. Today's mitigation: the Models table unions driver output with persisted rows, so admins can add a freshly-released model by hand without waiting for the driver's hardcoded list to be updated.
- **`test_connection()` is a no-op on Anthropic today** — it returns "Credentials OK" without probing the endpoint. Phase 3 fixes this.
- **`anthropic-subscription` provider_type** currently maps to the plain `AnthropicDriver`. There is no real OAuth driver. Treat that row in `DRIVER_REGISTRY` as unfinished scaffolding; Phase 3 either builds the driver or removes the type.

---

## Custom headers per provider

Some providers expect extra headers on every request — OpenRouter wants `HTTP-Referer` + `X-Title` for its analytics dashboard, OpenAI supports scoping via `OpenAI-Organization` / `OpenAI-Project`, Anthropic opt-in betas ride on `anthropic-beta: <flag>`. The provider edit page has a **Custom Headers** section with a key/value editor. Values are stored on `ProviderConfig.config['extra_headers']` (no migration needed) and passed to `AsyncOpenAI(default_headers=...)` — or the equivalent on `AnthropicOpenAIAdapter` / `OpenAIResponsesAdapter` — the next time a client is minted.

Caveats:

- Adapter-required headers (Bearer token, Accept, session_id, OpenAI-Beta, chatgpt-account-id for ChatGPT-subscription) are set first; your entries can still override them if they use the same casing, so use sparingly on subscription providers.
- Header values pass through as strings — numbers / booleans are coerced. Control characters and empty keys are rejected with a 422.

---

## Daily catalog refresh

`app/services/provider_catalog_refresh.py` runs at server boot and every 24h thereafter. For every enabled provider it calls `driver.list_models_enriched()` + `driver.fetch_pricing()` (where the driver advertises those capabilities), upserts `provider_models` rows, and records `last_refresh_ts` / `last_refresh_error` on `ProviderConfig.config`. The refresh is also triggered immediately after a successful **Test Connection** click, and admins can force one via:

```
POST /api/v1/admin/providers/{provider_id}/refresh-now
```

The Sync Models section on the provider edit page shows "Last auto-refresh: Xm ago" so you can eyeball staleness without clicking. Hardcoded fallback lists for Anthropic and OpenAI-subscription remain as a safety net (Anthropic has no public `/models` endpoint; OpenAI-subscription's live `/models` can fail before the user completes OAuth).

---

## Testing + diagnostics

- **Test connection** button on the edit page hits `driver.test_connection(...)`. On success it also kicks off a catalog refresh in the background. The OAuth provider's test confirms the issuer is reachable (it doesn't try to mint tokens — use the Connect flow for that).
- **Usage → Providers** tab aggregates `token_usage` trace events over the last 1–168h by `(provider_id, model)`: call count, p50/p95 latency, cache-hit rate, last-call timestamp, and circuit-breaker cooldown indicator. First stop when triage-ing "is my Ollama slow?" or "why is cost spiking?".
- **Usage dashboard** (`/admin/usage`) breaks cost out by provider and by model. Plan-billing providers report $0 per call; usage still tracks tokens and call counts for visibility. When a model has `cached_input_cost_per_1m` set, cost math splits cached vs uncached input — stops Anthropic spend from being inflated ~10× while prompt caching is active.

---

## Reference

| Driver | File |
|---|---|
| Base class + capabilities | `app/services/provider_drivers/base.py` |
| OpenAI | `openai_driver.py` (`OpenAIDriver`, `OpenAICompatibleDriver`) |
| OpenAI Subscription (OAuth) | `openai_subscription_driver.py` |
| Anthropic | `anthropic_driver.py` |
| Ollama | `ollama_driver.py` |
| LiteLLM | `litellm_driver.py` |
| OAuth device-code flow | `app/services/openai_oauth.py` + `app/routers/api_v1_admin/openai_oauth.py` |
| Responses-API adapter | `app/services/openai_responses_adapter.py` |
| Anthropic → OpenAI adapter | `app/services/anthropic_adapter.py` |
| Effort translator | `app/agent/model_params.py::translate_effort` |
| Prompt dialect rewrite | `app/services/prompt_dialect.py` |
| Slash command registry | `app/services/slash_commands.py::list_supported_slash_commands` |

## See also

- [Setup Guide](../setup.md) — initial bootstrap, `.env` fallback, setup wizard.
- [Usage & Billing](usage-and-billing.md) — cost tracking, plan billing, budget limits, spend forecasting.
- [API Reference](api.md) — `/api/v1/admin/providers/*` endpoints.
