import arxiv


class DailyArxivPipeline:
    LIST_PAGE_FIELDS = (
        "id",
        "pdf",
        "abs",
        "authors",
        "title",
        "categories",
        "comment",
        "summary",
    )

    def __init__(self):
        self.page_size = 100
        self.client = None

    def process_item(self, item: dict, spider):
        if all(field in item for field in self.LIST_PAGE_FIELDS):
            self._validate_list_page_item(item)
            return item

        item["pdf"] = f"https://arxiv.org/pdf/{item['id']}"
        item["abs"] = f"https://arxiv.org/abs/{item['id']}"
        search = arxiv.Search(
            id_list=[item["id"]],
        )
        if self.client is None:
            self.client = arxiv.Client(self.page_size)
        paper = next(self.client.results(search))
        item["authors"] = [author.name for author in paper.authors]
        item["title"] = paper.title
        item["categories"] = paper.categories
        item["comment"] = paper.comment
        item["summary"] = paper.summary
        return item

    def _validate_list_page_item(self, item):
        if set(item) != set(self.LIST_PAGE_FIELDS):
            raise ValueError("List-page item contains fields outside the output contract")

        arxiv_id = item["id"]
        if not isinstance(arxiv_id, str) or not arxiv_id:
            raise ValueError("List-page item has an invalid arXiv ID")

        expected_urls = {
            "pdf": f"https://arxiv.org/pdf/{arxiv_id}",
            "abs": f"https://arxiv.org/abs/{arxiv_id}",
        }
        for field, expected_url in expected_urls.items():
            if item[field] != expected_url:
                raise ValueError(f"List-page item has an invalid {field} URL")

        for field in ("title", "summary"):
            if not isinstance(item[field], str) or not item[field]:
                raise ValueError(f"List-page item has an invalid {field}")
        for field in ("authors", "categories"):
            if not isinstance(item[field], list) or not item[field] or not all(
                isinstance(value, str) and value for value in item[field]
            ):
                raise ValueError(f"List-page item has invalid {field}")
        if item["comment"] is not None and (
            not isinstance(item["comment"], str) or not item["comment"]
        ):
            raise ValueError("List-page item has an invalid comment")
