import abc
from abc import ABC, abstractmethod
from langchain_core.runnables import Runnable, RunnableConfig as RunnableConfig
from langchain_core.runnables.graph import Graph as DrawableGraph
from langgraph.pregel.types import All as All, StateSnapshot as StateSnapshot, StreamMode as StreamMode
from typing import Any, AsyncIterator, Iterator, Sequence
from typing_extensions import Self

class PregelProtocol(Runnable[dict[str, Any] | Any, dict[str, Any] | Any], ABC, metaclass=abc.ABCMeta):
    @abstractmethod
    def with_config(self, config: RunnableConfig | None = None, **kwargs: Any) -> Self: ...
    @abstractmethod
    def get_graph(self, config: RunnableConfig | None = None, *, xray: int | bool = False) -> DrawableGraph: ...
    @abstractmethod
    async def aget_graph(self, config: RunnableConfig | None = None, *, xray: int | bool = False) -> DrawableGraph: ...
    @abstractmethod
    def get_state(self, config: RunnableConfig, *, subgraphs: bool = False) -> StateSnapshot: ...
    @abstractmethod
    async def aget_state(self, config: RunnableConfig, *, subgraphs: bool = False) -> StateSnapshot: ...
    @abstractmethod
    def get_state_history(self, config: RunnableConfig, *, filter: dict[str, Any] | None = None, before: RunnableConfig | None = None, limit: int | None = None) -> Iterator[StateSnapshot]: ...
    @abstractmethod
    def aget_state_history(self, config: RunnableConfig, *, filter: dict[str, Any] | None = None, before: RunnableConfig | None = None, limit: int | None = None) -> AsyncIterator[StateSnapshot]: ...
    @abstractmethod
    def update_state(self, config: RunnableConfig, values: dict[str, Any] | Any | None, as_node: str | None = None) -> RunnableConfig: ...
    @abstractmethod
    async def aupdate_state(self, config: RunnableConfig, values: dict[str, Any] | Any | None, as_node: str | None = None) -> RunnableConfig: ...
    @abstractmethod
    def stream(self, input: dict[str, Any] | Any, config: RunnableConfig | None = None, *, stream_mode: StreamMode | list[StreamMode] | None = None, interrupt_before: All | Sequence[str] | None = None, interrupt_after: All | Sequence[str] | None = None, subgraphs: bool = False) -> Iterator[dict[str, Any] | Any]: ...
    @abstractmethod
    def astream(self, input: dict[str, Any] | Any, config: RunnableConfig | None = None, *, stream_mode: StreamMode | list[StreamMode] | None = None, interrupt_before: All | Sequence[str] | None = None, interrupt_after: All | Sequence[str] | None = None, subgraphs: bool = False) -> AsyncIterator[dict[str, Any] | Any]: ...
    @abstractmethod
    def invoke(self, input: dict[str, Any] | Any, config: RunnableConfig | None = None, *, interrupt_before: All | Sequence[str] | None = None, interrupt_after: All | Sequence[str] | None = None) -> dict[str, Any] | Any: ...
    @abstractmethod
    async def ainvoke(self, input: dict[str, Any] | Any, config: RunnableConfig | None = None, *, interrupt_before: All | Sequence[str] | None = None, interrupt_after: All | Sequence[str] | None = None) -> dict[str, Any] | Any: ...
