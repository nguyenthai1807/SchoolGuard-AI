"""Local face detection and anonymous matching within one video or camera day."""

import sqlite3
import uuid
from datetime import datetime

import cv2
import numpy as np

from .db import now
from .tracking import overlap

FACE_MODELS = ("face_detection_yunet_2026may.onnx", "face_recognition_sface_2021dec.onnx")
MATCH_THRESHOLD = 0.45  # Conservative relative to OpenCV Zoo's 0.363 demo threshold.


def models_ready(settings):
    return all((settings.models / name).is_file() for name in FACE_MODELS)


def local_day():
    return datetime.now().astimezone().date().isoformat()


def _face_bodies(box, people):
    """Return actual person tracks containing the face center in their head area."""
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return {p['track_id'] for p in (people or [])
            if p.get('class_id', 0) == 0 and p.get('track_id') is not None
            and p['bbox'][0] <= cx <= p['bbox'][2]
            and p['bbox'][1] <= cy <= p['bbox'][1] + .45 * (p['bbox'][3] - p['bbox'][1])}


def _unique_faces(observations, people):
    """Suppress near-identical proposals only with supporting appearance evidence."""
    unique = []
    for item in sorted(observations, key=lambda face: face['confidence'], reverse=True):
        bodies = _face_bodies(item['bbox'], people)
        duplicate = False
        for previous, prior_bodies in unique:
            # Distinct body assignments outweigh similar-looking face proposals.
            if bodies and prior_bodies and bodies.isdisjoint(prior_bodies):
                continue
            if (overlap(item['bbox'], previous['bbox']) >= .85
                    and item['embedding'].shape == previous['embedding'].shape
                    and float(np.dot(item['embedding'], previous['embedding'])) >= MATCH_THRESHOLD):
                duplicate = True
                break
        if not duplicate:
            unique.append((item, bodies))
    return [item for item, _bodies in unique]


class FaceRecognizer:
    """YuNet landmarks + SFace embedding; model files never leave this computer."""

    def __init__(self, settings):
        if not models_ready(settings):
            raise FileNotFoundError("Chưa có model khuôn mặt. Chạy python -m scripts.download_face_models.")
        self.detector = cv2.FaceDetectorYN.create(
            str(settings.models / FACE_MODELS[0]), "", (320, 320),
            score_threshold=0.7, nms_threshold=0.3,
        )
        self.recognizer = cv2.FaceRecognizerSF.create(str(settings.models / FACE_MODELS[1]), "")

    def _detect(self, frame, max_side=1280):
        height, width = frame.shape[:2]
        # Small research clips often contain 15-25 px faces. Upscaling helps
        # YuNet see them, though it cannot recover detail absent in the video.
        scale = min(3.0, max_side / max(width, height))
        sample = (cv2.resize(frame, None, fx=scale, fy=scale,
                             interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)
                  if abs(scale - 1) > 1e-6 else frame)
        height, width = sample.shape[:2]
        self.detector.setInputSize((sample.shape[1], sample.shape[0]))
        _, found = self.detector.detect(sample)
        observations = []
        if found is None:
            return observations
        for raw in found[:30]:
            face = raw.astype(np.float32).copy()
            x, y, w, h = face[:4]
            if w < 24 or h < 24:
                continue
            x1, y1 = max(0, int(x)), max(0, int(y))
            x2, y2 = min(width, int(x + w)), min(height, int(y + h))
            if x2 - x1 < 24 or y2 - y1 < 24:
                continue
            aligned = self.recognizer.alignCrop(sample, face)
            feature = self.recognizer.feature(aligned).reshape(-1).astype(np.float32)
            norm = float(np.linalg.norm(feature))
            if not np.isfinite(norm) or norm < 1e-8:
                continue
            feature /= norm
            pad = int(max(w, h) * 0.16)
            crop = sample[max(0, y1-pad):min(height, y2+pad), max(0, x1-pad):min(width, x2+pad)]
            crop = cv2.resize(crop, (160, 160), interpolation=cv2.INTER_AREA)
            ok, encoded = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 88])
            if not ok:
                continue
            observations.append({
                "bbox": [x1 / width, y1 / height, x2 / width, y2 / height],
                "confidence": float(face[14]), "embedding": feature,
                "image": encoded.tobytes(),
            })
        return observations


    def __call__(self, frame, people=None):
        observations = self._detect(frame)
        height, width = frame.shape[:2]
        # Retry only people whose upper body has no face, with a larger local
        # face image. This avoids repeatedly running high-resolution full frames.
        retries = 0
        candidates = list(people or [])
        offset = getattr(self, '_retry_offset', 0) % max(1, len(candidates))
        candidates = candidates[offset:] + candidates[:offset]
        self._retry_offset = offset + 2
        for person in candidates:
            if person.get('class_id', 0) != 0:
                continue
            a, b, c, d = person['bbox']
            bottom = b + (d-b)*.55
            if any(a <= (f['bbox'][0]+f['bbox'][2])/2 <= c
                   and b <= (f['bbox'][1]+f['bbox'][3])/2 <= bottom for f in observations):
                continue
            if retries >= 2:
                break
            x1, y1 = max(0, int(a*width)), max(0, int(b*height))
            x2, y2 = min(width, int(c*width)), min(height, int(bottom*height))
            if x2-x1 < 24 or y2-y1 < 24:
                continue
            retries += 1
            for face in self._detect(frame[y1:y2, x1:x2], max_side=640):
                x, y, r, t = face['bbox']
                box = [(x1+x*(x2-x1))/width, (y1+y*(y2-y1))/height,
                       (x1+r*(x2-x1))/width, (y1+t*(y2-y1))/height]
                observations.append({**face, 'bbox': box})
        return _unique_faces(observations, people)


