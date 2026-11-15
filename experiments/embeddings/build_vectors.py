"""Offline: trim GloVe into taxonomy/word_vectors.bin.gz for `linker/embed` (ROADMAP 24).

Source: GloVe 6B 100d (Pennington, Socher & Manning 2014; Public Domain Dedication and License),
downloaded once from https://huggingface.co/stanfordnlp/glove (glove.6B.zip -> glove.6B.100d.txt).
Never fetched at runtime. The 4.4 MB output is not committed (ROADMAP 24: embed is not recommended),
so build it before running embed, tune_embed.py or synonym_probe.py.

Keeps the TOP most frequent words (GloVe files are frequency-ordered), plus every word in the graph's
node text and the taxonomy's labels and synonyms. Each vector is stored as int8 with one float32 scale
(max |v| / 127): ~0.4% error per component, well below what changes a nearest-class choice.

A last entry "<mean>" holds the mean vector of the kept words (GloVe is anisotropic: unrelated
phrases share a common direction, so raw cosines of averaged phrases sit at 0.6-0.8; centring fixes that).

Format (gzip): b"WV1\\n", <II n, dim>, then per word: <H byte length>, utf-8 word, <f scale>, dim int8.

    bash -c '. scripts/env.sh; "$PY" experiments/embeddings/build_vectors.py path/to/glove.6B.100d.txt'
"""

from __future__ import annotations

import gzip
import re
import struct
import sys
from pathlib import Path

from camoreasoning.graph import load_graph
from camoreasoning.taxonomy import load_taxonomy

TOP = 40_000
OUT = Path("taxonomy/word_vectors.bin.gz")
NODE_FIELDS = ("name", "entity_term", "measured_attribute")


def corpus_words() -> set[str]:
    g, tax = load_graph(), load_taxonomy()
    text = [str(n.get(f) or "") for n in g.nodes.values() for f in NODE_FIELDS]
    text += [p for c in tax.classes.values() for p in (c.label, *c.synonyms)]
    return {w for t in text for w in re.findall(r"[a-z0-9]+", t.lower())}


def main(src: str) -> None:
    want = corpus_words()
    rows = []
    with open(src, encoding="utf-8") as f:
        for i, line in enumerate(f):
            word, *vals = line.rstrip("\n").split(" ")
            if i >= TOP and word not in want:
                continue
            v = [float(x) for x in vals]
            scale = max(abs(x) for x in v) / 127 or 1.0
            rows.append((word, scale, bytes((round(x / scale) & 0xFF) for x in v)))
    dim = len(rows[0][2])
    # "<mean>": the kept vocabulary's mean vector, so `linker/embed` can centre vectors without a 40k-row pass
    sums = [0.0] * dim
    for _, scale, q in rows:
        for i, b in enumerate(q):
            sums[i] += scale * (b - 256 if b > 127 else b)
    mean = [x / len(rows) for x in sums]
    mscale = max(abs(x) for x in mean) / 127 or 1.0
    rows.append(("<mean>", mscale, bytes((round(x / mscale) & 0xFF) for x in mean)))
    with open(OUT, "wb") as fh, gzip.GzipFile(fileobj=fh, mode="wb", compresslevel=9, mtime=0) as out:
        out.write(b"WV1\n" + struct.pack("<II", len(rows), dim))
        for word, scale, q in rows:
            w = word.encode("utf-8")
            out.write(struct.pack("<H", len(w)) + w + struct.pack("<f", scale) + q)
    covered = len(want & {r[0] for r in rows})
    size = OUT.stat().st_size / 1e6
    print(f"{len(rows)} words x {dim} -> {OUT} ({size:.1f} MB); corpus words covered {covered}/{len(want)}")


if __name__ == "__main__":
    main(sys.argv[1])
