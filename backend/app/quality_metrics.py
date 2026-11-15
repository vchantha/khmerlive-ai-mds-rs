"""Simple auditable source-language error metrics for monthly evaluation."""
import unicodedata

def normal(text:str,ignore_spaces:bool=False)->str:
    value=unicodedata.normalize("NFC",text.strip())
    return "".join(value.split()) if ignore_spaces else " ".join(value.split())

def distance(a:list[str],b:list[str])->int:
    previous=list(range(len(b)+1))
    for i,item in enumerate(a,1):
        current=[i]
        for j,other in enumerate(b,1):
            current.append(min(current[-1]+1,previous[j]+1,
                               previous[j-1]+(0 if item==other else 1)))
        previous=current
    return previous[-1]

def corpus_error(predictions:list[str],references:list[str],language:str)->dict:
    if len(predictions)!=len(references) or not predictions:
        raise ValueError("Predictions and references must have matching nonzero lengths")
    chars_err=0;chars_total=0
    words_err=0;words_total=0
    for predicted,reference in zip(predictions,references,strict=True):
        pred=normal(predicted,ignore_spaces=(language=="km"))
        ref=normal(reference,ignore_spaces=(language=="km"))
        chars_err+=distance(list(pred),list(ref))
        chars_total+=len(ref)
        if language=="en":
            words_err+=distance(normal(predicted).split(),normal(reference).split())
            words_total+=len(normal(reference).split())
    if chars_total==0:
        raise ValueError("All source references were empty")
    return {"cer":round(chars_err/chars_total,6),
            "wer":round(words_err/words_total,6) if words_total else None,
            "source_reference_characters":chars_total}
