"""Recover unprocessed papers from /new and the five recent announcement days."""
import argparse
import json
import re
import time
from pathlib import Path
from urllib.request import urlopen

from scrapy.http import HtmlResponse

from daily_arxiv.spiders.arxiv import ArxivSpider


def normalize_id(value):
    return re.sub(r"v\d+$", "", value)


def completed_ids(directory, language):
    files = sorted(Path(directory).glob(f"*_AI_enhanced_{language}.jsonl"))
    if not files:
        raise ValueError(f"No processed history found: {directory}")
    failed = {"Summary generation failed", "Motivation analysis unavailable",
              "Method extraction failed", "Result analysis unavailable",
              "Conclusion extraction failed", "Processing failed"}
    result = set()
    for path in files:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            ai = row["AI"]
            fields = [ai.get(k) for k in ("tldr", "motivation", "method", "result", "conclusion")]
            if (all(isinstance(v, str) and v.strip() and v not in failed for v in fields)
                    and isinstance(ai.get("score"), (int, float))):
                result.add(normalize_id(row["id"]))
    return result


def listing_ids(response, kind):
    counts = [tuple(map(int, m.groups()))
              for h in response.css("h3").xpath("normalize-space(.)").getall()
              if (m := re.search(r"showing (\d+) of (\d+) entries", h))]
    entries = response.css("dl dt")
    if not counts or any(a != b for a, b in counts) or sum(a for a, _ in counts) != len(entries):
        raise ValueError(f"Incomplete listing: {response.url}; counts={counts}")
    replacement = None
    if kind == "new":
        for link in response.css("#dlpage ul a"):
            if "Replacement" in link.xpath("string(.)").get():
                replacement = int(link.attrib["href"].removeprefix("#item"))
    result = []
    for entry in entries:
        anchor = entry.css("a[name^='item']::attr(name)").get()
        if not anchor:
            raise ValueError(f"Missing listing anchor: {response.url}")
        if replacement is not None and int(anchor.removeprefix("item")) >= replacement:
            continue
        href = entry.css("a[title='Abstract']::attr(href)").get()
        if not href:
            raise ValueError(f"Missing abstract link: {response.url}")
        result.append(normalize_id(href.rsplit("/", 1)[-1]))
    return result


def detail_item(response, pid):
    def meta(name):
        return response.css(f'meta[name="{name}"]::attr(content)').get()
    actual = meta("citation_arxiv_id")
    title, summary = meta("citation_title"), meta("citation_abstract")
    authors = response.css('meta[name="citation_author"]::attr(content)').getall()
    subjects = response.css("td.subjects").xpath("string(.)").get() or ""
    categories = re.findall(r"\(([a-zA-Z-]+\.[a-zA-Z-]+)\)", subjects)
    if not actual or normalize_id(actual) != pid or not all((title, summary, authors, categories)):
        raise ValueError(f"Incomplete or mismatched detail: {response.url}")
    return dict(id=pid, title=title, summary=summary, authors=authors, categories=categories,
                comment=response.css("td.comments").xpath("normalize-space(.)").get(),
                abs=f"https://arxiv.org/abs/{pid}", pdf=f"https://arxiv.org/pdf/{pid}")


class Fetcher:
    def __init__(self):
        self.last_request = None

    def __call__(self, url):
        if self.last_request is not None:
            time.sleep(max(0, 3 - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        with urlopen(url, timeout=60) as response:
            body = response.read()
        return HtmlResponse(url=url, body=body, encoding="utf-8")


def collect(categories, history, language, output, fetch):
    completed = completed_ids(history, language)
    candidates = set()
    new_listings = []
    for category in categories:
        for kind in ("new", "recent"):
            response = fetch(f"https://arxiv.org/list/{category}/{kind}?skip=0&show=2000")
            ids = listing_ids(response, kind)
            candidates.update(ids)
            if kind == "new":
                new_listings.append((response, set(ids)))
            print(f"{category}/{kind}: {len(ids)} entries", flush=True)
    pending = sorted(candidates - completed)
    print(f"Candidates={len(candidates)}, completed={len(candidates & completed)}, pending={len(pending)}", flush=True)
    metadata = {}
    parser = ArxivSpider()
    pending_ids = set(pending)
    for response, eligible in new_listings:
        for entry in response.css("dl dt"):
            href = entry.css('a[title="Abstract"]::attr(href)').get()
            pid = normalize_id(href.rsplit("/", 1)[-1]) if href else None
            if pid in eligible and pid in pending_ids and pid not in metadata:
                item = parser.listing_item(entry, response)
                item["id"] = pid
                metadata[pid] = item
    print(f"List metadata={len(metadata)}, detail requests={len(pending) - len(metadata)}", flush=True)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".jsonl.tmp")
    try:
        with temporary.open("w") as handle:
            for index, pid in enumerate(pending, 1):
                if pid in metadata:
                    item = metadata[pid]
                    source = "List"
                else:
                    item = detail_item(fetch(f"https://arxiv.org/abs/{pid}"), pid)
                    source = "Detail"
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
                print(f"{source} {index}/{len(pending)}: {pid}", flush=True)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return len(pending)


def merge_day(history, output, date, language):
    for suffix in (".jsonl", f"_AI_enhanced_{language}.jsonl"):
        destination = Path(output) / f"{date}{suffix}"
        previous = Path(history) / destination.name
        merged = {}
        for path in (previous, destination):
            if path.exists():
                for line in path.read_text().splitlines():
                    if line.strip():
                        row = json.loads(line)
                        merged[normalize_id(row["id"])] = row
        destination.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n"
                                       for row in merged.values()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("history", "output", "language"):
        parser.add_argument(f"--{argument}", required=True)
    parser.add_argument("--categories")
    parser.add_argument("--merge-date")
    args = parser.parse_args()
    if args.merge_date:
        merge_day(args.history, args.output, args.merge_date, args.language)
    else:
        categories = [c.strip() for c in (args.categories or "").split(",") if c.strip()]
        if not categories or not args.language:
            parser.error("Categories and language must not be empty")
        start = time.monotonic()
        count = collect(categories, args.history, args.language, args.output, Fetcher())
        print(f"Collected {count} papers in {time.monotonic() - start:.2f}s")
