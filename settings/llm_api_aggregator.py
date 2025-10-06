import requests
from typing import Dict, List, Optional, Any, Type, Union
from abc import ABC, abstractmethod
from pydantic import ValidationError
from langchain_core.output_parsers import StrOutputParser
from langchain.prompts import PromptTemplate
from langchain_core.language_models.llms import LLM
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langchain_together import ChatTogether
from .settings_manager import WWSettingsManager
import logging
import time  # Added for cache expiration

# Configuration constants
DEFAULT_MAX_TOKENS = 1024
DEFAULT_TEMPERATURE = 0.7
MODEL_CACHE_TTL = 3600  # Cache TTL in seconds (1 hour)

class LLMProviderBase(ABC):
    """Base class for all LLM providers."""
    
    def __init__(self, config: Dict[str, Any] = None, aggregator=None):
        self.config = config or {}
        self.cached_models = None
        self.aggregator = aggregator  # Reference to WW_Aggregator for cache access
    
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the name of the provider."""
        pass
    
    @property
    @abstractmethod
    def default_endpoint(self) -> str:
        """Return the default endpoint for the provider."""
        pass

    @property
    def model_list_key(self) -> str:
        """Return the key for the model name in the provider's json response."""
        return "data"

    @property
    def model_key(self) -> str:
        """Return the key for the model name in the provider's json response."""
        return "id"
    
    @property
    def model_requires_api_key(self) -> bool:
        """Return whether the provider requires an API key."""
        return False
    
    @property
    def use_reverse_sort(self) -> bool:
        """Return whether to reverse the output of the model list."""
        return False

    @abstractmethod
    def get_llm_instance(self, overrides) -> Union[LLM, BaseChatModel]:
        """Returns a configured LLM instance."""
        pass
    
    def _do_models_request(self, url: str, headers: Dict[str, str] = None) -> List[str]:
        """Send a request to the provider to fetch available models."""
        headers = headers or {'Authorization': f'Bearer {self.get_api_key()}'}
        return requests.get(url, headers=headers)
    
    def get_available_models(self, do_refresh: bool = False) -> List[str]:
        """Returns a list of available model IDs from the provider."""
        model_details = self.get_model_details(do_refresh)
        return [model[self.model_key] for model in model_details]

    def get_model_details(self, do_refresh: bool = False) -> List[Dict[str, Any]]:
        """Returns detailed information about available models."""
        # Check aggregator's cache first
        if self.aggregator and not do_refresh:
            cached = self.aggregator.get_cached_models(self.provider_name)
            if cached:
                logging.debug(f"Returning cached models for {self.provider_name} from aggregator")
                self.cached_models = cached  # Update local cache for compatibility
                return cached

        # Fallback to local cache if aggregator not available or refresh requested
        if self.cached_models is not None and not do_refresh:
            logging.debug(f"Returning local cached models for {self.provider_name}")
            return self.cached_models

        # Fetch models from API
        if self.model_requires_api_key and not self.get_api_key():
            raise ValueError(f"API key required for {self.provider_name}")
        url = self.get_base_url()
        if url[-1] != "/":
            url += "/"
        url += "models"
        logging.debug(f"Fetching models from {url}")
        response = self._do_models_request(url)
        if response.status_code == 200:
            models_data = response.json()
            self.cached_models = [
                {
                    "id": model.get(self.model_key, ""),
                    "name": model.get("name", model.get("display_name", model.get(self.model_key, ""))),
                    "description": model.get("description", "No description available"),
                    "architecture": model.get("architecture", {"modality": "text->text", "instruct_type": "general"})
                }
                for model in models_data.get(self.model_list_key, [])
            ]
            self.cached_models.sort(key=lambda x: x["id"], reverse=self.use_reverse_sort)
            # Store in aggregator's cache
            if self.aggregator:
                self.aggregator.cache_models(self.provider_name, self.cached_models)
        else:
            self.cached_models = []
            if do_refresh:
                raise ResourceWarning(response.json().get("error", "Failed to fetch models"))
        return self.cached_models

    def get_current_model(self) -> str:
        """Returns the currently configured model name."""
        return self.config.get("model", "")

    def get_default_endpoint(self) -> str:
        """Returns the default endpoint for the provider."""
        return self.default_endpoint

    def get_base_url(self) -> str:
        """Returns the base URL for the provider."""
        return self.config.get("endpoint") or self.get_default_endpoint()
    
    def get_api_key(self) -> str:
        """Returns the API key for the provider."""
        return self.config.get("api_key", "")
    
    def get_timeout(self, overrides) -> int:
        """Returns the timeout setting for the provider."""
        return overrides.get("timeout", self.config.get("timeout", 30))
    
    def get_context_window(self) -> int:
        """Returns the context window size for the current model."""
        return 4096

    def get_model_endpoint(self, overrides=None) -> str:
        """Returns the model endpoint for the provider."""
        url = overrides and overrides.get("endpoint") or self.config.get("endpoint", self.get_base_url())
        return url.replace("/chat/completions", "/models")

    def test_connection(self, overrides=None) -> bool:
        """Test the connection to the provider. Throws exception when it fails."""
        overrides = overrides or {}
        overrides["max_tokens"] = 1
        if not overrides.get("model"):
            overrides["model"] = self.get_current_model() or "None"
        llm = self.get_llm_instance(overrides)
        if not llm:
            return False

        prompt = PromptTemplate(input_variables=[], template="testing connection")
        chain = prompt | llm | StrOutputParser()
        response = chain.invoke({})
        return True

