"""Additional held-out body-only stress test; derived exclusively from test scenes."""
import json
import time

import cv2
import torch
from ultralytics import YOLO

from scripts.evaluate_training import compare, metrics
from scripts.prepare_phone_training import DATA, ROOT, crop_labels


def main():
    torch.set_num_threads(4);cv2.setNumThreads(2)
    report=json.loads((DATA/'report.json').read_text())
    manifest=json.loads((DATA/'manifest.json').read_text())
    samples=[]
    for item in [x for x in manifest['items'] if x['split']=='test']:
        image=cv2.imread(str(DATA/'images/test'/(item['name']+'.jpg')))
        h,w=image.shape[:2];labels=[]
        for line in (DATA/'labels/test'/(item['name']+'.txt')).read_text().splitlines():
            cls,x,y,bw,bh=map(float,line.split())
            if cls==0: labels.append([0,(x-bw/2)*w,(y-bh/2)*h,(x+bw/2)*w,(y+bh/2)*h])
        people=[p for p in labels if p[4]-p[2]>=70]
        if not people: continue
        _,a,b,c,d=max(people,key=lambda p:(p[3]-p[1])*(p[4]-p[2]))
        crop=(max(0,int(a-.2*(c-a))),int(b+.25*(d-b)),min(w,int(c+.2*(c-a))),min(h,int(d)))
        x,y,r,t=crop
        # Upsize small body crops to a realistic input size for the stress test.
        sample=image[y:t,x:r]
        truth=[p[1:] for p in crop_labels(labels,crop)]
        samples.append((item['name'],sample,truth))
    results=[]
    for name,path in [('baseline',ROOT/'models/yolo11s.pt'),('candidate',report['candidate_path'])]:
        model=YOLO(str(path));details=[]
        for label,image,truth in samples:
            start=time.perf_counter()
            result=model.predict(image,classes=[0],conf=.3,iou=.6,imgsz=640,device='cpu',verbose=False)[0]
            tp,fp,fn=compare(result.boxes.xyxy.tolist(),result.boxes.conf.tolist(),truth)
            details.append({'name':label,'tp':tp,'fp':fp,'fn':fn,'ms':(time.perf_counter()-start)*1000})
        results.append({'name':name,'metrics':metrics(*(sum(d[k] for d in details) for k in ['tp','fp','fn'])),
                        'samples':len(details),'details':details})
    report['body_only_stress_test']={'note':'Synthetic head-excluding crops of held-out test frames, not real occlusion footage. Same threshold for both models.',
                                     'results':results}
    baseline,candidate=results
    report['candidate_passed_gate']=bool(report['candidate_passed_gate'] and
        candidate['metrics']['recall']>=baseline['metrics']['recall'] and
        candidate['metrics']['precision']>=baseline['metrics']['precision'])
    (DATA/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(results),flush=True)


if __name__=='__main__':
    main()
