"""Model management for local LLM inference."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Try to import llama_cpp
try:
    from llama_cpp import Llama

    LLAMA_CPP_AVAILABLE = True
except ImportError:
    logger.warning("llama-cpp-python not installed, local model extraction disabled")
    LLAMA_CPP_AVAILABLE = False
    Llama = None


class ModelManager:
    """Manages loading and lifecycle of local LLM models."""

    def __init__(
        self,
        model_path: str | None = None,
        n_ctx: int = 2048,
        n_threads: int | None = None,
        n_gpu_layers: int = 0,
        lazy_load: bool = True,
    ):
        """
        Initialize model manager.

        Args:
            model_path: Path to GGUF model file
            n_ctx: Context size (default 2048 tokens)
            n_threads: Number of threads (default: auto-detect)
            n_gpu_layers: Number of layers to offload to GPU (0 = CPU only)
            lazy_load: If True, delay loading until first use (Phase 3 optimization)
        """
        self.model_path = model_path
        self.n_ctx = n_ctx
        self.n_threads = n_threads or os.cpu_count()
        self.n_gpu_layers = n_gpu_layers
        self.lazy_load = lazy_load
        self._model: Any | None = None
        self._initialized = False
        self._initialization_attempted = False

    @property
    def is_available(self) -> bool:
        """Check if llama-cpp-python is available."""
        return LLAMA_CPP_AVAILABLE

    @property
    def is_initialized(self) -> bool:
        """Check if model is loaded."""
        return self._initialized and self._model is not None

    async def initialize(self) -> bool:
        """
        Load the model into memory.

        Returns:
            True if successful, False otherwise
        """
        if not LLAMA_CPP_AVAILABLE:
            logger.error("Cannot initialize model: llama-cpp-python not installed")
            self._initialization_attempted = True
            return False

        if self._initialized:
            logger.debug("Model already initialized")
            return True

        if self._initialization_attempted:
            logger.debug("Model initialization was already attempted and failed")
            return False

        if not self.model_path:
            logger.error("Cannot initialize model: no model path provided")
            self._initialization_attempted = True
            return False

        model_file = Path(self.model_path)
        if not model_file.exists():
            logger.error(
                f"Model file not found: {self.model_path}",
                extra={"model_path": self.model_path},
            )
            self._initialization_attempted = True
            return False

        try:
            logger.info(
                f"Loading model from {self.model_path}",
                extra={
                    "model_path": self.model_path,
                    "n_ctx": self.n_ctx,
                    "n_threads": self.n_threads,
                    "n_gpu_layers": self.n_gpu_layers,
                },
            )

            # Import resource monitor for Phase 3 optimization
            try:
                from app.services.resource_monitor import get_resource_monitor
                from app.services.telemetry import telemetry

                resource_monitor = get_resource_monitor()

                # Check memory pressure before loading model
                if resource_monitor.should_disable_local_model():
                    logger.error(
                        "Cannot load model: system under memory pressure (>90% RAM usage)"
                    )
                    telemetry.increment_counter("model_load_skipped_memory_pressure")
                    self._initialization_attempted = True
                    return False

            except ImportError:
                # Resource monitor not available, proceed with loading
                pass

            self._model = Llama(
                model_path=str(model_file),
                n_ctx=self.n_ctx,
                n_threads=self.n_threads,
                n_gpu_layers=self.n_gpu_layers,
                verbose=False,
            )

            self._initialized = True
            self._initialization_attempted = True

            # Update telemetry
            try:
                from app.services.telemetry import telemetry

                telemetry.set_gauge("model_loaded_status", 1)
            except ImportError:
                pass

            logger.info(
                "Model loaded successfully",
                extra={"model_path": self.model_path},
            )
            return True

        except Exception as e:
            logger.error(
                f"Failed to load model: {e}",
                extra={"model_path": self.model_path, "error": str(e)},
                exc_info=True,
            )
            self._model = None
            self._initialized = False
            self._initialization_attempted = True

            # Update telemetry
            try:
                from app.services.telemetry import telemetry

                telemetry.increment_counter("model_load_failed")
            except ImportError:
                pass

            return False

    async def ensure_initialized(self) -> bool:
        """
        Ensure model is initialized (lazy loading support).

        For lazy loading, this will initialize on first use.
        Returns True if model is ready, False otherwise.
        """
        if self._initialized:
            return True

        if not self.lazy_load:
            # Eager loading mode, initialization should have been done already
            return False

        # Attempt lazy initialization
        return await self.initialize()

    async def generate(
        self,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.3,
        top_p: float = 0.9,
        stop: list[str] | None = None,
    ) -> str | None:
        """
        Generate text from the model.

        Args:
            prompt: Input prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (lower = more deterministic)
            top_p: Nucleus sampling threshold
            stop: Stop sequences

        Returns:
            Generated text or None on error
        """
        # Phase 3: Lazy loading - ensure model is initialized
        if not await self.ensure_initialized():
            logger.error("Cannot generate: model initialization failed")
            return None

        # Phase 3: Check resource pressure before inference
        try:
            from app.services.resource_monitor import get_resource_monitor

            resource_monitor = get_resource_monitor()
            if resource_monitor.should_disable_local_model():
                logger.warning(
                    "Skipping local model generation: system under memory pressure"
                )
                return None
        except ImportError:
            pass

        try:
            import time

            start_time = time.time()

            result = self._model(  # type: ignore
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                stop=stop or [],
                echo=False,
            )

            text = result["choices"][0]["text"]

            # Track inference latency
            elapsed_ms = int((time.time() - start_time) * 1000)
            try:
                from app.services.telemetry import telemetry

                telemetry.set_gauge("model_inference_latency_ms", elapsed_ms)
            except ImportError:
                pass

            return text.strip()

        except Exception as e:
            logger.error(
                f"Generation failed: {e}",
                extra={"error": str(e)},
                exc_info=True,
            )
            return None

    async def cleanup(self):
        """Unload model from memory."""
        if self._model is not None:
            logger.info("Unloading model")
            del self._model
            self._model = None
            self._initialized = False

            # Update telemetry
            try:
                from app.services.telemetry import telemetry

                telemetry.set_gauge("model_loaded_status", 0)
            except ImportError:
                pass

    def __del__(self):
        """Cleanup on deletion."""
        if self._model is not None:
            del self._model


# Recommended model: Phi-3-mini-3.8B Q4_K_M
# Download from: https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf
# File: Phi-3-mini-4k-instruct-q4.gguf (~2.2GB)
#
# Example download command:
# wget https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf/resolve/main/Phi-3-mini-4k-instruct-q4.gguf \
#      -O models/phi-3-mini-q4.gguf