class OpenAIProvider(LLMProviderBase):
    """OpenAI LLM provider implementation."""
    
    @property
    def provider_name(self) -> str:
        return "OpenAI"
    
    @property
    def default_endpoint(self) -> str:
        return "https://api.openai.com/v1/"
    
    @property
    def model_requires_api_key(self) -> bool:
        return True
    
    def get_llm_instance(self, overrides) -> BaseChatModel:
        return ChatOpenAI(
            openai_api_key=overrides.get("api_key", self.get_api_key()),
            openai_api_base=overrides.get("endpoint", self.get_base_url()),
            model=overrides.get("model", self.get_current_model()),
            temperature=overrides.get("temperature", self.config.get("temperature", DEFAULT_TEMPERATURE)),
            max_tokens=overrides.get("max_tokens", self.config.get("max_tokens", DEFAULT_MAX_TOKENS)),
            request_timeout=self.get_timeout(overrides)
        )

    def get_model_details(self, do_refresh: bool = False) -> List[Dict[str, Any]]:
        """Returns detailed information about available OpenAI models."""
        # Use shared cache logic from base class
        if self.aggregator and not do_refresh:
            cached = self.aggregator.get_cached_models(self.provider_name)
            if cached:
                logging.debug(f"Returning cached models for {self.provider_name} from aggregator")
                self.cached_models = cached
                return cached

        if self.cached_models is not None and not do_refresh:
            logging.debug(f"Returning local cached models for {self.provider_name}")
            return self.cached_models

        if self.model_requires_api_key and not self.get_api_key():
            raise ValueError(f"API key required for {self.provider_name}")
        url = self.get_base_url()
        if url[-1] != "/":
            url += "/"
        url += "models"
        logging.debug(f"Fetching models from {url}")
        response = self._do_models_request(url)
        if response.status_code == 200:
            models_data = response.json()
            self.cached_models = [
                {
                    "id": model.get("id", ""),
                    "name": model.get("id", ""),
                    "description": "https://platform.openai.com/docs/models/compare",
                    "context_length": "unknown",
                    "architecture": {"modality": "text->text", "instruct_type": "general"}
                }
                for model in models_data.get(self.model_list_key, [])
            ]
            self.cached_models.sort(key=lambda x: x["id"], reverse=self.use_reverse_sort)
            if self.aggregator:
                self.aggregator.cache_models(self.provider_name, self.cached_models)
        else:
            self.cached_models = []
            if do_refresh:
                raise ResourceWarning(response.json().get("error", "Failed to fetch models"))
        return self.cached_models

