# LH25 Admin demo curation — 2026-10-25

Purpose: a presentation/test shortlist, **not** a claim of model sensitivity,
specificity, or readiness as a certified safety alarm. A star means one source,
one completed LH25 job, a checked alert frame, and a documented usage basis.
Video and output remain local; the library is visible only to LH25 Admin.

## Decision contract

- Target: up to five distinct video sources per capability, never five timestamps
  from the same video.
- Promotion gate: original media rights checked; source SHA-256 recorded; LH25
  job completed; alert/frame matches the visible event; no known false-positive
  verdict; reviewer note names the evidence time and limitations.
- Unacceptable mistake: labeling a research-only clip as a commercial demo,
  or calling an AI alert correct without reviewing the relevant frame.
- Fallback: show fewer than five, with an honest counter, until eligible clips
  and human review exist.

## Reviewed fire/smoke shortlist — 5/5

Source: [official FURG fire dataset](https://github.com/steffensbola/furg-fire-dataset)
at pinned revision `6aff09d7baa27425f31d1df685284c26cbffe7af`,
[CC0 license](https://github.com/steffensbola/furg-fire-dataset/blob/6aff09d7baa27425f31d1df685284c26cbffe7af/LICENSE).
All five video hashes match `runtime/event-data/furg/manifest.json` and the
corresponding jobs completed. Each selected evidence JPEG was opened and
visually checked. **These are staged scale-model house scenes, not real
occupied homes.** Do not use them to claim real-home detection accuracy.

| Video | Reviewed fire time | Completed LH25 job | Visual finding |
| --- | ---: | --- | --- |
| `house1.mp4` | 29.36 s | `7a7a6ccbf1cd41b8a27180de8a2742f0` | Flame over a scale-model roof/opening correctly boxed. |
| `house3.mp4` | 12.51 s | `f8f71b1fe67a4a9f8118559f14b98987` | Flame in a scale-model roof window correctly boxed. |
| `house4.mp4` | 10.68 s | `014dfc49f7134eb99d65748ced55e147` | Flame inside an open scale-model room correctly boxed. |
| `house5.mp4` | 4.27, 19.75 s | `d1ab2e16ac8d40dbb0a7f72745f0f822` | Flame inside an open scale-model room correctly boxed at both alerts. |
| `house6.mp4` | 28.53 s | `8505984382fa4ed8aede21d3236b27d7` | Flame at a scale-model window correctly boxed; earlier smoke was separately reviewed. |

`house2.mp4` also produced two visually correct fire alerts (4.80 and 21.35 s)
and remains an unstarred reserve because the display limit is five. A prior
negative `non_fire_patrolbot_onboard.mp4` job with fire detection enabled
completed without a fire/smoke alert; this single negative is not a false-alarm
rate measurement. Video-level successes here are cherry-picked presentation
examples, not independent holdout evaluation.

Reproduce local processing, with Telegram suppressed:

```powershell
./.venv/Scripts/python.exe -m scripts.evaluate_fire_demos
./.venv/Scripts/python.exe -m scripts.evaluate_fire_demos --apply
./.venv/Scripts/python.exe -m scripts.seed_fire_demos
./.venv/Scripts/python.exe -m scripts.seed_fire_demos --apply
```

## Academic-only internal demo shortlist — 5/5 in each group

The project owner approved research footage **only for internal academic
presentation** on 2026-10-25. Every URFD/AIRTLab entry below has
`academic_only=1` in the Admin library and a visible “không quảng cáo” badge.
Do not reuse its video, thumbnails, face crops, or results in LH25 STORE,
marketing, a public presentation, or a commercial model benchmark without
separate rights. The app validates the academic label for newly starred
`[research]` sources. A star is a curated positive case, not a measured
accuracy score. The on-disk source manifest, SHA-256, completed LH25 job,
specific evidence frame/crop, and reviewer note are checked by
`scripts/seed_academic_demos.py`.

### Suspected fall — 5/5

Source: [UR Fall Detection Dataset](https://fenix.ur.edu.pl/~mkepski/ds/uf.html),
Kwolek & Kępski (2014), CC BY-NC-SA 4.0. All five are **staged** author RGB
previews extracted from the right half of depth+RGB video; original previews
remain intact. `fall-04` and `fall-05` were additionally downloaded directly
from the official host and recorded in `runtime/event-data/urfd-demo-manifest.json`.

| Video | Alert time | Completed job | Human review |
| --- | ---: | --- | --- |
| `fall-01-cam0-rgb` | 3.67 s | `a47f15dbd17243d8a053d49b04dc2a99` | Person on floor, pose box correctly placed. |
| `fall-02-cam0-rgb` | 2.13 s | `753ba5678346471a842027a5ef1220a1` | Person near floor after fall, pose box correctly placed. |
| `fall-03-cam0-rgb` | 6.10 s | `6b03a8a53e8f4d6e9374ab575ad261fa` | Person on floor, pose box correctly placed. |
| `fall-04-cam0-rgb` | 1.40 s | `67cdc241fed04509a4a348debb29e974` | Person falling toward floor, pose box correctly placed. |
| `fall-05-cam0-rgb` | 3.47 s | `bd908a2baf904c48a0837807936660ce` | Person near floor after fall, pose box correctly placed. |

These checks looked at the alert frame and author clip label, not every frame
or all possible misses; no sensitivity claim follows.

### Extra people above default 1 — 5/5

Source: AIRTLab staged research/education clips (Bianculli et al. 2020).
All reviewed alert frames contain more than one person. `non-violent-001`
visibly has three people while LH25 boxed only two; it is a valid *threshold*
example, **not an exact-count demo**. The other four selected alert frames
each show four people and four person boxes. The label “violent” is the
author's clip label; a people-count alert does not validate LH25 conflict
detection.

| Video | Alert time | Completed job | Review |
| --- | ---: | --- | --- |
| `non-violent-001` | 3.00 s | `0b8a6f28cd394e85b13eb911cf5fa669` | 3 visible, 2 boxed; threshold correct, one missed. |
| `non-violent-002` | 3.00 s | `44a66b5813c94d97afb56ff3f30af4ce` | 4 visible and boxed. |
| `non-violent-003` | 3.00 s | `ecde14c69cb34d9aaffb97696c3eeb57` | 4 visible and boxed. |
| `non-violent-005` | 3.00 s | `5679ca83e67e48d5802c60a6cb93a5d1` | 4 visible and boxed; face-gallery duplication possible. |
| `violent-003` | 3.00 s | `6ab17300527e4376891552d0471db458` | 4 visible and boxed. |

### Saved faces — 5/5

Source: five distinct AIRTLab clips. Each selected job has a saved crop that
was opened and visually inspected. The Admin card shows an actual saved face
crop, not a generic video thumbnail. A back-facing head is a *person*, not
proof of recognized facial identity. No listed clip verifies a person's name
or proves all visible people were saved; notably `non-violent-003` contains
four people but only two face crops.

| Video | Completed job | Checked crop | Limitation |
| --- | --- | --- | --- |
| `non-violent-001` | `0b8a6f28cd394e85b13eb911cf5fa669` | `3aa5a9c4bc204f5a92e73a4551191ffe.jpg` | One visibly valid crop; not all people. |
| `non-violent-002` | `44a66b5813c94d97afb56ff3f30af4ce` | `ccac25b1cdb3434098f6ecee719c109c.jpg` | Side profile. |
| `non-violent-003` | `ecde14c69cb34d9aaffb97696c3eeb57` | `15a9e40e7aee497d9163ab0ca264a415.jpg` | 4 people, 2 saved faces. |
| `non-violent-004` | `618174e1f12744219480548d72c26f2e` | `06a968aa1e674747a21c90fa2be5600d.jpg` | Side profile. |
| `violent-003` | `6ab17300527e4376891552d0471db458` | `5c2f23bf7c0746ca84e1872b47489e33.jpg` | Side profile; no identity matching. |

Reproduce the rights/evidence checks and idempotent local stars:

```powershell
./.venv/Scripts/python.exe -m scripts.prepare_fall_demos
./.venv/Scripts/python.exe -m scripts.prepare_fall_demos --apply
./.venv/Scripts/python.exe -m scripts.evaluate_fall_demos --apply
./.venv/Scripts/python.exe -m scripts.seed_academic_demos
./.venv/Scripts/python.exe -m scripts.seed_academic_demos --apply
```

## Remaining demo inventory

| Capability | Reviewed stars | Blocker before five can be claimed |
| --- | ---: | --- |
| Suspected fall | 5/5 internal only | Need a larger balanced test set, realistic scenes, and independent error measurement. |
| Extra people | 5/5 internal only | Some cases undercount; independent exact-count evaluation needed. |
| Saved faces | 5/5 internal only | Crops are valid examples, but unique-identity counts and retention need validation. |
| Suspected weapon | 0/5 | Existing AIRTLab runs include known false positives and research-use rights; no reviewed true-positive commercial-use clip. |
| Suspected conflict | 2/5 internal only | Two staged scenes have alert frames matching visible physical interaction; heuristic also fires on non-violent clips, so this is not an accuracy claim or commercial-use shortlist. |

Next experiment: collect or license five independent scenes per remaining
capability, plus negative controls and edge cases. Record ground-truth times,
review every alert and miss, and report precision/recall per scenario before
any external reliability claim. The current admin curation form can then add
stars one source at a time after a completed job and rights review.

### Additional review of weapon/conflict evidence

Two current AIRTLab `weapon` alert JPEGs were opened. The `violent-001` box is
on a dark doorway/person edge without a visible weapon. The `violent-005` box
is on a shoe; a stick appears elsewhere in the frame but is **not** what the
model boxed. Neither is a defensible positive demo, so weapon remains 0/5.
Five AIRTLab `violent` sources also have `vigorous_interaction` alerts, but
this wrist-motion rule has fired on non-violent footage. After comparing the
alert JPEGs with multiple author frames, only these two staged scenes were
promoted as **academic-only, scene-level examples**:

| Video | Alert time | Completed job | What the evidence supports |
| --- | ---: | --- | --- |
| `violent-002` | 1.67 s | `b6b3e14b66c64b239bab82efbb6c828d` | Alert frame shows arm contact; frames 31/79/126 show a shove sequence. Does not establish intent or general recall. |
| `violent-004` | 0.80 s | `1118d90fc54444eb879fd49595b11cc6` | Alert occurs in a staged scene with a man approaching a person on the floor holding a stick; frames 20/51/81 show the sequence. AI did **not** identify the stick as a weapon, and the red pose box is on another person. |

The two stars document only that an alert overlapped the staged scene. They
do not prove that LH25 correctly localized the aggressor, classified violence
versus a benign gesture, or would catch an unseen attack. Both are labeled
research/education **internal only**, never Store/marketing. The original
videos and alert evidence files remain unchanged. The two misboxed `weapon`
alerts were marked `false_positive` with reviewer notes and audit records by
`scripts/review_weapon_false_positives.py`; this is a review status, not a
new training label. Three more varied, independently reviewed interaction
positives and negative controls are needed before reaching 5/5.
