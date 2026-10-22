"""Prepare scene-disjoint Drive samples and explicit body-only training crops.

Teacher labels are provisional. Review validation/test labels before evaluation;
this script never promotes a checkpoint or claims that pseudo labels are truth.
"""
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "runtime/phone-training"
SPLITS = {"train": [1, 2, 3, 5, 6, 10, 13], "val": [4, 8, 11], "test": [7, 9, 12]}


def crop_labels(labels, crop):
    left, top, right, bottom = crop
    result = []
    for cls, a, b, c, d in labels:
        x, y, r, t = max(a, left), max(b, top), min(c, right), min(d, bottom)
        if r-x >= 8 and t-y >= 8 and (r-x)*(t-y) >= .25*(c-a)*(d-b):
            result.append([cls, x-left, y-top, r-left, t-top])
    return result


def main():
    import torch
    import yaml
    from ultralytics import YOLO

    torch.set_num_threads(4)
    cv2.setNumThreads(2)
    if (DATA/'manifest.json').exists():
        raise SystemExit('Existing dataset preserved; use another dataset directory for a new revision.')
    model = YOLO(str(ROOT/'models/yolo11s.pt'))
    items = []
    def save(name, image, labels, split, scene, source, frame_index, augmentation=None):
        for kind in ['images', 'labels']:
            (DATA/kind/split).mkdir(parents=True, exist_ok=True)
        height, width = image.shape[:2]
        target = DATA/'images'/split/(name+'.jpg')
        cv2.imwrite(str(target), image, [cv2.IMWRITE_JPEG_QUALITY, 94])
        (DATA/'labels'/split/(name+'.txt')).write_text('\n'.join(
            f'{int(cls)} {(a+c)/2/width:.7f} {(b+d)/2/height:.7f} {(c-a)/width:.7f} {(d-b)/height:.7f}'
            for cls,a,b,c,d in labels), encoding='utf-8')
        items.append({'name':name,'split':split,'scene':scene,'source':source,'frame':frame_index,
                      'augmentation':augmentation,'label_source':'yolo11s-960-conf025-provisional',
                      'reviewed':False,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    for split, scenes in SPLITS.items():
        for scene in scenes:
            source = next((DATA/'videos').glob(f'{scene:02}_*.avi'))
            cap = cv2.VideoCapture(str(source))
            count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fractions = [.1,.25,.4,.55,.7,.85] if split=='train' else [.2,.5,.8]
            for index, fraction in enumerate(fractions):
                frame_index = min(count-1, round(count*fraction))
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
                ok, image = cap.read()
                if not ok: raise RuntimeError(f'Cannot read {source.name} frame {frame_index}')
                prediction = model.predict(image, conf=.25, iou=.6, imgsz=960, device='cpu', verbose=False)[0]
                labels = [[int(c),*map(float,box)] for c,box in zip(prediction.boxes.cls.tolist(),prediction.boxes.xyxy.tolist())]
                name = f'scene{scene:02}-{index}'
                save(name,image,labels,split,scene,source.name,frame_index)
                if split=='train':
                    people = [row for row in labels if row[0]==0 and row[4]-row[2]>70]
                    if people:
                        _,a,b,c,d = max(people,key=lambda r:(r[3]-r[1])*(r[4]-r[2]))
                        h,w = image.shape[:2]
                        crop = (max(0,int(a-.2*(c-a))),max(0,int(b+.22*(d-b))),min(w,int(c+.2*(c-a))),min(h,int(d+.05*(d-b))))
                        x,y,r,t = crop
                        save(name+'-body',image[y:t,x:r],crop_labels(labels,crop),split,scene,source.name,frame_index,'body-crop-head-outside')
                        occluded=image.copy()
                        x,y,r,t=int(a),int(b+.55*(d-b)),int(c),int(b+.8*(d-b))
                        occluded[y:t,x:r]=np.mean(image,axis=(0,1)).astype(np.uint8)
                        save(name+'-occluded',occluded,labels,split,scene,source.name,frame_index,'synthetic-lower-body-occlusion')
            cap.release()
            print(f'Prepared {split} scene {scene}',flush=True)
    (DATA/'data.yaml').write_text(yaml.safe_dump({'path':str(DATA),'train':'images/train','val':'images/val','test':'images/test','names':model.names}),encoding='utf-8')
    manifest={'source_folder':'https://drive.google.com/drive/folders/11GtmyFtbIyrSj8snptr4I5S5WxOFCTMt',
              'splits':SPLITS,'teacher_sha256':hashlib.sha256((ROOT/'models/yolo11s.pt').read_bytes()).hexdigest(),'items':items}
    (DATA/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    for split in ['val','test']:
        tiles=[]
        for item in [i for i in items if i['split']==split]:
            image=cv2.imread(str(DATA/'images'/split/(item['name']+'.jpg')))
            h,w=image.shape[:2]
            image=cv2.resize(image,(640,360))
            for n,line in enumerate((DATA/'labels'/split/(item['name']+'.txt')).read_text().splitlines()):
                cls,x,y,bw,bh=map(float,line.split())
                if cls!=0: continue
                x1,y1,x2,y2=int((x-bw/2)*640),int((y-bh/2)*360),int((x+bw/2)*640),int((y+bh/2)*360)
                cv2.rectangle(image,(x1,y1),(x2,y2),(0,255,255),1)
                cv2.putText(image,str(n),(x1,max(14,y1-2)),cv2.FONT_HERSHEY_SIMPLEX,.4,(0,0,255),1)
            cv2.putText(image,item['name'],(8,22),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,0,255),2)
            tiles.append(image)
        sheet=np.vstack([np.hstack(tiles[i:i+3]) for i in range(0,len(tiles),3)])
        cv2.imwrite(str(DATA/(split+'-review.jpg')),sheet)
    print(json.dumps({split:sum(i['split']==split for i in items) for split in SPLITS}),flush=True)


if __name__=='__main__':
    main()
