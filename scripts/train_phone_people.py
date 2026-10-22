"""Train one candidate on scene-separated body/occlusion data, then compare.

The original production model is never overwritten. Evaluation records the
limitations of this small, partly pseudo-labelled development dataset.
"""
import argparse
import hashlib
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT/'runtime/phone-training'
os.environ['YOLO_CONFIG_DIR'] = str(ROOT/'runtime/ultralytics')
os.environ['OMP_NUM_THREADS'] = '4'
os.environ['MKL_NUM_THREADS'] = '4'


def main():
    import cv2
    import torch
    from ultralytics import YOLO, settings

    from scripts.evaluate_training import compare, metrics

    parser=argparse.ArgumentParser()
    parser.add_argument('--epochs',type=int,default=6)
    args=parser.parse_args()
    torch.set_num_threads(4);cv2.setNumThreads(2)
    settings.update({'sync':False})
    manifest=json.loads((DATA/'manifest.json').read_text())
    test=[r for r in manifest['items'] if r['split']=='test']
    if not all(r['reviewed'] for r in test):
        raise RuntimeError('Review and correct held-out person annotations before evaluation.')
    run=ROOT/'runtime/training-runs/phone-body-v2'
    if run.exists():
        raise RuntimeError('Existing run preserved; choose a new run name.')
    provenance={'source':manifest['source_folder'],'dataset_sha256':hashlib.sha256((DATA/'manifest.json').read_bytes()).hexdigest(),
                'seed':42,'epochs':args.epochs,'starting_model':'yolo11s.pt','device':'cpu',
                'train_images':sum(x['split']=='train' for x in manifest['items']),
                'val_images':9,'test_images':len(test),'scene_splits':manifest['splits'],
                'limitations':['Training and validation include teacher pseudo labels.',
                               'Only 9 test frames from 3 held-out outdoor scenes, reviewed by assistant.',
                               'Synthetic body crops/occlusions do not replace real indoor crowded video.',
                               'No guarantee of detecting every person or completely hidden people.']}
    (DATA/'training-status.json').write_text(json.dumps({'status':'training',**provenance},indent=2),encoding='utf-8')
    model=YOLO(str(ROOT/'models/yolo11s.pt'))
    model.train(data=str(DATA/'data.yaml'),epochs=args.epochs,imgsz=512,batch=4,device='cpu',workers=0,
                seed=42,deterministic=True,freeze=10,optimizer='AdamW',lr0=.0002,lrf=.1,warmup_epochs=1,
                patience=6,mosaic=.2,close_mosaic=2,mixup=0,degrees=3,translate=.1,scale=.3,
                fliplr=.5,cache=False,plots=False,project=str(run.parent),name=run.name,
                exist_ok=False,save=True,verbose=False,amp=False)
    run=Path(model.trainer.save_dir)
    (run/'provenance.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
    results=[]
    for name,weights in [('baseline',ROOT/'models/yolo11s.pt'),('candidate',run/'weights/best.pt')]:
        net=YOLO(str(weights))
        image=cv2.imread(str(DATA/'images/test'/(test[0]['name']+'.jpg')))
        net.predict(image,classes=[0],conf=.3,iou=.6,imgsz=960,device='cpu',verbose=False)
        details=[]
        for item in test:
            image=cv2.imread(str(DATA/'images/test'/(item['name']+'.jpg')))
            h,w=image.shape[:2];truth=[]
            for line in (DATA/'labels/test'/(item['name']+'.txt')).read_text().splitlines():
                cls,x,y,bw,bh=map(float,line.split())
                if cls==0: truth.append([(x-bw/2)*w,(y-bh/2)*h,(x+bw/2)*w,(y+bh/2)*h])
            t=time.perf_counter()
            prediction=net.predict(image,classes=[0],conf=.3,iou=.6,imgsz=960,device='cpu',verbose=False)[0]
            elapsed=(time.perf_counter()-t)*1000
            tp,fp,fn=compare(prediction.boxes.xyxy.tolist(),prediction.boxes.conf.tolist(),truth)
            details.append({'name':item['name'],'tp':tp,'fp':fp,'fn':fn,'latency_ms':elapsed,
                            'truth_count':len(truth),'predicted_count':len(prediction.boxes)})
        result={'name':name,'metrics':metrics(*(sum(d[k] for d in details) for k in ['tp','fp','fn'])),
                'count_mae':sum(abs(d['truth_count']-d['predicted_count']) for d in details)/len(details),
                'mean_latency_ms':sum(d['latency_ms'] for d in details)/len(details),'details':details}
        results.append(result);print(json.dumps(result),flush=True)
    baseline,candidate=results
    qualifies=(candidate['metrics']['f1']>=baseline['metrics']['f1']+.01
               and candidate['metrics']['precision']>=baseline['metrics']['precision']
               and candidate['metrics']['recall']>=baseline['metrics']['recall']
               and candidate['count_mae']<=baseline['count_mae']
               and candidate['mean_latency_ms']<=baseline['mean_latency_ms']*1.5)
    report={'status':'completed',**provenance,'results':results,'candidate_passed_gate':qualifies,
            'production_model':'yolo11s','candidate_path':str(run/'weights/best.pt'),
            'checkpoint_sha256':hashlib.sha256((run/'weights/best.pt').read_bytes()).hexdigest()}
    (DATA/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (DATA/'training-status.json').write_text(json.dumps({'status':'completed','candidate_passed_gate':qualifies},indent=2),encoding='utf-8')
    print('TRAINING_AND_EVALUATION_COMPLETED',flush=True)


if __name__=='__main__':
    main()
