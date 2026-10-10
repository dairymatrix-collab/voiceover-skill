"""Pinned and allowlisted model catalog for explicit local artifact acquisition.

The catalog intentionally contains no credentials or mutable arbitrary model IDs.
Revisions, file patterns, size ceilings, and licenses are reviewed independently.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tts_engine_adapters import (
    CHATTERBOX_MODEL_ID,
    CHATTERBOX_V2_ALLOW_PATTERNS,
    CHATTERBOX_V2_REVISION,
    KOKORO_MODEL_ID,
    KOKORO_MODEL_REVISION,
    KOKORO_MODEL_ALLOW_PATTERNS,
    QWEN_CUSTOM_VOICE_MODEL_ID,
    QWEN_CUSTOM_VOICE_REVISION,
    QWEN_VOICE_DESIGN_MODEL_ID,
    QWEN_VOICE_DESIGN_REVISION,
    QWEN_MODEL_ALLOW_PATTERNS,
)


@dataclass(frozen=True)
class ModelSpec:
    engine_id: str
    variant: str
    model_id: str
    revision: str
    license: str
    allow_patterns: tuple[str, ...]
    required_files: tuple[str, ...]
    required_patterns: tuple[str, ...]
    max_download_bytes: int
    expected_file_sizes: tuple[tuple[str, int], ...] = ()
    uses_main_ref: bool = False
    sources: tuple[str, ...] = ()

    @property
    def expected_file_size_map(self) -> dict[str, int]:
        return dict(self.expected_file_sizes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine_id": self.engine_id,
            "variant": self.variant,
            "model_id": self.model_id,
            "revision": self.revision,
            "license": self.license,
            "allow_patterns": list(self.allow_patterns),
            "required_files": list(self.required_files),
            "required_patterns": list(self.required_patterns),
            "max_download_bytes": self.max_download_bytes,
            "uses_main_ref": self.uses_main_ref,
            "expected_file_sizes": [
                {"path": name, "size_bytes": size}
                for name, size in self.expected_file_sizes
            ],
            "sources": list(self.sources),
        }


_QWEN_REQUIRED = (
    "config.json",
    "generation_config.json",
    "model.safetensors",
    "preprocessor_config.json",
    "tokenizer_config.json",
    "vocab.json",
    "merges.txt",
    "speech_tokenizer/config.json",
    "speech_tokenizer/configuration.json",
    "speech_tokenizer/model.safetensors",
    "speech_tokenizer/preprocessor_config.json",
)
_QWEN_EXPECTED_SIZES = (
    ("config.json", 4421),
    ("generation_config.json", 245),
    ("model.safetensors", 3_833_402_552),
    ("merges.txt", 1_671_839),
    ("preprocessor_config.json", 127),
    ("speech_tokenizer/config.json", 2336),
    ("speech_tokenizer/configuration.json", 76),
    ("speech_tokenizer/model.safetensors", 682_293_092),
    ("speech_tokenizer/preprocessor_config.json", 234),
    ("tokenizer_config.json", 7344),
    ("vocab.json", 2_776_833),
)

CHATTERBOX_EXPECTED_SIZES = (
    ("ve.pt", 5_698_626),
    ("t3_mtl23ls_v2.safetensors", 2_143_989_752),
    ("s3gen.pt", 1_057_165_844),
    ("grapheme_mtl_merged_expanded_v1.json", 69_989),
    ("conds.pt", 107_374),
    ("Cangjie5_TC.json", 1_920_163),
)

MODEL_SPECS: dict[tuple[str, str], ModelSpec] = {
    ("qwen3_tts", "voice_design"): ModelSpec(
        engine_id="qwen3_tts", variant="voice_design",
        model_id=QWEN_VOICE_DESIGN_MODEL_ID, revision=QWEN_VOICE_DESIGN_REVISION,
        license="Apache-2.0", allow_patterns=QWEN_MODEL_ALLOW_PATTERNS,
        required_files=_QWEN_REQUIRED,
        required_patterns=(), max_download_bytes=4_600_000_000,
        expected_file_sizes=_QWEN_EXPECTED_SIZES,
        sources=(
            "https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
            "https://huggingface.co/api/models/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign/tree/5ecdb67327fd37bb2e042aab12ff7391903235d3?recursive=true&expand=true",
        ),
    ),
    ("qwen3_tts", "preset"): ModelSpec(
        engine_id="qwen3_tts", variant="preset",
        model_id=QWEN_CUSTOM_VOICE_MODEL_ID, revision=QWEN_CUSTOM_VOICE_REVISION,
        license="Apache-2.0", allow_patterns=QWEN_MODEL_ALLOW_PATTERNS,
        required_files=_QWEN_REQUIRED,
        required_patterns=(), max_download_bytes=4_600_000_000,
        expected_file_sizes=(),
        sources=("https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",),
    ),
    ("chatterbox", "reference_clone"): ModelSpec(
        engine_id="chatterbox", variant="reference_clone",
        model_id=CHATTERBOX_MODEL_ID, revision=CHATTERBOX_V2_REVISION,
        license="MIT", allow_patterns=CHATTERBOX_V2_ALLOW_PATTERNS,
        required_files=("ve.pt", "t3_mtl23ls_v2.safetensors", "s3gen.pt",
                        "grapheme_mtl_merged_expanded_v1.json"),
        required_patterns=(), max_download_bytes=3_300_000_000,
        expected_file_sizes=CHATTERBOX_EXPECTED_SIZES,
        sources=(
            "https://huggingface.co/ResembleAI/chatterbox",
            "https://huggingface.co/api/models/ResembleAI/chatterbox/tree/5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18?recursive=true&expand=true",
        ),
    ),
    ("chatterbox", "preset"): ModelSpec(
        engine_id="chatterbox", variant="preset",
        model_id=CHATTERBOX_MODEL_ID, revision=CHATTERBOX_V2_REVISION,
        license="MIT", allow_patterns=CHATTERBOX_V2_ALLOW_PATTERNS,
        required_files=("ve.pt", "t3_mtl23ls_v2.safetensors", "s3gen.pt",
                        "grapheme_mtl_merged_expanded_v1.json"),
        required_patterns=(), max_download_bytes=3_300_000_000,
        expected_file_sizes=CHATTERBOX_EXPECTED_SIZES,
        sources=("https://huggingface.co/ResembleAI/chatterbox",),
    ),
    ("kokoro", "preset"): ModelSpec(
        engine_id="kokoro", variant="preset", model_id=KOKORO_MODEL_ID,
        revision=KOKORO_MODEL_REVISION, license="Apache-2.0",
        allow_patterns=KOKORO_MODEL_ALLOW_PATTERNS,
        required_files=("config.json", "kokoro-v1_0.pth"),
        required_patterns=("voices/*.pt",), max_download_bytes=1_250_000_000,
        uses_main_ref=True,
        sources=("https://huggingface.co/api/models/hexgrad/Kokoro-82M",),
    ),
}

DEFAULT_VARIANT = {
    "qwen3_tts": "voice_design",
    "chatterbox": "reference_clone",
    "kokoro": "preset",
}


def get_model_spec(engine_id: str, variant: str | None = None) -> ModelSpec:
    """Return one fixed model plan; never accept a caller-supplied repository or ref."""
    if not isinstance(engine_id, str) or engine_id not in {"qwen3_tts", "chatterbox", "kokoro"}:
        raise ValueError("UNKNOWN_ENGINE")
    chosen = DEFAULT_VARIANT[engine_id] if variant is None else variant
    if not isinstance(chosen, str):
        raise ValueError("MODEL_VARIANT_INVALID")
    try:
        return MODEL_SPECS[(engine_id, chosen)]
    except KeyError as exc:
        raise ValueError("MODEL_VARIANT_UNSUPPORTED") from exc
