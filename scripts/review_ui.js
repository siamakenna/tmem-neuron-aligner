'use strict';
// This file and the exact data/images it displays are bound by render_manifest.json.
const DATA = window.TMEM_REVIEW_DATA;
const DOC = JSON.parse(JSON.stringify(window.TMEM_REVIEW_BINDING));
const host = document.getElementById('tracks');
const SYNC = [];
const states = ['not_reviewed', 'pass', 'fail'];
const categories = ['', 'expected_handled', 'new_bug', 'new_QC_condition', 'scientific_limitation', 'visualization_only_issue'];
let dirty = false;
const el = (tag, text) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; return node; };
function markDirty() {
  dirty = true;
  const status = document.getElementById('save-status');
  status.textContent = 'Unsaved changes. Download manual_review.json before closing.';
  status.className = 'status dirty';
}
function markDownloaded(message) {
  dirty = false;
  const status = document.getElementById('save-status');
  status.textContent = message;
  status.className = 'status';
}
window.addEventListener('beforeunload', event => {
  if (dirty) { event.preventDefault(); event.returnValue = ''; }
});
function linkList(container, links) {
  container.replaceChildren();
  for (const link of links) {
    const a = el('a', link.label); a.href = link.href; a.target = '_blank'; a.rel = 'noopener'; container.append(a);
  }
}
function selectOptions(values, ariaLabel) {
  const select = el('select'); select.setAttribute('aria-label', ariaLabel);
  for (const value of values) { const option = el('option', value || 'No failure category recorded'); option.value = value; select.append(option); }
  return select;
}
function finiteText(value) { return Number(value).toLocaleString(undefined, {maximumFractionDigits: 6}); }
function lutText(lut) { return '[' + finiteText(lut.low) + ', ' + finiteText(lut.high) + '] ADU. ' + lut.scope + '. Source: ' + lut.source; }
document.getElementById('workspace-scope').textContent = 'Review schema: ' + DOC.schema_version + '. Workspace fingerprint: ' + DOC.workspace_sha256;
document.getElementById('reviewer').oninput = markDirty;

