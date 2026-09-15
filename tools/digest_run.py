"""Single-Digest local CLI. Frozen modules own all content contracts."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import subprocess

import local_only_safety as safety
from digest_registry import parse_digest_file, build_digest_registry, DigestContractError
from digest_planner import plan_digest_articles, DigestPlannerError
from digest_generator import generate_digest_content, render_digest_markdown, DigestGenerationError, DigestRenderError
from digest_audit import audit_digest_article
from digest_local_preview import create_local_digest_preview
from production_baseline import verify_production_baseline

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXPECTED_AGGREGATE = '4b00fd598a3a74c018e6e577575f79b959cda228a17ebfa447c85425a9fc7064'


class RunFailure(ValueError):
    def __init__(self, stage, code, message):
        self.stage, self.code, self.message = stage, code, message
        super().__init__(code)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise RunFailure('ARGUMENTS', 'INVALID_ARGUMENTS', 'Use --input <file> and optional --batch-id <name>.')


def require_local():
    if safety.PRODUCT_MODE != 'LOCAL_ONLY':
        raise RunFailure('SAFETY', 'LOCAL_ONLY_REQUIRED', 'This runner requires LOCAL_ONLY mode.')
    try:
        safety.assert_publication_candidate(PROJECT_ROOT, 'output/digest/markdown/check.md', 'stage')
    except safety.LocalOnlySafetyError as exc:
        if exc.code == 'LOCAL_ONLY_PUBLICATION_VIOLATION':
            return
    raise RunFailure('SAFETY', 'LOCAL_ONLY_REQUIRED', 'Generated content publication must be blocked.')


def assert_ignored(paths):
    result = subprocess.run(
        ['git', '-C', str(PROJECT_ROOT), 'check-ignore', '-z', '--stdin'],
        input=b'\0'.join(str(p).encode('utf-8') for p in paths) + b'\0',
        capture_output=True, check=False,
    )
    if result.returncode != 0 or len(result.stdout.split(b'\0')) - 1 != len(paths):
        raise RunFailure('SAFETY', 'DIGEST_OUTPUT_NOT_IGNORED', 'Restore output/digest ignore protection before running.')


def create_client(secret):
    # Same Responses SDK and direct transport used by the validated local run.
    import httpx
    from openai import OpenAI
    return OpenAI(
        api_key=secret, base_url='https://api.openai.com/v1', max_retries=0,
        organization=None, project=None, timeout=300,
        http_client=httpx.Client(transport=httpx.HTTPTransport(retries=0, trust_env=False),
                                follow_redirects=False, trust_env=False, timeout=300),
    )


@contextmanager
def quiet_libraries():
    # Do not let SDK debug logging or exception bodies expose runtime secrets.
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        logging.disable(previous)


class SingleCall:
    def __init__(self, client, secret):
        self.client, self.secret = client, secret
        self.responses = self
        self.count = 0
        self.error_code = None

    def create(self, **kwargs):
        prompt = kwargs.get('input', '')
        if self.count or self.secret in prompt or re.search(r'https?://', prompt, re.I):
            self.error_code = 'DIGEST_AI_CONTENT_LEAKAGE' if not self.count else 'OPENAI_CALL_LIMIT'
            raise ValueError('Request blocked')
        self.count += 1
        try:
            response = self.client.responses.create(**kwargs)
        except Exception as exc:
            if getattr(exc, 'status_code', None) == 429:
                self.error_code = 'OPENAI_HTTP_429'
            raise
        if self.secret in (getattr(response, 'output_text', '') or ''):
            self.error_code = 'DIGEST_AI_CONTENT_LEAKAGE'
            raise ValueError('Response blocked')
        return response


def main(argv=None):
    stage = 'ARGUMENTS'
    evidence_path = None
    client = adapter = None
    secret = os.environ.get('OPENAI_API_KEY', '').strip()
    record = {'batch_id': None, 'input_path': None, 'input_sha256': None, 'entry_count': 0,
              'registry_version': None, 'plan_hash': None, 'ai_call_count': 0,
              'audit_status': 'NOT_RUN', 'markdown_path': None, 'html_path': None,
              'final_state': 'FAILED'}
    failure = None
    try:
        parser = Parser(description='Generate one local Digest; open the HTML path after success.')
        parser.add_argument('--input', required=True, type=Path)
        parser.add_argument('--batch-id')
        args = parser.parse_args(argv)
        stage = 'SAFETY'
        require_local()
        stage = 'INPUT'
        input_path = args.input.resolve()
        digest = hashlib.sha256(input_path.read_bytes()).hexdigest()
        registry = build_digest_registry(parse_digest_file(input_path))
        if hashlib.sha256(input_path.read_bytes()).hexdigest() != digest:
            raise RunFailure(stage, 'DIGEST_INPUT_CHANGED', 'Input changed during reading; stop and check the file.')
        record.update(input_path=str(input_path), input_sha256=digest, entry_count=len(registry.entries),
                      registry_version=registry.digest_registry_version)
        if secret and any(secret in e.title or secret in e.url_exact for e in registry.entries):
            raise RunFailure(stage, 'DIGEST_INPUT_SENSITIVE_CONTENT', 'Remove sensitive content from the input before running.')
        stage = 'PLANNER'
        batch_id = args.batch_id or 'daily-' + registry.digest_registry_version.split(':')[-1]
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', batch_id):
            raise RunFailure(stage, 'INVALID_DAILY_BATCH_ID', 'Batch name must be 1-80 ASCII letters, digits, hyphens or underscores.')
        if secret and secret in batch_id:
            raise RunFailure(stage, 'INVALID_DAILY_BATCH_ID', 'Do not include sensitive content in batch names.')
        record['batch_id'] = batch_id
        batch = plan_digest_articles(registry, batch_id=batch_id,
                                    digest_registry_version=registry.digest_registry_version,
                                    config_version=registry.config_version)
        if batch.digest_count != 1 or len(batch.plans) != 1:
            raise RunFailure(stage, 'DAILY_RUN_MULTI_DIGEST_NOT_SUPPORTED', 'This runner supports one Digest only.')
        plan = batch.plans[0]
        record['plan_hash'] = plan.plan_hash
        stage = 'BASELINE'
        baseline = verify_production_baseline(PROJECT_ROOT)
        if not (baseline.get('status') == 'PASS' and baseline.get('schema_version') == 2
                and baseline.get('algorithm_version') == 'git-content-sha256-manifest-v1'
                and baseline.get('manifest_entry_count') == 200 and baseline.get('content_drift') is False
                and baseline.get('aggregate_sha256') == EXPECTED_AGGREGATE):
            raise RunFailure(stage, 'PRODUCTION_BASELINE_FAILED', 'Production baseline must pass before generation.')
        stage = 'CREDENTIAL'
        if not secret:
            raise RunFailure(stage, 'OPENAI_RUNTIME_CREDENTIAL_UNAVAILABLE', 'Set the process credential environment variable before running.')
        stage = 'OUTPUT'
        def output_path(relative):
            return safety.assert_digest_output_path(PROJECT_ROOT, 'output/digest/' + relative)
        markdown = output_path('markdown/' + plan.filename)
        html = output_path('html/' + Path(plan.filename).stem + '.html')
        preview_record = output_path('evidence/' + Path(plan.filename).stem + '.json')
        destination = output_path('evidence/' + batch_id + '/run-result.json')
        lock = output_path('evidence/.' + Path(plan.filename).stem + '.lock')
        paths = [markdown, html, preview_record, destination, lock]
        assert_ignored(paths)
        if any(p.exists() or p.is_symlink() for p in paths) or destination.parent.exists():
            raise RunFailure(stage, 'DIGEST_OUTPUT_EXISTS', 'Existing output or run reservation found; nothing overwritten. Review the previous run.')
        record.update(markdown_path=str(markdown), html_path=str(html))
        # Exclusive reservations prevent concurrent runners sharing output names.
        destination.parent.mkdir(parents=True, exist_ok=False)
        evidence_path = destination
        with lock.open('x', encoding='utf-8') as stream:
            stream.write(batch_id)
        stage = 'SAFETY'
        require_local()
        stage = 'AI_GENERATION'
        with quiet_libraries():
            client = create_client(secret)
            adapter = SingleCall(client, secret)
            generated = generate_digest_content(plan=plan, registry=registry, client=adapter, max_attempts=1)
        stage = 'RENDERER'
        published_date = date.today().isoformat()
        rendered = render_digest_markdown(plan=plan, registry=registry, generated_content=generated, published_date=published_date)
        stage = 'AUDIT'
        audit = audit_digest_article(registry=registry, plan=plan, generated_content=generated,
                                     render_result=rendered, published_date=published_date)
        record['audit_status'] = audit.status
        if audit.status != 'PASS':
            code = audit.errors[0].code if audit.errors else 'DIGEST_AUDIT_FAILED'
            raise RunFailure(stage, code, 'Audit failed; HTML preview was not created.')
        record['summary_warnings'] = len(audit.warnings)
        stage = 'OUTPUT'
        if any(p.exists() or p.is_symlink() for p in (markdown, html, preview_record)):
            raise RunFailure(stage, 'DIGEST_OUTPUT_EXISTS', 'Output appeared during generation; nothing overwritten.')
        stage = 'PREVIEW'
        preview = create_local_digest_preview(project_root=PROJECT_ROOT, filename=plan.filename,
                                              markdown=rendered.markdown, audit_status=audit.status)
        if preview.clickable_href_count != len(registry.entries):
            raise RunFailure(stage, 'DIGEST_PREVIEW_FAILED', 'Preview link count does not match input.')
        record['final_state'] = 'PENDING_MANUAL_REVIEW'
    except RunFailure as exc:
        failure = exc
    except (DigestContractError, DigestPlannerError, DigestGenerationError, DigestRenderError) as exc:
        code = adapter.error_code if adapter and adapter.error_code else exc.code
        message = 'Check API Billing / Rate Limit; no retry was performed.' if code == 'OPENAI_HTTP_429' else 'Check the input or result against the reported contract error; no automatic retry.'
        failure = RunFailure(stage, code, message)
    except safety.LocalOnlySafetyError:
        failure = RunFailure('SAFETY', 'LOCAL_ONLY_REQUIRED', 'Output must stay inside the local Digest area.')
    except Exception:
        code = {'INPUT': 'DIGEST_INPUT_UNREADABLE', 'BASELINE': 'PRODUCTION_BASELINE_FAILED',
                'PREVIEW': 'DIGEST_PREVIEW_FAILED', 'AI_GENERATION': 'DIGEST_AI_API_ERROR',
                'OUTPUT': 'DIGEST_OUTPUT_UNAVAILABLE'}.get(stage, 'DIGEST_RUN_FAILED')
        failure = RunFailure(stage, code, 'Operation failed; check input, local paths and runtime dependencies. No retry was performed.')
    finally:
        if client is not None:
            with quiet_libraries():
                try:
                    client.close()
                except Exception:
                    pass
    record['ai_call_count'] = adapter.count if adapter else 0
    if failure:
        record.update(final_state='FAILED', stage=failure.stage, error_code=failure.code)
    def safe_text(text):
        return text.replace(secret, '[REDACTED]') if secret else text
    if evidence_path is not None:
        try:
            with evidence_path.open('x', encoding='utf-8') as stream:
                stream.write(safe_text(json.dumps(record, ensure_ascii=False, indent=2)) + '\n')
        except Exception:
            failure = RunFailure('EVIDENCE', 'DIGEST_EVIDENCE_FAILED', 'Could not save local run evidence; no success is declared.')
    if failure:
        print(safe_text(f'DIGEST_RUN_RESULT=FAIL\nSTAGE={failure.stage}\nERROR_CODE={failure.code}\nMESSAGE={failure.message}'))
        return 1
    print(safe_text(f'DIGEST_RUN_RESULT=PASS\nENTRIES={record["entry_count"]}\nMARKDOWN={record["markdown_path"]}\nHTML={record["html_path"]}\nAUDIT=PASS\nCLICKABLE_HREF={record["entry_count"]}/{record["entry_count"]}\nFINAL_STATE=PENDING_MANUAL_REVIEW'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
