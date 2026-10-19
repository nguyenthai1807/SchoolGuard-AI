# SchoolGuard AI — UI direction

## Product contract

SchoolGuard AI is a local-first home security monitor. The repeated job is to
sign in, choose a video or webcam, mark a zone, start detection, and review
evidence. The first viewport must establish trust and show system state before
the user starts an analysis.

## Design direction

- **Tone:** calm security operations console; clear and dependable rather than
  alarmist or decorative.
- **Primary action:** start a video analysis or turn on the webcam.
- **Memorable detail:** a restrained teal control color paired with a small
  amber signal accent, echoing a security status light without turning the page
  into a hazard-stripe dashboard.
- **Typography:** system UI fonts for local reliability and fast rendering;
  compact uppercase labels are reserved for controls and metadata.
- **Information density:** dashboard counters first, configuration second,
  analysis surfaces next, and evidence history last.

## States covered

| State | Visible feedback | Recovery / next action |
|---|---|---|
| Loading | Backend status and action-level status text | Wait or retry the action |
| Empty | “Chưa có vùng” / no recent events copy | Load a sample, choose a file, or draw a zone |
| Error | Inline red error text near the failed action | Correct input, sign in again, or retry |
| Partial | Provider configuration explains unavailable email/SMS | Configure SMTP or Twilio when needed |
| Success | Dashboard values and backend-active status | Continue to video, webcam, or history |
| Permission | Login gate and browser camera permission flow | Sign in or grant camera access |

## Responsive contract

- 375px: one-column flow, two-column summary counters, touch-friendly controls.
- 768px: single-column analysis sections with wider form rows.
- 1440px: video and webcam surfaces share a two-column workspace; settings and
  event history remain full width.

The implementation lives in `style.css` and uses the tokens in
`design-tokens.json` as the source of truth for the visual vocabulary.
