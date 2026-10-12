"""Independent Decimal oracle and metamorphic checks for the fixed 8 x 4 IP.

No value or lookup table is imported from golden.py.  The RTL-facing reference
and this audit intentionally use different arithmetic implementations.  Passing
the sampled checks is evidence about the tested cases, not an exhaustive proof.
"""
from __future__ import annotations

import csv
from decimal import Decimal, ROUND_HALF_UP, localcontext
from functools import lru_cache
import json
import math
from pathlib import Path
import random

PRECISION = 80
WEIGHT_SCALE = 16
FRACTION_SCALE = 1


@lru_cache(maxsize=4096)
def _exp_minus(distance: int) -> Decimal:
    with localcontext() as context:
        context.prec = PRECISION
        return Decimal(-distance).exp()


def independent_lut() -> list[int]:
    """Round exp(-d) * 16 using 80-digit Decimal, for d = 0..3."""
    with localcontext() as context:
        context.prec = PRECISION
        return [int((Decimal(WEIGHT_SCALE) * _exp_minus(d)).to_integral_value(
            rounding=ROUND_HALF_UP)) for d in range(4)]


def _independent_case(q, k, v):
    # Deliberately independent input checking and arithmetic, including the LUT.
    if type(q) is not list or len(q) != 4:
        raise ValueError('query must be a list of four int8 values')
    for matrix in (k, v):
        if type(matrix) is not list or len(matrix) != 8:
            raise ValueError('key/value must each contain eight rows')
        if any(type(row) is not list or len(row) != 4 for row in matrix):
            raise ValueError('key/value rows must contain four values')
    for value in q + [value for matrix in (k, v) for row in matrix for value in row]:
        if type(value) is not int or value < -128 or value > 127:
            raise ValueError('only int8 integers, excluding bool, are supported')
    scores = [sum(q[d] * k[j][d] for d in range(4)) for j in range(8)]
    peak = max(scores)
    with localcontext() as context:
        context.prec = PRECISION
        exact_weights = [_exp_minus(peak - score) for score in scores]
        # Recompute every integer weight from exp, without using a stored LUT.
        weights = [int((weight * WEIGHT_SCALE).to_integral_value(rounding=ROUND_HALF_UP))
                   for weight in exact_weights]
        total = sum(weights)
        acc = [sum(weights[j] * v[j][d] for j in range(8)) for d in range(4)]
        # Independent Decimal rounding: ties away from zero, including negative halves.
        output = [int((Decimal(numerator) / Decimal(total)).to_integral_value(
            rounding=ROUND_HALF_UP)) for numerator in acc]
        exact_total = sum(exact_weights, Decimal(0))
        exact_output = [sum((exact_weights[j] * v[j][d] for j in range(8)), Decimal(0)) /
                        exact_total for d in range(4)]
    return dict(scores=scores, max_score=peak, weights=weights, L=total, acc=acc,
                output_int=output, decimal_output=exact_output)


