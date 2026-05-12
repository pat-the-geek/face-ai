"""Perceptual hash (pHash) sur image alignée — empreinte 64 bits.

La spec §11.1 prévoit FaceNet 512-dim ; on choisit ici une implémentation
plus légère pour l'itération en cours, suffisante pour la déduplication
("même image redistribuée") qui est le besoin opérationnel principal.
Comportement à l'intérieur du même contrat (`compute_embedding` retourne
`bytes | None`, comparaison via `embedding_distance`) — bascule future
vers ArcFace/FaceNet sans changer le pipeline.

Algorithme DCT-pHash standard (Cooper) :
  1. Image alignée → niveaux de gris 32×32
  2. DCT 2D
  3. Bloc basse fréquence 8×8 (on jette le coefficient DC)
  4. Médiane → 64 bits selon `coeff > median`
  5. Distance Hamming entre 2 hashes
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

PHASH_SIZE = 8  # côté du bloc basse fréquence retenu
DCT_INPUT = 32  # taille de redimensionnement avant DCT


def compute_embedding(image_path: Path) -> bytes | None:
    """Hash perceptuel 64 bits empaqueté en 8 octets."""
    img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    img = cv2.resize(img, (DCT_INPUT, DCT_INPUT), interpolation=cv2.INTER_AREA)
    dct = cv2.dct(img.astype(np.float32))
    low = dct[:PHASH_SIZE, :PHASH_SIZE].flatten()
    # On exclut le coefficient DC (luminance moyenne) du calcul de la médiane
    # pour ne pas être dominé par la luminosité globale
    median = float(np.median(low[1:]))
    bits = low > median
    return np.packbits(bits).tobytes()


def embedding_distance(a: bytes, b: bytes) -> float:
    """Distance Hamming normalisée à [0, 1] entre 2 hashes 64 bits.

    0 = hashes identiques, 1 = tous les bits diffèrent (cas extrême).
    Pour la déduplication, dist < 0.08 (≈ 5 bits) est un bon seuil.
    """
    bits_diff = sum(bin(x ^ y).count("1") for x, y in zip(a, b))
    return bits_diff / 64.0


def serialize(emb: bytes) -> bytes:
    return emb


def deserialize(data: bytes) -> bytes:
    return data
