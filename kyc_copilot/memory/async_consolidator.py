"""Vayu Asynchronous Memory Consolidator (Non-Blocking asyncio Background Tasks).

Named after *Vayu* (the swift wind that moves unimpeded), this module offloads
audit snapshot writes, Digital Twin graph updates, and Perpetual KYC (cKYC)
watch registrations onto background `asyncio.create_task` coroutines so
expensive persistence never blocks analyst turn latency.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from kyc_copilot.memory.persistent_store import (
    SmritiDigitalTwinStore,
    get_smriti_store,
)
from kyc_copilot.models.schemas import CorporateGoldenRecord
from kyc_copilot.observability.shilalekh_logger import get_shilalekh_logger


class VayuAsyncMemoryConsolidator:
    """Non-blocking background asyncio queue for Smriti memory persistence."""

    def __init__(self, store: Optional[SmritiDigitalTwinStore] = None) -> None:
        self._store = store
        self._pending_tasks: set[asyncio.Task[Any]] = set()
        self._logger = get_shilalekh_logger("kyc_copilot.memory.vayu")

    @property
    def store(self) -> SmritiDigitalTwinStore:
        return self._store if self._store is not None else get_smriti_store()

    def _schedule_coro(self, coro: Any) -> Optional[asyncio.Task[Any]]:
        """Schedules a coroutine via asyncio.create_task when a loop is running."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Safe synchronous fallback if called outside an active event loop.
            asyncio.run(coro)
            return None

        task = loop.create_task(coro)
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)
        return task

    def enqueue_snapshot_consolidation(
        self,
        snapshot_id: str,
        case_id: str,
        tool_name: str,
        source_uri: str,
        payload: dict[str, Any],
    ) -> Optional[asyncio.Task[Any]]:
        """Non-blocking background write of an immutable, PII-scrubbed snapshot."""

        async def _persist() -> None:
            await asyncio.to_thread(
                self.store.save_audit_snapshot,
                snapshot_id,
                case_id,
                tool_name,
                source_uri,
                payload,
            )
            self._logger.info(
                "vayu_snapshot_consolidated",
                case_id=case_id,
                agent_name="vayu_async_consolidator",
                snapshot_id=snapshot_id,
                tool_name=tool_name,
            )

        return self._schedule_coro(_persist())

    def enqueue_golden_record_update(
        self, record: CorporateGoldenRecord, case_id: str
    ) -> Optional[asyncio.Task[Any]]:
        """Non-blocking background upsert of a Digital Twin CorporateGoldenRecord."""

        async def _persist() -> None:
            await asyncio.to_thread(self.store.upsert_golden_record, record)
            self._logger.info(
                "vayu_digital_twin_updated",
                case_id=case_id,
                agent_name="vayu_async_consolidator",
                entity_id=record.entity_id,
            )

        return self._schedule_coro(_persist())

    def enqueue_ckyc_watch_registration(
        self,
        entity_id: str,
        case_id: str,
        risk_tier: str,
        watch_config: dict[str, Any],
    ) -> Optional[asyncio.Task[Any]]:
        """Non-blocking background registration of Stage 7 cKYC watch triggers."""

        async def _persist() -> None:
            await asyncio.to_thread(
                self.store.register_ckyc_watch,
                entity_id,
                case_id,
                risk_tier,
                watch_config,
            )
            self._logger.info(
                "vayu_ckyc_watch_registered",
                case_id=case_id,
                agent_name="vayu_async_consolidator",
                entity_id=entity_id,
                risk_tier=risk_tier,
            )

        return self._schedule_coro(_persist())

    async def flush(self) -> int:
        """Awaits all currently pending background tasks (useful in tests/shutdown)."""
        tasks = list(self._pending_tasks)
        if not tasks:
            return 0
        await asyncio.gather(*tasks)
        return len(tasks)


_GLOBAL_VAYU_CONSOLIDATOR: VayuAsyncMemoryConsolidator | None = None


def get_vayu_consolidator(
    store: Optional[SmritiDigitalTwinStore] = None,
) -> VayuAsyncMemoryConsolidator:
    """Returns the active VayuAsyncMemoryConsolidator singleton."""
    global _GLOBAL_VAYU_CONSOLIDATOR
    if store is not None:
        return VayuAsyncMemoryConsolidator(store=store)
    if _GLOBAL_VAYU_CONSOLIDATOR is None:
        _GLOBAL_VAYU_CONSOLIDATOR = VayuAsyncMemoryConsolidator()
    return _GLOBAL_VAYU_CONSOLIDATOR