def make_extra_inputs(seed: int, groups: int = 32):
    """Return independent inputs and explicit JSON-serializable relations.

    Each group has one base and seven exact integer-output transformations.
    Bases avoid -128 so sign reversal remains inside int8.  Thirty-two further
    adversarial cases choose V endpoints from probability-error signs to amplify
    the LUT approximation, then retain cases with large *measured* oracle error.
    This search constructs stressful samples; it is not a global optimization.
    """
    if type(seed) is not int or type(groups) is not int or groups < 0:
        raise ValueError('seed and nonnegative groups must be integers')
    rng = random.Random(seed ^ 0x6A09E667)
    inputs, relations = [], []

    def append(name, q, k, v):
        inputs.append((name, list(q), [list(row) for row in k], [list(row) for row in v]))

    for index in range(groups):
        base = f'metamorphic_{index:03d}_base'
        q = [rng.randint(-3, 3) for _ in range(4)]
        if not any(q):
            q[0] = 1
        k = [[rng.randint(-6, 6) for _ in range(4)] for _ in range(8)]
        v = [[rng.randint(-127, 127) for _ in range(4)] for _ in range(8)]
        append(base, q, k, v)

        def variant(kind, new_q, new_k, new_v, **metadata):
            derived = f'metamorphic_{index:03d}_{kind}'
            append(derived, new_q, new_k, new_v)
            relations.append(dict(kind=kind, base=base, derived=derived, **metadata))

        token_order = rng.sample(range(8), 8)
        variant('token_permutation', q, [k[j] for j in token_order], [v[j] for j in token_order],
                permutation=token_order)
        feature_order = rng.sample(range(4), 4)
        variant('qk_feature_permutation', [q[d] for d in feature_order],
                [[row[d] for d in feature_order] for row in k], v, permutation=feature_order)
        variant('qk_negation', [-value for value in q], [[-value for value in row] for row in k], v)
        shift = [rng.randint(-4, 4) for _ in range(4)]
        if not any(shift):
            shift[0] = 1
        variant('key_translation', q, [[row[d] + shift[d] for d in range(4)] for row in k], v,
                shift=shift)
        variant('value_negation', q, k, [[-value for value in row] for row in v])
        value_order = rng.sample(range(4), 4)
        variant('value_permutation', q, k, [[row[d] for d in value_order] for row in v],
                permutation=value_order)
        constants = [rng.randint(-128, 127) for _ in range(4)]
        variant('constant_values', q, k, [constants[:] for _ in range(8)], constants=constants)

    # Small score gaps are the difficult regime.  A large random int8 dot product
    # usually selects one winner, giving deceptively small approximation errors.
    candidates = {}
    with localcontext() as context:
        context.prec = PRECISION
        lookup = independent_lut()
        distributions = [[0] + [distance] * 7 for distance in range(1, 21)]
        distributions.extend([0] * winners + [rng.randint(1, 7) for _ in range(8 - winners)]
                             for winners in [rng.randint(1, 3) for _ in range(512)])
        for gaps in distributions:
            signature = tuple(sorted(gaps))
            if signature in candidates:
                continue
            exact = [_exp_minus(gap) for gap in gaps]
            integer = [lookup[gap] if gap <= 3 else 0 for gap in gaps]
            exact_total, integer_total = sum(exact), sum(integer)
            differences = [Decimal(integer[j]) / integer_total - exact[j] / exact_total for j in range(8)]
            values = [[127, -128, 126, 127] if difference >= 0 else [-128, 127, -127, -1]
                      for difference in differences]
            keys = [[-gap, 0, 0, 0] for gap in gaps]
            reference = _independent_case([1, 0, 0, 0], keys, values)
            error = max(abs(Decimal(reference['output_int'][d]) / FRACTION_SCALE -
                            reference['decimal_output'][d]) for d in range(4))
            candidates[signature] = (error, keys, values)
        selected = sorted(candidates.items(), key=lambda pair: (-pair[1][0], pair[0]))[:32]
    for index, (_, (_, keys, values)) in enumerate(selected):
        append(f'adversarial_{index:03d}', [1, 0, 0, 0], keys, values)
    return inputs, relations


def _stratum(name):
    for prefix, label in [('random_0_', 'random_full_int8'), ('random_1_', 'random_small_scores'),
                          ('random_2_', 'random_near_ties'), ('metamorphic_', 'metamorphic'),
                          ('adversarial_', 'adversarial')]:
        if name.startswith(prefix):
            return label
    return 'custom' if name == 'custom' else 'directed'