for (const track of DOC.tracks) {
  const info = DATA.tracks.find(item => item.neuron_id === track.neuron_id);
  const section = el('section'); section.setAttribute('aria-label', track.neuron_id + ' review');
  section.append(el('h2', track.neuron_id));
  if (info.exclusion) { const p = el('p', 'KNOWN EXCLUSION: ' + info.exclusion); p.className = 'warning'; section.append(p); }
  const evidence = el('details'), summary = el('summary', 'Evidence identity and display policy');
  evidence.append(summary, el('p', 'Source evidence fingerprint: ' + track.evidence_sha256),
    el('p', DATA.config.bbox_policy), el('p', DATA.config.ic_policy));
  section.append(evidence);
  const table = el('table'), head = el('tr');
  for (const title of ['Visit', 'Identity 488', 'ROI purity 488', 'Phenotype QC 561']) head.append(el('th', title));
  table.append(head);
  const rowByDay = new Map(), buttonByDay = new Map(), identityControls = [], phenotypeControls = [];
  const caption = el('h3'), identityMeta = el('p'); identityMeta.className = 'metadata';
  const identity = el('img'); identity.className = 'full'; identity.alt = '488 crop, adaptive mask, consensus core and phenotype ROI';
  const identityLinks = el('p'); identityLinks.className = 'links';
  const trackLinks = el('p'); trackLinks.className = 'links';
  linkList(trackLinks, [...info.identity_links, {href: info.identity_index, label: 'All 488 identity intermediates'}]);
  const visitNotesBox = el('div'); visitNotesBox.className = 'visit-notes';
  const visitNotesLabel = el('label'), visitNotes = el('textarea');
  visitNotes.placeholder = 'Notes for the selected visit: identity, ROI support, detector issue, or phenotype QC';
  visitNotesLabel.append(el('span', 'Selected-visit notes'), visitNotes);
  const categoryLabel = el('label', 'Selected-visit failure category '), category = selectOptions(categories, track.neuron_id + ' selected-visit failure category');
  categoryLabel.append(category); visitNotesBox.append(visitNotesLabel, categoryLabel);
  const showPhenotype = el('button', 'Show 561 after recording all nine 488 visits'); showPhenotype.type = 'button';
  const resetIdentity = el('button', 'Reset identity and phenotype judgments'); resetIdentity.type = 'button';
  const phenotype = el('div'); phenotype.className = 'phenotype-section';
  const rawDefinition = el('p', 'Raw 561 means the registered crop before local phenotype background correction. '
    + 'Both displayed LUTs stay fixed across the nine visits. LUT clipping is a display effect, not an acquisition-saturation measurement.');
  const display = el('img'); display.className = 'full'; display.alt = 'Reference and ROI-based fixed longitudinal 561 LUTs';
  const lutTable = el('table'); lutTable.className = 'metadata';
  const lutSources = el('p'); lutSources.className = 'metadata';
  const four = el('img'); four.className = 'full'; four.alt = 'Original four-panel 488, raw 561, puncta and diffuse decomposition';
  const phenotypeLinks = el('p'); phenotypeLinks.className = 'links';
  phenotype.append(el('h3', '561 phenotype and display sensitivity'), rawDefinition, display, lutTable, lutSources,
    el('p', 'Original phenotype reference: 488 / raw 561 / puncta / diffuse'), four, phenotypeLinks);
  let phenotypeVisible = false, selectedDay = track.visits[0].day;
  function currentVisit() { return track.visits.find(visit => Number(visit.day) === selectedDay); }
  function stage() {
    const ready = track.visits.every(visit => visit.identity_488 !== 'not_reviewed' && visit.roi_purity_488 !== 'not_reviewed');
    showPhenotype.disabled = !ready || phenotypeVisible;
    identityControls.forEach(control => { control.disabled = phenotypeVisible; });
    phenotypeControls.forEach(control => { control.disabled = !phenotypeVisible; });
    phenotype.style.display = phenotypeVisible ? 'block' : 'none';
    if (phenotypeVisible) updatePhenotype();
  }
  function updatePhenotype() {
    const frame = info.frames.find(item => item.day === selectedDay);
    display.src = frame.display; four.src = frame.phenotype;
    lutTable.replaceChildren();
    const head = el('tr'); for (const label of ['561 display', 'LUT min/max (ADU)', 'ROI below / above limits', 'Unchanged ROI sum (ADU)']) head.append(el('th', label));
    lutTable.append(head);
    for (const [label, key, lut] of [['Reference', 'reference_bbox', info.luts.reference], ['ROI sensitivity', 'roi_fixed', info.luts.candidate]]) {
      const stats = frame.clipping[key], row = el('tr');
      for (const text of [label, finiteText(lut.low) + ' / ' + finiteText(lut.high),
        stats.below_low + ' / ' + stats.above_high + ' of ' + stats.roi_pixels + ' pixels (' + finiteText(stats.above_high_percent) + '% above)',
        finiteText(stats.quantitative_sum)]) row.append(el('td', text));
      lutTable.append(row);
    }
    lutSources.textContent = 'Reference: ' + lutText(info.luts.reference) + ' ROI sensitivity: ' + lutText(info.luts.candidate);
    linkList(phenotypeLinks, [...frame.phenotype_links, {href: info.phenotype_index, label: 'All phenotype intermediates'},
      {href: track.neuron_id + '/luts.json', label: 'Exact LUT metadata'}, {href: 'lut_clipping.csv', label: 'All clipping diagnostics'}]);
  }
  function show(day) {
    selectedDay = Number(day);
    const frame = info.frames.find(item => item.day === selectedDay), visit = currentVisit();
    caption.textContent = track.neuron_id + ' — selected visit: Day ' + selectedDay;
    identity.src = frame.identity;
    identityMeta.textContent = frame.caption + ' Adaptive-mask valid flag: ' + frame.adaptive_valid + '. '
      + '488 LUT: ' + lutText(info.luts.identity488);
    for (const [rowDay, row] of rowByDay) row.className = rowDay === selectedDay ? 'active-day' : '';
    for (const [buttonDay, button] of buttonByDay) button.setAttribute('aria-pressed', buttonDay === selectedDay ? 'true' : 'false');
    visitNotes.value = visit.notes || ''; category.value = visit.failure_category || '';
    visitNotesLabel.firstChild.textContent = 'Day ' + selectedDay + ' notes';
    linkList(identityLinks, frame.identity_links);
    if (phenotypeVisible) updatePhenotype();
  }
  for (const visit of track.visits) {
    const row = el('tr'), cell = el('td'), dayButton = el('button', 'Day ' + visit.day);
    dayButton.type = 'button'; dayButton.onclick = () => show(visit.day); cell.append(dayButton); row.append(cell);
    rowByDay.set(Number(visit.day), row); buttonByDay.set(Number(visit.day), dayButton);
    for (const key of ['identity_488', 'roi_purity_488', 'phenotype_qc_561']) {
      const cell = el('td'), select = selectOptions(states, track.neuron_id + ' Day ' + visit.day + ' ' + key);
      select.value = visit[key]; select.onchange = () => { visit[key] = select.value; markDirty(); stage(); };
      if (key === 'phenotype_qc_561') phenotypeControls.push(select); else identityControls.push(select);
      SYNC.push(() => { select.value = visit[key]; }); cell.append(select); row.append(cell);
    }
    table.append(row);
  }
  showPhenotype.onclick = () => { phenotypeVisible = true; stage(); };
  resetIdentity.onclick = () => {
    phenotypeVisible = false; track.track_decision = 'not_reviewed';
    for (const visit of track.visits) for (const key of ['identity_488', 'roi_purity_488', 'phenotype_qc_561']) visit[key] = 'not_reviewed';
    SYNC.forEach(sync => sync()); stage(); markDirty();
  };
  visitNotes.oninput = () => { currentVisit().notes = visitNotes.value; markDirty(); };
  category.onchange = () => { currentVisit().failure_category = category.value; markDirty(); };
  section.append(table, caption, identityMeta, identity, identityLinks, trackLinks, visitNotesBox, showPhenotype, resetIdentity, phenotype);
  const decisionLabel = el('label', 'Track decision '), decision = selectOptions(['not_reviewed', 'accept', 'exclude'], track.neuron_id + ' track decision');
  if (info.exclusion) for (const option of decision.children) if (option.value === 'accept') option.disabled = true;
  decision.onchange = () => { track.track_decision = decision.value; markDirty(); };
  decisionLabel.append(decision); section.append(decisionLabel);
  const notesLabel = el('label', 'General track notes'), notes = el('textarea');
  notes.placeholder = 'Notes applying to the entire track; use selected-visit notes above for a specific day.';
  notes.oninput = () => { track.notes = notes.value; markDirty(); }; notesLabel.append(notes); section.append(notesLabel);
  SYNC.push(() => { decision.value = track.track_decision; notes.value = track.notes;
    phenotypeVisible = track.visits.some(visit => visit.phenotype_qc_561 !== 'not_reviewed'); show(selectedDay); stage(); });
  host.append(section); show(selectedDay); stage();
}