class FaceLedger:
    """Deduplicate faces per video, or across webcam sessions on the same local day."""

    def __init__(self, db, runtime, kind, job_id, recognizer, day_provider=local_day,
                 user_id=None):
        self.db, self.runtime = db, runtime
        self.kind, self.job_id = kind, job_id
        self.user_id = user_id
        self.recognizer, self.day_provider = recognizer, day_provider
        self.scope = None
        self.records = {}
        self.body_faces = {}
        self.pending_faces = {}
        self.refresh_scope()

    def refresh_scope(self):
        day = self.day_provider()
        scope = (f"live:{self.user_id}:{day}" if self.user_id is not None
                 else f"live:{day}") if self.kind == "live" else f"video:{self.job_id}"
        if scope == self.scope:
            return
        self.scope, self.day = scope, day
        self.records = {}
        self.body_faces.clear()
        self.pending_faces.clear()
        for row in self.db.all("SELECT id,ordinal,embedding,seen_count FROM faces WHERE scope=?",
                               (scope,)):
            feature = np.frombuffer(row["embedding"], dtype=np.float32).copy()
            if feature.size and np.isfinite(feature).all():
                self.records[row["id"]] = {
                    "ordinal": row["ordinal"], "embedding": feature,
                    "seen_count": row["seen_count"], "last_bbox": None,
                    "last_time": None,
                }

    def observe_people(self, people, video_time):
        """Expire bindings when a body actually disappears, not when its face turns."""
        self.refresh_scope()
        visible = {p['track_id'] for p in people
                   if p.get('class_id', 0) == 0 and p.get('track_id') is not None}
        for track, state in list(self.body_faces.items()):
            if track in visible:
                state['last'] = video_time
            elif video_time - state['last'] > 2.5:
                del self.body_faces[track]
        for key, pending in list(self.pending_faces.items()):
            if pending['body'] is not None:
                if pending['body'] in visible:
                    pending['body_last'] = video_time
                elif video_time - pending['body_last'] > 2.5:
                    del self.pending_faces[key]
        self.pending_faces = {k: v for k, v in self.pending_faces.items()
                              if 0 <= video_time - v['last'] <= 10.0}

    def update(self, frame, video_time, people=None):
        self.refresh_scope()
        observations = (self.recognizer(frame, people=people)
                        if isinstance(self.recognizer, FaceRecognizer) else self.recognizer(frame))
        observations = _unique_faces(observations, people)
        self.pending_faces = {k: v for k, v in self.pending_faces.items()
                              if 0 <= video_time - v['last'] <= 10.0}
        self.body_faces = {k: v for k, v in self.body_faces.items()
                           if 0 <= video_time - v['last'] <= 2.5}
        body_options = [_face_bodies(item['bbox'], people) for item in observations]
        bodies = [next(iter(options)) if len(options) == 1 else None for options in body_options]
        # Multiple distinct faces inside one body box are ambiguous; do not let
        # proposal order decide which person owns that track.
        body_counts = {body: bodies.count(body) for body in set(bodies) if body is not None}
        bodies = [body if body_counts.get(body) == 1 else None for body in bodies]
        current_tracks = {p['track_id'] for p in (people or [])
                          if p.get('class_id', 0) == 0 and p.get('track_id') is not None}
        owners = {}
        for track, binding in self.body_faces.items():
            owners.setdefault(binding['id'], set()).add(track)
        clear_bodies = {body for body in bodies if body is not None}
        reserved = {state['id']: track for track, state in self.body_faces.items()
                    if track in clear_bodies}
        assigned = set()
        pending_used = set()
        visible = []
        for item, body, options in zip(observations, bodies, body_options):
            box = item['bbox']
            # Reserve bound identities even when their face appears later in the
            # detector output (or is turned away on this particular frame).
            unavailable = {ident for ident, tracks in owners.items()
                           if (tracks - {body} if body is not None
                               else (tracks - options) & current_tracks)}
            unavailable.update(ident for ident, track in reserved.items() if track != body)

            candidates = [
                (float(np.dot(item["embedding"], row["embedding"])), ident)
                for ident, row in self.records.items() if ident not in assigned
                and ident not in unavailable
                and row["embedding"].shape == item["embedding"].shape
            ]
            score, ident = max(candidates, default=(-1.0, None))
            appearance_match = score >= MATCH_THRESHOLD
            binding = self.body_faces.get(body)
            if binding and binding['id'] in self.records and binding['id'] not in assigned:
                # A continuously tracked body keeps its face number during turns.
                # Do not teach the identity from an uncertain/profile embedding.
                ident = binding['id']
                score = MATCH_THRESHOLD
                feature = self.records[ident]['embedding']
                appearance_match = (feature.shape == item['embedding'].shape
                                    and float(np.dot(item['embedding'], feature)) >= MATCH_THRESHOLD)
            if score < MATCH_THRESHOLD:
                # Webcam face samples arrive at least one second apart.
                # Recover only with both appearance and spatial agreement.
                box = item["bbox"]
                center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
                nearby = []
                for candidate_score, candidate_id in candidates:
                    record = self.records[candidate_id]
                    previous, last = record["last_bbox"], record["last_time"]
                    if previous is None or last is None or not 0 <= video_time - last <= 2.5:
                        continue
                    prior = ((previous[0] + previous[2]) / 2,
                             (previous[1] + previous[3]) / 2)
                    distance = float(np.hypot(center[0] - prior[0], center[1] - prior[1]))
                    if candidate_score >= 0.25 and distance <= 0.08 and overlap(box, previous) >= 0.35:
                        nearby.append((candidate_score - distance, candidate_id))
                if nearby:
                    _, ident = max(nearby)
                    score = MATCH_THRESHOLD
            # A pending body follows the actual track through movement/turns.
            # Without a track, require both spatial and appearance agreement.
            matches = []
            for key, pending in self.pending_faces.items():
                if key in pending_used:
                    continue
                prior_body = pending['body']
                if prior_body in clear_bodies and body != prior_body:
                    continue
                if body is not None and prior_body is not None and body != prior_body:
                    continue
                if body is None and prior_body in current_tracks and prior_body not in options:
                    continue
                same_body = body is not None and body == prior_body
                spatial = overlap(box, pending['bbox'])
                if same_body or (spatial >= .3
                                 and pending['embedding'].shape == item['embedding'].shape
                                 and float(np.dot(pending['embedding'], item['embedding'])) >= .25):
                    matches.append((same_body, spatial, key))
            pending_key = max(matches)[2] if matches else None
            if pending_key is not None:
                pending_used.add(pending_key)
            if score < MATCH_THRESHOLD:
                if people is not None:
                    if pending_key is None:
                        pending_key = 'pending:' + uuid.uuid4().hex
                        self.pending_faces[pending_key] = {'embedding': item['embedding'].copy(),
                            'bbox': box, 'last': video_time, 'count': 1, 'confidence': item['confidence'],
                            'body': body, 'body_last': video_time}
                        pending_used.add(pending_key)
                        visible.append({'id': None, 'number': None, 'bbox': box,
                                        'confidence': item['confidence'], 'pending': True})
                        continue
                    pending = self.pending_faces[pending_key]
                    pending.update(count=pending['count'] + int(video_time > pending['last']),
                                   last=video_time, bbox=box,
                                   confidence=min(pending['confidence'], item['confidence']))
                    if body is not None:
                        pending.update(body=body, body_last=video_time)
                    required = 2 if pending['confidence'] >= .85 else 3
                    if pending['count'] < required:
                        visible.append({'id': None, 'number': None, 'bbox': box,
                                        'confidence': item['confidence'], 'pending': True})
                        continue
                    self.pending_faces.pop(pending_key, None)
                ident = uuid.uuid4().hex
                ordinal = max((r["ordinal"] for r in self.records.values()), default=0) + 1
                filename = ident + ".jpg"
                folder = self.runtime / "faces"
                folder.mkdir(parents=True, exist_ok=True)
                (folder / filename).write_bytes(item["image"])
                self.db.execute(
                    "INSERT INTO faces(id,scope,kind,job_id,day,ordinal,first_seen,last_seen,"
                    "video_time,seen_count,confidence,embedding,image) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (ident, self.scope, self.kind, self.job_id, self.day, ordinal,
                     now(), now(), video_time, 1, item["confidence"],
                     sqlite3.Binary(item["embedding"].tobytes()), filename),
                )
                self.records[ident] = {"ordinal": ordinal,
                                       "embedding": item["embedding"].copy(), "seen_count": 1,
                                       "last_bbox": item["bbox"], "last_time": video_time}
            else:
                record = self.records[ident]
                weight = min(record["seen_count"], 20)
                averaged = ((record["embedding"] * weight + item["embedding"]) / (weight + 1)
                            if appearance_match else record['embedding'].copy())
                averaged /= max(float(np.linalg.norm(averaged)), 1e-8)
                record["embedding"] = averaged
                record["seen_count"] += 1
                record["last_bbox"] = item["bbox"]
                record["last_time"] = video_time
                self.db.execute(
                    "UPDATE faces SET last_seen=?,seen_count=?,embedding=? WHERE id=?",
                    (now(), record["seen_count"], sqlite3.Binary(averaged.tobytes()), ident),
                )
            assigned.add(ident)
            if pending_key is not None:
                self.pending_faces.pop(pending_key, None)
            if body is not None:
                # One identity has one current body owner; expired/missing tracks
                # can later reconnect through appearance matching.
                self.body_faces = {track: state for track, state in self.body_faces.items()
                                   if state['id'] != ident or track == body}
                self.body_faces[body] = {'id': ident, 'last': video_time}
                owners[ident] = {body}
            visible.append({"id": ident, "number": self.records[ident]["ordinal"],
                            "bbox": item["bbox"], "confidence": item["confidence"]})
        return {"visible": visible, "total": len(self.records), "day": self.day}


def draw_faces(image, faces):
    height, width = image.shape[:2]
    for face in faces:
        x1, y1, x2, y2 = face["bbox"]
        left, top = int(x1 * width), int(y1 * height)
        right, bottom = int(x2 * width), int(y2 * height)
        cv2.rectangle(image, (left, top), (right, bottom), (164, 228, 156), 2)
        label = 'FACE ...' if face.get('pending') else f"FACE {face['number']}"
        cv2.putText(image, label, (left, max(18, top-5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (164, 228, 156), 1, cv2.LINE_AA)
