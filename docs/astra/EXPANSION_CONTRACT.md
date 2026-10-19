# Campus events v2 — prediction contract

Goal: help an operator review possible hazards in local video; no automatic punishment or emergency dispatch. Owner: school security operator, with human review of every alert.

Baseline: YOLO11s person detection + ByteTrack + restricted-zone dwell. Candidate: optional YOLO11n-pose for 17 COCO keypoints; temporal geometry rules for suspected fall, prolonged lying, vigorous close interaction, crowding and loitering. No identity inference or medical diagnosis.

Inputs: fixed-rate video, normalized boxes/keypoints, original frame timestamp, aspect ratio. Missing/low-confidence keypoints mean abstain, not normal/safe. Tracking gaps reset temporal evidence. Confidence stored is detector confidence, NOT probability of the event.

False alarms: sports, play, lying voluntarily, camera motion, occlusion and perspective can resemble hazards. Unacceptable: presenting a heuristic as a validated classifier, saying a person fainted or committed violence, hiding missing models, replacing a better baseline with a weaker fine-tune.

All action rules are opt-in experiments, separate from person detection. Fire requires a separate trained fire/smoke detector, not the COCO person model. No invented fire class. Model availability must fail closed. Each alert includes event type, reason, severity, duration, track(s), evidence and review status.

Evaluation: deterministic rule tests (positive, negative, missing pose, ID gap, aspect ratio, cooldown), real YOLO video smoke tests, independently held-out full scenes for future precision/recall and false-alerts/hour. Unit tests do not establish field accuracy. Original dataset splits and video groups are retained; no adjacent-frame random split. Data stays local; provenance/usage restrictions recorded. Camera connection deferred by user.

Person fine-tune v1: 12 CPU epochs complete; initial evaluation on 50 small development-test images gave F1 0.802 vs YOLO11s 0.832; ShanghaiTech 3-frame slice recall 0.706 vs 0.882. Do not promote. No threshold tuning on these held-out samples. Next experiment: better manually reviewed labels and larger independent campus clips.

Rollback: disable individual event toggles, select YOLO11s, preserve existing jobs and database. Default redaction now off at user's request; old rendered videos remain blurred and require reprocessing original sources.
