"""The future-meta recommender (design: docs/future-meta/DESIGN.md).

It lives in a subpackage, with its settings in config/future_meta/, because the model cache fingerprint
(crdeck.pipeline._fingerprint) hashes only the top-level files of src/crdeck and config. Everything here runs
after training, so changing it must never force the exported models to retrain.
"""
