"""Runs of C4b ``kmu_news`` through the run framework (docs/COLLECTORS.md §8.4, §12.1): on
a fresh database with the real codebook and seed, against the fixtures of
``backend/tests/fixtures/kmu_news/`` (the replay transport, with some URLs answered by the
test). Nothing reaches the network.

The fixture set has no third Ukrainian post sitemap and no page for five keyword
candidates: those requests are refused, so these runs end ``partial`` without a complete
listing unless a test answers the sitemap itself.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import httpx2
import yaml
from sqlalchemy import select

from mdt.collectors.replay import REPLAY_EXTENSION, ReplayTransport
from mdt.collectors.runs import RunEnvironment, RunRequest, execute_run, start_run
from mdt.collectors.throttle import HostThrottle
from mdt.config import REPO_ROOT
from mdt.db.models import Document, FetchLog, Organization, Project, RunMessage
from mdt.db.session import read_transaction
from mdt.domain.actor import Actor
from mdt.domain.revisions import soft_delete
from tests.api.conftest import FOCAL_ORG_SEED_KEY
from tests.collectors.acceptance import Acceptance, acceptance, acceptance_template
from tests.collectors.conftest import FIXTURES, FakeClock, fixture_path
from tests.helpers import fields_of

__all__ = ["acceptance", "acceptance_template"]

DIRECTORY = FIXTURES / "kmu_news"
SITE = "https://www.kmu.gov.ua"
POST_3 = f"{SITE}/sitemap-rainlab-blog-models-post-3.xml"
REGULATION = "uryad-zatverdiv-polozhennya-pro-ministerstvo-cifrovoyi-transformaciyi"
KOMANDA = (
    "komanda-ministerstva-cifrovoyi-transformaciyi-prezentuvala-proyekti-z-cifrovoyi-osviti-"
    "ta-rozvitku-malogo-ta-serednogo-biznesu"
)
OTHER_BODY = (
    "uryad-sproshchuye-mehanizmi-nadannya-poslug-vpo-za-dopomogoyu-mobilnogo-zastosunku-diya"
)
YEAR_REVIEW = (
    "vid-shi-asystenta-v-dii-do-suputnykovoho-zviazku-ta-oboronnykh-tekhnolohii-pidsumky-"
    "mintsyfry-u-2025-rotsi"
)
PLAYCITY = "pleisiti-stane-novym-rehuliatorom-azartnykh-ihor-uriad-ukhvalyv-postanovu"
#: The documents a run on the fixtures creates (the pages with a fixture).
KEPT = {
    f"uk:{REGULATION}",
    f"uk:{KOMANDA}",
    f"uk:{OTHER_BODY}",
    f"uk:{YEAR_REVIEW}",
    f"en:{REGULATION}",
}
#: Keyword candidates whose page has no fixture.
NO_FIXTURE = [
    "vidmovitisya-vid-rosijskoyi-muziki-pidtrimati-ukrayinsku-armiyu-mincifri-z-partnerami-"
    "zapustili-proekt-dlya-borotbi-z-propagandoyu",
    "wi-fi-v-ukryttiakh-ta-it-kursy-mykhailo-fedorov-pro-osvitni-initsiatyvy-mintsyfry-pid-"
    "chas-viiny",
    "mincifri-zapustit-nacionalnu-veb-platformu-centriv-nadannya-administrativnih-poslug",
    "mincifri-z-ukrayinskimi-zirkami-pidtrimali-onlajn-proekt-sluhaj-dlya-pidgotovki-do-zno",
    "mihajlo-fedorov-na-diia-summit-do-2022-roku-na-vsij-teritoriyi-ukrayini-bude-4g-internet",
]
CHALLENGE = (
    b"<html><head><title>Just a moment...</title></head><body>Example challenge</body></html>"
)
Answer = Callable[[httpx2.Request], httpx2.Response]


class PatchedReplay(ReplayTransport):
    """The fixtures, except the URLs the test answers itself."""

    def __init__(self, answers: Mapping[str, Answer] | None = None) -> None:
        super().__init__([DIRECTORY])
        self.answers = dict(answers or {})

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        answer = self.answers.get(str(request.url))
        if answer is None:
            return super().handle_request(request)
        response = answer(request)
        response.extensions[REPLAY_EXTENSION] = {
            "fixture": None,
            "retrieved_at": "2026-10-30T12:00:00.000000Z",
        }
        return response


def body(code: int, content: bytes, content_type: str = "text/html") -> Answer:
    return lambda request: httpx2.Response(
        code, content=content, headers={"content-type": content_type}
    )


#: The act sitemap excerpt served as the third post sitemap: a urlset without news pages.
NPA_AS_POST_3 = {
    POST_3: body(200, fixture_path("kmu_news", "npa_sitemap_excerpt.xml").read_bytes(), "text/xml")
}


def run_kmu(
    acceptance: Acceptance,
    transport: ReplayTransport | None = None,
    params: Mapping[str, Any] | None = None,
) -> str:
    """Start and execute one C4b run."""
    transport = transport or PatchedReplay()
    request = RunRequest("kmu_news", params=dict(params or {}), trigger="cli")
    with acceptance.db.session() as session:
        run_id = start_run(session, acceptance.settings, request, transport=transport)
    environment = RunEnvironment(transport=transport, clock=FakeClock(), throttle=HostThrottle())
    execute_run(acceptance.db.factory, acceptance.settings, run_id, environment=environment)
    return run_id


def documents(acceptance: Acceptance) -> dict[str, str]:
    """The live documents of C4b: external ID → document ID."""
    with acceptance.db.session() as session, read_transaction(session):
        rows = session.execute(
            select(Document.external_id, Document.id).where(
                Document.source_id == "kmu_news", Document.deleted_at.is_(None)
            )
        )
        return {str(external_id): str(document_id) for external_id, document_id in rows}


def requested(acceptance: Acceptance, run_id: str, outcome: str | None = None) -> list[str]:
    """The content URLs of a run's fetch log (optionally of one outcome), in order."""
    with acceptance.db.session() as session, read_transaction(session):
        query = select(FetchLog.url).where(FetchLog.run_id == run_id, FetchLog.purpose == "content")
        if outcome is not None:
            query = query.where(FetchLog.outcome == outcome)
        return list(session.scalars(query.order_by(FetchLog.id)))