class AnthropicProvider(LLMProviderBase):
    """Anthropic LLM provider implementation."""
    
    @property
    def provider_name(self) -> str:
        return "Anthropic"
    
    @property
    def default_endpoint(self) -> str:
        return "https://api.anthropic.com/v1/"

    @property
    def model_requires_api_key(self) -> bool:
        return True
    
    @property
    def use_reverse_sort(self) -> bool:
        return True

    def get_llm_instance(self, overrides) -> BaseChatModel:
        return ChatAnthropic(
            anthropic_api_key=overrides.get("api_key", self.get_api_key()),
            base_url=overrides.get("endpoint", None),
            model=overrides.get("model", self.get_current_model() or "claude-3-haiku-20240307"),
            temperature=overrides.get("temperature", self.config.get("temperature", DEFAULT_TEMPERATURE)),
            max_tokens=overrides.get("max_tokens", self.config.get("max_tokens", DEFAULT_MAX_TOKENS)),
            timeout=self.get_timeout(overrides)
        )
    
    def _do_models_request(self, url: str, headers: Dict[str, str] = None) -> List[str]:
        """Send a request to the provider to fetch available models."""
        default_headers = {
            "x-api-key": self.get_api_key(),
            "anthropic-version": '2023-06-01'
        }
        if headers:
            default_headers.update(headers)
        return requests.get(url, headers=default_headers)

class GeminiProvider(LLMProviderBase):
    """Google Gemini provider implementation."""
    
    @property
    def provider_name(self) -> str:
        return "Gemini"
    
    @property
    def default_endpoint(self) -> str:
        return "https://generativelanguage.googleapis.com/v1beta/"
    
    @property
    def model_requires_api_key(self) -> bool:
        return True
    
    @property
    def model_list_key(self) -> str:
        return "models"

    @property
    def model_key(self) -> str:
        return "id"
    
    @property
    def use_reverse_sort(self) -> bool:
        return True
    
    def get_llm_instance(self, overrides) -> BaseChatModel:
        return ChatGoogleGenerativeAI(
            google_api_key=overrides.get("api_key", self.get_api_key()),
            model=overrides.get("model", self.get_current_model() or "gemini-2.0-flash"),
            temperature=overrides.get("temperature", self.config.get("temperature", DEFAULT_TEMPERATURE)),
            max_output_tokens=overrides.get("max_tokens", self.config.get("max_tokens", DEFAULT_MAX_TOKENS)),
            timeout=self.get_timeout(overrides)
        )

    def _do_models_request(self, url: str, headers: Dict[str, str] = None) -> List[str]:
        """Send a request to the provider to fetch available models."""
        api_key = self.get_api_key()
        if not api_key:
            raise ValueError(f"API key required for {self.provider_name}")
        url += f"?key={api_key}"
        return requests.get(url, headers=headers)

    def get_model_details(self, do_refresh: bool = False) -> List[Dict[str, Any]]:
        """Returns detailed information about available Gemini models."""
        if self.aggregator and not do_refresh:
            cached = self.aggregator.get_cached_models(self.provider_name)
            if cached:
                logging.debug(f"Returning cached models for {self.provider_name} from aggregator")
                self.cached_models = cached
                return cached

        if self.cached_models is not None and not do_refresh:
            logging.debug(f"Returning local cached models for {self.provider_name}")
            return self.cached_models

        if self.model_requires_api_key and not self.get_api_key():
            raise ValueError(f"API key required for {self.provider_name}")
        url = self.get_base_url()
        if url[-1] != "/":
            url += "/"
        url += "models"
        logging.debug(f"Fetching models from {url}")
        response = self._do_models_request(url)
        if response.status_code == 200:
            models_data = response.json()
            self.cached_models = [
                {
                    "id": model.get("name", ""),
                    "name": model.get("displayName", model.get("name", "")),
                    "description": model.get("description", "Gemini model"),
                    "version": model.get("version", "unknown"),
                    "context_length": model.get("inputTokenLimit", 0),
                    "output_Length": model.get("outputTokenLimit", 0),
                    "architecture": {"modality": "text->text", "instruct_type": "general"},
                    "temperature": model.get("temperature", 0),
                    "max_temperature": model.get("maxTemperature", 1),
                    "topP": model.get("topP", 0),
                    "topK": model.get("topK", 0),
                    "methods": model.get("supportedGenerationMethods", "")
                }
                for model in models_data.get(self.model_list_key, [])
            ]
            self.cached_models.sort(key=lambda x: x["id"], reverse=self.use_reverse_sort)
            if self.aggregator:
                self.aggregator.cache_models(self.provider_name, self.cached_models)
        else:
            self.cached_models = []
            if do_refresh:
                raise ResourceWarning(response.json().get("error", "Failed to fetch models"))
        return self.cached_models

