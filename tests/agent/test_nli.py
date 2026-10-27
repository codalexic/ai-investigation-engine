import json
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from huggingface_hub.errors import EntryNotFoundError

from app.agent.nli import OnnxNliModel
from app.core.errors import LLMError


@pytest.mark.parametrize("cache_dir", [None, "model-cache"])
def test_lazy_load_batch_and_label_order(monkeypatch, tmp_path, cache_dir):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"id2label": {"0": "neutral", "1": "contradiction", "2": "entailment"}})
    )
    downloads = []

    def download(model, filename, **options):
        assert options == ({"cache_dir": cache_dir} if cache_dir else {})
        downloads.append(filename)
        if filename.endswith("model_quantized.onnx"):
            raise EntryNotFoundError("missing")
        return str(config) if filename == "config.json" else filename

    monkeypatch.setattr("huggingface_hub.hf_hub_download", download)
    tokenizer = Mock()
    tokenizer.encode_batch.return_value = [
        SimpleNamespace(ids=[1, 2], attention_mask=[1, 1], type_ids=[0, 1])
    ] * 2
    monkeypatch.setattr("tokenizers.Tokenizer", SimpleNamespace(from_file=lambda path: tokenizer))
    session = Mock()
    session.get_inputs.return_value = [
        SimpleNamespace(name="input_ids"),
        SimpleNamespace(name="attention_mask"),
    ]
    session.run.return_value = [np.array([[0.0, 0.0, 4.0], [0.0, 4.0, 0.0]])]
    factory = Mock(return_value=session)
    monkeypatch.setattr("onnxruntime.InferenceSession", factory)
    model = OnnxNliModel("test", cache_dir)
    assert not downloads
    predictions = model.predict_batch([("premise", "hypothesis"), ("other", "claim")])
    assert predictions[0]["entailment"] > 0.9 and predictions[1]["contradiction"] > 0.9
    assert sum(predictions[0].values()) == pytest.approx(1)
    assert "onnx/model.onnx" in downloads
    tokenizer.enable_truncation.assert_called_once_with(max_length=512)
    assert set(session.run.call_args.args[1]) == {"input_ids", "attention_mask"}
    model.predict_batch([("premise", "hypothesis")] * 2)
    assert factory.call_count == 1


def test_model_load_error(monkeypatch):
    monkeypatch.setattr("huggingface_hub.hf_hub_download", Mock(side_effect=OSError("offline")))
    with pytest.raises(LLMError, match="load NLI"):
        OnnxNliModel("test").predict("a", "b")
