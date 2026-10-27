import json
import re
from typing import Protocol

import numpy as np

from app.core.config import get_settings
from app.core.errors import LLMError


class NliModel(Protocol):
    def predict_batch(self, pairs: list[tuple[str, str]]) -> list[dict[str, float]]: ...

    def predict(self, premise: str, hypothesis: str) -> dict[str, float]: ...


class OnnxNliModel:
    def __init__(self, model_id: str, cache_dir: str | None = None) -> None:
        self.model_id = model_id
        self.cache_dir = cache_dir if cache_dir is not None else get_settings().model_cache_dir
        self.session = None

    def _load(self) -> None:
        if self.session is not None:
            return
        from huggingface_hub import hf_hub_download
        from huggingface_hub.errors import EntryNotFoundError, LocalEntryNotFoundError
        from onnxruntime import InferenceSession
        from tokenizers import Tokenizer

        options = {"cache_dir": self.cache_dir} if self.cache_dir else {}
        try:
            try:
                path = hf_hub_download(self.model_id, "onnx/model_quantized.onnx", **options)
            except (EntryNotFoundError, LocalEntryNotFoundError):
                path = hf_hub_download(self.model_id, "onnx/model.onnx", **options)
            tokenizer = Tokenizer.from_file(
                hf_hub_download(self.model_id, "tokenizer.json", **options)
            )
            tokenizer.enable_truncation(max_length=512)
            tokenizer.enable_padding()
            with open(
                hf_hub_download(self.model_id, "config.json", **options), encoding="utf-8"
            ) as file:
                config = json.load(file)
            labels = {int(k): v.lower() for k, v in config["id2label"].items()}
            if set(labels.values()) != {"entailment", "neutral", "contradiction"}:
                raise LLMError("NLI model must declare semantic id2label labels")
            session = InferenceSession(path, providers=["CPUExecutionProvider"])
            self.tokenizer, self.labels, self.session = tokenizer, labels, session
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError("Unable to load NLI model") from exc

    def predict_batch(self, pairs: list[tuple[str, str]]) -> list[dict[str, float]]:
        if not pairs:
            return []
        self._load()
        try:
            encoded = self.tokenizer.encode_batch(pairs)
            values = {
                "input_ids": np.array([e.ids for e in encoded], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask for e in encoded], dtype=np.int64),
                "token_type_ids": np.array([e.type_ids for e in encoded], dtype=np.int64),
            }
            inputs = {item.name: values[item.name] for item in self.session.get_inputs()}
            logits = self.session.run(None, inputs)[0]
            probs = np.exp(logits - logits.max(axis=-1, keepdims=True))
            probs /= probs.sum(axis=-1, keepdims=True)
            return [{self.labels[i]: float(value) for i, value in enumerate(row)} for row in probs]
        except Exception as exc:
            raise LLMError("NLI inference failed") from exc

    def predict(self, premise: str, hypothesis: str) -> dict[str, float]:
        return self.predict_batch([(premise, hypothesis)])[0]


class FakeNli:
    def predict(self, premise: str, hypothesis: str) -> dict[str, float]:
        a, b = set(re.findall(r"\w+", premise.lower())), set(re.findall(r"\w+", hypothesis.lower()))
        negative = {"not", "never", "no", "disabled", "failed"}
        overlap = len((a - negative) & (b - negative)) / max(1, len(b - negative))
        contradiction = bool(a & negative) != bool(b & negative) and overlap >= 0.5
        label = "contradiction" if contradiction else "entailment" if overlap >= 0.5 else "neutral"
        return {
            name: 0.96 if name == label else 0.02
            for name in ("entailment", "neutral", "contradiction")
        }

    def predict_batch(self, pairs: list[tuple[str, str]]) -> list[dict[str, float]]:
        return [self.predict(*pair) for pair in pairs]