class OllamaProvider(LLMProviderBase):
    """Ollama LLM provider implementation."""
    
    @property
    def provider_name(self) -> str:
        return "Ollama"
    
    @property
    def default_endpoint(self) -> str:
        return "http://localhost:11434/v1/"
    
    def get_llm_instance(self, overrides):
        mymodel = overrides.get("model", self.get_current_model())
        if mymodel[0:5] in ["", "Local"]:
            mymodel = self.get_current_model()
        return ChatOllama(
            model=mymodel,
            temperature=overrides.get("temperature", self.config.get("temperature", DEFAULT_TEMPERATURE)),
            timeout=self.get_timeout(overrides)
        )

    def get_model_details(self, do_refresh: bool = False) -> List[Dict[str, Any]]:
        """Returns detailed information about available Ollama models."""
        if self.aggregator and not do_refresh:
            cached = self.aggregator.get_cached_models(self.provider_name)
            if cached:
                logging.debug(f"Returning cached models for {self.provider_name} from aggregator")
                self.cached_models = cached
                return cached

        if self.cached_models is not None and not do_refresh:
            logging.debug(f"Returning local cached models for {self.provider_name}")
            return self.cached_models

        url = self.get_base_url().replace("/v1/", "/api/tags")
        logging.debug(f"Fetching models from {url}")
        response = self._do_models_request(url)
        if response.status_code == 200:
            models_data = response.json()
            self.cached_models = [
                {
                    "id": model.get("name", ""),
                    "name": model.get("model", model.get("name", "")),
                    "description": "Local Ollama model",
                    "context_length": 4096,
                    "pricing": {"prompt": "0", "completion": "0", "request": "0"},
                    "architecture": {"modality": "text->text", "instruct_type": "general"}
                }
                for model in models_data.get("models", [])
            ]
            self.cached_models.sort(key=lambda x: x["id"], reverse=self.use_reverse_sort)
            if self.aggregator:
                self.aggregator.cache_models(self.provider_name, self.cached_models)
        else:
            self.cached_models = []
            if do_refresh:
                raise ResourceWarning(response.json().get("error", "Failed to fetch models"))
        return self.cached_models

