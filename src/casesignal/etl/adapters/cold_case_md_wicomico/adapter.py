"""ColdCaseMDWicomicoAdapter — SourceAdapter for Wicomico County Sheriff."""

from __future__ import annotations

from casesignal.etl.adapters.base import SourceAdapter
from casesignal.etl.services.pipeline_context import PipelineContext
from casesignal.etl.services.polite_http import PoliteHTTPClient
from casesignal.etl.services.source_definition import SourceDefinition


class ColdCaseMDWicomicoAdapter(SourceAdapter):
    """Concrete source adapter for Wicomico County, MD Sheriff cold cases."""

    adapter_name = "cold_case_md_wicomico"

    def __init__(self, source_definition: SourceDefinition) -> None:
        super().__init__(source_definition)

    def prepare_input(self, context: PipelineContext) -> None:
        """Fetch all paginated index pages; parse refs; stash on context.

        Wicomico's site is paginated (?page=N). We collect all refs across
        pages and set wicomico_refs on context for downstream stages.
        """
        from casesignal.etl.adapters.cold_case_md_wicomico.scrape import (
            CaseRef,
            parse_index_page,
        )

        if context.logger is None:
            raise RuntimeError("PipelineContext.logger must be set before running stages.")

        source = self.source_definition
        if source.input_type != "url":
            raise ValueError(
                f"Wicomico adapter requires input_type='url', got '{source.input_type}'"
            )
        # SourceDefinition stores input_path as a Path; pathlib collapses
        # `https://` to `https:/` (a single slash). Normalize back so URLs
        # parse correctly downstream.
        base_url = str(source.input_path)
        if base_url.startswith(("http:/", "https:/")) and not base_url.startswith(
            ("http://", "https://")
        ):
            base_url = base_url.replace("http:/", "http://", 1).replace("https:/", "https://", 1)
        if not base_url.startswith(("http://", "https://")):
            raise ValueError(f"Wicomico input_path must be an absolute URL, got '{base_url}'")

        polite = PoliteHTTPClient()
        context.set_metadata("polite_http", polite)

        all_refs: list[CaseRef] = []
        seen_ids: set[str] = set()
        page = 1
        MAX_PAGES = 20  # safety cap; current corpus is ~12 cases / ~3 pages
        while page <= MAX_PAGES:
            page_url = base_url if page == 1 else f"{base_url}?page={page}"
            response = polite.get(page_url)
            page_refs = parse_index_page(response.text, base_url=page_url)
            new = [r for r in page_refs if r.source_case_id not in seen_ids]
            if not new:
                break
            all_refs.extend(new)
            for r in new:
                seen_ids.add(r.source_case_id)
            page += 1

        if len(all_refs) < 5:
            raise RuntimeError(
                f"Wicomico prepare_input: parsed {len(all_refs)} refs across {page - 1} pages;"
                f" expected >= 5. Page structure may have changed."
            )

        context.set_metadata("wicomico_refs", all_refs)
        context.set_metadata("wicomico_index_url", base_url)
        context.logger.info(
            "Wicomico prepare_input: parsed %d refs across %d pages",
            len(all_refs),
            page - 1,
        )

    def register_source(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_md_wicomico.register import (
            register_wicomico_source,
        )

        register_wicomico_source(context)

    def load_raw(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_md_wicomico.raw_load import (
            load_wicomico_raw,
        )

        load_wicomico_raw(context)

    def transform(self, context: PipelineContext) -> None:
        from casesignal.etl.adapters.cold_case_md_wicomico.transform import (
            transform_wicomico,
        )

        transform_wicomico(context)

        polite = context.get_metadata("polite_http")
        if polite is not None and hasattr(polite, "close"):
            try:
                polite.close()
            except Exception:
                pass
