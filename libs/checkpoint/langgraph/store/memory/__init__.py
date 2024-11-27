"""In-memory key-value store.

A lightweight store implementation using Python dictionaries. Supports basic
key-value operations and vector search when configured with embeddings.

Examples:
    Basic key-value storage:
        store = InMemoryStore()
        store.put(("users", "123"), "prefs", {"theme": "dark"})
        item = store.get(("users", "123"), "prefs")

    Vector search with embeddings:
        from langchain_openai import OpenAIEmbeddings
        store = InMemoryStore(embedding_config={
            "dims": 1536,
            "embed": OpenAIEmbeddings(model="text-embedding-3-small"),
        })

        # Store documents
        store.put(("docs",), "doc1", {"text": "Python tutorial"})
        store.put(("docs",), "doc2", {"text": "TypeScript guide"})

        # Search by similarity
        results = store.search(("docs",), query="python programming")


Note:
    For production use cases requiring persistence, use a database-backed store instead.
"""

import asyncio
import concurrent.futures as cf
import functools
import logging
from collections import defaultdict
from datetime import datetime, timezone
from importlib import util
from typing import Any, Iterable, Optional

from langchain_core.embeddings import Embeddings

from langgraph.store.base import (
    BaseStore,
    EmbeddingConfig,
    GetOp,
    Item,
    ListNamespacesOp,
    MatchCondition,
    Op,
    PutOp,
    Result,
    SearchItem,
    SearchOp,
    ensure_embeddings,
    get_text_at_path,
    tokenize_path,
)

logger = logging.getLogger(__name__)


