# Requirements accepted from the user's Google Doc

Source: document 1H-YfptV4D5ldZfoAhSkXbs4YCUbM4UMQuoXd6tGYrA0, read completely
on 2026-10-24. No requirement below is considered complete solely by listing it.

## Product decisions

- Browser inference remains the selected direction; trusted backend is still
  necessary for Google sessions, orders, quotas, notifications and entitlement.
- Signed payOS confirmation activates Pro automatically. Admin reviews exceptions
  and can resend the guide; manual approval must not override payOS verification.
- One shared bot with private verified per-user Telegram chats is supported.
  Separate customer-owned bots are a different, unimplemented credential workflow.
- More effort must mean measurable compute/sampling differences, never a fake
  "thinking" animation or guaranteed accuracy. Version labels are not new training.
- No Pro paywall, quotas or roles enforced only in JavaScript may be called secure.
- Do not publish images from customer or research datasets without permission.

## Work map and honest completion criteria

| Requirement | Actual status / next gate |
| --- | --- |
| Real Store illustrations | Added two screenshots captured from LH25 with an isolated, empty demo account (video library and Free plan). These show real product UI, not AI detections. Real detection examples await a clip with explicit public-use permission; no fabricated accuracy evidence |
| Plain-language copy | Updated Free/Pro limits, caveats and expert explainer; full editorial pass pending |
| VI/EN/JA/KO/ES | Language picker and visible Store body copy translated in all five languages, including technical sections and screenshot captions. Separate terms/privacy pages remain Vietnamese only; native and legal review pending |
| Google registration/login | Backend, consent UI and verified subject admin allowlist implemented; Store password form is hidden for new visitors and explicitly waits for Google OAuth. Legacy API/account login is retained for pilot migration; OAuth client, real browser login and public backend integration pending |
| Google-only public access | Server-side `LH25_GOOGLE_ONLY` mode implemented and tested; OFF until real OAuth client/admin subject configured; legacy sessions blocked when ON |
| Free limits + finite Pro quotas | Free 3/month, 2min/100MB; Pro 60/month, 10min/500MB and 5h webcam per Vietnam day enforced server-side; separate browser reservation enforcement pending |
| All Pro features except Admin | Existing backend entitlement partly implemented; browser feature migration and server gates pending |
| payOS activation | Signed webhook / idempotency implemented and mock-tested; public HTTPS and intentional real-payment test pending |
| Guide email | Text guide now included in durable activation receipt; image-illustrated localized guide pending |
| Admin resend / order email | Activated-order-only resend API and UI implemented; email dispatch depends on active configured worker |
| Customer-owned uploads only | Backend ownership regression passes; customer UI now hides research/training catalog; browser catalog separate |
| Pro badge and usage menu | Backend entitlement-backed Free/Pro label and remaining video count in app header, plan details show daily webcam use; browser-only app pending |
| Requested favicon | Generated LH25 and LH25 STORE PNG favicons from letter style; reference faces intentionally removed; wired into local pages and static build |
| Telegram per customer | Ownership routing already implemented; external two-customer delivery still unverified |
| Dedicated admin Google login | Allowlist by stable verified subject + live-session revocation implemented; unauthenticated `/admin` redirects to separate Google sign-in page. Actual Google sign-in and MFA remain unverified/pending |
| Admin accounts/order table | Existing users/email/plan/order UI, now order email + resend; full requested management refinement pending |
| YOLO26 | Python integration and browser person model exist; accuracy gates still open |
| Purpose-specific model catalog | Pending actual trained/exported assets and metrics, do not relabel COCO weights as Fire |
| Five effort levels | Python video path maps Low/Medium/High/Extra/Extra Max to 640/960px and 5/3/1/2/1 frame stride; browser sampling intervals 1000/600/300/150/80ms implemented, serialized inference; no guaranteed accuracy uplift |
| Locked Pro options | Python server now gates advanced detectors/models/effort; UI shows disabled Pro model/effort choices; independent browser app still lacks trusted entitlement |
| Terms/privacy | Separate clearly labeled beta terms and privacy pages built locally and for static Store; operator contacts, retention, deletion/refund workflow and legal review pending |
| Expert documentation | Store now distinguishes pretrained YOLO person/Pose models from separate fire/weapon/face components, links official YOLO26 documentation; licensing/benchmark audit pending |

## UI design contract

Keep the current calm teal/cream Store and dense dark application. Primary job:
sign in, understand actual rights, choose own input, see progress and evidence.
Target widths: 390px and 1440px. Loading, empty, error, partial, success and
camera permission states must be exercised. Source inspection alone is not
visual QA; record untested states rather than claim the finish gate passed.

No new billable cloud resources, real charge, public private-image upload or
production email blast has been authorized by this implementation batch.
