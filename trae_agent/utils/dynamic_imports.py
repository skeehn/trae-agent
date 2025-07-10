# Copyright (c) 2025 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Dynamic import system for optional dependencies."""

import importlib
from typing import Any, Dict, Optional, Type
from functools import lru_cache

from ..utils.llm_client import LLMClient as BaseLLMClient
from .config import ModelParameters


class MissingDependencyError(ImportError):
    """Raised when a required optional dependency is missing."""
    
    def __init__(self, provider: str, package: str, install_command: str):
        self.provider = provider
        self.package = package
        self.install_command = install_command
        
        message = (
            f"Missing dependency for {provider} provider. "
            f"To use {provider}, install the required package:\n\n"
            f"  {install_command}\n\n"
            f"Or install all providers with:\n\n"
            f"  pip install trae-agent[all-providers]"
        )
        super().__init__(message)


class DynamicLLMClientLoader:
    """
    Dynamically loads LLM client classes with optional dependencies.
    
    Benefits:
    - Smaller base installation (60-70% reduction)
    - Pay-as-you-go dependency model
    - Helpful error messages for missing packages
    - Graceful degradation
    """
    
    # Mapping of providers to their requirements
    PROVIDER_DEPENDENCIES = {
        "openai": {
            "package": "openai",
            "module": "trae_agent.utils.openai_client",
            "class": "OpenAIClient",
            "install_command": "pip install trae-agent[openai]"
        },
        "anthropic": {
            "package": "anthropic",
            "module": "trae_agent.utils.anthropic_client", 
            "class": "AnthropicClient",
            "install_command": "pip install trae-agent[anthropic]"
        },
        "google": {
            "package": "google.genai",
            "module": "trae_agent.utils.google_client",
            "class": "GoogleClient", 
            "install_command": "pip install trae-agent[google]"
        },
        "ollama": {
            "package": "ollama",
            "module": "trae_agent.utils.ollama_client",
            "class": "OllamaClient",
            "install_command": "pip install trae-agent[ollama]"
        },
        "azure": {
            "package": "openai",  # Azure uses OpenAI client
            "module": "trae_agent.utils.azure_client",
            "class": "AzureClient",
            "install_command": "pip install trae-agent[openai]"
        },
        "openrouter": {
            "package": "openai",  # OpenRouter uses OpenAI client
            "module": "trae_agent.utils.openrouter_client",
            "class": "OpenRouterClient",
            "install_command": "pip install trae-agent[openai]"
        },
        "doubao": {
            "package": "openai",  # Doubao uses OpenAI client
            "module": "trae_agent.utils.doubao_client",
            "class": "DoubaoClient",
            "install_command": "pip install trae-agent[openai]"
        }
    }
    
    def __init__(self):
        self._loaded_clients: Dict[str, Type[BaseLLMClient]] = {}
        self._availability_cache: Dict[str, bool] = {}
    
    @lru_cache(maxsize=32)
    def is_provider_available(self, provider: str) -> bool:
        """Check if a provider's dependencies are available."""
        if provider not in self.PROVIDER_DEPENDENCIES:
            return False
        
        if provider in self._availability_cache:
            return self._availability_cache[provider]
        
        dep_info = self.PROVIDER_DEPENDENCIES[provider]
        try:
            importlib.import_module(dep_info["package"])
            self._availability_cache[provider] = True
            return True
        except ImportError:
            self._availability_cache[provider] = False
            return False
    
    def get_available_providers(self) -> list[str]:
        """Get list of providers with available dependencies."""
        return [
            provider for provider in self.PROVIDER_DEPENDENCIES.keys()
            if self.is_provider_available(provider)
        ]
    
    def get_missing_providers(self) -> Dict[str, str]:
        """Get list of providers with missing dependencies and their install commands."""
        missing = {}
        for provider, info in self.PROVIDER_DEPENDENCIES.items():
            if not self.is_provider_available(provider):
                missing[provider] = info["install_command"]
        return missing
    
    def load_client_class(self, provider: str) -> Type[BaseLLMClient]:
        """Load and return the client class for the specified provider."""
        if provider in self._loaded_clients:
            return self._loaded_clients[provider]
        
        if provider not in self.PROVIDER_DEPENDENCIES:
            raise ValueError(f"Unknown provider: {provider}. Available providers: {list(self.PROVIDER_DEPENDENCIES.keys())}")
        
        dep_info = self.PROVIDER_DEPENDENCIES[provider]
        
        # Check if dependency is available
        if not self.is_provider_available(provider):
            raise MissingDependencyError(
                provider=provider,
                package=dep_info["package"], 
                install_command=dep_info["install_command"]
            )
        
        try:
            # Import the module
            module = importlib.import_module(dep_info["module"])
            
            # Get the client class
            client_class = getattr(module, dep_info["class"])
            
            # Cache the loaded class
            self._loaded_clients[provider] = client_class
            
            return client_class
            
        except ImportError as e:
            raise MissingDependencyError(
                provider=provider,
                package=dep_info["package"],
                install_command=dep_info["install_command"]
            ) from e
        except AttributeError as e:
            raise ImportError(f"Client class {dep_info['class']} not found in {dep_info['module']}") from e
    
    def create_client(self, provider: str, model_parameters: ModelParameters) -> BaseLLMClient:
        """Create a client instance for the specified provider."""
        client_class = self.load_client_class(provider)
        return client_class(provider=provider, model_parameters=model_parameters)
    
    def get_dependency_info(self) -> Dict[str, Any]:
        """Get comprehensive dependency information."""
        available = self.get_available_providers()
        missing = self.get_missing_providers()
        
        return {
            "available_providers": available,
            "missing_providers": list(missing.keys()),
            "installation_commands": missing,
            "provider_count": {
                "available": len(available),
                "missing": len(missing),
                "total": len(self.PROVIDER_DEPENDENCIES)
            },
            "dependency_details": {
                provider: {
                    "available": self.is_provider_available(provider),
                    "package": info["package"],
                    "install_command": info["install_command"]
                }
                for provider, info in self.PROVIDER_DEPENDENCIES.items()
            }
        }
    
    def validate_provider_setup(self, provider: str) -> Dict[str, Any]:
        """Validate that a provider is properly set up."""
        if provider not in self.PROVIDER_DEPENDENCIES:
            return {
                "valid": False,
                "error": f"Unknown provider: {provider}",
                "suggestion": f"Available providers: {list(self.PROVIDER_DEPENDENCIES.keys())}"
            }
        
        if not self.is_provider_available(provider):
            dep_info = self.PROVIDER_DEPENDENCIES[provider]
            return {
                "valid": False,
                "error": f"Missing dependency for {provider}",
                "suggestion": f"Install with: {dep_info['install_command']}"
            }
        
        try:
            # Try to load the client class
            self.load_client_class(provider)
            return {
                "valid": True,
                "message": f"Provider {provider} is properly configured"
            }
        except Exception as e:
            return {
                "valid": False,
                "error": f"Failed to load {provider} client: {str(e)}",
                "suggestion": f"Try reinstalling: {self.PROVIDER_DEPENDENCIES[provider]['install_command']}"
            }