def messages(acceptance: Acceptance, run_id: str, code: str) -> list[str]:
    with acceptance.db.session() as session, read_transaction(session):
        return list(
            session.scalars(
                select(RunMessage.message).where(
                    RunMessage.run_id == run_id, RunMessage.code == code
                )
            )
        )


def news(slug: str, language: str = "uk") -> str:
    return f"{SITE}/{'en/' if language == 'en' else ''}news/{slug}"


def use_sources(acceptance: Acceptance, tmp_path: Path, **options: Any) -> None:
    """A test sources file: the repository's, with these C4b options."""
    data = yaml.safe_load((REPO_ROOT / "sources.yaml").read_text("utf-8"))
    data["collectors"]["kmu_news"]["options"].update(options)
    path = tmp_path / "sources.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), "utf-8")
    acceptance.db.settings = acceptance.settings.model_copy(update={"sources_file": path})


# --------------------------------------------------------------------------------------
# Candidates, relevance and English versions
# --------------------------------------------------------------------------------------


def test_relevant_candidates_and_english_versions_become_documents(acceptance: Acceptance) -> None:
    run_id = run_kmu(acceptance)
    created = documents(acceptance)
    assert set(created) == KEPT
    with acceptance.db.session() as session:
        focal = session.scalar(
            select(Organization.id).where(Organization.seed_key == FOCAL_ORG_SEED_KEY)
        )
        values = fields_of(session, "document", created[f"uk:{REGULATION}"])
        other = fields_of(session, "document", created[f"uk:{OTHER_BODY}"])
    assert values["title"] == "Уряд затвердив Положення про Міністерство цифрової трансформації"
    assert values["url"] == news(REGULATION)
    assert (values["source_id"], values["external_id"]) == ("kmu_news", f"uk:{REGULATION}")
    assert (values["publisher"], values["publisher_org_id"]) == ("www.kmu.gov.ua", focal)
    assert (values["doc_type"], values["language"], values["license"]) == (
        "news",
        "uk",
        "cc_by_4_0",
    )
    assert (values["published"], values["published_basis"]) == ("2019-09-18", "stated_in_source")
    assert values["published_at_utc"] == "2019-09-18T12:50:00.000000Z"
    assert values["extraction_method"] == "selector" and values["text_hash"]
    assert other["publisher_org_id"] is None  # another body, kept by an alias match
    observations = acceptance.observations("kmu_news")
    assert observations[f"uk:{REGULATION}"]["details"]["relevance"] == "publishing_body"
    assert observations[f"uk:{OTHER_BODY}"]["details"]["relevance"] == "alias_match"
    assert observations[f"uk:{REGULATION}"]["details"]["discovery"] == "keyword"
    assert observations[f"uk:{REGULATION}"]["details"]["lastmod"] == "2019-09-18T15:50:00+03:00"
    english = observations[f"en:{REGULATION}"]
    assert english["details"]["discovery"] == "english_version"
    assert english["subject_id"] == created[f"en:{REGULATION}"]
    assert acceptance.run_row(run_id)["stats"]["extra"]["keyword_candidates"] == 9


