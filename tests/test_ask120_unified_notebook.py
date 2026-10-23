"""Exercise merged notebook mode routing and access stops without network access."""
import base64
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zlib

import pyarrow.parquet as pq
import requests

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import ask120_gate as gate
import build_120ask_holdout_notebook as builder


class UnifiedNotebookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nb=json.loads((ROOT/'notebooks/check_120ask_50.ipynb').read_text(encoding='utf-8'))
        cls.cells={c['id']:''.join(c['source']) for c in cls.nb['cells']}
        cls.bundle=json.loads(builder.SAMPLE_PATH.read_bytes())

    def setUp(self):
        (ROOT/'tmp').mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'tmp')
        self.addCleanup(self.temp.cleanup)
        self.out=Path(self.temp.name)

    def environment(self,mode):
        env={}
        source=self.cells['ask120-gate-1'].replace("MODE = 'replay'",'MODE = '+repr(mode),1)
        exec(compile(source,'config','exec'),env)
        env.update(RUN_DIR=self.out,SUPPORT_DIR=self.out/'support',POLICY={},
                   INPUT_PATH=self.out/'input.zip',SOURCE_PARQUET='custom.parquet',
                   HISTORY_PATHS=['custom-history.jsonl'],base64=base64,hashlib=hashlib,json=json,zlib=zlib)
        return env

    def run_workflow(self,mode,statuses=None,bad_mapping=False):
        env=self.environment(mode)
        mapping=self.bundle['selected_mapping'] if mode=='holdout_1000' else {'1':'https://www.120ask.com/question/1.htm'}
        env['HOLDOUT']={'selected_mapping':mapping}
        output=Mock(return_value={'checked':True})
        env['build_outputs']=output
        calls=[]
        def prepare():
            (self.out/'manifest.json').write_text('{}')
            rows=[] if bad_mapping else [{'id':int(k),'url':v} for k,v in mapping.items()]
            gate.jsonl(self.out/'sample.jsonl',rows)
        def replay(*args):
            calls.append('replay');prepare();return []
        def crawl(*args,**kwargs):
            calls.append(('crawl',kwargs));prepare()
            if statuses is not None:
                session=requests.Session()
                for _ in range(20):session.request('GET','https://www.120ask.com/question/1.htm')
            return []
        env['gate']=SimpleNamespace(replay=replay,crawl_new=crawl,read_jsonl_bytes=gate.read_jsonl_bytes)
        counter=iter(statuses or [])
        def response(*args,**kwargs):
            value=next(counter)
            if isinstance(value,Exception):raise value
            result=requests.Response();result.status_code=value;return result
        log=io.StringIO()
        with patch('requests.sessions.Session.request',side_effect=response if statuses is not None else AssertionError('network forbidden')) as http:
            with redirect_stdout(log):
                if bad_mapping:
                    with self.assertRaisesRegex(ValueError,'1000 URL'):
                        exec(compile(self.cells['ask120-gate-7'],'run','exec'),env)
                else:
                    exec(compile(self.cells['ask120-gate-7'],'run','exec'),env)
        output.assert_called_once()
        return env,calls,http.call_count,log.getvalue()

    def test_default_replay_and_custom_crawl_remain_independent(self):
        env,calls,count,_=self.run_workflow('replay')
        self.assertEqual(calls,['replay']);self.assertEqual(count,0)
        self.assertTrue(env['RUN_EXPERIMENTS'])
        env,calls,count,_=self.run_workflow('crawl_new')
        self.assertEqual(calls[0][0],'crawl');self.assertEqual(count,0)
        self.assertFalse(env['RUN_EXPERIMENTS'])
        self.assertEqual(calls[0][1]['history_paths'],['custom-history.jsonl'])

    def test_holdout_config_and_bundle_are_exact_and_offline(self):
        raw=builder.SAMPLE_PATH.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),'64cb946bce92d53611013d4c4dc7e5bdbb51ebaf16e5ce48c131d7c8978b69b7')
        env=self.environment('holdout_1000')
        self.assertEqual((env['LIMIT'],env['SEED'],env['ATTEMPTS']),(1000,2026102003,1))
        self.assertFalse(env['RUN_EXPERIMENTS'])
        env['gate']=gate
        with patch('requests.sessions.Session.request',side_effect=AssertionError('network forbidden')),redirect_stdout(io.StringIO()):
            exec(compile(self.cells['ask120-holdout-bundle'],'bundle','exec'),env)
        self.assertEqual(env['HOLDOUT'],self.bundle)
        rows=pq.read_table(env['SOURCE_PARQUET']).to_pylist()
        self.assertEqual(rows,self.bundle['rows'])
        self.assertEqual(len(gate.read_jsonl_bytes(env['HISTORY_FILE'].read_bytes())),1086)
        builder.validate_bundle(env['HOLDOUT'])

    def test_replay_bundle_cell_does_not_override_custom_input(self):
        for mode in ('replay','crawl_new'):
            env=self.environment(mode);env['gate']=Mock()
            exec(compile(self.cells['ask120-holdout-bundle'],'bundle','exec'),env)
            self.assertEqual(env['SOURCE_PARQUET'],'custom.parquet')
            self.assertEqual(env['HISTORY_PATHS'],['custom-history.jsonl'])
            self.assertFalse((self.out/'selected_holdout_source.parquet').exists())
            env['gate'].jsonl.assert_not_called()

    def test_holdout_stops_after_five_failures_and_still_builds_partial_outputs(self):
        env,calls,count,log=self.run_workflow('holdout_1000',[521]*5)
        self.assertEqual(count,5)
        self.assertEqual(env['_consecutive_errors'],5)
        self.assertIn('DỪNG DO TRUY CẬP',log)

    def test_holdout_success_resets_consecutive_errors(self):
        _,_,count,_=self.run_workflow('holdout_1000',[521,521,200,521,521,521,521,521])
        self.assertEqual(count,8)

    def test_holdout_mapping_mismatch_does_not_pass_as_the_fixed_sample(self):
        self.run_workflow('holdout_1000',bad_mapping=True)

    def test_unified_composition_is_idempotent_and_has_one_shared_runtime(self):
        import nbformat
        nbformat.validate(self.nb)
        self.assertEqual(builder.integrate_holdout(self.nb),self.nb)
        self.assertEqual(len(self.cells),len(self.nb['cells']))
        self.assertEqual(sum('PACK = ' in s for s in self.cells.values()),1)
        self.assertEqual(sum('samples=gate.crawl_new' in s for s in self.cells.values()),1)
        self.assertEqual(sum('archive=Path(shutil.make_archive' in s for s in self.cells.values()),1)
        self.assertTrue(self.cells['ask120-holdout-audit'].startswith((ROOT/'scripts/ask120_holdout_audit.py').read_text(encoding='utf-8')))
        for cell in self.nb['cells']:
            if cell['cell_type']=='code':compile(''.join(cell['source']),'unified-cell','exec')


if __name__=='__main__':unittest.main()