class InMemoryStore(BaseStore):
    """In-memory dictionary-backed store with optional vector search.

    Examples:
        Basic key-value storage:
            store = InMemoryStore()
            store.put(("users", "123"), "prefs", {"theme": "dark"})
            item = store.get(("users", "123"), "prefs")

        Vector search with embeddings:
            from langchain_openai import OpenAIEmbeddings
            store = InMemoryStore(embedding_config={
                "dims": 1536,
                "embed": OpenAIEmbeddings(model="text-embedding-3-small"),
            })

            # Store documents
            store.put(("docs",), "doc1", {"text": "Python tutorial"})
            store.put(("docs",), "doc2", {"text": "TypeScript guide"})

            # Search by similarity
            results = store.search(("docs",), query="python programming")

    Warning:
        This store keeps all data in memory. Data is lost when the process exits.
        For persistence, use a database-backed store like PostgresStore.

    Tip:
        For vector search, install numpy for better performance:
        ```bash
        pip install numpy
        ```
    """

    __slots__ = (
        "_data",
        "embedding_config",
        "inmem_store",
        "embeddings",
        "_vectors",
    )

    def __init__(self, embedding_config: Optional[EmbeddingConfig] = None) -> None:
        self._data: dict[tuple[str, ...], dict[str, Item]] = defaultdict(dict)
        # [ns][key][path]
        self.inmem_store: dict[tuple[str, ...], dict[str, dict[str, list[float]]]] = (
            defaultdict(lambda: defaultdict(dict))
        )
        self.embedding_config = embedding_config
        if self.embedding_config:
            self.embedding_config = self.embedding_config.copy()
            self.embeddings: Optional[Embeddings] = ensure_embeddings(
                self.embedding_config.get("embed"),
                aembed=self.embedding_config.get("aembed"),
            )
            self.embedding_config["__tokenized_fields"] = [
                (p, tokenize_path(p)) if p != "__root__" else (p, p)
                for p in (self.embedding_config.get("text_fields") or ["__root__"])
            ]

        else:
            self.embedding_config = None
            self.embeddings = None

    def batch(self, ops: Iterable[Op]) -> list[Result]:
        # The batch/abatch methods are treated as internal.
        # Users should access via put/search/get/list_namespaces/etc.
        results, put_ops, search_ops = self._prepare_ops(ops)
        if search_ops:
            queryinmem_store = self._embed_search_queries(search_ops)
            self._batch_search(search_ops, queryinmem_store, results)

        to_embed = self._extract_texts(put_ops)
        if to_embed and self.embedding_config and self.embeddings:
            embeddings = self.embeddings.embed_documents(list(to_embed))
            self._insertinmem_store(to_embed, embeddings)
        self._apply_put_ops(put_ops)
        return results

    async def abatch(self, ops: Iterable[Op]) -> list[Result]:
        # The batch/abatch methods are treated as internal.
        # Users should access via put/search/get/list_namespaces/etc.
        results, put_ops, search_ops = self._prepare_ops(ops)
        if search_ops:
            queryinmem_store = await self._aembed_search_queries(search_ops)
            self._batch_search(search_ops, queryinmem_store, results)

        to_embed = self._extract_texts(put_ops)
        if to_embed and self.embedding_config and self.embeddings:
            embeddings = await self.embeddings.aembed_documents(list(to_embed))
            self._insertinmem_store(to_embed, embeddings)
        self._apply_put_ops(put_ops)
        return results

    # Helpers

    def _filter_items(self, op: SearchOp) -> list[tuple[Item, list[list[float]]]]:
        """Filter items by namespace and filter function, return items with their embeddings."""
        namespace_prefix = op.namespace_prefix

        def filter_func(item: Item) -> bool:
            if not op.filter:
                return True

            return all(
                _compare_values(item.value.get(key), filter_value)
                for key, filter_value in op.filter.items()
            )

        filtered = []
        for namespace in self._data:
            if not (
                namespace[: len(namespace_prefix)] == namespace_prefix
                if len(namespace) >= len(namespace_prefix)
                else False
            ):
                continue

            for key, item in self._data[namespace].items():
                if filter_func(item):
                    if op.query and (
                        embeddings := self.inmem_store[namespace].get(key)
                    ):
                        filtered.append((item, list(embeddings.values())))
                    else:
                        filtered.append((item, []))
        return filtered

    def _embed_search_queries(
        self,
        search_ops: dict[int, tuple[SearchOp, list[tuple[Item, list[list[float]]]]]],
    ) -> dict[str, list[float]]:
        queryinmem_store = {}
        if self.embedding_config and self.embeddings and search_ops:
            queries = {op.query for (op, _) in search_ops.values() if op.query}

            if queries:
                with cf.ThreadPoolExecutor() as executor:
                    futures = {
                        q: executor.submit(self.embeddings.embed_query, q)
                        for q in queries
                    }
                    for query, future in futures.items():
                        queryinmem_store[query] = future.result()

        return queryinmem_store

    async def _aembed_search_queries(
        self,
        search_ops: dict[int, tuple[SearchOp, list[tuple[Item, list[list[float]]]]]],
    ) -> dict[str, list[float]]:
        queryinmem_store = {}
        if self.embedding_config and self.embeddings and search_ops:
            queries = {op.query for (op, _) in search_ops.values() if op.query}

            if queries:
                coros = [self.embeddings.aembed_query(q) for q in queries]
                results = await asyncio.gather(*coros)
                queryinmem_store = dict(zip(queries, results))

        return queryinmem_store

    def _batch_search(
        self,
        ops: dict[int, tuple[SearchOp, list[tuple[Item, list[list[float]]]]]],
        queryinmem_store: dict[str, list[float]],
        results: list[Result],
    ) -> None:
        """Perform batch similarity search for multiple queries."""
        for i, (op, candidates) in ops.items():
            if not candidates:
                results[i] = []
                continue
            if op.query:
                query_embedding = queryinmem_store[op.query]
                flat_items, flat_vectors = [], []
                for item, vectors in candidates:
                    for vector in vectors:
                        flat_items.append(item)
                        flat_vectors.append(vector)
                scores = _cosine_similarity(query_embedding, flat_vectors)
                sorted_results = sorted(
                    zip(scores, flat_items), key=lambda x: x[0], reverse=True
                )
                # max pooling
                seen: set[tuple[tuple[str, ...], str]] = set()
                kept = []
                for score, item in sorted_results:
                    key = (item.namespace, item.key)
                    if key in seen:
                        continue
                    ix = len(seen)
                    seen.add(key)
                    if ix >= op.offset + op.limit:
                        break
                    if ix < op.offset:
                        continue

                    kept.append((score, item))

                results[i] = [
                    SearchItem(
                        namespace=item.namespace,
                        key=item.key,
                        value=item.value,
                        created_at=item.created_at,
                        updated_at=item.updated_at,
                        response_metadata={"score": float(score)},
                    )
                    for score, item in kept
                ]
            else:
                results[i] = [
                    SearchItem(
                        namespace=item.namespace,
                        key=item.key,
                        value=item.value,
                        created_at=item.created_at,
                        updated_at=item.updated_at,
                    )
                    for (item, _) in candidates[op.offset : op.offset + op.limit]
                ]

    def _prepare_ops(
        self, ops: Iterable[Op]
    ) -> tuple[
        list[Result],
        dict[tuple[tuple[str, ...], str], PutOp],
        dict[int, tuple[SearchOp, list[tuple[Item, list[list[float]]]]]],
    ]:
        results: list[Result] = []
        put_ops: dict[tuple[tuple[str, ...], str], PutOp] = {}
        search_ops: dict[
            int, tuple[SearchOp, list[tuple[Item, list[list[float]]]]]
        ] = {}
        for i, op in enumerate(ops):
            if isinstance(op, GetOp):
                item = self._data[op.namespace].get(op.key)
                results.append(item)
            elif isinstance(op, SearchOp):
                search_ops[i] = (op, self._filter_items(op))
                results.append(None)
            elif isinstance(op, ListNamespacesOp):
                results.append(self._handle_list_namespaces(op))
            elif isinstance(op, PutOp):
                put_ops[(op.namespace, op.key)] = op
                results.append(None)
            else:
                raise ValueError(f"Unknown operation type: {type(op)}")

        return results, put_ops, search_ops

    def _apply_put_ops(self, put_ops: dict[tuple[tuple[str, ...], str], PutOp]) -> None:
        for (namespace, key), op in put_ops.items():
            if op.value is None:
                self._data[namespace].pop(key, None)
                self.inmem_store[namespace].pop(key, None)
            else:
                self._data[namespace][key] = Item(
                    value=op.value,
                    key=key,
                    namespace=namespace,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )

    def _extract_texts(
        self, put_ops: dict[tuple[tuple[str, ...], str], PutOp]
    ) -> dict[str, list[tuple[tuple[str, ...], str, str]]]:
        if put_ops and self.embedding_config and self.embeddings:
            to_embed = defaultdict(list)

            for op in put_ops.values():
                if op.value is not None and op.index is not False:
                    for path, field in self.embedding_config["__tokenized_fields"]:
                        texts = get_text_at_path(op.value, field)
                        if texts:
                            if len(texts) > 1:
                                for i, text in enumerate(texts):
                                    to_embed[text].append(
                                        (op.namespace, op.key, f"{path}.{i}")
                                    )

                            else:
                                to_embed[texts[0]].append((op.namespace, op.key, path))

            return to_embed

        return {}

    def _insertinmem_store(
        self,
        to_embed: dict[str, list[tuple[tuple[str, ...], str, str]]],
        embeddings: list[list[float]],
    ) -> None:
        indices = [index for indices in to_embed.values() for index in indices]
        if len(indices) != len(embeddings):
            raise ValueError(
                f"Number of embeddings ({len(embeddings)}) does not"
                f" match number of indices ({len(indices)})"
            )
        for embedding, (ns, key, path) in zip(embeddings, indices):
            self.inmem_store[ns][key][path] = embedding

    def _handle_list_namespaces(self, op: ListNamespacesOp) -> list[tuple[str, ...]]:
        all_namespaces = list(
            self._data.keys()
        )  # Avoid collection size changing while iterating
        namespaces = all_namespaces
        if op.match_conditions:
            namespaces = [
                ns
                for ns in namespaces
                if all(_does_match(condition, ns) for condition in op.match_conditions)
            ]

        if op.max_depth is not None:
            namespaces = sorted({ns[: op.max_depth] for ns in namespaces})
        else:
            namespaces = sorted(namespaces)
        return namespaces[op.offset : op.offset + op.limit]


