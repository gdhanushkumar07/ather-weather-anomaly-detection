"""Offline training pipeline for the Multivariate (ECOD + Isolation Forest) layer.

Reads the Indian historical weather dataset in chunks (it is never loaded whole
and never copied into the repository) and writes small inference artifacts to
backend/models/multivariate_ecod_if/.
"""