def test_pages_without_fixture_are_refused_and_the_listing_stays_incomplete(
    acceptance: Acceptance,
) -> None:
    run_id = run_kmu(acceptance)
    row = acceptance.run_row(run_id)
    assert row["status"] == "partial" and not row["complete_listing"]
    assert set(requested(acceptance, run_id, "refused")) == {POST_3} | {
        news(slug) for slug in NO_FIXTURE
    }
    urls = requested(acceptance, run_id)
    assert news(PLAYCITY) not in urls  # no keyword, no sample
    assert not any("/npas/" in url or "/storage/" in url for url in urls)


def test_a_second_run_fetches_no_page_judged_before(acceptance: Acceptance) -> None:
    run_kmu(acceptance)
    second = run_kmu(acceptance)
    articles = [url for url in requested(acceptance, second) if "/news/" in url]
    assert sorted(articles) == sorted(news(slug) for slug in NO_FIXTURE)
    observations = acceptance.observations("kmu_news")
    assert all(observations[key]["last_seen_run"] == second for key in KEPT)


def test_refetch_fetches_the_known_pages_again_and_writes_nothing(acceptance: Acceptance) -> None:
    run_kmu(acceptance)
    before = acceptance.state()
    second = run_kmu(acceptance, params={"refetch": True})
    articles = set(requested(acceptance, second))
    assert {news(REGULATION), news(KOMANDA), news(REGULATION, "en")} <= articles
    after = acceptance.state()
    assert (after.records, after.revisions, after.texts) == (
        before.records,
        before.revisions,
        before.texts,
    )


def test_an_irrelevant_page_is_discarded_and_not_fetched_again(acceptance: Acceptance) -> None:
    with acceptance.db.session() as session:
        diia = session.scalar(select(Project.id).where(Project.slug == "diia"))
        assert diia is not None  # its aliases are the only ones the page matches
        soft_delete(session, "project", diia, Actor.ui(), note="Example: test without aliases")
    first = run_kmu(acceptance)
    assert f"uk:{OTHER_BODY}" not in documents(acceptance)
    observation = acceptance.observations("kmu_news")[f"uk:{OTHER_BODY}"]
    assert observation["subject_id"] is None
    assert observation["details"]["discarded"] == "not_relevant"
    assert observation["details"]["publishing_body"] == "Міністерство соціальної політики України"
    assert acceptance.run_row(first)["stats"]["extra"]["discarded"] == 1
    (text,) = messages(acceptance, first, "discarded")
    assert news(OTHER_BODY) in text
    second = run_kmu(acceptance)
    assert news(OTHER_BODY) not in requested(acceptance, second)
    third = run_kmu(acceptance, params={"refetch": True})
    assert news(OTHER_BODY) in requested(acceptance, third)
    assert f"uk:{OTHER_BODY}" not in documents(acceptance)


# --------------------------------------------------------------------------------------
# Recall sample
# --------------------------------------------------------------------------------------


def test_the_recall_sample_is_judged_like_candidates(
    acceptance: Acceptance, tmp_path: Path
) -> None:
    use_sources(acceptance, tmp_path, recall_from="2025-01-01", recall_to="2025-12-31")
    params = {"recall_sample": 1, "recall_seed": 7}
    first = run_kmu(acceptance, params=params)
    assert f"uk:{PLAYCITY}" in documents(acceptance)  # the only non-keyword entry of 2025
    details = acceptance.observations("kmu_news")[f"uk:{PLAYCITY}"]["details"]
    assert (details["discovery"], details["recall_sample"]) == ("recall_sample", 7)
    expected = {
        "recall_seed": 7,
        "recall_from": 20250101,
        "recall_to": 20251231,
        "window_entries": 2,
        "keyword_entries": 1,
        "nonkeyword_entries": 1,
        "keyword_relevant": 1,
        "keyword_discarded": 0,
        "sample_size": 1,
        "sample_relevant": 1,
    }
    for run_id in (first, run_kmu(acceptance, params=params)):
        extra = acceptance.run_row(run_id)["stats"]["extra"]
        assert {name: extra.get(name) for name in expected} == expected
    second_urls = requested(acceptance, run_id)
    assert news(PLAYCITY) not in second_urls  # the same seed fetches nothing again