@functools.lru_cache(maxsize=1)
def _check_numpy() -> bool:
    if bool(util.find_spec("numpy")):
        return True
    logger.warning(
        "NumPy not found in the current Python environment. "
        "The InMemoryStore will use a pure Python implementation for vector operations, "
        "which may significantly impact performance, especially for large datasets or frequent searches. "
        "For optimal speed and efficiency, consider installing NumPy: "
        "pip install numpy"
    )
    return False


def _cosine_similarity(X: list[float], Y: list[list[float]]) -> list[float]:
    """
    Compute cosine similarity between a vector X and a matrix Y.
    Lazy import numpy for efficiency.
    """
    if _check_numpy():
        import numpy as np  # type: ignore

        X_arr = np.array(X) if not isinstance(X, np.ndarray) else X
        Y_arr = np.array(Y) if not isinstance(Y, np.ndarray) else Y
        X_norm = np.linalg.norm(X_arr)
        Y_norm = np.linalg.norm(Y_arr, axis=1)

        # Avoid division by zero
        mask = Y_norm != 0
        similarities = np.zeros_like(Y_norm)
        similarities[mask] = np.dot(Y_arr[mask], X_arr) / (Y_norm[mask] * X_norm)
        return similarities.tolist()

    similarities = []
    for y in Y:
        dot_product = sum(a * b for a, b in zip(X, y))
        norm1 = sum(a * a for a in X) ** 0.5
        norm2 = sum(a * a for a in y) ** 0.5
        similarity = dot_product / (norm1 * norm2) if norm1 > 0 and norm2 > 0 else 0.0
        similarities.append(similarity)

    return similarities


