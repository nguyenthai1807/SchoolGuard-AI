"""Download one clip per scene from the user's public Drive source."""
import dataclasses
import argparse
import hashlib
import json
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]/'runtime/phone-training'
SOURCE = 'https://drive.google.com/drive/folders/11GtmyFtbIyrSj8snptr4I5S5WxOFCTMt'
VIDEOS = 'https://drive.google.com/drive/folders/1KedC5T6snaDsPcc--n0jtgDsT13R7kus'


def fetch_local(video_root, destination=ROOT):
    video_root = Path(video_root).resolve()
    if not video_root.is_dir():
        raise RuntimeError(f'Video folder not found: {video_root}')
    destination.mkdir(parents=True, exist_ok=True)
    videos = destination/'videos'
    videos.mkdir(exist_ok=True)
    sources = []
    for scene in range(1, 14):
        candidates = sorted(video_root.glob(f'{scene:02}_*.avi'))
        if not candidates:
            raise RuntimeError(f'Missing scene {scene} in {video_root}')
        source = candidates[0]
        target = videos/source.name
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != source_hash:
                raise RuntimeError(f'Existing video differs; preserved: {target}')
        else:
            temporary = target.with_suffix('.download')
            if temporary.exists():
                raise RuntimeError(f'Incomplete copy must be inspected first: {temporary}')
            shutil.copy2(source, temporary)
            temporary.replace(target)
        sources.append({'name': source.name, 'source_path': str(source),
                        'bytes': target.stat().st_size, 'sha256': source_hash})
        print(source.name, target.stat().st_size, flush=True)
    (destination/'sources.json').write_text(
        json.dumps({'folder': str(video_root), 'items': sources}, indent=2), encoding='utf-8'
    )
    return sources


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--local-video-root', type=Path,
                        help='Use existing AVI clips instead of downloading from Drive')
    args = parser.parse_args()
    if args.local_video_root:
        fetch_local(args.local_video_root)
        return
    import gdown
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
