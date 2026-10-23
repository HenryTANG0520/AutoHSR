# Differential Universe pink-door detector

`du_target.onnx` is a local YOLO11n fine-tune, exported with a static 960px input,
raw boxes, and one class: `Target`. A sleeping door, an awake door, and a door
back all supply a bearing. The live enemy reticle authorizes an attack; the
live OCR 随意门 interaction authorizes F. Detection alone authorizes neither.

The model and its Ultralytics-derived weights are provided under AGPL-3.0;
see `LICENSE.du_target.txt`. Game imagery belongs to its respective owners.
The pretrained checkpoint came from the official Ultralytics assets release.
`du_target.json` records its hash, evaluation results, and limitations.

The reviewed local dataset uses separate capture sessions for train, validation,
and test. Train-only scale/crop augmentation supplements the near-door cases.
Original screenshots and the reviewed manifest stay in ignored `runs/`, with
the account identifier masked in training images. They are not uploaded by the
training or evaluation scripts. The held-out sample set is small; its scores
do not establish reliable full-run completion.

Training runs in an isolated environment using
`tools/requirements-du-training.txt`. Supply an existing local checkpoint:

```powershell
runs/gate-training-env/Scripts/python.exe tools/train_du_detector.py --manifest runs/gate-dataset/manifest-v3b.json --output runs/du-target-training --weights runs/yolo11n.pt
.venv/Scripts/python.exe tools/evaluate_du_detector.py --manifest runs/gate-dataset/manifest-v3b.json --model runs/du-target-training/fit/weights/best.onnx --output runs/du-target-training/cpu-evaluation
```

Runtime uses ONNX Runtime CPU and does not import PyTorch or Ultralytics.
`AUTOHSR_DU_DETECTOR` can point to a replacement local ONNX model for testing.

## World-card detector (2026-10-22)

`du_cards.onnx` is a separate YOLO11n derivative for floating world cards. It
runs through ONNX Runtime CPU with a 640px input and confidence threshold 0.80.
When installed, an empty learned result does not fall back to color/rectangle
artwork detection, which had confused facade advertisements with world cards.
Gate and card detectors retain separate classes and confidence thresholds.

The current incremental fit retains all previous data and adds four reviewed
two-card/edge-on views with 48 brightness variants: 26 native training images
and 776 training-only variants in total. The original four validation and eight
test images remain unchanged. At threshold 0.80, the CPU ONNX evaluation gives
validation TP4/FP0/FN0 and test TP3/FP0/FN0 (IoU 0.5). Brush, advertisement,
banner and console negatives, distant blue cards and front/back card regressions
also pass. Median CPU inference is about 21ms on this machine. New room views
are training/calibration examples, not held-out evidence; these small sets do
not establish independent full-run reliability.

`du_cards.json` records the hash, parameters and limitations. Like `du_target`,
this Ultralytics derivative is distributed under the included AGPL-3.0 license.
Raw captures, annotations, synthetic training scenes and checkpoints stay in
ignored `runs/`, with account identifiers masked.

## Brush and advertisement regressions (2026-10-23)

Both models now include reviewed cafeteria views containing decorative paint
brushes, wall advertisements, and the TV event card. Card training also rehearses
the distant blue maintenance card and the boss console negative. The card
threshold remains 0.80; the gate threshold remains 0.55. Original validation/test
capture groups are preserved. New room frames and their augmentations are
training/calibration examples, not independent accuracy evidence.

On the unchanged card set, the current checkpoint matches all seven objects
in twelve images with no false detections there. The native distant-blue
regression and console negative also pass. The selected gate checkpoint matches all 31 validation and
six test objects in 45 images with no extra detections at IoU 0.5. Brush and
advertisement regressions pass separately. These limited checks do not replace
the requested ten independent complete periodic runs.

The door model was additionally fitted on three reviewed console-occluded
door views and 36 brightness variants on 2026-10-23, keeping all earlier data
and validation/test groups. The selected last checkpoint completed eight
epochs. At threshold 0.55 the CPU evaluation retains validation TP31/FP0/FN0
and test TP6/FP0/FN0. Occluded door calibration views now provide a bearing;
this does not establish an awake face or authorize F. The new views are
training/calibration evidence, and independent full-run reliability is still
unproven. Metadata contains the current hash, provenance and limitations.

## Enemy bearing detector (2026-10-22)

`du_enemies.onnx` is a separate 640px Enemy-only YOLO11n derivative, running
on CPU at threshold 0.70 (about 21ms per frame). Its current data covers the
observed Aurumaton, Senior Staff: Team Leader, 正阳狮鹫, 金血忆灵·裁定, 乐变化天人,
承露天人 and 波涛夫人 appearances: sixteen native positive training frames,
twenty-three negatives and 1480 generated scenes. The seventh fit retains previous
examples and trains for 25 epochs. Its last checkpoint retains more test detections than
best. `du_enemies_fallback.onnx` preserves the preceding five-appearance fit;
it runs only when the primary model yields no usable enemy bearing.

With fallback, eight nearby positive calibration frames were detected. In
nineteen test frames, twelve backgrounds had no detections; six of seven enemy
boxes match, and bright celestial spawn effects still cause a miss. Primary
CPU inference is about 22ms; the combined calibration median is about 38ms,
including frames that require both models. Calibration views are
from the same trials. These small samples do not establish general monster
accuracy or independent full-run reliability.
The model supplies a bearing; the live range reticle still authorizes attack.
The former red-silhouette fallback was removed because it matched shop signs.
`du_enemies.json` records provenance, SHA-256 and limitations. The included
AGPL-3.0 terms apply to this Ultralytics derivative as well.
