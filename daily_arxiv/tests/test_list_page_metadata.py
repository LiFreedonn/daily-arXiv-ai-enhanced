import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scrapy.http import HtmlResponse

# The Scrapy project is nested one level below the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from daily_arxiv.pipelines import DailyArxivPipeline
from daily_arxiv.spiders.arxiv import ArxivSpider


LISTING_HTML = """
<html><body>
  <div id="dlpage">
    <ul>
      <li><a href="#item0">New submissions</a></li>
      <li><a href="#item3">Cross-lists</a></li>
      <li><a href="#item4">Replacements</a></li>
    </ul>
  </div>
  <dl id="articles">
    <h3>New submissions</h3>
    <dt><a name="item1">[1]</a><a title="Abstract" href="/abs/2609.00001">arXiv:2609.00001</a></dt>
    <dd><div class="meta">
      <div class="list-title"><span class="descriptor">Title:</span>  First\n paper title  </div>
      <div class="list-authors"><a>Alice Example</a>, <a>Bob Example</a></div>
      <div class="list-comments"><span class="descriptor">Comments:</span>  10 pages\n and code  </div>
      <div class="list-subjects"><span class="descriptor">Subjects:</span><span class="primary-subject">Computer Vision (cs.CV)</span>; Robotics (cs.RO)</div>
      <p> <span class="descriptor">Abstract:</span> First\n abstract text. </p>
    </div></dd>
    <dt><a name="item2">[2]</a><a title="Abstract" href="/abs/2609.00002">arXiv:2609.00002</a></dt>
    <dd><div class="meta">
      <div class="list-title"><span class="descriptor">Title:</span> Second title </div>
      <div class="list-authors"><a>Carol Example</a></div>
      <div class="list-subjects"><span class="descriptor">Subjects:</span><span class="primary-subject">Language (cs.CL)</span></div>
      <p>Second abstract.</p>
    </div></dd>
    <h3>Cross-lists</h3>
    <dt><a name="item3">[3]</a><a title="Abstract" href="/abs/2609.00003">arXiv:2609.00003</a></dt>
    <dd><div class="meta"><div class="list-title">Cross-list</div><div class="list-authors"><a>Ignored Author</a></div><div class="list-subjects">Vision (cs.CV)</div><p>Ignored abstract.</p></div></dd>
    <h3>Replacements</h3>
    <dt><a name="item4">[4]</a><a title="Abstract" href="/abs/2609.00004">arXiv:2609.00004</a></dt>
    <dd><div class="meta"><div class="list-title">Replacement</div><div class="list-authors"><a>Ignored Author</a></div><div class="list-subjects">Vision (cs.CV)</div><p>Ignored abstract.</p></div></dd>
  </dl>
</body></html>
"""


class ListPageMetadataTests(unittest.TestCase):
    def _parse(self, categories, url="https://arxiv.org/list/cs.CV/new"):
        with patch.dict(os.environ, {"CATEGORIES": categories}, clear=False):
            spider = ArxivSpider()
        response = HtmlResponse(url=url, body=LISTING_HTML.encode(), encoding="utf-8")
        return spider, list(spider.parse(response))

    def test_extracts_full_normalized_output_contract(self):
        _, items = self._parse("cs.CV")

        self.assertEqual(len(items), 1)
        self.assertEqual(
            items[0],
            {
                "id": "2609.00001",
                "pdf": "https://arxiv.org/pdf/2609.00001",
                "abs": "https://arxiv.org/abs/2609.00001",
                "authors": ["Alice Example", "Bob Example"],
                "title": "First paper title",
                "categories": ["cs.CV", "cs.RO"],
                "comment": "10 pages and code",
                "summary": "First abstract text.",
            },
        )

    def test_missing_comment_is_none_and_category_filtering_applies(self):
        _, items = self._parse("cs.CL")

        self.assertEqual([item["id"] for item in items], ["2609.00002"])
        self.assertIsNone(items[0]["comment"])

    def test_excludes_non_new_sections_and_suppresses_cross_category_duplicates(self):
        spider, first_items = self._parse("cs.CV")
        second_html = LISTING_HTML.replace("cs.CV)</span>; Robotics (cs.RO)", "cs.CL)</span>")
        response = HtmlResponse(
            url="https://arxiv.org/list/cs.CL/new",
            body=second_html.encode(),
            encoding="utf-8",
        )
        spider.target_categories = {"cs.CV", "cs.CL"}
        second_items = list(spider.parse(response))

        self.assertEqual([item["id"] for item in first_items], ["2609.00001"])
        self.assertEqual([item["id"] for item in second_items], ["2609.00002"])

    def test_list_page_item_bypasses_export_api(self):
        _, items = self._parse("cs.CV")
        with patch("daily_arxiv.pipelines.arxiv.Client", side_effect=AssertionError), patch(
            "daily_arxiv.pipelines.arxiv.Search", side_effect=AssertionError
        ):
            self.assertEqual(DailyArxivPipeline().process_item(items[0], None), items[0])

    def test_id_only_item_keeps_export_api_enrichment(self):
        paper = MagicMock()
        paper.authors = [MagicMock()]
        paper.authors[0].name = "Ada Lovelace"
        paper.title = "API title"
        paper.categories = ["cs.CV"]
        paper.comment = None
        paper.summary = "API summary"

        with patch("daily_arxiv.pipelines.arxiv.Client") as client_class:
            client_class.return_value.results.return_value = iter([paper])
            item = DailyArxivPipeline().process_item({"id": "2609.99999"}, None)

        self.assertEqual(item["authors"], ["Ada Lovelace"])
        self.assertEqual(item["title"], "API title")
        self.assertEqual(item["categories"], ["cs.CV"])
        client_class.assert_called_once_with(100)


if __name__ == "__main__":
    unittest.main()