class OpenRouterProvider(LLMProviderBase):
    """OpenRouter provider implementation."""
    
    @property
    def provider_name(self) -> str:
        return "OpenRouter"
    
    @property
    def default_endpoint(self) -> str:
        return "https://openrouter.ai/api/v1/"
    
    @property
    def model_requires_api_key(self) -> bool:
        return True
    
    def get_llm_instance(self, overrides) -> BaseChatModel:
        return ChatOpenAI(
            openai_api_key=overrides.get("api_key", self.get_api_key()),
            base_url=overrides.get("endpoint", self.get_base_url()),
            model=overrides.get("model", self.get_current_model()),
            temperature=overrides.get("temperature", self.config.get("temperature", DEFAULT_TEMPERATURE)),
            max_tokens=overrides.get("max_tokens", self.config.get("max_tokens", DEFAULT_MAX_TOKENS)),
            request_timeout=self.get_timeout(overrides)
        )

    def get_model_details(self, do_refresh: bool = False) -> List[Dict[str, Any]]:
        """Returns detailed information about available OpenRouter models."""
        if self.aggregator and not do_refresh:
            cached = self.aggregator.get_cached_models(self.provider_name)
            if cached:
                logging.debug(f"Returning cached models for {self.provider_name} from aggregator")
                self.cached_models = cached
                return cached

        if self.cached_models is not None and not do_refresh:
            logging.debug(f"Returning local cached models for {self.provider_name}")
            return self.cached_models

        if self.model_requires_api_key and not self.get_api_key():
            raise ValueError(f"API key required for {self.provider_name}")
        url = self.get_base_url()
        if url[-1] != "/":
            url += "/"
        url += "models"
        logging.debug(f"Fetching models from {url}")
        response = self._do_models_request(url)
        if response.status_code == 200:
            models_data = response.json()
            self.cached_models = [
                {
                    "id": model.get("id", ""),
                    "name": model.get("name", model.get("id", "")),
                    "description": model.get("description", "OpenRouter model"),
                    "context_length": model.get("context_length", 4096),
                    "pricing": model.get("pricing", {"prompt": "0", "completion": "0", "request": "0"}),
                    "architecture": model.get("architecture", {"modality": "text->text", "instruct_type": "general"})
                }
                for model in models_data.get(self.model_list_key, [])
            ]
            self.cached_models.sort(key=lambda x: x["id"], reverse=self.use_reverse_sort)
            if self.aggregator:
                self.aggregator.cache_models(self.provider_name, self.cached_models)
        else:
            self.cached_models = []
            if do_refresh:
                raise ResourceWarning(response.json().get("error", "Failed to fetch models"))
        return self.cached_models

class TogetherAIProvider(LLMProviderBase):
    """Together AI provider implementation."""
    
    @property
    def provider_name(self) -> str:
        return "TogetherAI"
    
    @property
    def default_endpoint(self) -> str:
        return "https://api.together.xyz/v1"
    
    @property
    def model_requires_api_key(self) -> bool:
        return True
    
    def get_llm_instance(self, overrides) -> BaseChatModel:
        return ChatTogether(
            together_api_key=overrides.get("api_key", self.get_api_key()),
            base_url=overrides.get("endpoint", self.get_base_url()),
            model=overrides.get("model", self.get_current_model()),
            temperature=overrides.get("temperature", self.config.get("temperature", DEFAULT_TEMPERATURE)),
            max_tokens=overrides.get("max_tokens", self.config.get("max_tokens", DEFAULT_MAX_TOKENS)),
        )

    def get_available_models(self, do_refresh: bool = False) -> List[str]:
        """Returns a list of available model IDs from the provider."""
        return [model["id"] for model in self.get_model_details(do_refresh)]

    def get_model_details(self, do_refresh: bool = False) -> List[Dict[str, Any]]:
        """Returns detailed information about available TogetherAI models."""
        if self.aggregator and not do_refresh:
            cached = self.aggregator.get_cached_models(self.provider_name)
            if cached:
                logging.debug(f"Returning cached models for {self.provider_name} from aggregator")
                self.cached_models = cached
                return cached

        if self.cached_models is not None and not do_refresh:
            logging.debug(f"Returning local cached models for {self.provider_name}")
            return self.cached_models

        if self.model_requires_api_key and not self.get_api_key():
            raise ValueError(f"API key required for {self.provider_name}")
        url = self.get_base_url()
        if url[-1] != "/":
            url += "/"
        url += "models"
        logging.debug(f"Fetching models from {url}")
        response = self._do_models_request(url)
        if response.status_code == 200:
            models_data = response.json()
            self.cached_models = [
                {
                    "id": model.get("id", ""),
                    "name": model.get("display_name", model.get("id", "")),
                    "description": model.get("description", "TogetherAI model"),
                    "context_length": model.get("context_length", 4096),
                    "pricing": model.get("pricing", {"hourly": "0", "input": "0", "output": "0", "base": "0", "finetune": "0"}),
                    "architecture": model.get("architecture", {"modality": "text->text", "instruct_type": "general"}),
                    "created": model.get("created", None),
                    "type": model.get("type", "chat"),
                    "running": model.get("running", False),
                    "organization": model.get("organization", ""),
                    "link": model.get("link", ""),
                    "license": model.get("license", ""),
                    "config": model.get("config", {
                        "chat_template": "",
                        "stop": [],
                        "bos_token": "",
                        "eos_token": "",
                        "max_output_length": None
                    })
                }
                for model in models_data
            ]
            self.cached_models.sort(key=lambda x: x["id"], reverse=self.use_reverse_sort)
            if self.aggregator:
                self.aggregator.cache_models(self.provider_name, self.cached_models)
        else:
            self.cached_models = []
            if do_refresh:
                raise ResourceWarning(response.json().get("error", "Failed to fetch models"))
        return self.cached_models
    
