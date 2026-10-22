"""Download one clip per scene from the user's public Drive source."""
import dataclasses
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import gdown

ROOT = Path(__file__).resolve().parents[1]/'runtime/phone-training'
SOURCE = 'https://drive.google.com/drive/folders/11GtmyFtbIyrSj8snptr4I5S5WxOFCTMt'
VIDEOS = 'https://drive.google.com/drive/folders/1KedC5T6snaDsPcc--n0jtgDsT13R7kus'


def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    (ROOT/'videos').mkdir(exist_ok=True)
    index=gdown.download_folder(VIDEOS,skip_download=True,quiet=True,use_cookies=False,timeout=30)
    rows=[dataclasses.asdict(item) for item in index]
    selected=[]
    for scene in range(1,14):
        candidates=[r for r in rows if re.fullmatch(rf'{scene:02}_\d{{3}}\.avi',Path(r['path']).name)]
        if not candidates: raise RuntimeError(f'Missing scene {scene}')
        selected.append(min(candidates,key=lambda r:r['path']))
    def fetch(row):
        name=Path(row['path']).name;dest=ROOT/'videos'/name
        if not dest.exists():
            temporary=dest.with_suffix('.download')
            gdown.download(id=row['id'],output=str(temporary),quiet=True,use_cookies=False,timeout=60)
            temporary.replace(dest)
        result={'name':name,'drive_id':row['id'],'bytes':dest.stat().st_size,
                'sha256':hashlib.sha256(dest.read_bytes()).hexdigest()}
        print(name,result['bytes'],flush=True)
        return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        sources=list(pool.map(fetch,selected))
    (ROOT/'sources.json').write_text(json.dumps({'folder':SOURCE,'items':sources},indent=2),encoding='utf-8')
    (ROOT/'drive-index.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')


if __name__=='__main__':
    main()
