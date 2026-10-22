from types import SimpleNamespace

import cv2
import numpy as np

from schoolguard.detector import PersonDetector
from schoolguard.live import LiveAnalyzer
from schoolguard.schemas import JobRequest


def test_body_counts_without_any_face_model():
    # Sideways/occluded faces are deliberately absent; these are body detections.
    boxes = [{'class_id':cls, 'track_id':i, 'confidence':.8,
              'bbox':[i*.25,.2,i*.25+.2,.9]} for i,cls in enumerate([0,0,2])]
    analyzer = LiveAnalyzer(JobRequest(source_id='live'), lambda _frame: boxes)
    result = analyzer.update(cv2.imencode('.jpg',np.zeros((240,320,3),np.uint8))[1].tobytes())
    assert result['people']==2 and result['objects']==1
    assert result['faces']==[]


def test_partial_body_needs_prior_confirmation_and_real_current_detection(monkeypatch):
    class Values:
        def __init__(self, values): self.values=values
        def int(self): return self
        def tolist(self): return self.values
    class Model:
        def __init__(self):
            self.names={0:'person',2:'car'}
            self.rows=[]
        def track(self, *_args, **_kwargs):
            boxes=SimpleNamespace(id=Values([r[0] for r in self.rows]),
                                  cls=Values([r[1] for r in self.rows]),conf=Values([r[2] for r in self.rows]),
                                  xyxyn=Values([[.1,.1,.4,.8] for r in self.rows]))
            return [SimpleNamespace(boxes=boxes,keypoints=None)]
    detector=object.__new__(PersonDetector)
    detector.model=Model();detector.config=JobRequest(source_id='live',confidence=.3)
    detector.classes=[0,2];detector.device='cpu';detector.confirmed_people={}
    clock=[0.]
    monkeypatch.setattr('schoolguard.detector.time.monotonic',lambda:clock[0])
    frame=np.zeros((240,320,3),np.uint8)
    detector.model.rows=[(1,0,.18),(2,2,.18)]
    assert detector(frame)==[]  # weak new detections never become confirmed people
    detector.model.rows=[(1,0,.8),(2,2,.8)]
    assert len(detector(frame))==2
    clock[0]=.5;detector.model.rows=[(1,0,.18),(2,2,.18)]
    assert [r['class_id'] for r in detector(frame)]==[0]
    detector.model.rows=[]
    assert detector(frame)==[]  # no invented box/count behind total occlusion
    clock[0]=4.;detector.model.rows=[(1,0,.18)]
    assert detector(frame)==[]
    detector.reset_tracking()
    assert detector.confirmed_people=={}
