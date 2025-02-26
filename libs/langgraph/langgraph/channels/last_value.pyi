from _typeshed import Incomplete
from langgraph.channels.base import BaseChannel, Value
from typing import Generic, Sequence
from typing_extensions import Self

class LastValue(BaseChannel[Value, Value, Value], Generic[Value]):
    def __eq__(self, value: object) -> bool: ...
    @property
    def ValueType(self) -> type[Value]: ...
    @property
    def UpdateType(self) -> type[Value]: ...
    def from_checkpoint(self, checkpoint: Value | None) -> Self: ...
    value: Incomplete
    def update(self, values: Sequence[Value]) -> bool: ...
    def get(self) -> Value: ...
