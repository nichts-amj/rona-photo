// Frontend knows only the Retouch service contract, never model names/adapters.
export class RetouchService {
  constructor(base='/api/retouch/'){this.token=null;this.base=base}
  async status(){const response=await fetch(this.base+'status');const data=await response.json();if(!response.ok)throw Error(data.error?.message||data.error);this.token=data.token;return data}
  async request(path,data,headers={}){
    if(!this.token)await this.status();
    const binary=data instanceof Blob;
    const response=await fetch(this.base+path,{method:'POST',headers:{'X-Studio-Token':this.token,'Content-Type':binary?'image/png':'application/json',...headers},body:binary?data:JSON.stringify(data)});
    const result=await response.json();if(!response.ok)throw Object.assign(Error(result.error?.message||result.error||'AI Retouch tidak tersedia.'),{code:result.error?.code});return result;
  }
  async upload(canvas,document){const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));if(!blob)throw Error('Foto tidak dapat dikirim ke service lokal.');return this.request('image',blob,document?{'X-Retouch-Document':document}:{})}
  async run(kind,data,onProgress,onJob){
    const {job}=await this.request(kind,data);onJob?.(job);
    for(;;){
      const response=await fetch(this.base+'status?job='+encodeURIComponent(job));const state=await response.json();
      if(!response.ok)throw Error(state.error?.message||'Status AI tidak tersedia.');onProgress?.(state);
      if(state.status==='done')return state.result;
      if(['failed','cancelled'].includes(state.status))throw Object.assign(Error(state.error?.message||'AI Retouch dibatalkan.'),{code:state.error?.code});
      await new Promise(resolve=>setTimeout(resolve,250));
    }
  }
  async release(document){if(document)await this.request('release',{document})}
  cancel(job){return job?this.request('cancel',{job}):Promise.resolve()}
}

export class SnapshotStore {
  constructor(){this.records=new Map();this.active=null;this.image=null}
  register(result,image){this.records.set(result.id,result);this.active=result.id;this.image=image}
  get(id){return this.active===id?this.image:null}
  async ensure(id){
    if(this.get(id))return this.image;
    const record=this.records.get(id);if(!record)throw Error('Snapshot AI tidak tersedia.');
    const image=new Image();image.src=record.url;await image.decode();this.active=id;this.image=image;return image;
  }
  clear(){this.records.clear();this.active=null;this.image=null}
}
