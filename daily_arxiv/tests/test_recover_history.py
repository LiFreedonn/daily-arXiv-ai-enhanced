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
                if '/list/' in url:return listing(['1','2','2'])
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


if __name__=='__main__':unittest.main()
