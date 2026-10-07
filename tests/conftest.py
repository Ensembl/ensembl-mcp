"""Offline fixtures; accidental TCP access is a test failure."""

import copy
import socket

import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    original = socket.socket.connect

    def connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError("Default tests must not use the network")
        return original(sock, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect)


@pytest.fixture
def genome():
    # Deliberately different from the historical human UUID.
    return {
        "genome_id": "cf06c737-7528-4f21-9a01-07aa29f6ffab",
        "scientific_name": "Homo sapiens",
        "assembly_accession": "GCA_000001405.29",
        "release_number": 115,
        "is_reference": True,
    }


@pytest.fixture
def brca2():
    # Historical manual gene response; not a live-data assertion.
    return copy.deepcopy({
        "stable_id": "ENSG00000139618.19",
        "symbol": "BRCA2",
        "name": "BRCA2 DNA repair associated",
        "so_term": "protein_coding",
        "transcript_count": 19,
        "alternative_symbols": ["BRCC2", "FACD", "FAD", "FAD1", "FANCD", "FANCD1", "XRCC11"],
    })
