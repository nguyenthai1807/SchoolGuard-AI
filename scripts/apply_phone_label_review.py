"""Apply the recorded visual corrections only to the exact reviewed images/labels."""
import hashlib
import json
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT/'runtime/phone-training'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review', type=Path, default=ROOT/'docs/phone-body-test-review.json')
    args = parser.parse_args()
    review=json.loads(args.review.read_text(encoding='utf-8'))
    manifest=json.loads((DATA/'manifest.json').read_text())
    by_name={r['name']:r for r in manifest['items'] if r['split']=='test'}
    changes=[]
    for item in review['items']:
        label=DATA/'labels/test'/(item['name']+'.txt')
        image=DATA/'images/test'/(item['name']+'.jpg')
        if hashlib.sha256(image.read_bytes()).hexdigest()!=item['image_sha256']:
            raise RuntimeError('Image changed; needs new visual review: '+item['name'])
        if by_name[item['name']]['reviewed']:
            continue
        if hashlib.sha256(label.read_bytes()).hexdigest()!=item['proposed_labels_sha256']:
            raise RuntimeError('Labels changed; needs new visual review: '+item['name'])
        rows=label.read_text().splitlines()
        changes.append((label,'\n'.join(row for i,row in enumerate(rows) if i not in item['remove_rows']),item['name']))
    for label,content,name in changes:
        label.write_text(content,encoding='utf-8')
        by_name[name]['reviewed']=True
        by_name[name]['label_source']='teacher proposals corrected by recorded assistant visual review'
    manifest['review_notes']=review['notes']
    (DATA/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(f'Applied {len(changes)} reviewed test label files; already reviewed files preserved.')


if __name__=='__main__':
    main()