class LMStudioProvider(LLMProviderBase):
    """LMStudio provider implementation."""
    
    @property
    def provider_name(self) -> str:
        return "LMStudio"
    
    @property
    def default_endpoint(self) -> str:
        return "http://localhost:1234/v1"

    def get_llm_instance(self, overrides) -> BaseChatModel:
        return ChatOpenAI(
            api_key="not-needed",
            base_url=overrides.get("endpoint", self.get_base_url()),
            model_name=overrides.get("model", self.get_current_model() or "local-model"),
            temperature=overrides.get("temperature", self.config.get("temperature", DEFAULT_TEMPERATURE)),
            max_tokens=overrides.get("max_tokens", self.config.get("max_tokens", DEFAULT_MAX_TOKENS)),
            request_timeout=self.get_timeout(overrides)
        )

class CustomProvider(LLMProviderBase):
    """Custom LLM provider implementation for local network tools."""
    
    @property
    def provider_name(self) -> str:
        return "Custom"
    
    @property
    def default_endpoint(self) -> str:
        return "http://localhost:11434/v1/"
    
    def get_api_key(self):
        return super().get_api_key() or "not-needed"
    
    def get_llm_instance(self, overrides) -> BaseChatModel:
        self.config["endpoint"] = overrides.get("endpoint", self.get_base_url())
        self.config["api_key"] = overrides.get("api_key", self.get_api_key())
        self.config["model"] = overrides.get("model", self.get_current_model())
        return ChatOpenAI(
            base_url=self.get_base_url(),
            api_key=self.get_api_key(),
            model_name=self.get_current_model() or "custom-model",
            temperature=overrides.get("temperature", self.config.get("temperature", DEFAULT_TEMPERATURE)),
            max_tokens=overrides.get("max_tokens", self.config.get("max_tokens", DEFAULT_MAX_TOKENS)),
            request_timeout=self.get_timeout(overrides)
        )

