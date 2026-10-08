"""Default C workflow; source-bound manual regions, optional Swin2SR comparison."""
import json
import uuid
from pathlib import Path

import numpy as np

from pipeline.io import read_photo, save_png, sha256
from pipeline.fusion import make_alpha, fuse

from resource_paths import ROOT


def resolve_regions(source_hash, size, path=None):
    if path is not None:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if data['source_sha256'] != source_hash or data['source_size'] != list(size):
            raise ValueError('Masker tidak sesuai hash/ukuran foto sumber.')
        return data['config']
    prior = ROOT/'outputs/batch-20260929-hybrid4/experiment.json'
    if prior.exists():
        data = json.loads(prior.read_text(encoding='utf-8'))
        for row in data['entries']:
            if row['source']['source_sha256'] == source_hash:
                return row['fusion']['config']
    raise ValueError('C memerlukan masker manual untuk foto baru. Gunakan --regions JSON berisi source_sha256, source_size, dan config. Belum ada deteksi area otomatis.')


def run_hybrid(input_path, output_root, device='cuda', tile=128, overlap=32,
               regions=None, compare_swin2sr=False):
    from pipeline.upscale import SwinIRX2
    from pipeline.realesrgan import CompactRealESRGAN
    from pipeline.tiling import validate_tiles
    validate_tiles(tile, overlap)
    before, source = read_photo(input_path)
    config = resolve_regions(source['source_sha256'], before.size, regions)
    alpha, protected = make_alpha((before.width*2, before.height*2), config)
    folder = Path(output_root).resolve()/('hybrid_c_'+uuid.uuid4().hex)
    folder.mkdir(parents=True, exist_ok=False)
    engine = None
    try:
        save_png(before, folder/'input_normalized.png')
        engine = SwinIRX2(device)
        a_meta = engine.metadata()
        a, a_stats = engine.infer(before, tile, overlap)
        engine.close()
        engine = None
        save_png(a, folder/'A_swinir_x2.png')
        engine = CompactRealESRGAN(denoise=0.5, device=device)
        b_meta = engine.provenance
        b, b_stats = engine.infer(before)
        engine.close()
        engine = None
        save_png(b, folder/'B_realesrgan_x2.png')
        c = fuse(a, b, alpha)
        if not np.array_equal(np.asarray(c)[protected], np.asarray(a)[protected]):
            raise RuntimeError('Area terlindungi berubah.')
        save_png(c, folder/'result_C_x2.png')
        np.save(folder/'candidate_weight_float32.npy', alpha, allow_pickle=False)
        manifest = {'status':'success','mode':'hybrid-c','default_result':'result_C_x2.png',
                    'source':source,'output_size':list(c.size),'config':config,
                    'automatic_region_detection':False,'blend':'(1-alpha) A + alpha B in encoded sRGB',
                    'models':{'A':a_meta,'B':b_meta},'inference':{'A':a_stats,'B':b_stats},
                    'protected_core_exact_A':True,'comparison_swin2sr':compare_swin2sr}
        if compare_swin2sr:
            from pipeline.swin2sr import Swin2SRCompressed
            engine = Swin2SRCompressed(device)
            s, stats = engine.infer(before)
            engine.close()
            engine = None
            save_png(s, folder/'S_swin2sr_comparison_x2.png')
            manifest['inference']['S'] = stats
        if sha256(input_path) != source['source_sha256']:
            raise RuntimeError('Sumber berubah saat pemrosesan.')
        manifest['artifacts'] = {p.name:sha256(p) for p in folder.iterdir() if p.is_file()}
        (folder/'processing.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
    except Exception as error:
        (folder/'failure.json').write_text(json.dumps({'status':'failed','error':str(error)}),encoding='utf-8')
        raise
    finally:
        if engine is not None:
            engine.close()
    return folder
