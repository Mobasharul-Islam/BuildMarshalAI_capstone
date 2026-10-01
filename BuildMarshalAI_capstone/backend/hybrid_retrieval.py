"""Hybrid text + ColPali late-interaction retrieval for BuildMarshalAI."""

from __future__ import annotations

import logging
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import torch
from PIL import Image

try:  # the notebook puts this directory on sys.path
    from document_links import document_project_ids
except ModuleNotFoundError:  # imported as backend.hybrid_retrieval
    from backend.document_links import document_project_ids


LOGGER = logging.getLogger("BuildMarshalAI.retrieval")

STOPWORDS = {
    "a", "an", "and", "are", "about", "can", "could", "details", "do", "for",
    "from", "give", "i", "in", "is", "me", "of", "on", "please", "show", "tell",
    "the", "this", "to", "very", "what", "with", "you",
}


def search_tokens(value: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", str(value).casefold())
        if token not in STOPWORDS
    ]


def lexical_score(query: str, page: Mapping[str, Any]) -> float:
    query_tokens = search_tokens(query)
    if not query_tokens:
        return 0.0
    haystack = f"{page.get('doc_name', '')} {page.get('text_content', '')}".casefold()
    haystack_tokens = search_tokens(haystack)
    if not haystack_tokens:
        return 0.0
    counts = Counter(haystack_tokens)
    unique_query = list(dict.fromkeys(query_tokens))
    matched = sum(1 for token in unique_query if counts.get(token, 0))
    coverage = matched / max(len(unique_query), 1)
    frequency = sum(min(counts.get(token, 0), 4) for token in unique_query) / max(len(unique_query), 1)
    phrase = " ".join(unique_query)
    phrase_bonus = 4.0 if len(unique_query) >= 2 and phrase in " ".join(haystack_tokens) else 0.0
    detail_intent = bool(re.search(
        r"\b(detail|details|describe|description|information|spec|specification|specifications)\b",
        query.casefold(),
    ))
    index_page = any(marker in haystack for marker in (
        "item index", "drawing index", "table of contents", "sheet index",
    )) or "index" in search_tokens(str(page.get("doc_name", "")))
    # An index often contains the exact requested label but only points to the
    # real answer. For detail/specification questions, prefer the richer page.
    richness_bonus = (
        min(2.0, len(haystack_tokens) / 400.0)
        if detail_intent and phrase_bonus
        else 0.0
    )
    index_penalty = 3.0 if detail_intent and index_page else 0.0
    return max(
        0.0,
        phrase_bonus + 3.0 * coverage + 0.35 * frequency
        + richness_bonus - index_penalty,
    )


def normalize_scores(values: Mapping[str, float]) -> dict[str, float]:
    if not values:
        return {}
    low, high = min(values.values()), max(values.values())
    if high - low < 1e-9:
        return {key: (1.0 if high > 0 else 0.0) for key in values}
    return {key: (value - low) / (high - low) for key, value in values.items()}


