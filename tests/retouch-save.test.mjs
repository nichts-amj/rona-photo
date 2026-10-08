import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {AIRetouchController} from '../web/retouch/ai-controller.mjs';
function fixture(){
 const nodes=new Map();globalThis.document={getElementById(id){if(!nodes.has(id))nodes.set(id,{dataset:{},classList:{toggle(){}},setAttribute(){},value:0});return nodes.get(id)}};globalThis.window={addEventListener(){}};
 let scans=0,previews=0;
 const c=new AIRetouchController({hasImage:()=>true,signature:()=> 'photo',flush(){},restore(){},lock(){},notice(){}});c.visible=true;c.analysis={faces:[{}]};c.sourceSignature='photo';c.service.run=async kind=>{if(kind==='analyze')scans++;else previews++;return {faces:[],models:{}}};c.service.cancel=async()=>({});
 return{c,nodes,counts:()=>({scans,previews})};
}
test('Save pause blocks queued analysis, slider previews, Apply and menu navigation',async()=>{
 const {c,nodes,counts}=fixture();c.pauseAfterSave();c.queueAnalysis();c.schedule(0);await c.analyze();await c.preview();await c.apply();c.show(false);c.show(true);await new Promise(r=>setTimeout(r,10));
 assert.deepEqual(counts(),{scans:0,previews:0});assert.equal(nodes.get('ai-controls').disabled,true);assert.equal(nodes.get('ai-apply').disabled,true);
});
test('explicit Retouch reactivation starts a new preview, with no Apply until requested',async()=>{
 const {c,counts}=fixture();c.pauseAfterSave();let applied=0,started=0;c.hooks.apply=()=>applied++;c.preview=async()=>started++;c.resumeAfterSave();c.show(true);await new Promise(r=>setTimeout(r,10));assert.equal(started,1);assert.equal(applied,0);assert.equal(c.pausedAfterSave,false);
});
test('replacement photo clears the saved pause and automatic scanning remains available',async()=>{
 const {c}=fixture();c.pauseAfterSave();await c.resetDocument();assert.equal(c.pausedAfterSave,false);let scans=0;c.analyze=async()=>scans++;c.photoLoaded();await new Promise(r=>setTimeout(r,10));assert.equal(scans,1);
});
test('Save uses the Export style, no header save-status text, and no post-save analysis trigger',()=>{
 const html=fs.readFileSync(new URL('../web/retouch.html',import.meta.url),'utf8'),editor=fs.readFileSync(new URL('../web/retouch/editor.mjs',import.meta.url),'utf8');assert(html.includes('id="save-history" class="primary" disabled>Save</button>'));assert(!html.includes('id="history-status"'));assert(!editor.includes('history-status'));
 const save=editor.slice(editor.indexOf('async function saveWorkspace'),editor.indexOf('async function decodeFile'));assert(!save.includes('queueAnalysis()'));assert(save.includes('retouch.pauseAfterSave();aiEdit.cancel();flushAdjustment()'));
});