def _check_relation_inputs(base, derived, relation):
    q, k, v = base['q'], base['k'], base['v']
    kind = relation['kind']
    if kind == 'token_permutation':
        order = relation['permutation']
        if sorted(order) != list(range(8)):
            return False
        expected = (q, [k[j] for j in order], [v[j] for j in order])
    elif kind == 'qk_feature_permutation':
        order = relation['permutation']
        if sorted(order) != list(range(4)):
            return False
        expected = ([q[d] for d in order], [[row[d] for d in order] for row in k], v)
    elif kind == 'qk_negation':
        expected = ([-value for value in q], [[-value for value in row] for row in k], v)
    elif kind == 'key_translation':
        shift = relation['shift']
        expected = (q, [[row[d] + shift[d] for d in range(4)] for row in k], v)
    elif kind == 'value_negation':
        expected = (q, k, [[-value for value in row] for row in v])
    elif kind == 'value_permutation':
        order = relation['permutation']
        if sorted(order) != list(range(4)):
            return False
        expected = (q, k, [[row[d] for d in order] for row in v])
    elif kind == 'constant_values':
        expected = (q, k, [relation['constants']] * 8)
    else:
        raise ValueError(f'unknown metamorphic relation: {kind}')
    return expected == (derived['q'], derived['k'], derived['v'])


def _statistics(records):
    errors = sorted(item['error'] for item in records)
    if not errors:
        return dict(cases=0, outputs=0, max_abs_error=0.0, mean_abs_error=0.0,
                    rmse=0.0, p99_abs_error=0.0)
    worst = max(records, key=lambda item: item['error'])
    with localcontext() as context:
        context.prec = PRECISION
        mean = sum(errors) / len(errors)
        rmse = (sum(error * error for error in errors) / len(errors)).sqrt()
    return dict(cases=len({item['case'] for item in records}), outputs=len(errors),
                max_abs_error=float(errors[-1]), mean_abs_error=float(mean), rmse=float(rmse),
                p99_abs_error=float(errors[math.ceil(0.99 * len(errors)) - 1]),
                worst_case=worst['name'], worst_case_index=worst['case'],
                worst_dimension=worst['dimension'])


