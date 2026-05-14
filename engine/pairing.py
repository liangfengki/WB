import os
import random
from typing import List
from dataclasses import dataclass


@dataclass
class PairingResult:
    """单次配对结果"""
    source_path: str
    reference_path: str
    source_filename: str
    reference_filename: str
    generation_index: int  # 该 source 的第几次生成 (0-based)
    ref_index: int = 1  # 参考图在列表中的 1-based 索引

    @property
    def output_filename(self) -> str:
        """
        生成输出文件名。
        格式: {source_name}_ref{ref_index}_gen{gen_index}.jpg
        其中 ref_index 和 gen_index 均为 1-based。
        """
        source_name = os.path.splitext(self.source_filename)[0]
        return f"{source_name}_ref{self.ref_index}_gen{self.generation_index + 1}.jpg"


class PairingEngine:
    """随机配对引擎"""

    def __init__(
        self,
        source_files: List[str],
        reference_files: List[str],
        generations_per_source: int = 1,
    ):
        """
        Args:
            source_files: 人物图文件路径列表
            reference_files: 参考背景图文件路径列表
            generations_per_source: 每张人物图的生成数量 (clamped to 1-5)
        """
        self.source_files = source_files
        self.reference_files = reference_files
        self.generations_per_source = min(max(generations_per_source, 1), 5)

    def generate_pairings(self) -> List[PairingResult]:
        """
        生成所有配对结果。

        规则：
        - 当 refs >= N: 每张 source 的 N 次生成配对 N 张不重复的 reference
        - 当 N > refs > 1: 先用完所有不重复的 reference，剩余随机选取
        - 当 refs == 1: 所有生成均使用唯一的 reference

        Returns:
            配对结果列表
        """
        results: List[PairingResult] = []
        for source_path in self.source_files:
            results.extend(self._pair_single_source(source_path))
        return results

    def _pair_single_source(self, source_path: str) -> List[PairingResult]:
        """为单张 source 生成 N 个配对"""
        n = self.generations_per_source
        m = len(self.reference_files)
        source_filename = os.path.basename(source_path)
        pairings: List[PairingResult] = []

        if m == 0:
            return pairings

        if m == 1:
            # 当 refs == 1: 所有生成均使用唯一的 reference
            ref_path = self.reference_files[0]
            ref_filename = os.path.basename(ref_path)
            for gen_idx in range(n):
                result = PairingResult(
                    source_path=source_path,
                    reference_path=ref_path,
                    source_filename=source_filename,
                    reference_filename=ref_filename,
                    generation_index=gen_idx,
                    ref_index=1,
                )
                pairings.append(result)
        elif m >= n:
            # 当 refs >= N: 每张 source 的 N 次生成配对 N 张不重复的 reference
            selected_indices = random.sample(range(m), n)
            for gen_idx, ref_idx in enumerate(selected_indices):
                ref_path = self.reference_files[ref_idx]
                ref_filename = os.path.basename(ref_path)
                result = PairingResult(
                    source_path=source_path,
                    reference_path=ref_path,
                    source_filename=source_filename,
                    reference_filename=ref_filename,
                    generation_index=gen_idx,
                    ref_index=ref_idx + 1,  # 1-based
                )
                pairings.append(result)
        else:
            # 当 N > refs > 1: 先用完所有 M 张不重复的 reference，剩余随机选取
            all_indices = list(range(m))
            random.shuffle(all_indices)
            # First M pairings use all distinct references
            selected_indices = all_indices[:]
            # Remaining N-M picks are random from full list
            remaining = n - m
            for _ in range(remaining):
                selected_indices.append(random.randint(0, m - 1))

            for gen_idx, ref_idx in enumerate(selected_indices):
                ref_path = self.reference_files[ref_idx]
                ref_filename = os.path.basename(ref_path)
                result = PairingResult(
                    source_path=source_path,
                    reference_path=ref_path,
                    source_filename=source_filename,
                    reference_filename=ref_filename,
                    generation_index=gen_idx,
                    ref_index=ref_idx + 1,  # 1-based
                )
                pairings.append(result)

        return pairings
