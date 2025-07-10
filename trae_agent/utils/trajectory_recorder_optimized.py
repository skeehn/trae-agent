# Copyright (c) 2025 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Optimized trajectory recording functionality for Trae Agent with performance improvements."""

import json
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any
from concurrent.futures import ThreadPoolExecutor

from ..tools.base import ToolCall, ToolResult
from .llm_basics import LLMMessage, LLMResponse


class OptimizedTrajectoryRecorder:
    """
    Optimized trajectory recorder with batched writing and async I/O.
    
    Performance improvements:
    - Batched writing: Only saves to disk every N interactions
    - Background I/O: Uses thread pool for file operations
    - Memory efficient: Optionally limits trajectory size
    """

    def __init__(
        self, 
        trajectory_path: str | None = None,
        batch_size: int = 5,
        max_interactions: int | None = None,
        background_io: bool = True
    ):
        """Initialize optimized trajectory recorder.

        Args:
            trajectory_path: Path to save trajectory file. If None, generates default path.
            batch_size: Number of interactions to accumulate before writing to disk
            max_interactions: Maximum number of interactions to keep in memory (None = unlimited)
            background_io: Whether to use background thread for I/O operations
        """
        if trajectory_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            trajectory_path = f"trajectory_{timestamp}.json"

        self.trajectory_path: Path = Path(trajectory_path)
        self.batch_size = batch_size
        self.max_interactions = max_interactions
        self.background_io = background_io
        
        # Batching state
        self._batch_count = 0
        self._pending_writes = []
        
        # Background I/O
        self._executor = ThreadPoolExecutor(max_workers=1) if background_io else None
        
        self.trajectory_data: dict[str, Any] = {
            "task": "",
            "start_time": "",
            "end_time": "",
            "provider": "",
            "model": "",
            "max_steps": 0,
            "llm_interactions": [],
            "agent_steps": [],
            "success": False,
            "final_result": None,
            "execution_time": 0.0,
        }
        self._start_time: datetime | None = None

    def start_recording(self, task: str, provider: str, model: str, max_steps: int) -> None:
        """Start recording a new trajectory."""
        self._start_time = datetime.now()
        self.trajectory_data.update(
            {
                "task": task,
                "start_time": self._start_time.isoformat(),
                "provider": provider,
                "model": model,
                "max_steps": max_steps,
                "llm_interactions": [],
                "agent_steps": [],
            }
        )
        # Initial save
        self._maybe_save_trajectory()

    def record_llm_interaction(
        self,
        messages: list[LLMMessage],
        response: LLMResponse,
        provider: str,
        model: str,
        tools: list[Any] | None = None,
    ) -> None:
        """Record an LLM interaction with batching."""
        interaction = {
            "timestamp": datetime.now().isoformat(),
            "provider": provider,
            "model": model,
            "input_messages": [self._serialize_message(msg) for msg in messages],
            "response": {
                "content": response.content,
                "model": response.model,
                "finish_reason": response.finish_reason,
                "usage": {
                    "input_tokens": response.usage.input_tokens if response.usage else None,
                    "output_tokens": response.usage.output_tokens if response.usage else None,
                    "cache_creation_input_tokens": getattr(
                        response.usage, "cache_creation_input_tokens", None
                    )
                    if response.usage
                    else None,
                    "cache_read_input_tokens": getattr(
                        response.usage, "cache_read_input_tokens", None
                    )
                    if response.usage
                    else None,
                    "reasoning_tokens": getattr(response.usage, "reasoning_tokens", None)
                    if response.usage
                    else None,
                },
                "tool_calls": [self._serialize_tool_call(tc) for tc in response.tool_calls]
                if response.tool_calls
                else None,
            },
            "tools_available": [tool.name for tool in tools] if tools else None,
        }

        self.trajectory_data["llm_interactions"].append(interaction)
        
        # Memory management
        if self.max_interactions and len(self.trajectory_data["llm_interactions"]) > self.max_interactions:
            # Remove oldest interaction
            self.trajectory_data["llm_interactions"].pop(0)
        
        self._batch_count += 1
        self._maybe_save_trajectory()

    def record_agent_step(
        self,
        step_number: int,
        state: str,
        llm_messages: list[LLMMessage] | None = None,
        llm_response: LLMResponse | None = None,
        tool_calls: list[ToolCall] | None = None,
        tool_results: list[ToolResult] | None = None,
        reflection: str | None = None,
        error: str | None = None,
    ) -> None:
        """Record an agent execution step with batching."""
        step_data = {
            "step_number": step_number,
            "timestamp": datetime.now().isoformat(),
            "state": state,
            "llm_messages": [self._serialize_message(msg) for msg in llm_messages]
            if llm_messages
            else None,
            "llm_response": {
                "content": llm_response.content,
                "model": llm_response.model,
                "finish_reason": llm_response.finish_reason,
                "usage": {
                    "input_tokens": llm_response.usage.input_tokens if llm_response.usage else None,
                    "output_tokens": llm_response.usage.output_tokens
                    if llm_response.usage
                    else None,
                }
                if llm_response.usage
                else None,
                "tool_calls": [self._serialize_tool_call(tc) for tc in llm_response.tool_calls]
                if llm_response.tool_calls
                else None,
            }
            if llm_response
            else None,
            "tool_calls": [self._serialize_tool_call(tc) for tc in tool_calls]
            if tool_calls
            else None,
            "tool_results": [self._serialize_tool_result(tr) for tr in tool_results]
            if tool_results
            else None,
            "reflection": reflection,
            "error": error,
        }

        self.trajectory_data["agent_steps"].append(step_data)
        self._batch_count += 1
        self._maybe_save_trajectory()

    def _maybe_save_trajectory(self) -> None:
        """Save trajectory only if batch size is reached."""
        if self._batch_count >= self.batch_size:
            if self.background_io:
                # Schedule background save
                asyncio.create_task(self.save_trajectory_async())
            else:
                self.save_trajectory()
            self._batch_count = 0

    async def finalize_recording(self, success: bool, final_result: str | None = None) -> None:
        """Finalize the trajectory recording."""
        end_time = datetime.now()
        self.trajectory_data.update(
            {
                "end_time": end_time.isoformat(),
                "success": success,
                "final_result": final_result,
                "execution_time": (end_time - self._start_time).total_seconds()
                if self._start_time
                else 0.0,
            }
        )

        # Force save at the end
        if self.background_io:
            await self.save_trajectory_async()
        else:
            self.save_trajectory()

    def save_trajectory(self) -> None:
        """Save the current trajectory data to file synchronously."""
        try:
            # Ensure directory exists
            self.trajectory_path.parent.mkdir(parents=True, exist_ok=True)

            with open(self.trajectory_path, "w", encoding="utf-8") as f:
                json.dump(self.trajectory_data, f, indent=2, ensure_ascii=False)

        except Exception as e:
            print(f"Warning: Failed to save trajectory to {self.trajectory_path}: {e}")

    async def save_trajectory_async(self) -> None:
        """Save the current trajectory data to file asynchronously."""
        if not self._executor:
            self.save_trajectory()
            return
            
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(self._executor, self.save_trajectory)
        except Exception as e:
            print(f"Warning: Failed to save trajectory asynchronously to {self.trajectory_path}: {e}")

    def _serialize_message(self, message: LLMMessage) -> dict[str, Any]:
        """Serialize an LLM message to a dictionary."""
        data: dict[str, Any] = {"role": message.role, "content": message.content}

        if message.tool_call:
            data["tool_call"] = self._serialize_tool_call(message.tool_call)

        if message.tool_result:
            data["tool_result"] = self._serialize_tool_result(message.tool_result)

        return data

    def _serialize_tool_call(self, tool_call: ToolCall) -> dict[str, Any]:
        """Serialize a tool call to a dictionary."""
        return {
            "call_id": tool_call.call_id,
            "name": tool_call.name,
            "arguments": tool_call.arguments,
            "id": getattr(tool_call, "id", None),
        }

    def _serialize_tool_result(self, tool_result: ToolResult) -> dict[str, Any]:
        """Serialize a tool result to a dictionary."""
        return {
            "call_id": tool_result.call_id,
            "success": tool_result.success,
            "result": tool_result.result,
            "error": tool_result.error,
            "id": getattr(tool_result, "id", None),
        }

    def get_trajectory_path(self) -> str:
        """Get the path where trajectory is being saved."""
        return str(self.trajectory_path)

    def cleanup(self) -> None:
        """Clean up resources."""
        if self._executor:
            self._executor.shutdown(wait=True)