class HybridColPaliRetriever:
    """Retrieve candidates lexically and visually, then apply ColPali MaxSim."""

    def __init__(self, namespace: Mapping[str, Any]):
        # The ColPali model and processor are stateless and shared.  Everything
        # that holds data -- the vector collection, the page metadata, and the
        # multi-vector cache -- comes from the workspace passed per call, so one
        # retriever instance can never mix two accounts' pages.
        self.model = namespace["COLPALI_MODEL"]
        self.processor = namespace["COLPALI_PROCESSOR"]
        self.device = namespace.get("COLPALI_DEVICE", "cuda:0")

    def _cache_path(self, image_path: str, workspace: Any) -> Path:
        safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(image_path).stem)
        cache_dir = Path(workspace.multivector_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / f"{safe_stem}.npy"

    @torch.no_grad()
    def _encode_image(self, image_path: str) -> torch.Tensor | None:
        try:
            with Image.open(image_path) as source:
                image = source.convert("RGB")
            batch = self.processor.process_images([image]).to(self.model.device)
            return self.model(**batch).squeeze(0).to(torch.float16).cpu()
        except Exception as exc:
            LOGGER.error("ColPali page encoding failed for %s: %s", image_path, exc)
            return None

    def _page_multivector(self, image_path: str, workspace: Any) -> torch.Tensor | None:
        cache_path = self._cache_path(image_path, workspace)
        if cache_path.exists():
            try:
                return torch.from_numpy(np.load(cache_path, allow_pickle=False))
            except Exception as exc:
                LOGGER.warning("Discarding invalid ColPali cache %s: %s", cache_path.name, exc)
                cache_path.unlink(missing_ok=True)
        vector = self._encode_image(image_path)
        if vector is not None:
            np.save(cache_path, vector.numpy())
        return vector

    @torch.no_grad()
    def _query_multivector(self, query: str) -> torch.Tensor | None:
        try:
            batch = self.processor.process_queries([query]).to(self.model.device)
            return self.model(**batch).squeeze(0).to(torch.float16).cpu()
        except Exception as exc:
            LOGGER.error("ColPali query encoding failed: %s", exc)
            return None

    def embed_image(self, image_path: str, workspace: Any = None) -> np.ndarray | None:
        multi = (
            self._page_multivector(image_path, workspace)
            if workspace is not None else self._encode_image(image_path)
        )
        return None if multi is None else multi.float().mean(dim=0).numpy()

    def embed_query(self, query: str) -> np.ndarray | None:
        multi = self._query_multivector(query)
        return None if multi is None else multi.float().mean(dim=0).numpy()

    @staticmethod
    def _scope(project_id: Any) -> set[str]:
        """The project ids a search is limited to; empty means the whole account."""
        if not project_id:
            return set()
        return {project_id} if isinstance(project_id, str) else {str(p) for p in project_id if p}

    def _pages(self, project_id: Any, workspace: Any) -> list[dict[str, Any]]:
        pages: list[dict[str, Any]] = []
        scope = self._scope(project_id)
        for doc_id, document in workspace.load_metadata().get("documents", {}).items():
            linked = document_project_ids(document)
            # A document shared by several projects is found from each of them.
            if scope and not scope.intersection(linked):
                continue
            doc_project = linked[0] if linked else None
            for page in document.get("pages", []):
                page_num = int(page.get("page_num", 1))
                pages.append({
                    "id": f"{doc_id}_p{page_num}",
                    "doc_name": document.get("name", doc_id),
                    "doc_id": doc_id,
                    "page": page_num,
                    "image_path": workspace.resolve_page_path(page.get("image_path", "")),
                    "text_content": page.get("text_content", ""),
                    "project_id": doc_project,
                    "source_type": document.get("source_type", "project_document"),
                })
        return pages

    def retrieve(self, query: str, top_k: int = 5, project_id: Any = None,
                 workspace: Any = None) -> list[dict[str, Any]]:
        """The best ``top_k`` pages, from the whole account or only ``project_id``.

        ``project_id`` may be one id or several. Scoped, no page of a document
        outside the scope can be returned by any of the three channels.
        """
        if workspace is None:
            raise RuntimeError("Hybrid retrieval requires the caller's account workspace")
        collection = workspace.collection
        pages = self._pages(project_id, workspace)
        if not pages:
            LOGGER.warning("No indexed pages match project_id=%r", project_id)
            return []
        by_id = {page["id"]: page for page in pages}
        candidate_limit = min(len(pages), max(12, top_k * 3))
        lexical_raw = {page["id"]: lexical_score(query, page) for page in pages}
        lexical_ids = sorted(lexical_raw, key=lexical_raw.get, reverse=True)[:candidate_limit]

        query_multi = self._query_multivector(query)
        pooled_raw: dict[str, float] = {}
        if query_multi is not None and collection.count() > 0:
            pooled_query = query_multi.float().mean(dim=0).numpy()
            try:
                kwargs: dict[str, Any] = {
                    "query_embeddings": [pooled_query.tolist()],
                    "n_results": min(candidate_limit, collection.count()),
                    "include": ["metadatas", "distances"],
                }
                if self._scope(project_id):
                    # Page vectors know their document, not its projects (links
                    # change without re-embedding), so filter on the documents.
                    kwargs["where"] = {"doc_id": {"$in": sorted({p["doc_id"] for p in pages})}}
                result = collection.query(**kwargs)
                for item_id, distance in zip(result["ids"][0], result["distances"][0]):
                    if item_id in by_id:
                        pooled_raw[item_id] = 1.0 - float(distance)
            except Exception as exc:
                LOGGER.warning("Chroma candidate retrieval failed: %s", exc)

        preliminary_ids = set(lexical_ids) | set(pooled_raw)
        if len(preliminary_ids) > candidate_limit:
            lexical_norm = normalize_scores({key: lexical_raw.get(key, 0.0) for key in preliminary_ids})
            pooled_norm = normalize_scores({key: pooled_raw.get(key, 0.0) for key in preliminary_ids})
            preliminary_ids = set(sorted(
                preliminary_ids,
                key=lambda key: 0.75 * lexical_norm.get(key, 0.0) + 0.25 * pooled_norm.get(key, 0.0),
                reverse=True,
            )[:candidate_limit])
        candidates = [by_id[item_id] for item_id in preliminary_ids]

        late_raw: dict[str, float] = {}
        if query_multi is not None:
            vectors, vector_ids = [], []
            for page in candidates:
                image_path = page.get("image_path", "")
                if image_path and os.path.exists(image_path):
                    vector = self._page_multivector(image_path, workspace)
                    if vector is not None:
                        vectors.append(vector)
                        vector_ids.append(page["id"])
            if vectors:
                try:
                    scores = self.processor.score_multi_vector(
                        [query_multi], vectors, batch_size=8, device=self.device
                    )[0].tolist()
                    late_raw = {item_id: float(score) for item_id, score in zip(vector_ids, scores)}
                except Exception as exc:
                    LOGGER.warning("ColPali MaxSim reranking failed: %s", exc)

        lexical = normalize_scores({key: lexical_raw.get(key, 0.0) for key in preliminary_ids})
        pooled = normalize_scores({key: pooled_raw.get(key, 0.0) for key in preliminary_ids})
        late = normalize_scores({key: late_raw.get(key, 0.0) for key in preliminary_ids})
        strong_exact_match = max(lexical_raw.values(), default=0.0) >= 6.0
        weights = {
            "lexical": (0.70 if strong_exact_match else 0.55) if lexical_raw else 0.0,
            "late": (0.28 if strong_exact_match else 0.40) if late_raw else 0.0,
            "pooled": (0.02 if strong_exact_match else 0.05) if pooled_raw else 0.0,
        }
        total_weight = sum(weights.values()) or 1.0
        ranked = []
        for page in candidates:
            item_id = page["id"]
            score = (
                weights["lexical"] * lexical.get(item_id, 0.0)
                + weights["late"] * late.get(item_id, 0.0)
                + weights["pooled"] * pooled.get(item_id, 0.0)
            ) / total_weight
            lexical_value = lexical.get(item_id, 0.0)
            late_value = late.get(item_id, 0.0)
            pooled_value = pooled.get(item_id, 0.0)
            methods = []
            if lexical_raw.get(item_id, 0.0) > 0:
                methods.append("text match")
            if item_id in late_raw:
                methods.append("ColPali MaxSim")
            if item_id in pooled_raw:
                methods.append("vector candidate")
            haystack = f"{page.get('doc_name', '')} {page.get('text_content', '')}".casefold()
            ranked.append({
                **page,
                "score": round(max(0.0, min(1.0, score)), 4),
                "retrieval_method": " + ".join(methods) or "metadata fallback",
                "score_breakdown": {
                    "text": round(lexical_value, 4),
                    "colpali": round(late_value, 4),
                    "vector": round(pooled_value, 4),
                },
                "matched_terms": [
                    token for token in dict.fromkeys(search_tokens(query)) if token in haystack
                ],
            })
        ranked.sort(key=lambda page: page["score"], reverse=True)
        selected = ranked[: min(top_k, len(ranked))]
        if selected:
            LOGGER.info(
                "Hybrid retrieval selected %d pages; top=%s p%d score=%.3f",
                len(selected), selected[0]["doc_name"], selected[0]["page"], selected[0]["score"],
            )
        torch.cuda.empty_cache()
        return selected


def install_hybrid_retrieval(namespace: dict[str, Any]) -> HybridColPaliRetriever:
    """Replace the pooled-vector helpers with the hybrid retriever.

    ``retrieve_context``, ``embed_image``, and ``embed_query`` are looked up as
    globals at call time, so rebinding them here upgrades every existing caller.
    Both signatures keep the ``workspace`` keyword the callers already pass.
    """
    retriever = HybridColPaliRetriever(namespace)
    namespace["HYBRID_RETRIEVER"] = retriever
    namespace["embed_image"] = retriever.embed_image
    namespace["embed_query"] = retriever.embed_query
    namespace["retrieve_context"] = retriever.retrieve
    return retriever
