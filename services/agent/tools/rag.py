"""KnowledgeAgent tool: Vertex AI Search retrieval with citation metadata."""
from __future__ import annotations

import logging

from google.adk.tools import ToolContext
from google.cloud import discoveryengine_v1 as discoveryengine

from shared.config import load_config

logger = logging.getLogger(__name__)

_client: discoveryengine.SearchServiceClient | None = None


def _search_client() -> discoveryengine.SearchServiceClient:
    global _client
    if _client is None:
        _client = discoveryengine.SearchServiceClient()
    return _client


def search_knowledge_base(query: str, tool_context: ToolContext) -> dict:
    """Search program guides, eligibility policies, facility FAQs and health advisories.

    Args:
        query: the citizen's question, rephrased as a search query.

    Returns:
        {"chunks": [{n, title, uri, snippet}]} — cite these as [n] in the answer.
        An empty chunks list means the knowledge base has nothing relevant:
        say so; do NOT invent an answer.
    """
    cfg = load_config()
    serving_config = (
        f"projects/{cfg.project_id}/locations/global/collections/default_collection/"
        f"dataStores/{cfg.rag.datastore_id}/servingConfigs/default_search"
    )
    request = discoveryengine.SearchRequest(
        serving_config=serving_config,
        query=query,
        page_size=cfg.rag.top_k,
        content_search_spec=discoveryengine.SearchRequest.ContentSearchSpec(
            snippet_spec=discoveryengine.SearchRequest.ContentSearchSpec.SnippetSpec(
                return_snippet=True
            ),
            extractive_content_spec=discoveryengine.SearchRequest.ContentSearchSpec.ExtractiveContentSpec(
                max_extractive_answer_count=1
            ),
        ),
    )
    try:
        response = _search_client().search(request=request)
    except Exception as e:
        logger.warning("vertex ai search failed: %s", e)
        return {"error": "knowledge base temporarily unavailable — apologize and suggest retrying"}

    chunks: list[dict] = []
    for i, result in enumerate(response.results, start=1):
        data = result.document.derived_struct_data or {}
        snippet = ""
        answers = data.get("extractive_answers")
        if answers:
            snippet = answers[0].get("content", "")
        if not snippet:
            snippets = data.get("snippets")
            if snippets:
                snippet = snippets[0].get("snippet", "")
        chunks.append(
            {
                "n": i,
                "title": data.get("title", result.document.id),
                "uri": data.get("link", ""),
                "snippet": snippet,
            }
        )
        if i >= cfg.rag.top_k:
            break

    if chunks:
        tool_context.state["citations"] = chunks
    return {"chunks": chunks}
