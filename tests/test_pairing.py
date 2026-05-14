"""Unit tests for engine/pairing.py - PairingResult and PairingEngine"""
import os
import pytest
from engine.pairing import PairingResult, PairingEngine


class TestPairingResult:
    """Tests for PairingResult dataclass"""

    def test_output_filename_format(self):
        """Output filename follows {source_name}_ref{ref_index}_gen{gen_index}.jpg convention"""
        result = PairingResult(
            source_path="/tmp/model_01.jpg",
            reference_path="/tmp/bg_03.jpg",
            source_filename="model_01.jpg",
            reference_filename="bg_03.jpg",
            generation_index=0,
            ref_index=3,
        )
        assert result.output_filename == "model_01_ref3_gen1.jpg"

    def test_output_filename_gen_index_is_1_based(self):
        """generation_index is 0-based internally but 1-based in output filename"""
        result = PairingResult(
            source_path="/tmp/src.jpg",
            reference_path="/tmp/ref.jpg",
            source_filename="src.jpg",
            reference_filename="ref.jpg",
            generation_index=2,
            ref_index=1,
        )
        assert result.output_filename == "src_ref1_gen3.jpg"

    def test_output_filename_strips_extension(self):
        """Source extension is stripped from output filename"""
        result = PairingResult(
            source_path="/tmp/photo.png",
            reference_path="/tmp/bg.webp",
            source_filename="photo.png",
            reference_filename="bg.webp",
            generation_index=0,
            ref_index=2,
        )
        assert result.output_filename == "photo_ref2_gen1.jpg"


class TestPairingEngineInit:
    """Tests for PairingEngine initialization"""

    def test_generations_clamped_to_min_1(self):
        engine = PairingEngine([], [], generations_per_source=0)
        assert engine.generations_per_source == 1

    def test_generations_clamped_to_max_5(self):
        engine = PairingEngine([], [], generations_per_source=10)
        assert engine.generations_per_source == 5

    def test_generations_within_range_unchanged(self):
        for n in range(1, 6):
            engine = PairingEngine([], [], generations_per_source=n)
            assert engine.generations_per_source == n

    def test_negative_generations_clamped_to_1(self):
        engine = PairingEngine([], [], generations_per_source=-5)
        assert engine.generations_per_source == 1

    def test_default_generations_is_1(self):
        engine = PairingEngine([], [])
        assert engine.generations_per_source == 1


class TestPairingEngineRefsGeN:
    """Tests for refs >= N case: each source gets N distinct references"""

    def test_each_source_gets_n_pairings(self):
        sources = [f"/tmp/src{i}.jpg" for i in range(3)]
        refs = [f"/tmp/ref{i}.jpg" for i in range(5)]
        engine = PairingEngine(sources, refs, generations_per_source=3)
        pairings = engine.generate_pairings()
        assert len(pairings) == 9  # 3 sources * 3 gens

    def test_each_source_has_distinct_references(self):
        sources = [f"/tmp/src{i}.jpg" for i in range(2)]
        refs = [f"/tmp/ref{i}.jpg" for i in range(5)]
        engine = PairingEngine(sources, refs, generations_per_source=3)
        pairings = engine.generate_pairings()

        for src in sources:
            src_pairings = [p for p in pairings if p.source_path == src]
            ref_paths = [p.reference_path for p in src_pairings]
            assert len(set(ref_paths)) == 3  # All distinct

    def test_generation_indices_are_sequential(self):
        sources = ["/tmp/src.jpg"]
        refs = [f"/tmp/ref{i}.jpg" for i in range(5)]
        engine = PairingEngine(sources, refs, generations_per_source=3)
        pairings = engine.generate_pairings()
        indices = [p.generation_index for p in pairings]
        assert indices == [0, 1, 2]


class TestPairingEngineOverflow:
    """Tests for N > refs > 1 case: use all distinct first, then random"""

    def test_total_pairings_equals_n(self):
        sources = ["/tmp/src.jpg"]
        refs = ["/tmp/ref1.jpg", "/tmp/ref2.jpg"]
        engine = PairingEngine(sources, refs, generations_per_source=4)
        pairings = engine.generate_pairings()
        assert len(pairings) == 4

    def test_first_m_are_distinct(self):
        sources = ["/tmp/src.jpg"]
        refs = ["/tmp/ref1.jpg", "/tmp/ref2.jpg"]
        engine = PairingEngine(sources, refs, generations_per_source=5)
        pairings = engine.generate_pairings()
        first_m_refs = set(p.reference_path for p in pairings[:2])
        assert len(first_m_refs) == 2

    def test_all_references_are_valid(self):
        sources = ["/tmp/src.jpg"]
        refs = ["/tmp/ref1.jpg", "/tmp/ref2.jpg", "/tmp/ref3.jpg"]
        engine = PairingEngine(sources, refs, generations_per_source=5)
        pairings = engine.generate_pairings()
        for p in pairings:
            assert p.reference_path in refs


class TestPairingEngineSingleRef:
    """Tests for refs == 1 case: all use the single reference"""

    def test_all_pairings_use_single_reference(self):
        sources = [f"/tmp/src{i}.jpg" for i in range(3)]
        refs = ["/tmp/only_ref.jpg"]
        engine = PairingEngine(sources, refs, generations_per_source=4)
        pairings = engine.generate_pairings()
        assert len(pairings) == 12  # 3 sources * 4 gens
        for p in pairings:
            assert p.reference_path == "/tmp/only_ref.jpg"
            assert p.reference_filename == "only_ref.jpg"
            assert p.ref_index == 1


class TestPairingEngineEdgeCases:
    """Edge case tests"""

    def test_empty_references_returns_empty(self):
        sources = ["/tmp/src.jpg"]
        engine = PairingEngine(sources, [], generations_per_source=3)
        assert engine.generate_pairings() == []

    def test_empty_sources_returns_empty(self):
        refs = ["/tmp/ref.jpg"]
        engine = PairingEngine([], refs, generations_per_source=3)
        assert engine.generate_pairings() == []

    def test_output_filename_contains_source_name(self):
        sources = ["/tmp/my_model.png"]
        refs = ["/tmp/bg.jpg"]
        engine = PairingEngine(sources, refs, generations_per_source=1)
        pairings = engine.generate_pairings()
        assert "my_model" in pairings[0].output_filename
