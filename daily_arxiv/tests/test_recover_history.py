import json
import sys
import tempfile
import unittest
from pathlib import Path

from scrapy.http import HtmlResponse
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from recover_history import collect, completed_ids, detail_item, listing_ids, merge_day


def response(html, url='https://arxiv.org/list/cs.RO/recent'):
    return HtmlResponse(url=url, body=html.encode(), encoding='utf-8')


def listing(ids):
    return response(f'<h3>Wed, 14 Oct 2026 (showing {len(ids)} of {len(ids)} entries)</h3><dl>' + ''.join(
        f'<dt><a name="item{i}"></a><a title="Abstract" href="/abs/{pid}"></a></dt>'
        for i, pid in enumerate(ids, 1)) + '</dl>')


def row(pid, score=0):
    return {'id': pid, 'AI': dict.fromkeys(['tldr','motivation','method','result','conclusion'], 'valid') | {'score':score}}


class RecoveryTests(unittest.TestCase):
    def test_low_score_complete_and_failure_retry(self):
        with tempfile.TemporaryDirectory() as d:
            failed=row('2'); failed['AI']['tldr']='Processing failed'
            Path(d,'old_AI_enhanced_Chinese.jsonl').write_text('\n'.join(map(json.dumps,[row('1v2'),failed])))
            self.assertEqual(completed_ids(d,'Chinese'),{'1'})

    def test_partial_listing_fails(self):
        with self.assertRaises(ValueError):
            listing_ids(response('<h3>showing 1 of 2 entries</h3><dl><dt></dt></dl>'),'recent')

    def test_cross_lists_included_replacements_excluded(self):
        html='<div id="dlpage"><ul><a href="#item3">Replacements</a></ul></div>'+listing(['1','2','3']).text
        self.assertEqual(listing_ids(response(html),'new'),['1','2'])

    def test_detail_requires_summary(self):
        with self.assertRaises(ValueError):
            detail_item(response(''), '1')

    def test_collect_deduplicates_and_preserves_output_on_failure(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d,'old_AI_enhanced_Chinese.jsonl').write_text(json.dumps(row('1')))
            output=Path(d,'out.jsonl'); output.write_text('original')
            calls=[]
            def fetch(url):
                calls.append(url)
                if '/list/' in url:return listing(['1'] if '/new?' in url else ['1','2','2'])
                raise RuntimeError('request failure')
            with self.assertRaises(RuntimeError): collect(['cs.RO'],d,'Chinese',output,fetch)
            self.assertEqual(output.read_text(),'original')
            self.assertEqual(sum('/abs/' in u for u in calls),1)
            self.assertFalse(output.with_suffix('.jsonl.tmp').exists())

    def test_rerun_merge_preserves_previous_rows(self):
        with tempfile.TemporaryDirectory() as d:
            old=Path(d,'old'); new=Path(d,'new'); old.mkdir(); new.mkdir()
            for suffix in ['.jsonl','_AI_enhanced_Chinese.jsonl']:
                (old/('2026-10-16'+suffix)).write_text(json.dumps(row('1'))+'\n')
                (new/('2026-10-16'+suffix)).write_text(json.dumps(row('2'))+'\n')
            merge_day(old,new,'2026-10-16','Chinese')
            self.assertEqual([json.loads(x)['id'] for x in (new/'2026-10-16.jsonl').read_text().splitlines()],['1','2'])


    def test_new_metadata_avoids_details_with_crosslists_and_versions(self):
        from test_list_page_metadata import LISTING_HTML
        html = LISTING_HTML.replace('<h3>New submissions</h3>', '<h3>New submissions (showing 2 of 2 entries)</h3>')
        html = html.replace('<h3>Cross-lists</h3>', '<h3>Cross-lists (showing 1 of 1 entries)</h3>')
        html = html.replace('<h3>Replacements</h3>', '<h3>Replacements (showing 1 of 1 entries)</h3>')
        html = html.replace('2609.00001', '2609.00001v2')
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'old_AI_enhanced_Chinese.jsonl').write_text(json.dumps(row('2609.00002')))
            calls = []
            def fetch(url):
                calls.append(url)
                if '/new?' in url:
                    return response(html, url)
                if '/recent?' in url:
                    return listing(['2609.00001', '2609.00002', '2609.00003'])
                self.fail(f'Unexpected detail request: {url}')
            output = Path(d, 'out.jsonl')
            self.assertEqual(collect(['cs.CV', 'cs.RO'], d, 'Chinese', output, fetch), 2)
            rows = [json.loads(line) for line in output.read_text().splitlines()]
            self.assertEqual([r['id'] for r in rows], ['2609.00001', '2609.00003'])
            self.assertEqual(rows[0]['summary'], 'First abstract text.')
            self.assertEqual(rows[1]['summary'], 'Ignored abstract.')
            self.assertEqual(len(calls), 4)

    def test_recent_only_fetches_details_and_new_missing_summary_fails(self):
        from test_list_page_metadata import LISTING_HTML
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'old_AI_enhanced_Chinese.jsonl').write_text(json.dumps(row('old')))
            calls = []
            detail_html = '<meta name="citation_arxiv_id" content="new"><meta name="citation_title" content="Title"><meta name="citation_abstract" content="Summary"><meta name="citation_author" content="Author"><table><tr><td class="subjects">Robotics (cs.RO)</td></tr></table>'
            def fetch(url):
                calls.append(url)
                if '/new?' in url:
                    return listing(['old'])
                if '/recent?' in url:
                    return listing(['new', 'old'])
                return response(detail_html, url)
            output = Path(d, 'out.jsonl')
            self.assertEqual(collect(['cs.RO'], d, 'Chinese', output, fetch), 1)
            self.assertEqual(sum('/abs/' in url for url in calls), 1)
            original = output.read_text()
            invalid = LISTING_HTML.replace('<h3>New submissions</h3>', '<h3>New submissions (showing 4 of 4 entries)</h3>').replace('First\n abstract text.', '')
            with self.assertRaisesRegex(ValueError, 'summary'):
                collect(['cs.RO'], d, 'Chinese', output, lambda url: response(invalid, url))
            self.assertEqual(output.read_text(), original)


if __name__=='__main__':unittest.main()