def _does_match(match_condition: MatchCondition, key: tuple[str, ...]) -> bool:
    """Whether a namespace key matches a match condition."""
    match_type = match_condition.match_type
    path = match_condition.path

    if len(key) < len(path):
        return False

    if match_type == "prefix":
        for k_elem, p_elem in zip(key, path):
            if p_elem == "*":
                continue  # Wildcard matches any element
            if k_elem != p_elem:
                return False
        return True
    elif match_type == "suffix":
        for k_elem, p_elem in zip(reversed(key), reversed(path)):
            if p_elem == "*":
                continue  # Wildcard matches any element
            if k_elem != p_elem:
                return False
        return True
    else:
        raise ValueError(f"Unsupported match type: {match_type}")


def _compare_values(item_value: Any, filter_value: Any) -> bool:
    """Compare values in a JSONB-like way, handling nested objects."""
    if isinstance(filter_value, dict):
        if any(k.startswith("$") for k in filter_value):
            return all(
                _apply_operator(item_value, op_key, op_value)
                for op_key, op_value in filter_value.items()
            )
        if not isinstance(item_value, dict):
            return False
        return all(
            _compare_values(item_value.get(k), v) for k, v in filter_value.items()
        )
    elif isinstance(filter_value, (list, tuple)):
        return (
            isinstance(item_value, (list, tuple))
            and len(item_value) == len(filter_value)
            and all(_compare_values(iv, fv) for iv, fv in zip(item_value, filter_value))
        )
    else:
        return item_value == filter_value


def _apply_operator(value: Any, operator: str, op_value: Any) -> bool:
    """Apply a comparison operator, matching PostgreSQL's JSONB behavior."""
    if operator == "$eq":
        return value == op_value
    elif operator == "$gt":
        return float(value) > float(op_value)
    elif operator == "$gte":
        return float(value) >= float(op_value)
    elif operator == "$lt":
        return float(value) < float(op_value)
    elif operator == "$lte":
        return float(value) <= float(op_value)
    elif operator == "$ne":
        return value != op_value
    else:
        raise ValueError(f"Unsupported operator: {operator}")
