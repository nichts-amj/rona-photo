export class RetouchLibrary {
  constructor(){this.token=null;this.id=null;this.parent=null;this.original=null;this.signature=null}
  reset(original,parent=null){this.id=null;this.parent=parent;this.original=original;this.signature=null}
  async request(path,data,headers={}){
    if(!this.token){const response=await fetch('/api/retouch/status');this.token=(await response.json()).token}
    const binary=data instanceof Blob;
    const response=await fetch('/api/library/'+path,{method:'POST',headers:{'X-Studio-Token':this.token,'Content-Type':binary?'application/octet-stream':'application/json',...headers},body:binary?data:JSON.stringify(data)});
    const result=await response.json();if(!response.ok)throw Error(result.error?.message||result.error||'Riwayat tidak dapat disimpan.');globalThis.RonaHistoryCache?.invalidate();return result;
  }
  async save({name,state,settings,tool,snapshots,result}){
    const signature=JSON.stringify(state);
    if(this.id&&signature===this.signature){
      const check=await fetch('/api/library/item/retouch/'+this.id);
      if(!check.ok)throw Error('Riwayat ini telah dihapus atau tidak tersedia. Export foto sebagai salinan baru.');
      return {saved:true,reused:true};
    }
    if(!this.original)throw Error('Salinan unggahan tidak tersedia untuk Riwayat.');
    if(!this.id){const source=await this.request('retouch/source',this.original,{'X-Filename':encodeURIComponent(name),...(this.parent?{'X-History-Parent':encodeURIComponent(JSON.stringify(this.parent))}:{})});this.id=source.id}
    const saved=await this.request('retouch/state',{id:this.id,state,settings,tool,snapshots});
    await this.request('retouch/result/'+this.id+'/'+saved.run,result);
    this.signature=signature;return {saved:true};
  }
  async open(ticket){
    const response=await fetch('/api/library/handoff/'+encodeURIComponent(ticket));const payload=await response.json();if(!response.ok)throw Error(payload.error);
    if(payload.target!=='retouch')throw Error('Sesi Edit tidak sesuai dengan Retouch.');
    const source=await fetch(payload.source);if(!source.ok)throw Error('Foto riwayat tidak tersedia.');
    const blob=await source.blob();return {...payload,blob};
  }
}