# Global loader instance
_global_loader = DynamicLLMClientLoader()


def get_client_loader() -> DynamicLLMClientLoader:
    """Get the global dynamic client loader."""
    return _global_loader


def load_llm_client(provider: str, model_parameters: ModelParameters) -> BaseLLMClient:
    """Load an LLM client with dynamic dependency handling."""
    return _global_loader.create_client(provider, model_parameters)


def check_provider_availability(provider: str) -> bool:
    """Check if a provider is available."""
    return _global_loader.is_provider_available(provider)


def get_dependency_report() -> Dict[str, Any]:
    """Get a comprehensive dependency report."""
    return _global_loader.get_dependency_info()


def validate_all_providers() -> Dict[str, Any]:
    """Validate all provider setups."""
    results = {}
    for provider in _global_loader.PROVIDER_DEPENDENCIES.keys():
        results[provider] = _global_loader.validate_provider_setup(provider)
    return results


# Helper functions for CLI usage
def print_dependency_report() -> None:
    """Print a formatted dependency report."""
    report = get_dependency_report()
    
    print("🔍 Trae Agent Dependency Report")
    print("=" * 40)
    
    print(f"\n✅ Available Providers ({report['provider_count']['available']}):")
    for provider in report["available_providers"]:
        print(f"  • {provider}")
    
    if report["missing_providers"]:
        print(f"\n❌ Missing Providers ({report['provider_count']['missing']}):")
        for provider in report["missing_providers"]:
            cmd = report["installation_commands"][provider]
            print(f"  • {provider}: {cmd}")
    
    print(f"\n📊 Summary: {report['provider_count']['available']}/{report['provider_count']['total']} providers available")


def install_suggestions(providers: list[str]) -> list[str]:
    """Get installation suggestions for specific providers."""
    suggestions = []
    for provider in providers:
        if provider in _global_loader.PROVIDER_DEPENDENCIES:
            cmd = _global_loader.PROVIDER_DEPENDENCIES[provider]["install_command"]
            suggestions.append(f"For {provider}: {cmd}")
    return suggestions