def audit_cases(cases, rtl_rows, relations, output_dir):
    """Audit references, actual RTL outputs, metamorphic laws, and error bounds.

    ``rtl_rows`` is an iterable of DictReader-like rows with case, L, o0..o3.
    Results are written inside output_dir.  Any mismatch writes the available
    failure evidence and raises AssertionError; a failed audit cannot be PASS.
    Rounded integer outputs remain within the integer Value extrema.
    """
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    cases, rtl_rows, relations = list(cases), list(rtl_rows), list(relations)
    failures, records, detailed, relation_details = [], [], [], []
    by_index, by_name = {}, {}
    for row in rtl_rows:
        index = int(row['case'])
        if index in by_index:
            raise ValueError(f'duplicate RTL case index {index}')
        by_index[index] = row
    if set(by_index) != set(range(len(cases))):
        raise ValueError('RTL case indices must match the complete reference case set')
    if not cases:
        raise ValueError('no cases supplied')
    measured = {}
    with localcontext() as context:
        context.prec = PRECISION
        # Each encoded weight has error <= 1/2, including the zero tail d >= 4.
        # Sum error <= 4; both totals >= 16. This is a loose analytic bound,
        # not an accuracy target. Final nearest rounding adds at most 0.5.
        error_bound = Decimal(2 * 255 * 4) / WEIGHT_SCALE + Decimal("0.5")
        one_lsb = Decimal(0)
        for index, case in enumerate(cases):
            name = case['name']
            if name in by_name:
                raise ValueError(f'duplicate case name {name}')
            by_name[name] = case
            reference = _independent_case(case['q'], case['k'], case['v'])
            for field in ['scores', 'max_score', 'weights', 'L', 'acc', 'output_int']:
                if case.get(field) != reference[field]:
                    failures.append(f'case {index} {name}: independent {field} mismatch')
            row = by_index[index]
            actual = [int(row[f'o{d}']) for d in range(4)]
            measured[name] = actual
            if int(row['L']) != reference['L']:
                failures.append(f'case {index} {name}: RTL denominator mismatch')
            if actual != reference['output_int']:
                failures.append(f'case {index} {name}: RTL integer output mismatch')
            layer = _stratum(name)
            for dimension, integer_output in enumerate(actual):
                output = Decimal(integer_output) / FRACTION_SCALE
                truth = reference['decimal_output'][dimension]
                error = abs(output - truth)
                lower = min(row[dimension] for row in case['v'])
                upper = max(row[dimension] for row in case['v'])
                convex_pass = Decimal(lower) - one_lsb <= output <= Decimal(upper) + one_lsb
                bound_pass = error <= error_bound
                if not convex_pass:
                    failures.append(f'case {index} {name} dimension {dimension}: convex hull violated')
                if not bound_pass:
                    failures.append(f'case {index} {name} dimension {dimension}: error bound violated')
                records.append(dict(case=index, name=name, dimension=dimension, error=error, stratum=layer))
                detailed.append(dict(case=index, name=name, stratum=layer, dimension=dimension,
                                     rtl_output_int=integer_output, rtl_output_decimal=str(output),
                                     high_precision_reference=str(truth), abs_error=str(error),
                                     convex_min=lower, convex_max=upper, convex_tolerance=str(one_lsb),
                                     convex_pass=int(convex_pass), conservative_error_bound=str(error_bound),
                                     error_bound_pass=int(bound_pass)))
        for relation in relations:
            base_name, derived_name, kind = relation['base'], relation['derived'], relation['kind']
            if base_name not in by_name or derived_name not in by_name:
                raise ValueError(f'metamorphic relation names missing: {relation}')
            input_pass = _check_relation_inputs(by_name[base_name], by_name[derived_name], relation)
            base_output = measured[base_name]
            expected = base_output
            if kind == 'value_negation':
                expected = [-value for value in base_output]
            elif kind == 'value_permutation':
                expected = [base_output[d] for d in relation['permutation']]
            elif kind == 'constant_values':
                expected = [value * FRACTION_SCALE for value in relation['constants']]
            output_pass = measured[derived_name] == expected
            if not input_pass or not output_pass:
                failures.append(f'metamorphic {kind}: {base_name} -> {derived_name} failed')
            relation_details.append(dict(kind=kind, base=base_name, derived=derived_name,
                                         inputs_valid=int(input_pass), rtl_relation_pass=int(output_pass),
                                         expected=json.dumps(expected), actual=json.dumps(measured[derived_name])))

    for filename, rows in [('high_precision_errors.csv', detailed), ('metamorphic_checks.csv', relation_details)]:
        with (destination / filename).open('w', encoding='utf-8', newline='') as stream:
            columns = list(rows[0]) if rows else ['kind', 'base', 'derived', 'inputs_valid', 'rtl_relation_pass', 'expected', 'actual']
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
    result = dict(status='FAIL' if failures else 'PASS', **_statistics(records),
                  decimal_precision=PRECISION, sampled_validation_only=True,
                  scope='Sampled validation of supplied cases; no exhaustive input-domain proof.',
                  independent_lut=independent_lut(), conservative_abs_error_bound=float(error_bound),
                  conservative_abs_error_bound_decimal=str(error_bound),
                  quantile_method='nearest rank', convex_tolerance=float(one_lsb),
                  internal_reference_fields_checked=['scores', 'max_score', 'weights', 'L', 'acc', 'output_int'],
                  rtl_fields_checked=['L', 'o0', 'o1', 'o2', 'o3'],
                  metamorphic_relations_checked=len(relations),
                  metamorphic_relation_counts={kind: sum(item['kind'] == kind for item in relations)
                                              for kind in sorted({item['kind'] for item in relations})},
                  strata={layer: _statistics([item for item in records if item['stratum'] == layer])
                          for layer in sorted({item['stratum'] for item in records})},
                  detailed_errors_file='high_precision_errors.csv',
                  metamorphic_checks_file='metamorphic_checks.csv', failures=failures)
    (destination / 'numeric_validation.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    if failures:
        raise AssertionError(f'Independent numeric audit failed ({len(failures)} findings): ' + '; '.join(failures[:8]))
    return result
