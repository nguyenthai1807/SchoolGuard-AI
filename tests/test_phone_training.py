import json

from schoolguard.app import create_app
from schoolguard.config import Settings
from scripts.prepare_phone_training import crop_labels
from scripts.fetch_phone_training import fetch_local


def test_body_crop_keeps_visible_torso_and_rejects_outside_labels():
    labels=[[0,20,10,60,100],[2,100,50,150,90],[0,0,0,10,10]]
    assert crop_labels(labels,(15,35,70,100))==[[0,5,0,45,65]]


def test_local_phone_clips_are_selected_without_downloading_or_overwriting(tmp_path):
    source = tmp_path/'source'
    source.mkdir()
    for scene in range(1, 14):
        (source/f'{scene:02}_001.avi').write_bytes(f'video-{scene}'.encode())
    (source/'01_002.avi').write_bytes(b'not selected')
    destination = tmp_path/'phone-training'
    first = fetch_local(source, destination)
    assert len(first) == 13
    assert first[0]['name'] == '01_001.avi'
    assert first[0]['sha256']
    assert (destination/'videos/01_001.avi').read_bytes() == b'video-1'
    assert fetch_local(source, destination) == first
    (destination/'videos/01_001.avi').write_bytes(b'changed')
    import pytest
    with pytest.raises(RuntimeError, match='preserved'):
        fetch_local(source, destination)


def test_training_status_separates_new_run_from_old_report(tmp_path):
    settings=Settings(runtime=tmp_path/'runtime',models=tmp_path/'models',data_root=tmp_path/'data',start_worker=False)
    app=create_app(settings)
    folder=settings.runtime/'phone-training';folder.mkdir()
    (folder/'training-status.json').write_text(json.dumps({'status':'training','epochs':6,'train_images':114}))
    run=settings.runtime/'training-runs/phone-body-v2';run.mkdir(parents=True)
    (run/'results.csv').write_text('epoch,time\n1,90\n2,180\n3,\n')
    endpoint=next(r.endpoint for r in app.routes if r.path=='/api/training')
    result=endpoint({'id':1,'role':'admin'})
    assert result['phone_training']['epochs_completed']==2
    assert result['phone_training']['status']=='training'
    assert result['runs']==[]
    (folder/'report.json').write_text(json.dumps({'status':'completed','candidate_passed_gate':False,'results':[]}))
    assert endpoint({'id':1,'role':'admin'})['phone_training']['status']=='completed'
    (folder/'report.json').write_text('{')
    assert endpoint({'id':1,'role':'admin'})['phone_training']['status']=='updating'
