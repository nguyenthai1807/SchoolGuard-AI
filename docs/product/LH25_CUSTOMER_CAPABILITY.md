# LH25 customer onboarding and Telegram capability

## Capability

- **Source:** Owner's LH25 commercialization and customer-onboarding request (October 2026).
- **Primary actors:** LH25 operator (platform owner), customer account, Telegram bot.
- **Outcome:** A pilot customer supplies contact details, pairs a private Telegram chat, then analyzes their own video or webcam stream and receives their own event alerts.
- **Success signal:** A private-chat test message succeeds; a fall test video creates an urgent alert routed only to that customer's chat; another customer cannot read its source, result, face image or evidence.

## Product intent and current delivery

The customer-facing flow is `admin creates account -> customer signs in -> customer saves contact profile -> customer pairs Telegram with a one-time /start code -> bot confirms delivery -> customer may start video/webcam analysis`. The local administrator remains able to run demos without onboarding, including the original optional shared chat ID. Email is contact information only; it is **not verified**. The current implementation is a **local single-process pilot**, not a public paid SaaS.

## Constraints

- A non-admin account cannot start new video or webcam analysis until it has a profile, a configured platform bot and a verified private Telegram chat.
- The bot token is controlled by the LH25 operator in `.env`, never supplied by a customer or returned by API. Customers never enter a Telegram password.
- A one-time pairing code expires after 10 minutes. Only a private Telegram chat whose sender matches its chat ID can bind. A successful outbound test message is required before marking it verified.
- Customer video sources, jobs, alerts, evidence, face records and exports are scoped to the owning account. Existing unowned sources are admin-only; existing admin jobs remain visible to admin.
- No promise of emergency-grade fall/fire detection or guaranteed Telegram delivery. Failed Telegram sends remain visible in alert history; a disconnected or blocked bot may fail even after earlier verification.
- Existing local `admin` can see all accounts for support. This does **not** yet provide organization/household roles or tenant administrators.

## Actors and surfaces

- **Customer:** Login, `Telegram` menu with profile and pairing, Video Analysis, Webcam, Alerts.
- **Local admin:** Create accounts in System, provision one bot token, inspect all data and audit entries.
- **Bot:** `getMe`, `getUpdates`, private `/start <one-time-code>`, `sendMessage` confirmation, `sendPhoto` for events.
- **API:** `/api/profile`, `/api/telegram/status`, `/api/telegram/link`, `/api/telegram/check`, `/api/jobs`, `/api/live/*`, read-only result routes.

## States and transitions

- Profile: `missing -> saved -> updated`.
- Telegram: `unlinked -> pending (10 min) -> verified -> disconnected`; expired/replaced codes cannot be used.
- Analysis: `blocked -> allowed` only after profile and Telegram are ready; admin pilot exemption is explicit.
- Alert delivery: `pending -> delivered | telegram_not_configured | telegram_delivery_failed | telegram_rejected`. Manual retry is available where safe.

## Interface and data implications

- `customer_profiles` stores contact name, email, optional phone; `telegram_accounts` stores account-to-chat binding; `telegram_pending` stores only a hash of the pairing code; `telegram_poll` stores the bot update cursor; `source_ownership` stores account ownership for uploaded/live sources. Existing `jobs.user_id` anchors result ownership.
- Telegram pairing uses on-demand `getUpdates` when the user presses **Check & verify**. It must be the only consumer for this bot token. This is suitable for a local pilot, not concurrent web replicas.
- Starting a new analysis checks onboarding server-side, not only in JavaScript. UI does not imply that a successfully paired bot will always deliver future messages.
- Existing uploaded videos without an ownership record are not auto-assigned to a customer, because past ownership cannot be proved. They remain accessible to admin only.

## Security and policy

- UI/API mask chat ID, never expose token, avoid logging pairing codes. Site must remain localhost-only until HTTPS, production session security, multi-tenant authorization review, persistent queue, backups, rate limits and production bot webhook are in place.
- Video, face crops and contact data require consent, retention/deletion policy, access audit and legal review before paid public use.
- Research clips and model weights need independent commercial-use license review; URFD fall clips are for research/development smoke tests only.

## Non-goals for this local slice

- Public deployment, customer self-registration, verified email, payments, subscription/license enforcement, invoices, 24/7 camera agent, organization memberships, production webhook/worker scaling, automatic Telegram retry and emergency dispatch.

## Open questions before public sale

1. Business entity, domain/hosting region, payment provider, terms, privacy policy and required ecommerce procedure.
2. Data retention defaults for raw videos, evidence, face crops and embeddings; deletion/export workflow.
3. Whether the product is one account per household or supports family operators/viewers under a household tenant.
4. Policy when Telegram becomes unreachable during an active webcam session, and whether a backup channel is required.
5. Commercial licenses for detector, weights and all training/evaluation media; independently measured false alarms and miss rates.

## Handoff

- **Ready now:** Local pilot with one admin and separately owned customer accounts; test with a dedicated bot and a consenting Telegram user.
- **Needs architecture review:** Multi-tenant public service, webhook, PostgreSQL/object storage, background queue and secure deployment.
- **Needs product/legal clarification:** Billing, retention, household role model, emergency claims and licensing.
