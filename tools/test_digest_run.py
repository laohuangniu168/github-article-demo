from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from html.parser import HTMLParser

import digest_run as runner


SUMMARY = ('这一主题可以从日常使用场景、参与方式和公共需求之间的关系展开理解，关注不同人群如何接触并体验相关活动。'
           '进一步阅读时，可留意便利性与持续参与的条件，但不应仅凭标题推断具体措施、实施效果或新闻正文中的事实。')


class FakeClient:
    def __init__(self, mutate=None, error=None):
        self.responses = self
        self.calls = []
        self.mutate = mutate
        self.error = error

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        prompt = kwargs['input']
        data = json.loads(prompt.split('输入数据：', 1)[1])
        payload = {'digest_title': 'Hot News Digest 热点新闻汇编', 'sections': [
            {'name': '生活与公共空间', 'entries': [
                {'entry_id': e['entry_id'], 'summary': SUMMARY} for e in data['entries']]}]}
        if self.mutate:
            self.mutate(payload)
        return SimpleNamespace(output_text=json.dumps(payload, ensure_ascii=False))

    def close(self):
        pass


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.hrefs.append(dict(attrs)['href'])


class DigestRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.input = self.root / 'daily.txt'
        self.urls = [f'{"http" if i % 2 else "https"}://example.com/News//Item%2F{i}?view=One&lang=zh#Part' for i in range(20)]
        self.input.write_text('\n'.join(f'{url}|社区生活观察{i}' for i, url in enumerate(self.urls)), encoding='utf-8')
        self.client = FakeClient()
        self.baseline = {'status': 'PASS', 'schema_version': 2,
            'algorithm_version': 'git-content-sha256-manifest-v1', 'manifest_entry_count': 200,
            'content_drift': False, 'aggregate_sha256': runner.EXPECTED_AGGREGATE}
        for p in [patch.object(runner, 'PROJECT_ROOT', self.root),
                  patch.object(runner, 'assert_ignored'),
                  patch.object(runner, 'verify_production_baseline', return_value=self.baseline),
                  patch.object(runner, 'create_client', side_effect=lambda secret: self.client),
                  patch.dict('os.environ', {'OPENAI_API_KEY': 'offline-test-value'})]:
            p.start()
            self.addCleanup(p.stop)

    def invoke(self, *extra):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = runner.main(['--input', str(self.input), *extra])
        self.assertNotIn('Traceback', output.getvalue())
        return code, output.getvalue()

    def failure(self, stage, code, *args):
        result, text = self.invoke(*args)
        self.assertNotEqual(0, result)
        self.assertIn('DIGEST_RUN_RESULT=FAIL', text)
        self.assertIn('STAGE=' + stage, text)
        self.assertIn('ERROR_CODE=' + code, text)
        return text

    def test_twenty_entry_happy_path_and_evidence(self):
        code, output = self.invoke()
        self.assertEqual(0, code)
        self.assertIn('CLICKABLE_HREF=20/20', output)
        self.assertIn('FINAL_STATE=PENDING_MANUAL_REVIEW', output)
        evidence = json.loads(next(self.root.glob('output/digest/evidence/*/run-result.json')).read_text('utf-8'))
        for key in ('batch_id','input_path','input_sha256','entry_count','registry_version','plan_hash',
                    'ai_call_count','audit_status','markdown_path','html_path','final_state'):
            self.assertIn(key, evidence)
        self.assertEqual(1, evidence['ai_call_count'])
        self.assertEqual(20, evidence['entry_count'])
        self.assertTrue(Path(evidence['html_path']).is_absolute())
        doc = Path(evidence['html_path']).read_text('utf-8')
        links = Links(); links.feed(doc)
        self.assertCountEqual(self.urls, links.hrefs)
        self.assertNotIn('{% raw %}', doc)
        self.assertNotIn('description:', doc)
        self.assertEqual(1, len(self.client.calls))
        self.assertNotIn('https://', self.client.calls[0]['input'])
        self.assertNotIn('http://', self.client.calls[0]['input'])
        from digest_generator import build_digest_prompt
        from digest_registry import build_digest_registry, parse_digest_file
        from digest_planner import plan_digest_articles
        reg = build_digest_registry(parse_digest_file(self.input))
        plan = plan_digest_articles(reg,batch_id=evidence['batch_id'],digest_registry_version=reg.digest_registry_version,config_version=reg.config_version).plans[0]
        self.assertEqual(build_digest_prompt(plan, reg), self.client.calls[0]['input'])

    def test_missing_input(self):
        self.input = self.root/'absent.txt'
        self.failure('INPUT', 'DIGEST_INPUT_UNREADABLE')
        self.assertFalse(self.client.calls)

    def test_malformed_input(self):
        self.input.write_text('missing separator', encoding='utf-8')
        self.failure('INPUT','INVALID_DIGEST_INPUT_FORMAT')

    def test_duplicate_url(self):
        self.input.write_text('https://example.com/a|标题\nhttps://example.com/a|另一标题',encoding='utf-8')
        self.failure('INPUT','DUPLICATE_DIGEST_URL')

    def test_missing_credential(self):
        with patch.dict('os.environ', {'OPENAI_API_KEY': ''}):
            self.failure('CREDENTIAL','OPENAI_RUNTIME_CREDENTIAL_UNAVAILABLE')
        self.assertFalse(self.client.calls)
        self.assertFalse(list(self.root.glob('output/digest/evidence/*')))
        self.assertEqual(0,self.invoke()[0])

    def test_baseline_failure(self):
        with patch.object(runner,'verify_production_baseline',side_effect=ValueError('private failure')):
            self.failure('BASELINE','PRODUCTION_BASELINE_FAILED')
        self.assertFalse(self.client.calls)

    def test_baseline_wrong_identity(self):
        for field, value in [('manifest_entry_count',199),('content_drift',True),('aggregate_sha256','wrong'),('schema_version',1)]:
            with self.subTest(field=field), patch.object(runner,'verify_production_baseline',return_value=dict(self.baseline,**{field:value})):
                self.failure('BASELINE','PRODUCTION_BASELINE_FAILED')
        self.assertFalse(self.client.calls)

    def test_multi_digest_rejected(self):
        with patch.object(runner,'plan_digest_articles',return_value=SimpleNamespace(digest_count=2,plans=(None,None))):
            self.failure('PLANNER','DAILY_RUN_MULTI_DIGEST_NOT_SUPPORTED')
        self.assertFalse(self.client.calls)

    def test_ai_failure(self):
        self.client.error=RuntimeError('private failure')
        self.failure('AI_GENERATION','DIGEST_AI_API_ERROR')
        self.assertEqual(1,len(self.client.calls))

    def test_http_429(self):
        error=RuntimeError('private billing body'); error.status_code=429
        self.client.error=error
        text=self.failure('AI_GENERATION','OPENAI_HTTP_429')
        self.assertIn('Billing',text)
        self.assertEqual(1,len(self.client.calls))

    def test_ai_entry_contract(self):
        mutations={
            'DIGEST_AI_ENTRY_MISSING': lambda p:p['sections'][0]['entries'].pop(),
            'DIGEST_AI_ENTRY_DUPLICATED': lambda p:p['sections'][0]['entries'].append(p['sections'][0]['entries'][0]),
            'DIGEST_AI_ENTRY_UNKNOWN': lambda p:p['sections'][0]['entries'][0].update(entry_id='unknown'),
            'DIGEST_AI_SUMMARY_TOO_SHORT': lambda p:p['sections'][0]['entries'][0].update(summary='短'),
            'DIGEST_AI_SUMMARY_TOO_LONG': lambda p:p['sections'][0]['entries'][0].update(summary='文'*181),
        }
        for code, mutation in mutations.items():
            with self.subTest(code=code):
                self.client=FakeClient(mutate=mutation)
                self.failure('AI_GENERATION',code,'--batch-id',code.lower())

    def test_audit_failure_blocks_preview(self):
        audit=SimpleNamespace(status='FAIL',errors=[SimpleNamespace(code='DIGEST_AUDIT_URL_MISMATCH')])
        with patch.object(runner,'audit_digest_article',return_value=audit), patch.object(runner,'create_local_digest_preview') as preview:
            self.failure('AUDIT','DIGEST_AUDIT_URL_MISMATCH')
            preview.assert_not_called()

    def test_preview_failure(self):
        with patch.object(runner,'create_local_digest_preview',side_effect=OSError('private failure')):
            self.failure('PREVIEW','DIGEST_PREVIEW_FAILED')

    def test_existing_run_never_overwritten_or_recalled(self):
        self.assertEqual(0,self.invoke()[0])
        snapshot={p:p.read_bytes() for p in self.root.glob('output/digest/**/*') if p.is_file()}
        self.failure('OUTPUT','DIGEST_OUTPUT_EXISTS')
        self.assertEqual(1,len(self.client.calls))
        self.assertTrue(all(p.read_bytes()==b for p,b in snapshot.items()))

    def test_existing_html_collision_before_ai(self):
        from digest_registry import build_digest_registry,parse_digest_file
        from digest_planner import plan_digest_articles
        reg=build_digest_registry(parse_digest_file(self.input))
        plan=plan_digest_articles(reg,batch_id='collision',digest_registry_version=reg.digest_registry_version,config_version=reg.config_version).plans[0]
        html=self.root/'output/digest/html'/(Path(plan.filename).stem+'.html')
        html.parent.mkdir(parents=True); html.write_text('human-reviewed',encoding='utf-8')
        self.failure('OUTPUT','DIGEST_OUTPUT_EXISTS','--batch-id','collision')
        self.assertEqual('human-reviewed',html.read_text('utf-8'))
        self.assertFalse(self.client.calls)

    def test_local_only_startup(self):
        with patch.object(runner.safety,'PRODUCT_MODE','PUBLIC'):
            self.failure('SAFETY','LOCAL_ONLY_REQUIRED')
        self.assertFalse(self.client.calls)

    def test_local_only_checked_again_before_ai(self):
        def baseline(_):
            runner.safety.PRODUCT_MODE='PUBLIC'
            return self.baseline
        with patch.object(runner.safety,'PRODUCT_MODE','LOCAL_ONLY'),patch.object(runner,'verify_production_baseline',side_effect=baseline):
            self.failure('SAFETY','LOCAL_ONLY_REQUIRED')
        self.assertFalse(self.client.calls)

    def test_secret_not_in_errors_or_evidence(self):
        self.client.error=RuntimeError('offline-test-value confidential response')
        text=self.failure('AI_GENERATION','DIGEST_AI_API_ERROR')
        self.assertNotIn('offline-test-value',text)
        for p in self.root.glob('output/digest/**/*.json'):
            self.assertNotIn('offline-test-value',p.read_text('utf-8'))

    def test_secret_in_ai_response_rejected(self):
        self.client.mutate=lambda p:p['sections'][0]['entries'][0].update(summary=SUMMARY+'offline-test-value')
        self.failure('AI_GENERATION','DIGEST_AI_CONTENT_LEAKAGE')
        self.assertFalse(list(self.root.glob('output/digest/html/*')))

    def test_url_in_title_not_sent_to_ai(self):
        self.input.write_text(self.input.read_text('utf-8').replace('社区生活观察0','https://example.net/private'),encoding='utf-8')
        self.failure('AI_GENERATION','DIGEST_AI_CONTENT_LEAKAGE')
        self.assertFalse(self.client.calls)

    def test_invalid_batch_path(self):
        self.failure('PLANNER','INVALID_DAILY_BATCH_ID','--batch-id','../escape')
        self.assertFalse(self.client.calls)

    def test_argparse_fail_closed(self):
        self.failure('ARGUMENTS','INVALID_ARGUMENTS','--publish')

    def test_generated_paths_ignored_in_repository(self):
        import subprocess
        root=Path(__file__).resolve().parent.parent
        result=subprocess.run(['git','-C',str(root),'check-ignore','output/digest/markdown/check.md','output/digest/html/check.html','output/digest/evidence/check/run-result.json'],capture_output=True)
        self.assertEqual(0,result.returncode)
        self.assertEqual(3,len(result.stdout.splitlines()))

    def test_request_adapter_caps_calls(self):
        client=SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: SimpleNamespace(output_text='{}')))
        adapter=runner.SingleCall(client,'offline-test-value')
        adapter.create(input='safe')
        with self.assertRaises(ValueError):
            adapter.create(input='safe')
        self.assertEqual(1,adapter.count)
        self.assertEqual('OPENAI_CALL_LIMIT',adapter.error_code)

    def test_credential_in_input_never_written(self):
        self.input.write_text(self.input.read_text('utf-8').replace('/News/','/offline-test-value/'),encoding='utf-8')
        self.failure('INPUT','DIGEST_INPUT_SENSITIVE_CONTENT')
        self.assertFalse(self.client.calls)
        self.assertFalse(list(self.root.glob('output/digest/**/*')))

    def test_credential_in_batch_never_written(self):
        self.failure('PLANNER','INVALID_DAILY_BATCH_ID','--batch-id','offline-test-value')
        self.assertFalse(list(self.root.glob('output/digest/**/*')))

    def test_evidence_write_failure_has_no_success(self):
        original=Path.open
        def fail_evidence(path,*args,**kwargs):
            if path.name=='run-result.json':
                raise PermissionError('private evidence detail')
            return original(path,*args,**kwargs)
        with patch.object(Path,'open',fail_evidence):
            text=self.failure('EVIDENCE','DIGEST_EVIDENCE_FAILED')
        self.assertNotIn('DIGEST_RUN_RESULT=PASS',text)

    def test_ignore_failure_prevents_ai(self):
        with patch.object(runner,'assert_ignored',side_effect=runner.RunFailure('SAFETY','DIGEST_OUTPUT_NOT_IGNORED','Restore protection.')):
            self.failure('SAFETY','DIGEST_OUTPUT_NOT_IGNORED')
        self.assertFalse(self.client.calls)

    def test_client_creation_failure_is_safe(self):
        with patch.object(runner,'create_client',side_effect=RuntimeError('offline-test-value private')):
            text=self.failure('AI_GENERATION','DIGEST_AI_API_ERROR')
        self.assertNotIn('offline-test-value',text)
        self.assertFalse(self.client.calls)

    def test_invalid_utf8_is_input_failure(self):
        self.input.write_bytes(b'\xff\xfe\x00')
        self.failure('INPUT','INVALID_DIGEST_INPUT_FORMAT')


if __name__ == '__main__':
    unittest.main()
