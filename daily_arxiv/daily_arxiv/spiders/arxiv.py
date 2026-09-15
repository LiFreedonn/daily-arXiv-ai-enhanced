import os
import re

import scrapy


class ArxivSpider(scrapy.Spider):
    name = "arxiv"
    allowed_domains = ["arxiv.org"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        categories = os.environ.get("CATEGORIES", "cs.CV")
        self.target_categories = {
            category.strip() for category in categories.split(",") if category.strip()
        }
        self.start_urls = [
            f"https://arxiv.org/list/{category}/new"
            for category in sorted(self.target_categories)
        ]
        self.seen_ids = set()

    def parse(self, response):
        section_anchors = []
        for href in response.css("div#dlpage ul a::attr(href)").getall():
            match = re.fullmatch(r"#item(\d+)", href)
            if match:
                section_anchors.append(int(match.group(1)))

        # The second navigation anchor begins Cross-lists. If it is absent, the
        # page contains only New submissions and all entries remain in scope.
        new_submissions_end = section_anchors[1] if len(section_anchors) > 1 else None

        for paper_dt in response.css("dl dt"):
            paper_anchor = paper_dt.css("a[name^='item']::attr(name)").get()
            if not paper_anchor:
                continue

            anchor_match = re.fullmatch(r"item(\d+)", paper_anchor)
            if not anchor_match:
                self._parser_failure(response, "<unknown>", "invalid listing anchor")

            if new_submissions_end is not None and int(anchor_match.group(1)) >= new_submissions_end:
                continue

            abstract_link = paper_dt.css("a[title='Abstract']::attr(href)").get()
            if not abstract_link:
                self._parser_failure(response, "<unknown>", "missing abstract link")
            arxiv_id = abstract_link.rstrip("/").split("/")[-1]

            paper_dd = paper_dt.xpath("following-sibling::dd[1]")
            if not paper_dd:
                self._parser_failure(response, arxiv_id, "missing adjacent metadata block")

            title = self._field_text(paper_dd, "list-title")
            authors = self._authors(paper_dd)
            categories = self._categories(paper_dd)
            comment = self._field_text(paper_dd, "list-comments") or None
            summary = self._summary(paper_dd)

            required_fields = {
                "title": title,
                "authors": authors,
                "categories": categories,
                "summary": summary,
            }
            missing_fields = [name for name, value in required_fields.items() if not value]
            if missing_fields:
                self._parser_failure(
                    response,
                    arxiv_id,
                    f"missing required fields: {', '.join(missing_fields)}",
                )

            if not set(categories).intersection(self.target_categories):
                self.logger.debug(
                    "Skipped paper %s with categories %s (not in target %s)",
                    arxiv_id,
                    categories,
                    sorted(self.target_categories),
                )
                continue

            if arxiv_id in self.seen_ids:
                self.logger.debug("Skipped duplicate paper %s", arxiv_id)
                continue

            self.seen_ids.add(arxiv_id)
            yield {
                "id": arxiv_id,
                "pdf": f"https://arxiv.org/pdf/{arxiv_id}",
                "abs": f"https://arxiv.org/abs/{arxiv_id}",
                "authors": authors,
                "title": title,
                "categories": categories,
                "comment": comment,
                "summary": summary,
            }

    @staticmethod
    def _normalize_text(values):
        return " ".join(" ".join(value.split()) for value in values if value.strip())

    def _field_text(self, paper_dd, class_name):
        field = paper_dd.css(f".{class_name}")
        return self._normalize_text(
            field.xpath(
                ".//text()[not(ancestor::span[contains(concat(' ', normalize-space(@class), ' '), ' descriptor ')])]"
            ).getall()
        )

    def _authors(self, paper_dd):
        return [
            author
            for author in (
                self._normalize_text([name])
                for name in paper_dd.css(".list-authors a::text").getall()
            )
            if author
        ]

    def _categories(self, paper_dd):
        subjects = self._field_text(paper_dd, "list-subjects")
        return re.findall(r"\(([a-zA-Z-]+\.[a-zA-Z-]+)\)", subjects)

    def _summary(self, paper_dd):
        return self._normalize_text(
            paper_dd.xpath(
                ".//div[contains(@class, 'meta')]/p[1]//text()[not(ancestor::span[contains(concat(' ', normalize-space(@class), ' '), ' descriptor ')])]"
            ).getall()
        )

    def _parser_failure(self, response, arxiv_id, reason):
        message = f"List-page parser failure for paper {arxiv_id} at {response.url}: {reason}"
        self.logger.error(message)
        raise ValueError(message)
