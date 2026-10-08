import io
import json
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from PIL import Image
from local_engine import Studio
from unified_history import SharedHistory
from web_app import make_server


def png(color=(40,80,120),alpha=255):
    stream=io.BytesIO();Image.new('RGBA',(16,12),(*color,alpha)).save(stream,'PNG');return stream.getvalue()


class SharedHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'studio'
        self.studio=Studio(self.root,lambda model,image,config,progress:(image.resize((32,24)),{'device':'cpu'}))
        self.service=SimpleNamespace(active=None,result=lambda doc,name:png((100,110,120)))
        self.history=SharedHistory(self.studio,self.service,self.service)

    def tearDown(self):self.temp.cleanup()

    def save(self,state=None,snapshots=None,result=None):
        uid=self.history.source(png(),'keluarga.png')['id']
        project=self.history.state({'id':uid,'state':state or {'operations':[],'adjust':{},'filter':'none'},'snapshots':snapshots or [],'settings':{'retouch':{'model':'gfpgan','strength':70}}})
        self.history.result(uid,project['run'],result or png((100,110,120)))
        return uid,project['run']

    def upscale(self):
        photo=self.studio.upload(png(),'upscale.png')
        job=self.studio.start({'upload':photo['id'],'configs':[{'weights':{'A':100},'use_mask':False}], 'regions':[]})
        deadline=time.monotonic()+5
        while self.studio.active and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(self.studio.status(job)['status'],'done')
        return photo['id'],job

    def test_both_modules_are_listed_with_existing_history_unchanged(self):
        old,_=self.upscale();uid,_=self.save()
        listing=self.history.listing();self.assertEqual({i['module'] for i in listing['items']},{'retouch','upscale'})
        self.assertEqual(listing['result_count'],2)
        self.assertEqual(self.studio.history()['items'][0]['id'],old)
        self.assertEqual(self.studio.history()['result_count'],1)

    def test_restart_restores_recipe_parameters_and_ai_snapshots(self):
        sid='a'*32;state={'operations':[{'type':'retouch','id':sid,'width':16,'height':12,'settings':{'strokes':[{'x':.2,'y':.4,'r':.01}]}}]}
        uid,rid=self.save(state,[{'id':sid,'url':'/api/retouch/result/'+'b'*32+'/result-'+sid+'.png'}])
        fresh=SharedHistory(Studio(self.root),self.service,self.service)
        opened=fresh.edit({'module':'retouch','id':uid,'run':rid,'target':'retouch'})
        ticket=opened['url'].split('=')[1];payload=fresh.tickets[ticket]['data']
        self.assertEqual(payload['project']['state'],state);self.assertEqual(payload['project']['settings']['retouch']['model'],'gfpgan')
        self.assertEqual(fresh.asset(payload['project']['snapshots'][0]['url']),png((100,110,120)))
        # Saved assets remain usable even after transient Retouch session release.
        self.service.result=lambda *a:(_ for _ in ()).throw(ValueError('temporary session closed'))
        copied=fresh.state({'id':uid,'state':state,'snapshots':payload['project']['snapshots']})
        fresh.result(uid,copied['run'],png());self.assertEqual(fresh.detail('retouch',uid)['result_count'],2)

    def test_cross_module_edit_and_native_upscale_settings(self):
        old,run=self.upscale();uid,rid=self.save()
        opened=self.history.edit({'module':'upscale','id':old,'run':run,'target':'retouch'})
        payload=self.history.tickets[opened['url'].split('=')[1]]['data']
        self.assertTrue(payload['source'].startswith('/files/'));self.assertNotIn('project',payload)
        opened=self.history.edit({'module':'retouch','id':uid,'run':rid,'target':'upscale'})
        payload=self.history.tickets[opened['url'].split('=')[1]]['data']
        self.assertIn(payload['upscale']['photo']['id'],self.studio.uploads)
        native=self.history.edit({'module':'upscale','id':old,'run':run,'target':'upscale'})
        payload=self.history.tickets[native['url'].split('=')[1]]['data']
        self.assertEqual(payload['upscale']['configs'][0]['weights']['A'],100)

    def test_transparent_result_is_preserved_and_preparation_is_opt_in(self):
        raw=png(alpha=180);uid,rid=self.save(result=raw)
        request={'module':'retouch','id':uid,'run':rid,'target':'upscale'}
        self.assertTrue(self.history.edit(request)['needs_prepare'])
        self.history.edit({**request,'prepare':True})
        self.assertEqual(self.history.file(uid,rid+'/result.png'),raw)
        self.assertEqual(len(self.studio.uploads),1)

    def test_33_mb_transfer_is_accepted_and_keeps_source(self):
        raw=png()+b'\0'*(33*1024*1024);uid,rid=self.save(result=raw)
        request={'module':'retouch','id':uid,'run':rid,'target':'upscale'}
        self.assertIn('/upscale?edit=',self.history.edit(request)['url'])
        self.assertEqual(len(self.studio.uploads),1)
        self.assertEqual(self.history.file(uid,rid+'/result.png'),raw)

    def test_individual_and_all_deletion_are_scoped_and_require_fresh_confirmation(self):
        uid,rid=self.save();old,_=self.upscale();outside=Path(self.temp.name)/'keep.txt';outside.write_text('keep')
        request={'kind':'result','module':'retouch','id':uid,'run':rid}
        plan=self.history.delete(request)
        with self.assertRaises(ValueError):self.history.delete({**request,'confirm':True,'signature':'stale'})
        self.history.delete({**request,'confirm':True,'signature':plan['signature']})
        self.assertEqual(self.history.detail('retouch',uid)['result_count'],0)
        plan=self.history.delete({'kind':'all'})
        self.history.delete({'kind':'all','confirm':True,'signature':plan['signature']})
        self.assertEqual(self.history.listing()['items'],[]);self.assertEqual(outside.read_text(),'keep')

    def test_shared_snapshots_are_stored_once_and_released_only_after_last_reference(self):
        sid='e'*32;state={'operations':[{'type':'retouch','id':sid}]}
        uid,rid=self.save(state,[{'id':sid,'url':'/api/retouch/result/'+'f'*32+'/result-'+sid+'.png'}])
        snapshot={'id':sid,'url':self.history.url(uid,'assets/snapshot-'+sid+'.png')}
        second=self.history.state({'id':uid,'state':state,'snapshots':[snapshot]});self.history.result(uid,second['run'],png())
        self.assertEqual(len(list((self.history.root/uid).rglob('snapshot-*.png'))),1)
        for run in [rid,second['run']]:
            request={'kind':'result','module':'retouch','id':uid,'run':run};plan=self.history.delete(request)
            self.history.delete({**request,'confirm':True,'signature':plan['signature']})
            if run==rid:self.assertTrue((self.history.root/uid/'assets'/('snapshot-'+sid+'.png')).exists())
        self.assertFalse((self.history.root/uid/'assets'/('snapshot-'+sid+'.png')).exists())

    def test_cache_cleanup_preserves_retouch_edit_assets(self):
        old,_=self.upscale();sid='c'*32
        uid,rid=self.save({'operations':[{'type':'retouch','id':sid}]},[{'id':sid,'url':'/api/ai-edit/result/'+'d'*32+'/result-'+sid+'.png'}])
        request={'kind':'cache'};plan=self.history.delete(request)
        self.assertGreater(plan['bytes'],0)
        self.history.delete({**request,'confirm':True,'signature':plan['signature']})
        self.assertEqual(self.history.detail('upscale',old)['cache_bytes'],0)
        self.assertEqual(self.history.file(uid,'assets/snapshot-'+sid+'.png'),png((100,110,120)))
        self.assertEqual(self.history.detail('retouch',uid)['result_count'],1)

    def test_rejects_traversal_external_assets_incomplete_snapshots_and_busy_deletion(self):
        uid,_=self.save()
        for name in ['../../keep.txt','photo.json','../original.png']:
            with self.assertRaises(ValueError):self.history.file(uid,name)
        for url in ['https://example.com/photo.png','/files/arbitrary.png','/api/retouch/result/'+'a'*32+'/preview-'+'b'*32+'.png']:
            with self.assertRaises(ValueError):self.history.asset(url)
        with self.assertRaises(ValueError):self.history.state({'id':uid,'state':{'operations':[{'type':'retouch','id':'a'*32}]}})
        self.service.active='working'
        with self.assertRaises(ValueError):self.history.delete({'kind':'all'})
        with self.assertRaises(ValueError):self.history.edit({'module':'retouch','id':uid,'target':'retouch'})

    def test_http_routes_csrf_save_and_handoff(self):
        server=make_server(0,self.studio);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        def post(path,data,token=None,origin=None):
            headers={'X-Studio-Token':token or '', 'Content-Type':'application/octet-stream' if isinstance(data,bytes) else 'application/json'}
            if origin:headers['Origin']=origin
            request=urllib.request.Request(base+path,data=data if isinstance(data,bytes) else json.dumps(data).encode(),headers=headers)
            with urllib.request.urlopen(request) as response:return json.load(response)
        try:
            with urllib.request.urlopen(base+'/api/retouch/status') as response:token=json.load(response)['token']
            with self.assertRaises(urllib.error.HTTPError):post('/api/library/retouch/source',png())
            with self.assertRaises(urllib.error.HTTPError):post('/api/library/retouch/source',png(),token,'https://foreign.example')
            photo=post('/api/library/retouch/source',png(),token)
            run=post('/api/library/retouch/state',{'id':photo['id'],'state':{'operations':[]}},token)
            post('/api/library/retouch/result/'+photo['id']+'/'+run['run'],png(),token)
            edited=post('/api/library/edit',{'module':'retouch','id':photo['id'],'target':'retouch'},token)
            ticket=edited['url'].split('=')[1]
            with urllib.request.urlopen(base+'/api/library/handoff/'+ticket) as response:self.assertIn('project',json.load(response))
            with urllib.request.urlopen(base+'/history') as response:self.assertIn('Riwayat foto',response.read().decode())
            with urllib.request.urlopen(base+'/api/library/list') as response:self.assertEqual(json.load(response)['result_count'],1)
        finally:server.shutdown();server.server_close();thread.join(2)


if __name__=='__main__':unittest.main()
