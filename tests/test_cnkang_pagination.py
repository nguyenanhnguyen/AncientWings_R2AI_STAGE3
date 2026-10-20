"""F2/F3: full articles, real 26-page replay, crash/resume and adversarial audit."""
from contextlib import redirect_stdout
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import cnkang
import cnkang_transport as transport

ARTICLE = transport.ARTICLE
FIXTURES = ROOT/'tests/fixtures/cnkang_pagination'
CHAINS = json.loads((FIXTURES/'manifest.json').read_text(encoding='utf-8'))
BASE = 'https://www.cnkang.com/myjk/202001/123.html'


def synthetic(number=1, *, title='测试正文标题', date='2020-01-02', body=None, next_href=None, total=2):
    body = body or (f'<p>页面{number}。这是一段完整的测试正文，保持医学数字与内容顺序。' + '测试内容。'*45 + '</p>')
    links = ''
    if number > 1: links += f'<a href="123{("_"+str(number-1)) if number>2 else ""}.html">上一页</a>'
    links += ''.join(f'<a href="123{"_"+str(i) if i>1 else ""}.html">{i}</a>' for i in range(1, total+1))
    if next_href is not None: links += f'<a href="{next_href}">下一页</a>'
    return (f'<html><meta charset="utf-8"><title>{title}</title><div class="detail">'
            f'<h1 class="detaila">{title}</h1><div class="detailb">{date}</div>'
            f'<div class="detailc">{body}</div><div class="pageStyle"><p>{links}</p></div>'
            '</div></html>').encode()


def reply(body, status=200, headers=None):
    result = transport.requests.Response()
    result.status_code, result._content = status, body
    result.headers.update(headers or {'Content-Type': 'text/html; charset=utf-8'})
    return result


class Crash(BaseException): pass


class PaginationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/'tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sample = {'id': 1, 'ids': [1], 'url': BASE, 'source_url': BASE,
                       'canonical_url': ARTICLE.key(BASE), 'branch': 'myjk'}

    def net(self, config=None):
        net = transport.Transport(self.root, config)
        self.addCleanup(net.close)
        for name, options in [('wait', {}), ('robot_policy', {'return_value': {'allowed': True, 'status': 'checked'}})]:
            p = patch.object(net, name, **options)
            p.start()
            self.addCleanup(p.stop)
        return net

    def fetch(self, pages, config=None, sample=None):
        net = self.net(config)
        def get(url):
            value = pages[ARTICLE.key(url)]
            return value if isinstance(value, transport.requests.Response) else reply(value)
        with patch.object(net, 'get', side_effect=get) as get:
            record = net.fetch(sample or self.sample)
        return net, record, get

    def audit(self, record):
        return cnkang.audit((self.root/record['raw_html_path']).read_bytes(), record['final_url'],
                            record, record['content_type'], base_dir=self.root)

    def normal_pages(self):
        return {ARTICLE.key(BASE): synthetic(next_href='123_2.html'),
                ARTICLE.key(BASE.replace('.html', '_2.html')): synthetic(2)}

    def test_real_nine_chains_26_pages_match_original_9723_chars_and_five_pagers(self):
        mapping = {ARTICLE.key(p['url']): reply((FIXTURES/p['file']).read_bytes(),
                                               headers={'Content-Type': p['content_type']})
                   for chain in CHAINS for p in chain['pages']}
        net, chars, pages, pagers = self.net(), 0, 0, 0
        with patch.object(net, 'get', side_effect=lambda url: mapping[ARTICLE.key(url)]) as get:
            for chain in CHAINS:
                sample = {'id': chain['id'], 'url': chain['url'], 'canonical_url': ARTICLE.key(chain['url'])}
                record = net.fetch(sample)
                self.assertTrue(record['article_complete'])
                self.assertEqual(record['article_page_count'], len(chain['pages']))
                self.assertEqual(record['text_sha256'], chain['experiment_merged_sha256'])
                self.assertTrue(self.audit(record)['cnkang_article_verified'])
                chars += record['chars_after']
                pages += record['article_page_count']
                pagers += sum(a.get('action') == 'remove_verified_pager' for a in record['cleaning_actions'])
        self.assertEqual((chars, pages, pagers), (9723, 26, 5))
        self.assertEqual(get.call_count, 26)
        self.assertEqual(len(list((self.root/'records').glob('*.json'))), 9)

    def test_exact_overlap_only_and_short_components_rechecked_as_full_article(self):
        overlap = '这是两页共同出现的完整段落，超过二十个字符且必须精确匹配。'
        body1, body2 = '<p>第一部分。</p><p>'+overlap+'</p>', '<p>'+overlap+'</p><p>'+'后续内容。'*45+'</p>'
        pages = {ARTICLE.key(BASE): synthetic(body=body1, next_href='123_2.html'),
                 ARTICLE.key(BASE.replace('.html', '_2.html')): synthetic(2, body=body2)}
        net, record, get = self.fetch(pages)
        self.assertTrue(record['article_complete'])
        self.assertEqual(record['text'].count(overlap), 1)
        self.assertEqual(record['article_overlaps'][1]['paragraphs'], 1)
        self.assertNotIn('SHORT_TEXT_REVIEW', record['parser_flags'])
        self.assertNotIn('PAGINATION_REVIEW', record['parser_flags'])
        self.audit(record)

    def test_next_wrong_host_query_path_jump_or_untrusted_scope_never_fetched(self):
        for href in ('https://evil.example/123_2.html', '999_2.html', '123_3.html',
                     '123.html', '123_2.html?other=1'):
            with self.subTest(href=href):
                raw = synthetic(next_href=href)
                net = self.net()
                sample = dict(self.sample, id=100+len(list((self.root/'records').glob('*.json'))))
                with patch.object(net, 'get', return_value=reply(raw)) as get:
                    record = net.fetch(sample)
                net.close()
                self.assertFalse(record['article_complete'])
                self.assertEqual(record['quality_status'], 'review')
                self.assertEqual(get.call_count, 1)
                self.audit(record)

    def test_title_date_template_and_repeated_body_rejected_before_merge(self):
        for kind in ('title', 'date', 'template', 'body'):
            with self.subTest(kind=kind):
                first = synthetic(next_href='123_2.html')
                following = synthetic(2, title='另一个标题' if kind == 'title' else '测试正文标题',
                                      date='2020-01-03' if kind == 'date' else '2020-01-02')
                if kind == 'template':
                    following = following.replace(b'class="detailc"', b'id="endText"')
                if kind == 'body':
                    following = following.replace('页面2'.encode(), '页面1'.encode())
                net = self.net()
                sample = dict(self.sample, id=200+len(list((self.root/'records').glob('*.json'))))
                mapping = {ARTICLE.key(BASE): first, ARTICLE.key(BASE.replace('.html', '_2.html')): following}
                with patch.object(net, 'get', side_effect=lambda u: reply(mapping[ARTICLE.key(u)])):
                    record = net.fetch(sample)
                net.close()
                self.assertFalse(record['article_complete'])
                self.assertEqual(record['article_page_count'], 1)
                self.assertIn('ARTICLE_INCOMPLETE_REVIEW', record['parser_flags'])
                self.audit(record)

    def test_numeric_pager_prevents_false_complete_when_next_link_missing(self):
        net, record, get = self.fetch({ARTICLE.key(BASE): synthetic(total=3)})
        self.assertFalse(record['article_complete'])
        self.assertEqual(record['article_reason'], 'missing_next_link')
        get.assert_called_once()
        self.audit(record)

    def test_unsupported_source_url_is_durable_review_and_never_follows(self):
        url = BASE + '?other=1'
        net = self.net()
        with patch.object(net, 'get', return_value=reply(synthetic(next_href='123_2.html'))) as get:
            record = net.fetch(dict(self.sample, url=url, source_url=url))
        self.assertEqual(record['article_reason'], 'unsafe_or_unknown_page_url')
        self.assertFalse(record['article_complete'])
        self.assertEqual(record['quality_status'], 'review')
        get.assert_called_once()
        self.audit(record)

    def test_untrusted_scope_unknown_layout_and_redirect_do_not_fetch_foreign_page(self):
        for kind in ('scope', 'unknown', 'redirect'):
            with self.subTest(kind=kind):
                self.root = self.root/kind
                raw = synthetic(next_href='123_2.html')
                if kind == 'scope': raw = raw.replace(b'class="pageStyle"', b'class="sidebar"')
                if kind == 'unknown': raw = raw.replace(b'class="detailc"', b'class="unverified"')
                net = self.net()
                def response(url):
                    if ARTICLE.identity(url)[2] == 1: return reply(raw)
                    return reply(b'', 302, {'Location': 'https://evil.example/other.html'})
                with patch.object(net, 'get', side_effect=response) as get:
                    record = net.fetch(self.sample)
                self.assertFalse(record['article_complete'])
                self.assertEqual(get.call_count, 2 if kind == 'redirect' else 1)
                self.assertTrue(all('evil.example' not in c.args[0] for c in get.call_args_list))
                self.audit(record)
                net.close()

    def test_missing_first_date_does_not_allow_inconsistent_later_dates(self):
        pages = {ARTICLE.key(BASE): synthetic(date='', total=3, next_href='123_2.html'),
                 ARTICLE.key(BASE.replace('.html', '_2.html')): synthetic(2, total=3, next_href='123_3.html'),
                 ARTICLE.key(BASE.replace('.html', '_3.html')): synthetic(3, total=3, date='2020-01-03')}
        net, record, get = self.fetch(pages)
        self.assertFalse(record['article_complete'])
        self.assertEqual(record['article_page_count'], 2)
        self.assertEqual(record['article_reason'], 'page_date_mismatch')
        self.audit(record)

    def test_manifest_cannot_be_removed_to_publish_first_page_as_complete(self):
        net, record, get = self.fetch(self.normal_pages())
        changed = cnkang.extract((self.root/record['raw_html_path']).read_bytes(), BASE)
        changed.update(id=1, engine='requests', article_complete=True, quality_status='accepted')
        with self.assertRaisesRegex(ValueError, 'full article manifest'):
            cnkang.audit((self.root/record['raw_html_path']).read_bytes(), BASE, changed, base_dir=self.root)

    def test_check_export_audits_all_extracted_records_even_without_manifest(self):
        import cnkang_check
        net, record, get = self.fetch(self.normal_pages())
        cnkang_check.export(self.root, [self.sample])
        raw = (self.root/record['raw_html_path']).read_bytes()
        changed = dict(record, **cnkang.extract(raw, BASE), article_complete=True)
        changed.pop('article_manifest_path')
        changed.pop('article_manifest_sha256')
        transport.write_json(self.root/'records/1.json', changed)
        with self.assertRaisesRegex(ValueError, 'full article manifest'):
            cnkang_check.export(self.root, [self.sample])

    def test_article_budget_expiry_preserves_first_page_and_never_gets_next(self):
        net = self.net()
        original = net.budget
        def budget(stage):
            if stage == 'article_page':
                net._article_limit = transport.NETWORK.deadline(-1)
            return original(stage)
        with patch.object(net, 'get', return_value=reply(synthetic(next_href='123_2.html'))) as get, \
                patch.object(net, 'budget', side_effect=budget):
            record = net.fetch(self.sample)
        self.assertFalse(record['article_complete'])
        self.assertEqual(record['article_reason'], 'article_deadline')
        self.assertTrue(record['retry_deferred'])
        get.assert_called_once()
        self.audit(record)

    def test_noninitial_corpus_url_keeps_id_and_never_claims_full_article(self):
        url = BASE.replace('.html', '_2.html')
        net, record, get = self.fetch({ARTICLE.key(url): synthetic(2)}, sample=dict(self.sample, url=url, source_url=url))
        self.assertEqual((record['id'], record['url']), (1, url))
        self.assertFalse(record['article_complete'])
        self.assertEqual(record['article_reason'], 'source_is_not_first_page')
        get.assert_called_once()
        self.audit(record)

    def test_page_cap_partial_is_not_accepted_and_resume_reuses_first(self):
        net, partial, get = self.fetch(self.normal_pages(), {'max_pages': 1})
        self.assertFalse(partial['article_complete'])
        self.assertTrue(partial['retry_deferred'])
        self.assertEqual(get.call_count, 1)
        old_manifest = (self.root/partial['article_manifest_path']).read_bytes()
        net.close()
        resumed = self.net({'max_pages': 6})
        with patch.object(resumed, 'get', return_value=reply(synthetic(2))) as get:
            complete = resumed.fetch(self.sample)
        self.assertEqual(get.call_count, 1)
        self.assertEqual(ARTICLE.identity(get.call_args.args[0])[2], 2)
        self.assertTrue(complete['article_complete'])
        self.assertEqual((self.root/partial['article_manifest_path']).read_bytes(), old_manifest)
        self.audit(complete)

    def test_failure_mid_chain_then_resume_never_refetches_completed_pages(self):
        pages = self.normal_pages()
        pages[ARTICLE.key(BASE.replace('.html', '_2.html'))] = reply(b'busy', 503)
        net, partial, get = self.fetch(pages, {'attempts': 1})
        self.assertFalse(partial['article_complete'])
        self.assertEqual(partial['article_failure']['http_status'], 503)
        self.audit(partial)
        net.close()
        resumed = self.net({'attempts': 1})
        with patch.object(resumed, 'get', return_value=reply(synthetic(2))) as get:
            complete = resumed.fetch(self.sample)
        self.assertTrue(complete['article_complete'])
        self.assertEqual(get.call_count, 1)
        self.audit(complete)

    def test_crash_after_second_page_commit_reuses_it_on_restart(self):
        chain = CHAINS[1]
        mapping = {ARTICLE.key(p['url']): reply((FIXTURES/p['file']).read_bytes(),
                                               headers={'Content-Type': p['content_type']}) for p in chain['pages']}
        sample = {'id': chain['id'], 'url': chain['url'], 'canonical_url': ARTICLE.key(chain['url'])}
        net = self.net()
        original = transport.STORAGE.os.replace
        second = cnkang.sha(ARTICLE.key(chain['pages'][1]['url'])) + '.json'
        def replace(source, target):
            result = original(source, target)
            if Path(target).parent.name == 'cnkang_pages' and Path(target).name == second:
                raise Crash()
            return result
        with patch.object(net, 'get', side_effect=lambda u: mapping[ARTICLE.key(u)]), \
                patch.object(transport.STORAGE.os, 'replace', side_effect=replace):
            with self.assertRaises(Crash): net.fetch(sample)
        net.close()
        resumed = self.net()
        with patch.object(resumed, 'get', side_effect=lambda u: mapping[ARTICLE.key(u)]) as get:
            result = resumed.fetch(sample)
        self.assertTrue(result['article_complete'])
        self.assertEqual([ARTICLE.identity(c.args[0])[2] for c in get.call_args_list], [3])
        self.audit(result)

    def test_missing_raw_changed_text_order_or_complete_flag_fails_audit(self):
        net, record, get = self.fetch(self.normal_pages())
        for field, value in [('text', record['text']+'changed'), ('article_complete', False),
                             ('article_overlaps', []), ('quality_status', 'review')]:
            changed = copy.deepcopy(record)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): self.audit(changed)
        path = self.root/record['article_manifest_path']
        original = path.read_bytes()
        manifest = json.loads(original)
        for transform in ('order', 'missing'):
            changed = copy.deepcopy(manifest)
            if transform == 'order': changed['parts'].reverse()
            else: changed['parts'].pop()
            path.write_text(json.dumps(changed), encoding='utf-8')
            modified = dict(record, article_manifest_sha256=cnkang.sha(path.read_bytes()))
            with self.subTest(transform=transform), self.assertRaises(ValueError): self.audit(modified)
        path.write_bytes(original)
        raw = self.root/manifest['parts'][1]['raw_path']
        data = raw.read_bytes()
        raw.unlink()
        with self.assertRaises(FileNotFoundError): self.audit(record)
        raw.write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'run directory'):
            cnkang.audit((self.root/record['raw_html_path']).read_bytes(), record['final_url'], record)

    def test_max_new_counts_source_records_not_pages(self):
        mapping = self.normal_pages()
        published = Mock()
        with patch.object(transport.Transport, 'wait'), \
                patch.object(transport.Transport, 'robot_policy', return_value={'allowed': True, 'status': 'checked'}), \
                patch.object(transport.Transport, 'get', side_effect=lambda u: reply(mapping[ARTICLE.key(u)])):
            count = transport.crawl(None, None, self.root, [self.sample, dict(self.sample, id=2)],
                                    max_new=1, on_record=published)
        self.assertEqual(count, 1)
        published.assert_called_once()
        self.assertEqual(published.call_args.args[0]['article_page_count'], 2)
        self.assertEqual(len(list((self.root/'requests_records').glob('*.json'))), 1)

    def test_recovery_copies_every_raw_and_reextracts_without_network(self):
        net, record, _ = self.fetch(self.normal_pages())
        net.close()
        destination = self.root/'recovered'
        with patch.object(transport.NETWORK.NetworkWorker, 'get', side_effect=AssertionError('network in recovery')):
            result = transport.seed_recovery(destination, [self.sample], self.root)
        self.assertEqual(result['reused_ids'], [1])
        recovered = json.loads((destination/'requests_records/1.json').read_text(encoding='utf-8'))
        self.assertTrue(recovered['article_complete'])
        self.assertEqual(recovered['text_sha256'], record['text_sha256'])
        self.assertTrue(transport.audit_saved(destination, recovered)['cnkang_article_verified'])
        # Evidence is self-contained after moving/copying the recovered run.
        self.assertNotIn(str(self.root), (destination/recovered['article_manifest_path']).read_text(encoding='utf-8'))

    def test_offline_recovery_with_missing_part_remains_incomplete_without_get(self):
        net, partial, _ = self.fetch(self.normal_pages(), {'max_pages': 1})
        net.close()
        destination = self.root/'recovered'
        with patch.object(transport.NETWORK.NetworkWorker, 'get', side_effect=AssertionError('network in recovery')):
            transport.seed_recovery(destination, [self.sample], self.root)
        recovered = json.loads((destination/'requests_records/1.json').read_text(encoding='utf-8'))
        self.assertFalse(recovered['article_complete'])
        self.assertEqual(recovered['article_reason'], 'offline_missing_page')
        self.assertEqual(recovered['quality_status'], 'review')
        self.assertTrue(transport.audit_saved(destination, recovered)['cnkang_article_verified'])

    def test_changed_next_raw_or_member_checkpoint_cannot_be_published(self):
        net, record, _ = self.fetch(self.normal_pages())
        manifest = json.loads((self.root/record['article_manifest_path']).read_text())
        part = manifest['parts'][1]
        checkpoint = self.root/part['checkpoint_path']
        data = checkpoint.read_bytes()
        changed = json.loads(data)
        changed['text'] = '伪造正文'
        checkpoint.write_text(json.dumps(changed), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'checkpoint hash'):
            transport.audit_saved(self.root, record)
        checkpoint.write_bytes(data)
        self.assertTrue(transport.audit_saved(self.root, record)['cnkang_article_verified'])

    def test_403_blocks_followup_without_fallback_and_429_preserves_cooldown(self):
        original_root = self.root
        for code in (403, 429):
            with self.subTest(code=code):
                self.root = original_root / str(code)
                net = self.net({'attempts': 1})
                sample = dict(self.sample, id=code)
                pages = self.normal_pages()
                pages[ARTICLE.key(BASE.replace('.html', '_2.html'))] = reply(
                    b'blocked', code, {'Retry-After': '600', 'Content-Type': 'text/html'})
                with patch.object(net, 'get', side_effect=lambda u: (
                        pages[ARTICLE.key(u)] if isinstance(pages[ARTICLE.key(u)], transport.requests.Response)
                        else reply(pages[ARTICLE.key(u)]))) as get:
                    record = net.fetch(sample)
                net.close()
                self.assertFalse(record['article_complete'])
                self.assertTrue(all(call.args[0].startswith('https:') for call in get.call_args_list))
                self.assertEqual(record['article_failure']['http_status'], code)
                if code == 429:
                    import time
                    self.assertGreater(transport.STORAGE.load_state(
                        self.root/'cnkang_transport_state.json')['not_before'], time.time()+590)
                self.audit(record)
        self.root = original_root


if __name__ == '__main__': unittest.main()
