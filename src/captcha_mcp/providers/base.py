from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class TaskResult:
    status: str  # "processing" | "ready" | "error"
    token: str | None = None
    error: str | None = None


class BaseProvider(ABC):
    name: str

    @abstractmethod
    async def create_task(self, task_type: str, params: dict) -> str:
        """Tạo task, trả về task_id."""

    @abstractmethod
    async def get_result(self, task_id: str) -> TaskResult:
        """Poll kết quả. status='processing' nghĩa là chưa xong."""
