import io
import json
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from PIL import Image
from local_engine import Studio
from web_app import make_server


def png():
    stream=io.BytesIO();Image.new('RGB',(16,12),(25,35,45)).save(stream,'PNG');return stream.getvalue()


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'studio';self.calls=[]
        def infer(model,image,c,progress):
            self.calls.append(model);progress(1,1,64)
            return image.resize((32,24)),{'device':c['device']}
        self.infer=infer;self.studio=Studio(self.root,infer)
        self.photo=self.studio.upload(png(),'Foto keluarga.png')
        self.config={'weights':{'A':100},'use_mask':True,'feather':0}
        self.regions=[{'polygon':[[0,0],[5,0],[5,5],[0,5]]}]

    def tearDown(self):self.temp.cleanup()

    def wait(self,jid,studio=None):
        studio=studio or self.studio;end=time.monotonic()+5
        while studio.active and time.monotonic()<end:time.sleep(.01)
        self.assertIsNone(studio.active)
        result=studio.status(jid);self.assertEqual(result['status'],'done',result.get('error'));return result

    def run_photo(self,two=False):
        return self.wait(self.studio.start({'upload':self.photo['id'],'configs':[self.config]+([{'weights':{'B':100},'use_mask':False}] if two else []),'regions':self.regions}))

    def delete(self,request,studio=None):
        studio=studio or self.studio;plan=studio.history_delete(request)
        return studio.history_delete({**request,'confirm':True,'signature':plan['signature']})

    def test_restart_edit_preserves_source_config_masks_and_cache(self):
        run=self.run_photo();fresh=Studio(self.root,self.infer)
        listing=fresh.history();self.assertEqual(listing['items'][0]['name'],'Foto keluarga.png')
        edit=fresh.history_edit({'upload':self.photo['id'],'run':run['id'],'result':'result_1.png'})
        self.assertEqual(edit['regions'],self.regions);self.assertEqual(edit['photo']['id'],self.photo['id'])
        self.assertEqual(edit['configs'][0]['weights']['A'],100)
        calls=len(self.calls)
        rerun=self.wait(fresh.start({'upload':edit['photo']['id'],'configs':edit['configs'],'regions':edit['regions']}),fresh)
        self.assertEqual(len(self.calls),calls);self.assertEqual(rerun['reused'],1)
        self.assertEqual(fresh.history()['result_count'],2)

    def test_legacy_upload_without_metadata_is_recovered(self):
        run=self.run_photo();(self.root/self.photo['id']/'upload.json').unlink()
        fresh=Studio(self.root,self.infer);self.assertEqual(fresh.history()['result_count'],1)
        edit=fresh.history_edit({'upload':self.photo['id'],'run':run['id']})
        self.assertEqual(edit['regions'],self.regions);self.assertTrue((self.root/self.photo['id']/'upload.json').exists())

    def test_delete_one_result_keeps_other_config_and_cache(self):
        run=self.run_photo(two=True)
        self.delete({'kind':'result','upload':self.photo['id'],'run':run['id'],'result':'result_1.png'})
        detail=self.studio.history_detail(self.photo['id']);self.assertEqual(detail['result_count'],1);self.assertEqual(len(detail['caches']),2)
        self.assertEqual(detail['runs'][0]['results'][0]['config']['weights']['B'],100)
        edit=self.studio.history_edit({'upload':self.photo['id'],'run':run['id'],'result':'result_2.png'})
        self.assertEqual(edit['configs'][0]['weights']['B'],100)
        self.delete({'kind':'result','upload':self.photo['id'],'run':run['id'],'result':'result_2.png'})
        self.assertFalse((self.root/self.photo['id']/run['id']).exists());self.assertTrue((self.root/self.photo['id']/'source.png').exists())

    def test_cache_delete_keeps_results_and_recomputes(self):
        run=self.run_photo();detail=self.studio.history_detail(self.photo['id']);key=detail['caches'][0]['key']
        self.delete({'kind':'cache','upload':self.photo['id'],'key':key})
        self.assertEqual(self.studio.history()['result_count'],1);self.assertEqual(self.studio.history()['cache_bytes'],0)
        rerun=self.run_photo();self.assertEqual(rerun['reused'],0);self.assertEqual(len(self.calls),2)

    def test_all_cache_and_all_history_preserve_presets_and_external_data(self):
        self.run_photo();self.studio.save_preset('Gaya saya',[self.config])
        unrelated=self.root/'research';unrelated.mkdir();(unrelated/'keep.txt').write_text('keep')
        external=Path(self.temp.name)/'source-original.png';external.write_bytes(png())
        self.delete({'kind':'all-cache'})
        self.assertEqual(self.studio.history()['cache_bytes'],0);self.assertEqual(self.studio.history()['result_count'],1)
        self.delete({'kind':'all'})
        self.assertEqual(self.studio.history()['items'],[]);self.assertEqual(self.studio.presets()[0]['name'],'Gaya saya')
        self.assertTrue(external.exists());self.assertTrue((unrelated/'keep.txt').exists())

    def test_preview_required_and_stale_confirmation_rejected(self):
        request={'kind':'upload','upload':self.photo['id']}
        with self.assertRaises(ValueError):self.studio.history_delete({**request,'confirm':True})
        plan=self.studio.history_delete(request);self.assertTrue((self.root/self.photo['id']).exists())
        (self.root/self.photo['id']/'new.txt').write_text('new')
        with self.assertRaises(ValueError):self.studio.history_delete({**request,'confirm':True,'signature':plan['signature']})
        self.assertTrue((self.root/self.photo['id']/'source.png').exists())

    def test_active_processing_blocks_delete_and_edit(self):
        self.studio.active='test-active'
        try:
            for kind in ('all','all-cache','upload'):
                with self.assertRaises(ValueError):self.studio.history_delete({'kind':kind,'upload':self.photo['id']})
            with self.assertRaises(ValueError):self.studio.history_edit({'upload':self.photo['id']})
        finally:self.studio.active=None

    def test_traversal_and_external_metadata_are_not_followed(self):
        for uid in ('../','../../models','C:/Users','f'*32+'/..'):
            with self.assertRaises(ValueError):self.studio.history_delete({'kind':'upload','upload':uid})
        with self.assertRaises(ValueError):self.studio.history_delete({'kind':'cache','upload':self.photo['id'],'key':'../../source'})
        run=self.run_photo();path=self.root/self.photo['id']/run['id']/'processing.json';data=json.loads(path.read_text());data['source']['source_path']='C:/outside.png';path.write_text(json.dumps(data))
        fresh=Studio(self.root,self.infer);edit=fresh.history_edit({'upload':self.photo['id'],'run':run['id']})
        self.assertEqual(edit['photo']['size'],[16,12])

    def test_failed_or_orphaned_run_can_be_deleted(self):
        run=self.root/self.photo['id']/('e'*32);run.mkdir();(run/'failure.json').write_text('{"error":"failed"}')
        detail=self.studio.history_detail(self.photo['id']);self.assertEqual(detail['runs'][0]['error'],'failed')
        self.delete({'kind':'run','upload':self.photo['id'],'run':'e'*32});self.assertFalse(run.exists())

    def test_history_http_auth_and_edit_after_restart(self):
        self.run_photo();server=make_server(0,Studio(self.root,self.infer));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with urllib.request.urlopen(base+'/api/history') as r:self.assertEqual(json.load(r)['result_count'],1)
            with urllib.request.urlopen(base+'/api/bootstrap') as r:token=json.load(r)['token']
            payload=json.dumps({'upload':self.photo['id']}).encode()
            bad=urllib.request.Request(base+'/api/history/edit',data=payload)
            with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(bad)
            self.assertEqual(e.exception.code,403)
            good=urllib.request.Request(base+'/api/history/edit',data=payload,headers={'X-Studio-Token':token})
            with urllib.request.urlopen(good) as r:self.assertEqual(json.load(r)['photo']['id'],self.photo['id'])
            bad=urllib.request.Request(base+'/api/history/delete',data=b'{"kind":"all"}')
            with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(bad)
            self.assertEqual(e.exception.code,403)
        finally:server.shutdown();server.server_close();thread.join()
