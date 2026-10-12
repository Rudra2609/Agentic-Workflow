import re
from collections import Counter
def top_words(text, k):
    if k <= 0:
        return []
    c = Counter(re.findall(r"[a-z]+", text.lower()))
    return sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
