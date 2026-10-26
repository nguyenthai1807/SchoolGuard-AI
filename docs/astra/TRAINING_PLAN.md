# Training contract — experiment 1

Goal: improve person detection on campus video without materially increasing false alerts. Owner: project author. Output remains person boxes + anonymous track IDs, not identity or intent.

Baseline: pretrained YOLO11n and current demo YOLO11s at 640, person confidence 0.35. Candidate: YOLO11n transfer learning; CPU-only budget, fixed seed 42, 12 epochs, image size 512, freeze first 10 layers, batch 8, conservative learning rate. This is a first local adaptation experiment, not exhaustive optimization.

Sources: local ShanghaiTech campus videos; COCO128 via official Ultralytics assets; Penn-Fudan pedestrian images and instance masks via University of Pennsylvania (also used by official PyTorch tutorial). Do not upload images or local video to GitHub. Keep source links, archive SHA256 and split manifest.

Labels: person=0. Penn-Fudan masks become per-instance bounding boxes. COCO original person labels retained, other classes discarded (negative images retained). ShanghaiTech anomaly masks are NOT person labels. Sampled ShanghaiTech training scenes use YOLO11s teacher boxes marked `pseudo`; a few visually reviewed boxes are marked `assistant_reviewed`. Pseudo labels can omit people and preserve teacher errors; they do not count as accuracy evidence.

Split before sampling: ShanghaiTech scenes 1,2,3,5,6,10,13 for train. Scenes 4,7 for validation; 8,9,12 for held-out evaluation. No frame from a held-out camera scene enters training. Penn-Fudan sorted capture sequences partitioned into contiguous train/val/test blocks by prefix to reduce adjacent-image leakage. COCO deterministic image-level splits; COCO128 is from COCO train2017, already seen by pretrained YOLO, so its held-out result is NOT novel-data generalization evidence. Exact image SHA256 must not cross splits. ShanghaiTech held-out labels were inspected during initial model development, so they are a development holdout rather than a blind final benchmark.

Promotion gate declared before training: compare candidate and YOLO11s on identical held-out frames at confidence .35 / IoU .5; require overall F1 >= baseline + .01, precision >= baseline - .01, ShanghaiTech recall >= baseline and fewer/equal false positives, and mean latency <= 1.5x baseline. Report COCO, Penn-Fudan and ShanghaiTech slices separately. Fail closed on missing measurements. If rejected, retain YOLO11s as default and allow explicitly selecting the trained experimental candidate.

Known limitations: small subjective campus-label set; occlusion/very small people; pseudo-label noise; one training seed; camera-domain shift. More epochs or more unlabelled video do not establish higher accuracy. Save best/last checkpoints, exact arguments, curves and evaluation so a longer GPU experiment can be repeated later.
