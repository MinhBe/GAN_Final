from __future__ import annotations


def ngram_overlap(generated: list[str], reference: list[str], k: int = 3) -> float:
    if not generated or not reference:
        return 0.0
    reference_grams: set[str] = set()
    for text in reference:
        value = str(text)
        reference_grams.update(value[index:index + k] for index in range(max(0, len(value) - k + 1)))
    scores: list[float] = []
    for text in generated:
        value = str(text)
        grams = [value[index:index + k] for index in range(max(0, len(value) - k + 1))]
        scores.append(sum(gram in reference_grams for gram in grams) / len(grams) if grams else 0.0)
    return sum(scores) / len(scores)
