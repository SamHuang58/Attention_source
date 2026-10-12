"""Behavioral tests for the reference generator and independent numeric audit."""
import contextlib
import copy
import csv
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'model'))
import golden
import research_validation as audit


def _rows(cases):
    return [dict(case=str(index), L=str(case['L']),
                 **{f'o{d}': str(case['output_int'][d]) for d in range(4)})
            for index, case in enumerate(cases)]


class ReferenceContractTests(unittest.TestCase):
    def setUp(self):
        self.q = [0, 0, 0, 0]
        self.k = [[0, 0, 0, 0] for _ in range(8)]
        self.v = [[0, 0, 0, 0] for _ in range(8)]

    def test_rejects_non_int8_and_malformed_inputs(self):
        for invalid in [True, False, 1.0, -1.5, '1', None, 128, -129]:
            for position in ['q', 'k', 'v']:
                with self.subTest(invalid=invalid, position=position):
                    q, k, v = copy.deepcopy((self.q, self.k, self.v))
                    if position == 'q':
                        q[0] = invalid
                    else:
                        (k if position == 'k' else v)[0][0] = invalid
                    with self.assertRaises(ValueError):
                        golden.evaluate(q, k, v)
        malformed = [(self.q[:3], self.k, self.v), (tuple(self.q), self.k, self.v),
                     (self.q, self.k[:7], self.v), (self.q, self.k, self.v[:7]),
                     (self.q, [[0] * 3] * 8, self.v), (self.q, self.k, [(0,) * 4] * 8)]
        for arguments in malformed:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                golden.evaluate(*arguments)

    def test_evaluate_is_pure_and_preserves_inputs(self):
        self.q[:] = [1, -2, 3, -4]
        self.v[3][:] = [-128, 127, 6, -7]
        before = copy.deepcopy((self.q, self.k, self.v))
        with tempfile.TemporaryDirectory() as temporary:
            previous = Path.cwd()
            try:
                os.chdir(temporary)
                first = golden.evaluate(self.q, self.k, self.v)
                second = golden.evaluate(self.q, self.k, self.v)
                self.assertEqual(list(Path(temporary).iterdir()), [])
            finally:
                os.chdir(previous)
        self.assertEqual(first, second)
        self.assertEqual(before, (self.q, self.k, self.v))

    def test_seed_reproduces_vectors_without_overwriting_custom_input(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()):
            root = Path(temporary)
            (root / 'docs').mkdir()
            sentinel = root / 'docs/demo_input.json'
            sentinel.write_text('{"user_owned": true}\n', encoding='utf-8')
            first = golden.generate(12, seed=37, output_root=root)
            first_vectors = (root / 'build/vectors.txt').read_bytes()
            second = golden.generate(12, seed=37, output_root=root)
            self.assertEqual(first, second)
            self.assertEqual(first_vectors, (root / 'build/vectors.txt').read_bytes())
            third = golden.generate(12, seed=38, output_root=root)
            self.assertEqual([c for c in first if not c['name'].startswith('random_')],
                             [c for c in third if not c['name'].startswith('random_')])
            self.assertNotEqual(first[-12:], third[-12:])
            self.assertEqual(sentinel.read_text(encoding='utf-8'), '{"user_owned": true}\n')

    def test_generator_rejects_invalid_case_counts(self):
        for count in [-1, True, 1.5]:
            with self.subTest(count=count), self.assertRaises(ValueError):
                golden.generate(count)

    def test_independent_lut_matches_known_rounded_exponentials(self):
        self.assertEqual(audit.independent_lut(), [16, 6, 2, 1])

    def test_v2_preserves_fractional_weights_and_zero_tail(self):
        keys = [[-d, 0, 0, 0] for d in range(8)]
        values = [[0]*4, [8]*4]+[[0]*4]*6
        case = golden.evaluate([1,0,0,0], keys, values)
        self.assertEqual(case['weights'], [16,6,2,1,0,0,0,0])
        self.assertEqual(case['L'], 25)
        self.assertEqual(case['acc'], [48]*4)
        self.assertEqual(case['output_int'], [2]*4)
        self.assertEqual(case['output'], [2]*4)

    def test_v2_rounding_halves_neighbors_and_odd_denominator(self):
        for numerator, expected in [(3,0), (4,1), (5,1), (12,2), (20,3)]:
            with self.subTest(numerator=numerator):
                values = [[numerator,-numerator,127,-128]]+[[0,0,127,-128]]*7
                arguments = ([0]*4, [[0]*4]*8, values)
                want = [expected,-expected,127,-128]
                self.assertEqual(golden.evaluate(*arguments)['output_int'], want)
                self.assertEqual(audit._independent_case(*arguments)['output_int'], want)
        keys = [[0]*4,[-3,0,0,0]]+[[-4,0,0,0]]*6
        values = [[0]*4,[8,9,-8,-9]]+[[127]*4]*6
        arguments = ([1,0,0,0], keys, values)
        self.assertEqual(golden.evaluate(*arguments)['L'], 17)
        self.assertEqual(golden.evaluate(*arguments)['output_int'], [0,1,0,-1])
        self.assertEqual(audit._independent_case(*arguments)['output_int'], [0,1,0,-1])

    def test_v2_rounding_at_int8_endpoints(self):
        values = [[127,-128,127,-128]]*4+[[126,-127,126,-127]]*4
        case = golden.evaluate([0]*4, [[0]*4]*8, values)
        self.assertEqual(case['output_int'], [127,-128,127,-128])

    def test_known_average_and_extreme_constant_cases(self):
        self.v[0] = [-1, 1, -128, 127]
        average = dict(name='known_average', **golden.evaluate(self.q, self.k, self.v))
        self.assertEqual(average['output_int'], [0, 0, -16, 16])
        extreme = dict(name='known_extreme', **golden.evaluate([-128] * 4,
                       [[-128] * 4] * 8, [[-128, 127, 0, 7]] * 8))
        self.assertEqual(extreme['scores'], [65536] * 8)
        self.assertEqual(extreme['output_int'], [-128, 127, 0, 7])
        with tempfile.TemporaryDirectory() as temporary:
            result = audit.audit_cases([average, extreme], _rows([average, extreme]), [], temporary)
            self.assertEqual(result['status'], 'PASS')
            self.assertEqual(result['max_abs_error'], 0.125)
            with (Path(temporary) / 'high_precision_errors.csv').open(encoding='utf-8', newline='') as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 8)

    def test_metamorphic_inputs_and_actual_output_relations(self):
        inputs, relations = audit.make_extra_inputs(123, groups=4)
        again = audit.make_extra_inputs(123, groups=4)
        self.assertEqual((inputs, relations), again)
        self.assertNotEqual(inputs, audit.make_extra_inputs(124, groups=4)[0])
        self.assertEqual(len(inputs), 4 * 8 + 32)
        self.assertEqual(len(relations), 4 * 7)
        json.dumps(relations)  # Metadata must survive the experiment manifest.
        cases = [dict(name=name, **golden.evaluate(q, k, v)) for name, q, k, v in inputs]
        with tempfile.TemporaryDirectory() as temporary:
            result = audit.audit_cases(cases, _rows(cases), relations, temporary)
            self.assertEqual(result['metamorphic_relations_checked'], 28)
            self.assertEqual(result['strata']['adversarial']['cases'], 32)
            self.assertGreater(result['strata']['adversarial']['max_abs_error'], 1.0)
            self.assertLess(result['max_abs_error'], result['conservative_abs_error_bound'])

    def test_audit_detects_corrupted_reference_and_records_failure(self):
        case = dict(name='corrupt_score', **golden.evaluate(self.q, self.k, self.v))
        case['scores'][0] = 1
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(AssertionError, 'scores mismatch'):
                audit.audit_cases([case], _rows([case]), [], temporary)
            result = json.loads((Path(temporary) / 'numeric_validation.json').read_text(encoding='utf-8'))
            self.assertEqual(result['status'], 'FAIL')

    def test_audit_detects_actual_rtl_mismatch_and_missing_case(self):
        case = dict(name='corrupt_output', **golden.evaluate(self.q, self.k, self.v))
        rows = _rows([case])
        rows[0]['o0'] = '1'
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(AssertionError, 'RTL integer output mismatch'):
                audit.audit_cases([case], rows, [], temporary)
            with self.assertRaisesRegex(ValueError, 'complete reference case set'):
                audit.audit_cases([case], [], [], temporary)

    def test_relation_claim_is_checked_against_inputs(self):
        inputs, relations = audit.make_extra_inputs(123, groups=1)
        cases = [dict(name=name, **golden.evaluate(q, k, v)) for name, q, k, v in inputs]
        broken = copy.deepcopy(relations)
        broken[0]['permutation'] = [0] * 8
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(AssertionError, 'metamorphic token_permutation'):
                audit.audit_cases(cases, _rows(cases), broken, temporary)


if __name__ == '__main__':
    unittest.main()