def test_the_same_seed_draws_the_same_sample(acceptance: Acceptance) -> None:
    params = {"recall_sample": 3, "recall_seed": 1}
    first = run_kmu(acceptance, params=params)
    second = run_kmu(acceptance, params=params)

    def sampled(run_id: str) -> list[str]:
        candidates = {news(slug) for slug in NO_FIXTURE}
        return [url for url in requested(acceptance, run_id, "refused") if url not in candidates]

    assert len(sampled(first)) == 4  # three sample entries and the third post sitemap
    assert sampled(first) == sampled(second)
    extra = acceptance.run_row(first)["stats"]["extra"]
    assert (extra["window_entries"], extra["keyword_entries"], extra["nonkeyword_entries"]) == (
        20,
        6,
        14,
    )
    assert (extra["keyword_relevant"], extra["keyword_discarded"]) == (3, 0)
    assert (extra["sample_size"], extra["sample_relevant"]) == (3, 0)


# --------------------------------------------------------------------------------------
# Robots, blocks, limits
# --------------------------------------------------------------------------------------


def test_no_act_page_is_ever_requested(acceptance: Acceptance) -> None:
    run_id = run_kmu(acceptance, PatchedReplay(NPA_AS_POST_3))
    assert not any("/npas/" in url for url in requested(acceptance, run_id))
    assert acceptance.run_row(run_id)["complete_listing"]  # every post sitemap parsed


def test_an_entry_that_leaves_the_sitemaps_is_missing_after_a_complete_run(
    acceptance: Acceptance,
) -> None:
    run_kmu(acceptance, PatchedReplay(NPA_AS_POST_3))
    sitemap = fixture_path("kmu_news", "sitemap_posts_uk_2016_2021_excerpt.xml").read_text("utf-8")
    start = sitemap.index(f"<url>\n        <loc>{news(REGULATION)}</loc>")
    end = sitemap.index("</url>", start) + len("</url>")
    without = (sitemap[:start] + sitemap[end:]).encode("utf-8")
    post_2 = f"{SITE}/sitemap-rainlab-blog-models-post-2.xml"
    second = run_kmu(acceptance, PatchedReplay({**NPA_AS_POST_3, post_2: body(200, without)}))
    assert acceptance.run_row(second)["complete_listing"]
    observations = acceptance.observations("kmu_news")
    assert observations[f"uk:{REGULATION}"]["present"] is False
    assert observations[f"en:{REGULATION}"]["last_seen_run"] == second  # still listed
    assert observations[f"uk:{KOMANDA}"]["last_seen_run"] == second
    assert f"uk:{REGULATION}" in documents(acceptance)  # documents stay


def test_a_block_after_the_complete_listing_makes_the_run_partial(acceptance: Acceptance) -> None:
    answers = {**NPA_AS_POST_3, news(YEAR_REVIEW): body(403, CHALLENGE)}
    run_id = run_kmu(acceptance, PatchedReplay(answers))
    row = acceptance.run_row(run_id)
    assert (row["status"], row["error"], row["complete_listing"]) == ("partial", None, True)
    assert len(messages(acceptance, run_id, "blocked")) == 1
    assert documents(acceptance) == {}  # later pages of the blocked host are refused


def test_a_blocked_sitemap_fails_the_run(acceptance: Acceptance) -> None:
    run_id = run_kmu(acceptance, PatchedReplay({f"{SITE}/sitemap.xml": body(403, CHALLENGE)}))
    row = acceptance.run_row(run_id)
    assert (row["status"], row["error"]) == ("failed", "www.kmu.gov.ua: blocked")


def test_limit_stops_after_that_many_pages(acceptance: Acceptance) -> None:
    run_id = run_kmu(acceptance, PatchedReplay(NPA_AS_POST_3), {"limit": 1})
    articles = [url for url in requested(acceptance, run_id) if "/news/" in url]
    assert articles == [news(YEAR_REVIEW)]  # the first candidate in listing order
    assert not acceptance.run_row(run_id)["complete_listing"]


# --------------------------------------------------------------------------------------
# With C4
# --------------------------------------------------------------------------------------


def test_the_same_item_on_both_sites_is_a_possible_duplicate(acceptance: Acceptance) -> None:
    acceptance.run("ministry_news", "ministry_news", mode="full")  # the 2019 item: page 366
    run_kmu(acceptance)
    kmu = documents(acceptance)[f"uk:{KOMANDA}"]
    with acceptance.db.session() as session, read_transaction(session):
        ministry = session.scalar(
            select(Document.id).where(
                Document.url
                == "https://thedigital.gov.ua/news/education/komanda-ministrerstva-prezentuvala-proekty-tsyfrovoi-osvity"
            )
        )
    assert ministry is not None
    pair = sorted([kmu, ministry])
    (proposal,) = [
        item
        for item in acceptance.proposals(kind="possible_duplicate")
        if [item["subject_id"], item["related_id"]] == pair
    ]
    assert proposal["payload"]["basis"] == "title_date"
    assert proposal["collector"] == "kmu_news"
