# LH25 weapon model

LH25 optionally evaluates the `cosgun99/gun-knife-yolo11n` checkpoint published
with a model card on Hugging Face. The installer downloads the repository's
`best.pt` through a pinned HTTPS URL, stores it as `weapon-gun-knife-v1.pt` and
writes a local SHA-256 manifest. Runtime code resolves class IDs from checkpoint
names and accepts its `gun` and `knife` classes. It does **not** claim generic
stick detection because that class is absent from this checkpoint.

This is an experimental visible-object warning, not a violence or intent
classifier. It can miss small/occluded weapons and can mistake ordinary objects;
LH25 now requires at least four spatially consistent observations spanning
0.6 seconds, with two strong scores, a peak of at least 0.8 and a mean of at
least 0.55. It labels evidence `WEAPON?` for human review. A single high
confidence frame cannot trigger a Telegram alert. This deliberately reduces
false alarms and can miss small, distant, or partly hidden objects.

The four AIRTLab clips used during the 2026-10-23 diagnostic were labelled
violent/non-violent, not weapon-present/absent. The previous engine produced
four weapon alerts on `violent-005` and two on `violent-006` while visually
placing many boxes on people and background; there is no ground truth that
those alerts represented real weapons. The stricter rule emits none on these
four clips. This is only a false-alarm smoke check, **not** a precision or
recall estimate. Before a commercial release, collect independently labelled
weapon-positive and weapon-negative footage and test both recall and false
alerts per hour on held-out cameras. Keep the feature off by default.

The model repository declares MIT and documents 29,446 training, 3,681
validation and 3,681 test images, but also says it is intended for academic
evaluation and not as a standalone safety system. Ultralytics runtime/base-model
terms still apply (AGPL-3.0 or Enterprise). Before running LH25 as a closed-source
paid service, review <https://www.ultralytics.com/license> and obtain the
appropriate commercial license when required. Model card:
<https://huggingface.co/cosgun99/gun-knife-yolo11n>.