class WW_Aggregator:
    """Main aggregator class for managing LLM providers."""
    
    def __init__(self):
        self._provider_cache = {}
        self._settings = None
        self._model_cache = {}  # New: Shared cache for model details
        self._model_cache_timestamps = {}  # New: Timestamps for cache expiration
    
    def create_provider(self, provider_name: str, config: Dict[str, Any] = None) -> Optional[LLMProviderBase]:
        """Create a new provider instance."""
        provider_class = self._get_provider_class(provider_name)
        if not provider_class:
            return None
        
        config = config or {}
        return provider_class(config, aggregator=self)  # Pass self as aggregator
    
    def get_provider(self, provider_name: str) -> Optional[LLMProviderBase]:
        """Get a provider instance by name."""
        if provider_name not in self._provider_cache:
            config = self._get_provider_config(provider_name)
            if not config:
                return None
            
            provider = config.get("provider")
            provider_class = self._get_provider_class(provider)
            if not provider_class:
                return None
            
            self._provider_cache[provider_name] = provider_class(config, aggregator=self)
        
        return self._provider_cache[provider_name]
    
    def get_active_llms(self) -> List[str]:
        """Returns a list of all configured and cached LLMs."""
        return list(self._provider_cache.keys())
    
    def _get_provider_config(self, provider_name: str) -> Optional[Dict[str, Any]]:
        """Get the configuration for a provider from settings."""
        settings = WWSettingsManager.get_llm_configs()
        if not settings:
            return None
        
        return settings.get(provider_name)
    
    def _get_provider_class(self, provider_name: str) -> Optional[Type[LLMProviderBase]]:
        """Get the provider class based on the provider name."""
        provider_map = {
            cls().provider_name: cls
            for cls in LLMProviderBase.__subclasses__()
        }
        return provider_map.get(provider_name)
    
    def cache_models(self, provider_name: str, models: List[Dict[str, Any]]):
        """Cache model details for a provider."""
        self._model_cache[provider_name] = models
        self._model_cache_timestamps[provider_name] = time.time()
        logging.debug(f"Cached models for {provider_name}")
    
    def get_cached_models(self, provider_name: str) -> Optional[List[Dict[str, Any]]]:
        """Retrieve cached model details for a provider."""
        if provider_name in self._model_cache:
            timestamp = self._model_cache_timestamps.get(provider_name, 0)
            if time.time() - timestamp < MODEL_CACHE_TTL:
                return self._model_cache[provider_name]
            else:
                logging.debug(f"Cache expired for {provider_name}")
                del self._model_cache[provider_name]
                del self._model_cache_timestamps[provider_name]
        return None

import threading

