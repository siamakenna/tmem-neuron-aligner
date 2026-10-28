/* Offline human review only: no network, auto-approval, localStorage or source writes. */
'use strict';
const ctx = REVIEW_DATA.context;
const fields = ['neuron_id','day','trace_manifest_sha256','reviewer','same_cell_yes_no_uncertain',
  'ROI_ownership_clear_uncertain_contaminated','notes','reviewed_at','source_sha256',
  'display_sha256','workspace_sha256','source_channel'];
const idStates = ['', 'yes', 'no', 'uncertain'];
const roiStates = ['', 'clear', 'uncertain', 'contaminated'];
const $ = id => document.getElementById(id);
const key = r => r.neuron_id + ':' + r.day;
const expected = new Map(ctx.visits.map(r => [key(r), r]));
const blank = () => ({schema_version:'tmem.diagnostic_review.v1', workspace_sha256:ctx.workspace_sha256,
  source_channel:'488_only', reviewer:'', observations:ctx.visits.map(r => ({
    neuron_id:r.neuron_id, day:r.day, trace_manifest_sha256:r.trace_manifest_sha256,
    source_sha256:r.source_sha256, display_sha256:r.display_sha256,
    workspace_sha256:ctx.workspace_sha256, source_channel:'488_only', reviewer:'',
    reviewed_at:'', same_cell_yes_no_uncertain:'', ROI_ownership_clear_uncertain_contaminated:'', notes:''}))});
