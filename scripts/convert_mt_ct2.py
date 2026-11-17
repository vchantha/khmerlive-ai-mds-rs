"""Convert models/mt (Hugging Face M2M100) to CTranslate2 int8. Called by convert-mt-ct2.sh."""
import sys
import transformers
from ctranslate2.converters import TransformersConverter

# CTranslate2 >= 4.6 passes `dtype=`; transformers 4.51 still calls it `torch_dtype`.
_orig = transformers.PreTrainedModel.from_pretrained.__func__
def _from_pretrained(cls, *args, **kwargs):
    if "dtype" in kwargs and "torch_dtype" not in kwargs:
        kwargs["torch_dtype"] = kwargs.pop("dtype")
    return _orig(cls, *args, **kwargs)
transformers.PreTrainedModel.from_pretrained = classmethod(_from_pretrained)

src, dst = sys.argv[1], sys.argv[2]
TransformersConverter(src, copy_files=["sentencepiece.bpe.model", "vocab.json", "tokenizer_config.json",
                                       "special_tokens_map.json"]).convert(dst, quantization=(sys.argv[3] if len(sys.argv) > 3 else "int8"), force=True)
print("converted", src, "->", dst)
