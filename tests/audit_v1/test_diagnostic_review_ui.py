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
