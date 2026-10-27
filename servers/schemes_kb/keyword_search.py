import math
import unicodedata
from collections import Counter
from html.parser import HTMLParser


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, text):
        self.parts.append(text)


def tokenize(text, is_html=False):
    if is_html:
        parser = VisibleText()
        parser.feed(text)
        text = " ".join(parser.parts)
    words = []
    current = []
    for character in unicodedata.normalize("NFC", text).casefold():
        # Combining marks are part of Hindi words, not separators.
        if unicodedata.category(character)[0] in "LNM":
            current.append(character)
        elif current:
            words.append("".join(current))
            current = []
    if current:
        words.append("".join(current))
    return words


def bm25_rank(question, records, limit=20, k1=1.2, b=0.75):
    terms = set(tokenize(question))
    documents = [(key, Counter(tokenize(row["text"], row.get("kind") == "table")))
                 for key, row in records.items()]
    if not documents or not terms:
        return []
    count = len(documents)
    average_length = sum(sum(words.values()) for _, words in documents) / count or 1
    frequencies = {term: sum(term in words for _, words in documents) for term in terms}
    scores = []
    for key, words in documents:
        length = sum(words.values())
        score = 0
        for term in terms:
            frequency = words[term]
            if not frequency:
                continue
            idf = math.log(1 + (count - frequencies[term] + 0.5) / (frequencies[term] + 0.5))
            denominator = frequency + k1 * (1 - b + b * length / average_length)
            score += idf * frequency * (k1 + 1) / denominator
        if score > 0:
            scores.append((key, score))
    return sorted(scores, key=lambda item: (-item[1], item[0]))[:limit]


def reciprocal_rank_fusion(*rankings, constant=60):
    scores = {}
    for ranking in rankings:
        for rank, (key, _) in enumerate(ranking, start=1):
            scores[key] = scores.get(key, 0) + 1 / (constant + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))
