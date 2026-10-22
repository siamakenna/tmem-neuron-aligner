// Execute the real offline scripts against a minimal DOM. This does not claim Safari testing.
'use strict';
const fs = require('fs'), path = require('path'), vm = require('vm'), assert = require('assert');
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.style = {}; this.disabled = false; this.value = ''; this.attributes = {}; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(name, value) { this.attributes[name] = value; }
  get firstChild() { return this.children[0]; }
  click() { if (!this.disabled && this.onclick) this.onclick(); }
}
const ids = {};
for (const id of ['tracks', 'reviewer', 'load', 'save', 'message', 'save-status', 'workspace-scope', 'global-evidence']) ids[id] = new Element(id);
const blobs = [], handlers = {}, context = {document: {createElement: tag => new Element(tag), getElementById: id => ids[id]},
  Blob: class {constructor(content) { this.content = content; blobs.push(this); }},
  URL: {createObjectURL: () => 'blob:test', revokeObjectURL: () => {}}, setTimeout: () => {}, Date, console};
context.window = {addEventListener: (name, fn) => { handlers[name] = fn; }};
vm.createContext(context);
for (const name of ['review_data.js', 'review_binding.js', 'ui.js']) vm.runInContext(fs.readFileSync(path.join(process.argv[2], name), 'utf8'), context);
function find(node, tag) { return [...(node.tag === tag ? [node] : []), ...node.children.flatMap(child => find(child, tag))]; }
const sections = ids.tracks.children;
assert.equal(sections.length, 3);
for (const section of sections) {
  const criteria = find(section, 'select').filter(node => /identity_488|roi_purity_488|phenotype_qc_561/.test(node.attributes['aria-label'] || ''));
  assert.equal(criteria.length, 27); assert.equal(criteria.filter(node => node.disabled).length, 9);
  const phenotype = find(section, 'div').find(node => node.className === 'phenotype-section');
  assert.equal(phenotype.style.display, 'none');
  const images = find(section, 'img'); assert.equal(images.length, 3); assert(!images[1].src); assert(!images[2].src);
}
const section = sections[0], buttons = find(section, 'button');
const unlock = buttons.find(node => node.textContent.startsWith('Show 561')), reset = buttons.find(node => node.textContent.startsWith('Reset identity'));
const criteria = find(section, 'select').filter(node => /identity_488|roi_purity_488|phenotype_qc_561/.test(node.attributes['aria-label'] || ''));
assert(unlock.disabled);
for (const control of criteria) if (!control.disabled) { control.value = 'pass'; control.onchange(); }
assert(!unlock.disabled); assert(ids['save-status'].textContent.startsWith('Unsaved changes'));
let prevented = false; handlers.beforeunload({preventDefault: () => { prevented = true; }}); assert(prevented);
unlock.click(); assert.equal(criteria.filter(node => node.disabled).length, 18);
for (const control of criteria) if (!control.disabled) { control.value = 'pass'; control.onchange(); }
const phenotype = find(section, 'div').find(node => node.className === 'phenotype-section');
assert.equal(phenotype.style.display, 'block');
const images = find(section, 'img'); assert(images[1].src.endsWith('_display.png')); assert(images[2].src.endsWith('_phenotype.png'));
assert(find(phenotype, 'table')[0].children.length === 3);
const day12 = buttons.find(node => node.textContent === 'Day 12'); day12.click();
assert(find(section, 'h3')[0].textContent.endsWith('Day 12'));
const notes = find(section, 'textarea')[0]; notes.value = 'AUTOMATED UI TEST: adaptive-mask issue'; notes.oninput();
const category = find(section, 'select').find(node => node.attributes['aria-label'].endsWith('selected-visit failure category'));
category.value = 'new_QC_condition'; category.onchange();
const decision = find(section, 'select').find(node => node.attributes['aria-label'].endsWith('track decision'));
decision.value = 'accept'; decision.onchange();
ids.reviewer.value = 'AUTOMATED UI TEST - NOT A HUMAN REVIEW'; ids.reviewer.oninput(); ids.save.click();
const saved = JSON.parse(blobs.at(-1).content[0]);
assert.equal(saved.schema_version, 'tmem.manual_review.v2'); assert(saved.workspace_sha256);
assert.equal(saved.tracks[0].visits.find(node => node.day === 12).notes, notes.value);
assert.equal(saved.tracks[0].visits.find(node => node.day === 12).failure_category, 'new_QC_condition');
assert.equal(saved.tracks[0].track_decision, 'accept'); assert(saved.reviewed_at);
prevented = false; handlers.beforeunload({preventDefault: () => { prevented = true; }}); assert(!prevented);
const f05decision = find(sections[2], 'select').find(node => node.attributes['aria-label'].endsWith('track decision'));
assert(f05decision.children.find(node => node.value === 'accept').disabled);
reset.click(); assert(unlock.disabled); assert.equal(phenotype.style.display, 'none'); assert.equal(decision.value, 'not_reviewed');
(async () => {
  await ids.load.onchange({target: {files: [{text: async () => JSON.stringify(saved)}]}});
  assert.equal(decision.value, 'accept'); assert.equal(criteria[0].disabled, true); assert.equal(phenotype.style.display, 'block');
  for (const field of ['workspace_sha256', 'source']) {
    const bad = JSON.parse(JSON.stringify(saved));
    if (field === 'source') bad.tracks[0].evidence_sha256 = 'stale'; else bad.workspace_sha256 = 'stale';
    await ids.load.onchange({target: {files: [{text: async () => JSON.stringify(bad)}]}});
    assert(ids.message.textContent.startsWith('Review was not loaded')); assert.equal(decision.value, 'accept');
  }
  const bad = JSON.parse(JSON.stringify(saved)); bad.tracks[2].track_decision = 'accept';
  await ids.load.onchange({target: {files: [{text: async () => JSON.stringify(bad)}]}});
  assert(ids.message.textContent.includes('known exclusion'));
  console.log('PASS: 488-first stages, exact LUT diagnostics, visit notes/categories, unsaved warning, save/resume/reset and stale-evidence rejection. No human review file written.');
})().catch(error => { console.error(error); process.exitCode = 1; });