let review = blank(), dirty = false, draftDirty = false, shownKey = null;
function validateDocument(value) {
  if (!value || Object.keys(value).sort().join('|') !== ['schema_version','workspace_sha256','source_channel','reviewer','observations'].sort().join('|'))
    throw Error('Unknown or missing document fields; no acceptance/QC/561 overrides are allowed.');
  if (!value || value.schema_version !== 'tmem.diagnostic_review.v1' ||
      value.workspace_sha256 !== ctx.workspace_sha256 || value.source_channel !== '488_only' ||
      !Array.isArray(value.observations) || value.observations.length !== expected.size ||
      typeof value.reviewer !== 'string' || value.reviewer !== value.reviewer.trim()) throw Error('Wrong schema, source channel, reviewer or stale workspace.');
  const seen = new Set();
  for (const r of value.observations) {
    const e = expected.get(key(r));
    if (!e || seen.has(key(r)) || Object.keys(r).sort().join('|') !== [...fields].sort().join('|') ||
        !Number.isInteger(r.day)) throw Error('Unknown, duplicate or malformed observation.');
    seen.add(key(r));
    for (const name of ['trace_manifest_sha256','source_sha256','display_sha256'])
      if (r[name] !== e[name]) throw Error('Evidence fingerprint is stale.');
    if (r.workspace_sha256 !== ctx.workspace_sha256 || r.source_channel !== '488_only' ||
        !idStates.includes(r.same_cell_yes_no_uncertain) || !roiStates.includes(r.ROI_ownership_clear_uncertain_contaminated) ||
        typeof r.notes !== 'string') throw Error('Invalid category or non-488 source.');
    const annotated = !!(r.same_cell_yes_no_uncertain || r.ROI_ownership_clear_uncertain_contaminated || r.notes);
    if (annotated && (!value.reviewer || r.reviewer !== value.reviewer || typeof r.reviewed_at !== 'string' ||
        !/(Z|[+-]\d\d:\d\d)$/.test(r.reviewed_at) || Number.isNaN(Date.parse(r.reviewed_at))))
      throw Error('Missing/inconsistent reviewer or timezone-aware timestamp.');
    if (!annotated && (r.reviewer || r.reviewed_at)) throw Error('Attribution without an annotation.');
    if ((['no','uncertain'].includes(r.same_cell_yes_no_uncertain) ||
         ['uncertain','contaminated'].includes(r.ROI_ownership_clear_uncertain_contaminated)) && !r.notes.trim())
      throw Error('Explain negative or uncertain decisions in notes.');
  }
  return value;
}
function active() { return review.observations.find(r => r.neuron_id === $('neuron').value && r.day === Number($('day').value)); }
function complete(r) {return !!(r.same_cell_yes_no_uncertain && r.ROI_ownership_clear_uncertain_contaminated);}
function displaysReady() {
  const r=active(); if(!r) return false;
  const c=ctx.cases.find(c=>c.neuron_id===r.neuron_id); if(!c) return false;
  const i=ctx.days.indexOf(r.day);
  return $('fixed').dataset.loaded===c.fixed_image+':'+i && $('search').dataset.loaded===c.search_image+':'+i;
}
function updateSaveAvailability() { $('save').disabled=!displaysReady(); }
function progress() {
  $('reviewer').readOnly=review.observations.some(r=>r.reviewed_at);
  const per = ctx.cases.map(c => c.neuron_id + ' ' + review.observations.filter(r => r.neuron_id===c.neuron_id && complete(r)).length + '/9');
  const unresolved = review.observations.filter(r => complete(r) && (r.same_cell_yes_no_uncertain !== 'yes' || r.ROI_ownership_clear_uncertain_contaminated !== 'clear')).length;
  $('progress').textContent = review.observations.filter(complete).length + '/' + expected.size + ' complete decisions · ' + unresolved + ' unresolved · 0 accepted\n' + per.join(' · ');
}
function draw(name, canvas, visitIndex, tileW, tileH) {
  const token=name+':'+visitIndex; canvas.dataset.reviewToken=token;
  canvas.dataset.loaded='';canvas.getContext('2d').clearRect(0,0,canvas.width,canvas.height);
  $('save').disabled=true;
  const image = new Image(); image.onload = () => {
    if(canvas.dataset.reviewToken!==token) return; // late load must not show another visit
    const gc = canvas.getContext('2d'); gc.imageSmoothingEnabled=false;
    gc.clearRect(0,0,canvas.width,canvas.height);
    gc.drawImage(image,(visitIndex%3)*tileW,Math.floor(visitIndex/3)*tileH,tileW,tileH,0,0,canvas.width,canvas.height);
    canvas.dataset.loaded=token;updateSaveAvailability();
  }; image.src=REVIEW_DATA.pictures[name];
  image.onerror=()=>{if(canvas.dataset.reviewToken===token){canvas.dataset.loaded='';updateSaveAvailability();message('Image failed to load. Do not annotate this visit; validate the workspace.');}};
}
function show() {
  const r = active(), c = ctx.cases.find(c => c.neuron_id===r.neuron_id), i=ctx.days.indexOf(r.day);
  shownKey=key(r);
  $('identity').value=r.same_cell_yes_no_uncertain; $('ownership').value=r.ROI_ownership_clear_uncertain_contaminated;
  $('notes').value=r.notes; draftDirty=false;
  const e=expected.get(key(r));
  $('qc').textContent='IMMUTABLE automated QC: ' + (e.automated_valid_488?'valid':'FAILED') +
    '\nInherited tracking: ' + e.inherited_tracking_valid + '\nReasons: ' + (e.automated_failure_reasons.join('; ') || 'No primary failure recorded; NOT a manual approval') +
    '\nTrack: ' + c.diagnostic_status + '\nRecorded human timestamp: ' + (r.reviewed_at || 'Not reviewed');
  $('provenance').textContent=JSON.stringify({source:e.source_sha256,display:e.display_sha256,trace:e.trace_manifest_sha256,
    workspace:ctx.workspace_sha256,core_area_px:c.core_area_px,geometry:e.geometry,
    automated_single_soma_pass_is_not_ownership:c.secondary_soma_pass_is_not_ownership},null,2);
  draw(c.fixed_image,$('fixed'),i,384,432); draw(c.search_image,$('search'),i,402,450); progress();
}
function message(text) { $('message').textContent=text; }
function save() {
  try {
    if(!displaysReady()) throw Error('Wait until both current-visit 488 images are loaded.');
    const reviewer=$('reviewer').value.trim();
    if (!reviewer) throw Error('Enter your reviewer identity. Codex must not supply it.');
    if (review.reviewer && review.reviewer!==reviewer && review.observations.some(r => r.reviewed_at))
      throw Error('This file belongs to another reviewer. Start a separate file; do not reattribute their work.');
    const r=active(), copy=JSON.parse(JSON.stringify(review));
    copy.reviewer=reviewer;
    const target=copy.observations.find(x => key(x)===key(r));
    target.same_cell_yes_no_uncertain=$('identity').value;
    target.ROI_ownership_clear_uncertain_contaminated=$('ownership').value;
    target.notes=$('notes').value;
    const annotated=!!(target.same_cell_yes_no_uncertain || target.ROI_ownership_clear_uncertain_contaminated || target.notes);
    target.reviewer=annotated?reviewer:''; target.reviewed_at=annotated?new Date().toISOString():'';
    review=validateDocument(copy); dirty=true; draftDirty=false; message('Annotation recorded locally. Download private JSON to save it to disk. No source/QC was changed.'); show();
  } catch(error) {message(error.message);}
}
function navigate(offset) {
  if(draftDirty && !confirm('Discard unsaved edits for this visit?')) return;
  const index=ctx.visits.findIndex(r => key(r)===key(active()));
  const next=ctx.visits[(index+offset+ctx.visits.length)%ctx.visits.length];
  $('neuron').value=next.neuron_id; $('day').value=String(next.day); show();
}
for(const c of ctx.cases) {const o=document.createElement('option');o.value=c.neuron_id;o.textContent=c.neuron_id;$('neuron').appendChild(o);}
for(const day of ctx.days) {const o=document.createElement('option');o.value=String(day);o.textContent='Day '+day;$('day').appendChild(o);}
for(const id of ['identity','ownership','notes']) $(id).addEventListener('input',()=>{draftDirty=true;});
for(const id of ['neuron','day']) $(id).addEventListener('change',()=>{
  if(draftDirty && !confirm('Discard unsaved edits for this visit?')) {
    const previous=expected.get(shownKey);$('neuron').value=previous.neuron_id;$('day').value=String(previous.day);return;
  }
  show();
});
$('save').onclick=save; $('prev').onclick=()=>navigate(-1); $('next').onclick=()=>navigate(1);
$('download').onclick=()=>{
  try {
    if(draftDirty) throw Error('Save this visit annotation before downloading.');
    validateDocument(review);
    const blob=new Blob([JSON.stringify(review,null,2)+'\n'],{type:'application/json'});
    const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;
    a.download='private-488-review-'+new Date().toISOString().replace(/[:.]/g,'-')+'.json'; a.click();
    setTimeout(()=>URL.revokeObjectURL(url),2000);dirty=false;
    message('Private JSON downloaded. Run the Python validator against current sources before using decisions.');
  }catch(error){message(error.message);}
};
$('load').onchange=async event=>{
  try {
    if ((dirty || draftDirty) && !confirm('Replace unsaved in-memory annotations with this file?')) return;
    const text=await event.target.files[0].text();
    const loaded=validateDocument(JSON.parse(text));
    review=loaded;$('reviewer').value=review.reviewer;dirty=false;draftDirty=false;
    message('Loaded annotations. Current-source verification still requires the Python validator.');show();
  }catch(error){message('Import blocked: '+error.message);}
};
window.addEventListener('beforeunload',event=>{if(dirty||draftDirty){event.preventDefault();event.returnValue='Download unsaved annotations first.';}});
show();
