from langchain_core.runnables.utils import AddableDict
from langgraph.channels.base import BaseChannel as BaseChannel
from langgraph.checkpoint.base import PendingWrite as PendingWrite
from langgraph.types import Command, PregelExecutableTask as PregelExecutableTask
from typing import Any, Iterator, Literal, Mapping, Sequence, TypeVar

def is_task_id(task_id: str) -> bool: ...
def read_channel(channels: Mapping[str, BaseChannel], chan: str, *, catch: bool = True, return_exception: bool = False) -> Any: ...
def read_channels(channels: Mapping[str, BaseChannel], select: Sequence[str] | str, *, skip_empty: bool = True) -> dict[str, Any] | Any: ...
def map_command(cmd: Command, pending_writes: list[PendingWrite]) -> Iterator[tuple[str, str, Any]]: ...
def map_input(input_channels: str | Sequence[str], chunk: dict[str, Any] | Any | None) -> Iterator[tuple[str, Any]]: ...

class AddableValuesDict(AddableDict):
    def __add__(self, other: dict[str, Any]) -> AddableValuesDict: ...
    def __radd__(self, other: dict[str, Any]) -> AddableValuesDict: ...

def map_output_values(output_channels: str | Sequence[str], pending_writes: Literal[True] | Sequence[tuple[str, Any]], channels: Mapping[str, BaseChannel]) -> Iterator[dict[str, Any] | Any]: ...

class AddableUpdatesDict(AddableDict):
    def __add__(self, other: dict[str, Any]) -> AddableUpdatesDict: ...
    def __radd__(self, other: dict[str, Any]) -> AddableUpdatesDict: ...

def map_output_updates(output_channels: str | Sequence[str], tasks: list[tuple[PregelExecutableTask, Sequence[tuple[str, Any]]]], cached: bool = False) -> Iterator[dict[str, Any | dict[str, Any]]]: ...
T = TypeVar('T')

def single(iter: Iterator[T]) -> T | None: ...
