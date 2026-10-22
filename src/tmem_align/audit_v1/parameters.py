"""Describe the unchanged curated algorithm from its actual source snapshot.

This module reads Python syntax rather than importing microscopy code. It never
changes arrays or supplies new parameters to the scientific calculation.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.metadata
from pathlib import Path


def _functions(path):
    source = path.read_text()
    tree = ast.parse(source, filename=str(path))
    return source, {node.name: node for node in tree.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _name(node):
    return ast.unparse(node.func) if isinstance(node, ast.Call) else ''


def _calls(node, suffix):
    return [call for call in ast.walk(node) if isinstance(call, ast.Call)
            and _name(call).split('.')[-1] == suffix]


def _assignment(function, name):
    for node in ast.walk(function):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name
                                               for t in node.targets):
            return node.value
    raise ValueError(f'Parameter recorder cannot find assignment {name}')


def _literal(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError) as exc:
        raise ValueError('Parameter recorder expected a literal scientific constant') from exc


def _sigma(call):
    for keyword in call.keywords:
        if keyword.arg == 'sigma':
            return _literal(keyword.value)
    return _literal(call.args[1])


def _function_record(source, node):
    text = ast.get_source_segment(source, node)
    return {'function': node.name, 'source_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'source_expression': text,
            'numeric_literals': [{'value': n.value, 'source_line': n.lineno}
                                 for n in ast.walk(node)
                                 if isinstance(n, ast.Constant)
                                 and type(n.value) in (int, float)]}


def build_resolved_parameters(repo_root, parameters):
    """Return JSON-safe source-derived parameters for one immutable fixture.

    ``parameters`` is the existing fixture's parameters.json object. It records
    the values actually used, including phenotype dilation=2 in this audit even
    though the renderer's standalone CLI defaults to 1.
    """
    root = Path(repo_root).resolve()
    required = {'bbox_size', 'identity_consensus_fraction', 'phenotype_dilation',
                'segmentation_min_area', 'min_core_area', 'max_core_area',
                'background_exclusion', 'puncta_min_size'}
    if not isinstance(parameters, dict) or not required.issubset(parameters):
        raise ValueError('Supply the complete existing fixture parameter object')
    files = {
        'renderer': root/'scripts/render_curated_neuron_phenotypes.py',
        'adaptive_segmentation': root/'scripts/make_soma_anchored_bbox_movies_v2.py',
        'audit_invocation': root/'scripts/audit_curated_neurons.py',
        'preprocessing': root/'src/tmem_align/preprocess.py',
        'alignment_audit': root/'src/tmem_align/audit_v1/reference.py',
    }
    parsed = {key: _functions(path) for key, path in files.items()}
    render_source, render = parsed['renderer']
    phenotype = render['quantify_phenotype']
    dog = _assignment(phenotype, 'dog')
    if not isinstance(dog, ast.BinOp) or not isinstance(dog.op, ast.Sub):
        raise ValueError('Curated DoG expression changed; update its parameter description')
    sigmas = [_sigma(dog.left), _sigma(dog.right)]
    sigma_expr = _assignment(phenotype, 'robust_sigma')
    if not isinstance(sigma_expr, ast.BinOp):
        raise ValueError('Curated robust-sigma expression changed')
    mad_factor = _literal(sigma_expr.left)
    threshold = _assignment(phenotype, 'dog_thr')
    # Source: max(med + multiplier * robust_sigma, percentile(vals, p)).
    try:
        mad_multiplier = _literal(threshold.args[0].right.left)
        percentile = _literal(_calls(threshold, 'percentile')[0].args[1])
    except (AttributeError, IndexError) as exc:
        raise ValueError('Curated puncta-threshold expression changed') from exc
    fallback = [n for n in ast.walk(phenotype) if isinstance(n, ast.Compare)
                and ast.unparse(n.left) == 'int(bg_region.sum())']
    if len(fallback) != 1:
        raise ValueError('Curated background fallback expression changed')
    audit_source, audit = parsed['audit_invocation']
    screen_calls = _calls(audit['audit_track'], 'screen_secondary_soma')
    if len(screen_calls) != 1:
        raise ValueError('Audit soma-screen invocation changed')
    soma_kwargs = {kw.arg: _literal(kw.value) for kw in screen_calls[0].keywords}
    soma = render['screen_secondary_soma']
    # Keep exact source alongside readable principal values. This exposes less
    # prominent adaptive-mask and soma-screen constants without guessing them.
    requested = {
        'renderer': ['quantify_phenotype', 'build_tight_identity_core',
                     'keep_component_near_center', 'screen_secondary_soma',
                     'reconstruct_masks', 'build_reference_488', 'robust_limits'],
        'adaptive_segmentation': ['robust01', '_candidate_from_binary', 'segment_neuron_in_box'],
        'audit_invocation': ['audit_track'],
        'preprocessing': ['_quantize', '_apply_ic_field_float', '_smooth_and_rescale_2d',
                          '_rescale_field'],
        'alignment_audit': ['alignment_steps', 'phenotype_steps'],
    }
    source_algorithms = {}
    for key, names in requested.items():
        text, functions = parsed[key]
        source_algorithms[key] = [_function_record(text, functions[name]) for name in names]
    try:
        morphology_version = importlib.metadata.version('scikit-image')
    except importlib.metadata.PackageNotFoundError:
        morphology_version = None
    return {
        'schema_version': 'tmem.resolved_parameters.v1',
        'description': 'Description only. No calculation, retracking, ROI modification or LUT adoption.',
        'fixture_parameters_used': dict(parameters),
        'channel_contract': {'identity_tracking_geometry': '488, channel index 2 only',
                             'phenotype': '561, channel index 1 after identity and ROI definition'},
        'geometry': {'bbox_size_px': parameters['bbox_size'],
                     'identity_consensus_fraction': parameters['identity_consensus_fraction'],
                     'minimum_valid_488_masks': _literal(_calls(render['build_tight_identity_core'], 'max')[0].args[0]),
                     'phenotype_dilation_radius_px': parameters['phenotype_dilation'],
                     'dilation_source': 'Existing audit invocation and fixture parameters; standalone renderer defaults differ',
                     'min_core_area_px2': parameters['min_core_area'],
                     'max_core_area_px2': parameters['max_core_area'],
                     'segmentation_min_area_px2': parameters['segmentation_min_area']},
        'phenotype': {
            'input': 'Registered uint16 561 crop before local phenotype background subtraction',
            'background_exclusion_radius_px': parameters['background_exclusion'],
            'background_statistic': 'median outside dilated ROI',
            'background_fallback_min_pixels': _literal(fallback[0].comparators[0]),
            'background_fallback': 'If insufficient background support, use outside ROI; if empty, use 0',
            'negative_corrected_intensity': 'clip to zero',
            'dog_sigmas_px': sigmas,
            'mad_to_sigma_factor': mad_factor,
            'robust_sigma_multiplier': mad_multiplier,
            'roi_percentile_threshold': percentile,
            'threshold_expression': ast.unparse(threshold),
            'puncta_candidate_comparison': 'strictly greater than threshold, intersect ROI',
            'minimum_puncta_size_px': parameters['puncta_min_size'],
            'remove_small_objects_max_size_px': max(0, int(parameters['puncta_min_size']) - 1),
            'size_filter_boundary': ('max_size removes objects with area <= max_size; '
                                     f'minimum size {parameters["puncta_min_size"]} keeps area '
                                     f'>={parameters["puncta_min_size"]}'),
            'size_filter_library_version_in_render_environment': morphology_version,
            'upper_puncta_size_filter': None,
            'upper_filter_note': 'Current curated quantify_phenotype has no upper-area filter. Other phenotype modules differ.',
            'diffuse_support': 'ROI minus filtered puncta mask',
            'sum_dtype': 'float64',
            'intensity_units': 'background-corrected stored pixel ADU; integrated values are sums over pixels',
        },
        'secondary_soma_screen': {
            **soma_kwargs,
            'smoothing_sigma_px': _sigma(_calls(soma, 'gaussian_filter')[0]),
            'search_radius_and_min_distance_units': 'pixels',
            'interpretation': 'Automated review flag only; cannot override known multi-neuron exclusion',
        },
        'preprocessing_policy': {
            'review_build_adds_IC': False,
            'adopted_alignment_reference': 'raw/no empirical-IC registration',
            'empirical_IC': 'Separate sensitivity experiment, not physical calibration or adopted correction',
            'upstream_registered_stack_provenance': 'See immutable fixture provenance; crop label does not assert untouched ND2 values',
            'source_implementation': 'Exact source functions and hashes below describe optional preprocessing',
        },
        'source_files': {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in files.values()},
        'source_algorithms': source_algorithms,
    }
