"""New offline UI logic controls; not the previously completed Node baseline suite."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_offline_import_validation_and_late_image_load_protection():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable: browser UI logic control cannot execute")
    path = Path(__file__).resolve().parents[2] / "scripts/diagnostic_review_ui.js"
    program = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8');
const code=source.slice(0,source.indexOf('for(const c of ctx.cases)'));
assert(code.length>1000);
const row={neuron_id:'E05_N101',day:8,trace_manifest_sha256:'t',source_sha256:'s',display_sha256:'d'};
const images=[],calls=[];let clears=0;
const sandbox={REVIEW_DATA:{context:{workspace_sha256:'w',visits:[row],cases:[],days:[8]},pictures:{a:'a',b:'b'}},
  document:{getElementById:()=>({})},Image:class {constructor(){images.push(this);}}};
vm.createContext(sandbox);vm.runInContext(code,sandbox);
const blank=vm.runInContext('blank()',sandbox);
assert.strictEqual(sandbox.validateDocument(blank).observations[0].reviewer,'');
const copy=()=>JSON.parse(JSON.stringify(blank));
for(const mutate of [
 d=>d.observations.push(d.observations[0]),d=>d.source_channel='561',
 d=>d.accepted_ids=['E05_N101'],d=>d.observations[0].source_sha256='stale',
 d=>d.observations[0].same_cell_yes_no_uncertain='pass']) {
 const value=copy();mutate(value);assert.throws(()=>sandbox.validateDocument(value));
}
let value=copy();value.reviewer='SOFTWARE CONTROL';Object.assign(value.observations[0],{
 reviewer:'SOFTWARE CONTROL',reviewed_at:'2026-10-27T20:00:00Z',
 same_cell_yes_no_uncertain:'uncertain',ROI_ownership_clear_uncertain_contaminated:'clear',notes:'CONTROL uncertainty'});
sandbox.validateDocument(value);
value.observations[0].reviewer='someone else';assert.throws(()=>sandbox.validateDocument(value));
const canvas={dataset:{},width:768,height:864,getContext:()=>({clearRect(){clears++;},drawImage(...args){calls.push(args);}})};
sandbox.draw('a',canvas,0,384,432);sandbox.draw('b',canvas,4,384,432);
assert.strictEqual(calls.length,0);assert.strictEqual(clears,2,'clear stale images before load');
images[1].onload();images[0].onload();
assert.strictEqual(calls.length,1,'stale asynchronous image must not overwrite current visit');
assert.strictEqual(calls[0][1],384);assert.strictEqual(calls[0][2],432);
console.log('offline UI controls passed; no real annotations created');
"""
    result = subprocess.run(
        [node, "-e", program, str(path)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_all_108_synthetic_visits_save_reload_and_unsaved_navigation():
    """Full controller-state simulation; never opens or annotates real research files."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable")
    path = Path(__file__).resolve().parents[2] / "scripts/diagnostic_review_ui.js"
    program = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
async function main(){
 const days=[8,12,16,20,25,29,32,36,39],cases=[],visits=[],pictures={};
 for(const well of ['E05','F05','I05','J05','M05','N05']) for(const number of [101,102]){
  const nid=well+'_N'+number,c={neuron_id:nid,fixed_image:nid+'_488.png',search_image:nid+'_context.png',
    diagnostic_status:'CONTROL_ONLY',core_area_px:64,secondary_soma_pass_is_not_ownership:true};cases.push(c);
  pictures[c.fixed_image]='CONTROL:'+c.fixed_image;pictures[c.search_image]='CONTROL:'+c.search_image;
  for(const day of days)visits.push({neuron_id:nid,day,trace_manifest_sha256:nid+'trace',source_sha256:nid+day,
    display_sha256:nid+'display',automated_valid_488:day!==8,inherited_tracking_valid:day!==8,
    automated_failure_reasons:day===8?['SOFTWARE CONTROL FAILURE']:[],geometry:{}});
 }
 const elements={},images=[],downloads=[],frames={},events={};let confirmReply=true;
 function element(id){return elements[id]??=( {value:'',dataset:{},handlers:{},children:[],disabled:false,
  appendChild(o){this.children.push(o);if(!this.value)this.value=o.value;},
  addEventListener(name,fn){this.handlers[name]=fn;},click(){},
  getContext(){return {clearRect(){frames[id]=null;},drawImage(...args){frames[id]=args;}}},width:768,height:864});}
 const document={getElementById:element,createElement:()=>({value:'',click(){}})};
 const box={REVIEW_DATA:{context:{workspace_sha256:'CONTROL',cases,visits,days},pictures},document,
  Image:class{constructor(){images.push(this);}},Blob,URL:{createObjectURL(b){downloads.push(b);return 'blob:control';},revokeObjectURL(){}},
  setTimeout(fn){fn();},confirm(){return confirmReply;},window:{addEventListener(n,f){events[n]=f;}}};
 vm.createContext(box);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),box);
 const get=()=>vm.runInContext('review',box),active=()=>box.active();
 function flush(){for(const image of images)if(!image.done){image.done=true;image.onload();}}
 assert.strictEqual(element('save').disabled,true);images[0].done=true;images[0].onload();
 assert.strictEqual(element('save').disabled,true,'both images are required');flush();
 assert.strictEqual(element('save').disabled,false);
 for(const row of visits){element('neuron').value=row.neuron_id;element('day').value=String(row.day);box.show();
  assert.strictEqual(element('save').disabled,true);assert.strictEqual(frames.fixed,null);flush();
  const i=days.indexOf(row.day);assert.strictEqual(frames.fixed[1],(i%3)*384);assert.strictEqual(frames.fixed[2],Math.floor(i/3)*432);
  assert.strictEqual(frames.fixed[0].src,pictures[row.neuron_id+'_488.png']);assert.strictEqual(element('save').disabled,false);
 }
 element('neuron').value=cases[0].neuron_id;element('day').value='8';box.show();flush();
 assert(element('qc').textContent.includes('FAILED'));
 element('reviewer').value='SOFTWARE CONTROL ONLY';element('identity').value='uncertain';element('ownership').value='clear';
 box.save();assert(element('message').textContent.includes('Explain'));assert.strictEqual(get().observations[0].reviewer,'');
 element('notes').value='CONTROL uncertainty, not biological review';box.save();flush();
 assert.strictEqual(get().observations[0].same_cell_yes_no_uncertain,'uncertain');assert(element('reviewer').readOnly);
 assert(get().observations[0].reviewed_at.endsWith('Z'));assert.strictEqual(visits[0].automated_valid_488,false);
 const saved=JSON.parse(JSON.stringify(get()));element('download').onclick();
 assert.strictEqual(downloads.length,1);assert.strictEqual(JSON.parse(await downloads[0].text()).observations.length,108);
 element('identity').value='yes';element('identity').handlers.input();confirmReply=false;
 const previous=active().day;box.navigate(1);assert.strictEqual(active().day,previous);
 element('day').value='12';element('day').handlers.change();assert.strictEqual(element('day').value,'8');
 confirmReply=true;box.navigate(1);flush();assert.strictEqual(active().day,12);
 await element('load').onchange({target:{files:[{async text(){return JSON.stringify(saved);}}]}});flush();
 assert.strictEqual(get().observations[0].same_cell_yes_no_uncertain,'uncertain');
 const stale=JSON.parse(JSON.stringify(saved));stale.observations[0].source_sha256='stale';
 await element('load').onchange({target:{files:[{async text(){return JSON.stringify(stale);}}]}});
 assert(element('message').textContent.includes('Import blocked'));assert.strictEqual(get().observations[0].source_sha256,visits[0].source_sha256);
 let prevented=false;element('identity').handlers.input();events.beforeunload({preventDefault(){prevented=true;}});assert(prevented);
 console.log('108 synthetic visits, binding, loading guards, uncertainty, download/reload and unsaved-state controls passed');
}
main().catch(e=>{console.error(e);process.exit(1);});
"""
    result = subprocess.run(
        [node, "-e", program, str(path)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
