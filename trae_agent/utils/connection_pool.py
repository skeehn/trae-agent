# Copyright (c) 2025 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""HTTP connection pooling for LLM clients to improve performance."""

import httpx
import asyncio
from typing import Dict, Optional
from contextlib import asynccontextmanager


class ConnectionPoolManager:
    """
    Manages HTTP connection pools for different LLM providers.
    
    Benefits:
    - Reuses connections across requests
    - Configurable timeout and connection limits
    - Automatic cleanup and connection management
    - Provider-specific optimizations
    """
    
    _instance: Optional['ConnectionPoolManager'] = None
    _clients: Dict[str, httpx.AsyncClient] = {}
    _lock = asyncio.Lock()
    
    def __new__(cls) -> 'ConnectionPoolManager':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    async def get_client(
        cls, 
        provider: str, 
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 30.0,
        max_connections: int = 10,
        max_keepalive_connections: int = 5
    ) -> httpx.AsyncClient:
        """Get or create an HTTP client for the specified provider."""
        instance = cls()
        
        async with cls._lock:
            client_key = f"{provider}:{base_url or 'default'}"
            
            if client_key not in cls._clients:
                # Create optimized client for the provider
                headers = {}
                if api_key:
                    if provider == "openai":
                        headers["Authorization"] = f"Bearer {api_key}"
                    elif provider == "anthropic":
                        headers["x-api-key"] = api_key
                        headers["anthropic-version"] = "2023-06-01"
                    elif provider == "google":
                        headers["Authorization"] = f"Bearer {api_key}"
                
                # Provider-specific timeout optimizations
                provider_timeouts = {
                    "openai": httpx.Timeout(
                        connect=10.0,
                        read=60.0,  # Longer read timeout for streaming
                        write=10.0,
                        pool=5.0
                    ),
                    "anthropic": httpx.Timeout(
                        connect=10.0,
                        read=120.0,  # Anthropic can be slower
                        write=10.0,
                        pool=5.0
                    ),
                    "google": httpx.Timeout(
                        connect=10.0,
                        read=90.0,
                        write=10.0,
                        pool=5.0
                    ),
                    "default": httpx.Timeout(timeout)
                }
                
                timeout_config = provider_timeouts.get(provider, provider_timeouts["default"])
                
                cls._clients[client_key] = httpx.AsyncClient(
                    base_url=base_url,
                    headers=headers,
                    timeout=timeout_config,
                    limits=httpx.Limits(
                        max_connections=max_connections,
                        max_keepalive_connections=max_keepalive_connections,
                        keepalive_expiry=30.0  # Keep connections alive for 30 seconds
                    ),
                    # Enable HTTP/2 for better performance
                    http2=True,
                    # Retry configuration
                    transport=httpx.AsyncHTTPTransport(retries=3)
                )
            
            return cls._clients[client_key]
    
    @classmethod
    async def close_all(cls) -> None:
        """Close all HTTP clients and clean up resources."""
        async with cls._lock:
            for client in cls._clients.values():
                await client.aclose()
            cls._clients.clear()
    
    @classmethod
    @asynccontextmanager
    async def get_pooled_client(cls, provider: str, **kwargs):
        """Context manager for getting a pooled HTTP client."""
        client = await cls.get_client(provider, **kwargs)
        try:
            yield client
        finally:
            # Client stays in pool for reuse
            pass


# Enhanced OpenAI client with connection pooling
class PooledOpenAIClient:
    """OpenAI client wrapper with connection pooling."""
    
    def __init__(self, api_key: str, base_url: Optional[str] = None):
        self.api_key = api_key
        self.base_url = base_url or "https://api.openai.com/v1"
        self._client = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get pooled HTTP client for OpenAI."""
        if self._client is None:
            self._client = await ConnectionPoolManager.get_client(
                provider="openai",
                base_url=self.base_url,
                api_key=self.api_key,
                max_connections=15,  # Higher for OpenAI
                max_keepalive_connections=8
            )
        return self._client
    
    async def chat_completion(self, **kwargs) -> dict:
        """Make a chat completion request with pooled connection."""
        client = await self._get_client()
        
        response = await client.post(
            "/chat/completions",
            json=kwargs,
            headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()
        return response.json()
    
    async def chat_completion_stream(self, **kwargs):
        """Stream chat completion with pooled connection."""
        client = await self._get_client()
        kwargs["stream"] = True
        
        async with client.stream(
            "POST",
            "/chat/completions", 
            json=kwargs,
            headers={"Content-Type": "application/json"}
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    yield line[6:]  # Remove "data: " prefix


# Performance monitoring for connection pools
class ConnectionPoolMetrics:
    """Monitor connection pool performance."""
    
    def __init__(self):
        self.request_count = 0
        self.connection_reuse_count = 0
        self.total_request_time = 0.0
        self.average_request_time = 0.0
    
    def record_request(self, duration: float, connection_reused: bool = False):
        """Record a request for metrics."""
        self.request_count += 1
        self.total_request_time += duration
        self.average_request_time = self.total_request_time / self.request_count
        
        if connection_reused:
            self.connection_reuse_count += 1
    
    def get_stats(self) -> dict:
        """Get connection pool statistics."""
        reuse_rate = (self.connection_reuse_count / self.request_count * 100) if self.request_count > 0 else 0
        
        return {
            "total_requests": self.request_count,
            "connection_reuse_count": self.connection_reuse_count,
            "connection_reuse_rate_percent": round(reuse_rate, 2),
            "average_request_time_ms": round(self.average_request_time * 1000, 2),
            "total_request_time_seconds": round(self.total_request_time, 2)
        }


# Global metrics instance
pool_metrics = ConnectionPoolMetrics()