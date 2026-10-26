"""Build isolated local preview. No credentials, private media, or auto-deployment."""
from pathlib import Path
import shutil
import json

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'runtime' / 'browser-lab'
FILES = ('index.html', 'browser.css', 'browser.js', 'detection.mjs', 'inference-worker.js', 'effort.mjs')
VENDOR = ('ort.wasm.min.mjs', 'ort-wasm-simd-threaded.mjs', 'ort-wasm-simd-threaded.wasm')
FREE_MODELS = ('yolov8n', 'yolov9t', 'yolov10n')


def build():
    dist = ROOT / 'tools/browser-runtime/node_modules/onnxruntime-web/dist'
    models = [ROOT / 'models' / f'{name}.onnx' for name in FREE_MODELS]
    required = [ROOT / 'browser-client' / f for f in FILES] + [dist / f for f in VENDOR] + models
    for path in required:
        if not path.is_file():
            raise RuntimeError(f'Missing prerequisite: {path.name}')
    for directory in ('vendor', 'models'):
        (OUTPUT / directory).mkdir(parents=True, exist_ok=True)
    legacy_model = OUTPUT / 'models' / 'person.onnx'
    if legacy_model.is_file():
        legacy_model.unlink()
    for name in FILES:
        shutil.copyfile(ROOT / 'browser-client' / name, OUTPUT / name)
    for name in VENDOR:
        shutil.copyfile(dist / name, OUTPUT / 'vendor' / name)
    for name, model in zip(FREE_MODELS, models):
        shutil.copyfile(model, OUTPUT / 'models' / f'{name}.onnx')
    expected = set(FILES) | {'vendor/' + f for f in VENDOR} | {'models/' + name + '.onnx' for name in FREE_MODELS}
    actual = {p.relative_to(OUTPUT).as_posix() for p in OUTPUT.rglob('*') if p.is_file()}
    if expected != actual:
        raise RuntimeError('Unexpected files in browser preview. Do not publish.')
    print(json.dumps({'files': len(actual), 'directory': str(OUTPUT), 'public_deployment': False}))


if __name__ == '__main__':
    build()