document.getElementById('load').onchange = async event => {
  try {
    const loaded = JSON.parse(await event.target.files[0].text());
    if (loaded.schema_version !== DOC.schema_version || loaded.workspace_sha256 !== DOC.workspace_sha256
      || !Array.isArray(loaded.tracks) || loaded.tracks.length !== DOC.tracks.length) throw Error('Wrong review schema, cohort or rendered-workspace fingerprint');
    for (const target of DOC.tracks) {
      const matches = loaded.tracks.filter(item => item.neuron_id === target.neuron_id);
      if (matches.length !== 1) throw Error('Missing or duplicate track');
      const item = matches[0], info = DATA.tracks.find(track => track.neuron_id === target.neuron_id);
      if (item.evidence_sha256 !== target.evidence_sha256 || !Array.isArray(item.visits) || item.visits.length !== 9) throw Error('Stale source evidence or incomplete visits');
      if (!['not_reviewed', 'accept', 'exclude'].includes(item.track_decision) || typeof item.notes !== 'string') throw Error('Invalid track decision or notes');
      if (info.exclusion && item.track_decision === 'accept') throw Error('A known exclusion cannot be accepted');
      for (const visit of target.visits) {
        const found = item.visits.filter(value => Number(value.day) === Number(visit.day));
        if (found.length !== 1) throw Error('Missing or duplicate visit');
        for (const key of ['identity_488', 'roi_purity_488', 'phenotype_qc_561']) if (!states.includes(found[0][key])) throw Error('Invalid criterion');
        const note = found[0].notes === undefined ? '' : found[0].notes;
        const failureCategory = found[0].failure_category === undefined ? '' : found[0].failure_category;
        if (typeof note !== 'string' || !categories.includes(failureCategory)) throw Error('Invalid visit notes or failure category');
      }
    }
    if (typeof loaded.reviewer !== 'string') throw Error('Invalid reviewer name');
    for (const target of DOC.tracks) {
      const item = loaded.tracks.find(track => track.neuron_id === target.neuron_id);
      target.track_decision = item.track_decision; target.notes = item.notes;
      for (const visit of target.visits) {
        const found = item.visits.find(value => Number(value.day) === Number(visit.day));
        for (const key of ['identity_488', 'roi_purity_488', 'phenotype_qc_561']) visit[key] = found[key];
        visit.notes = found.notes || ''; visit.failure_category = found.failure_category || '';
      }
    }
    DOC.reviewer = loaded.reviewer; DOC.reviewed_at = typeof loaded.reviewed_at === 'string' ? loaded.reviewed_at : '';
    document.getElementById('reviewer').value = DOC.reviewer; SYNC.forEach(sync => sync());
    markDownloaded('Loaded matching saved review. Further changes require a new JSON download.');
    document.getElementById('message').textContent = 'Loaded review with matching source and rendered-workspace fingerprints.';
  } catch (error) { document.getElementById('message').textContent = 'Review was not loaded: ' + error.message; }
};
document.getElementById('save').onclick = () => {
  DOC.reviewer = document.getElementById('reviewer').value.trim(); DOC.reviewed_at = new Date().toISOString();
  const json = JSON.stringify(DOC, null, 2), blob = new Blob([json], {type: 'application/json'}), url = URL.createObjectURL(blob), anchor = el('a');
  anchor.href = url; anchor.download = 'manual_review.json'; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  markDownloaded('JSON download requested. Confirm manual_review.json was saved before closing.');
  document.getElementById('message').textContent = 'The saved JSON still requires independent source/render verification and all manual/automated QC before metrics export.';
};
if (DATA.config.evidence_index) linkList(document.getElementById('global-evidence'), [{href: DATA.config.evidence_index,
  label: 'Separate workflow evidence: raw inputs, IC and alignment (not identity evidence for these crops)'}]);