class LLMAPIAggregator:
    """Main class for the LLM API Aggregator."""
    
    def __init__(self):
        self.aggregator = WW_Aggregator()
        self.interrupt_flag = threading.Event()
        self.is_streaming = False
        logging.debug("LLMAPIAggregator initialized")
    
    def get_llm_providers(self) -> List[str]:
        """Dynamically returns a list of supported LLM provider names."""
        return [cls().provider_name for cls in LLMProviderBase.__subclasses__()]
    
    def send_prompt_to_llm(
        self, 
        final_prompt: Union[str, List[Dict[str, str]]], 
        overrides: Optional[Dict[str, Any]] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> str:
        """Send a prompt to the active LLM and return the generated text.
        final_prompt may be a string (existing behavior) or a list of message dicts
        like [{'role': 'system','content':'...'}, ...] for chat-style calls.
        """
        overrides = overrides or {}
        
        provider_name = overrides.get("provider") or WWSettingsManager.get_active_llm_name()
        if provider_name in ["Local", "Default"]:
            provider_name = WWSettingsManager.get_active_llm_name()
            overrides = {}
        if not provider_name:
            raise ValueError("No active LLM provider specified")
        
        provider = self.aggregator.get_provider(provider_name)
        if not provider:
            raise ValueError(f"Provider '{provider_name}' not found or not configured")
        
        # Fallback for default prompt overrides
        if overrides.get("model") in [None, "Default Model"]:
            overrides["model"] = provider.get_current_model()
        
        llm = provider.get_llm_instance(overrides)

        # If final_prompt is already a list of message dicts, treat as chat request
        if isinstance(final_prompt, list):
            from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
            messages = []
            for message in final_prompt:
                role = (message.get("role") or "").lower()
                content = message.get("content", "")
                if role == "system":
                    messages.append(SystemMessage(content=content))
                elif role in ("user", "human"):
                    messages.append(HumanMessage(content=content))
                elif role in ("assistant", "ai"):
                    messages.append(AIMessage(content=content))
            response = llm.invoke(messages)
            return response.content

        # If a conversation_history was provided, convert and append the prompt as a HumanMessage
        if conversation_history:
            from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
            messages = []
            for message in conversation_history:
                role = (message.get("role") or "").lower()
                content = message.get("content", "")
                if role == "system":
                    messages.append(SystemMessage(content=content))
                elif role in ("user", "human"):
                    messages.append(HumanMessage(content=content))
                elif role in ("assistant", "ai"):
                    messages.append(AIMessage(content=content))
            messages.append(HumanMessage(content=final_prompt))
            response = llm.invoke(messages)
            return response.content
        else:
            # fallback: keep existing completion-style behavior
            return llm.invoke(final_prompt).content

    def stream_prompt_to_llm(
        self, 
        final_prompt: Union[str, List[Dict[str, str]]], 
        overrides: Optional[Dict[str, Any]] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ):
        """Stream a prompt to the active LLM and yield the generated text.
        Supports chat-style `final_prompt` (list of dicts) or string fallback.
        """
        logging.debug(f"Starting stream_prompt_to_llm, interrupt_flag: {self.interrupt_flag.is_set()}")
        overrides = overrides or {}
        
        provider_name = overrides.get("provider") or WWSettingsManager.get_active_llm_name()
        if provider_name in ["Local", "Default"]:
            provider_name = WWSettingsManager.get_active_llm_name()
            overrides = {}
        if not provider_name:
            raise ValueError("No active LLM provider specified")
        
        provider = self.aggregator.get_provider(provider_name)
        if not provider:
            raise ValueError(f"Provider '{provider_name}' not found or not configured")
        
        if provider.model_requires_api_key:
            api_key = overrides.get("api_key", provider.get_api_key())
            if not api_key or api_key == "not-needed":
                raise ValueError(f"API key required for {provider_name} but not provided")
            
        # Fallback for default prompt overrides
        if overrides.get("model") in [None, "Default Model"]:
            overrides["model"] = provider.get_current_model()

        try:
            llm = provider.get_llm_instance(overrides)
        except ValueError as e:
            raise ValueError(f"Failed to initialize LLM: {e}")

        self.is_streaming = True
        try:
            # chat-style list of messages
            if isinstance(final_prompt, list):
                from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
                messages = []
                for message in final_prompt:
                    role = (message.get("role") or "").lower()
                    content = message.get("content", "")
                    if role == "system":
                        messages.append(SystemMessage(content=content))
                    elif role in ("user", "human"):
                        messages.append(HumanMessage(content=content))
                    elif role in ("assistant", "ai"):
                        messages.append(AIMessage(content=content))
                stream = llm.stream(messages)
                for chunk in stream:
                    if self.interrupt_flag.is_set():
                        break
                    yield chunk.content

            elif conversation_history:
                from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
                messages = []
                for message in conversation_history:
                    role = (message.get("role") or "").lower()
                    content = message.get("content", "")
                    if role == "system":
                        messages.append(SystemMessage(content=content))
                    elif role in ("user", "human"):
                        messages.append(HumanMessage(content=content))
                    elif role in ("assistant", "ai"):
                        messages.append(AIMessage(content=content))
                messages.append(HumanMessage(content=final_prompt))
                stream = llm.stream(messages)
                for chunk in stream:
                    if self.interrupt_flag.is_set():
                        break
                    yield chunk.content

            else:
                # fallback to string streaming
                stream = llm.stream(final_prompt)
                for chunk in stream:
                    if self.interrupt_flag.is_set():
                        break
                    yield chunk.content
        except Exception as e:
            logging.error(f"Streaming error: {e}")
            raise
        finally:
            self.is_streaming = False
            self.interrupt_flag.clear()

WWApiAggregator = LLMAPIAggregator()

def main():
    """Example usage of the LLM API Aggregator."""
    aggregator = LLMAPIAggregator()
    
    overrides = {
        "api_key": "AIFakeKey123",
    }

    try:
        p = aggregator.aggregator.create_provider("Gemini")
        p.get_default_endpoint()
        p.get_base_url()
    except ValidationError as exc:
        print(exc.errors())

    providers = aggregator.get_llm_providers()
    print(f"Supported providers: {providers}")
    
    try:
        response = aggregator.send_prompt_to_llm("Hello, tell me a short story about a robot.")
        print(f"Response: {response}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()