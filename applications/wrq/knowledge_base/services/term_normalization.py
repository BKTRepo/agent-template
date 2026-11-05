import re
import unicodedata

def normalize_term(value):
    text = unicodedata.normalize('NFKC', str(value or '').strip()).lower()
    text = re.sub(r'[-_/\\|,，、:：]+', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()
