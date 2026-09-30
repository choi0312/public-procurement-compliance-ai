"""Canonical ordering of one notice's original documents, without text edits."""
import hashlib
import re


def canonical_record(rec):
    def key(doc):
        natural = tuple((1, int(part)) if part.isdigit() else (0, part)
                        for part in re.split(r'(\d+)', doc['doc_id']))
        return (doc['type'] != '공고문', natural, doc['type'],
                hashlib.sha256(doc['text'].encode('utf-8')).hexdigest())
    return {**rec, 'docs': sorted(rec['docs'], key=key)}
