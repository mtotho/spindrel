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

## Testing + diagnostics

- **Test connection** button on the edit page hits `driver.test_connection(...)`. The OAuth provider's test confirms the issuer is reachable (it doesn't try to mint tokens — use the Connect flow for that).
- **Diagnostics** (`/admin/diagnostics`) surfaces per-provider health: last-call timestamp, recent error rates, model catalog freshness.
- **Usage dashboard** (`/admin/usage`) breaks cost out by provider and by model. Plan-billing providers report $0 per call; usage still tracks tokens and call counts for visibility.

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
| Anthropic → OpenAI adapter | `app/services/anthropic_openai_adapter.py` |

## See also

- [Setup Guide](../setup.md) — initial bootstrap, `.env` fallback, setup wizard.
- [Usage & Billing](usage-and-billing.md) — cost tracking, plan billing, budget limits, spend forecasting.
- [API Reference](api.md) — `/api/v1/admin/providers/*` endpoints.
