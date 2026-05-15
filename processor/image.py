import os
import numpy as np
from PIL import Image
from config.settings import settings


class ImageProcessor:
    @staticmethod
    def preprocess_image(image_path: str) -> Image.Image:
        img = Image.open(image_path).convert("RGB")

        max_size = settings.OUTPUT_SIZE
        if max(img.size) > max_size:
            ratio = max_size / max(img.size)
            new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        return img

    @staticmethod
    def save_image(image: Image.Image, output_path: str):
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        image.save(output_path, "JPEG", quality=95, optimize=True)

    @staticmethod
    def harmonize_color(source_img: Image.Image, reference_img: Image.Image, strength: float = 0.3) -> Image.Image:
        """Reinhard 色彩迁移：将 source_img 的色调向 reference_img 靠拢。

        仅迁移 A/B 色度通道，L 通道以较低权重参与，避免大幅改变亮度。
        strength 控制混合强度 (0.0=原图, 1.0=完全迁移)。
        """
        if strength <= 0:
            return source_img

        # 将两张图缩放到相同尺寸进行统计计算
        ref_resized = reference_img.resize(source_img.size, Image.Resampling.LANCZOS)

        # 转为 LAB（Pillow 11+ 支持；fallback 到手动 numpy 转换）
        try:
            src_lab = np.array(source_img.convert("LAB"), dtype=np.float32)
            ref_lab = np.array(ref_resized.convert("LAB"), dtype=np.float32)
        except Exception:
            # Fallback: 手动 sRGB -> XYZ -> LAB
            src_lab = _rgb_to_lab(np.array(source_img, dtype=np.float32) / 255.0)
            ref_lab = _rgb_to_lab(np.array(ref_resized, dtype=np.float32) / 255.0)

        # 每通道均值和标准差
        src_mean = src_lab.reshape(-1, 3).mean(axis=0)
        src_std = src_lab.reshape(-1, 3).std(axis=0) + 1e-6
        ref_mean = ref_lab.reshape(-1, 3).mean(axis=0)
        ref_std = ref_lab.reshape(-1, 3).std(axis=0) + 1e-6

        # Reinhard 迁移（限制 A/B 通道 std 比率，防止白色区域色块放大）
        ratio = ref_std / src_std
        ratio[1] = min(ratio[1], 3.0)  # A 通道上限 3x
        ratio[2] = min(ratio[2], 3.0)  # B 通道上限 3x
        result_lab = (src_lab - src_mean) * ratio + ref_mean

        # L 通道保留更多原始值（只迁移 30% 的亮度变化），A/B 按 strength 迁移
        l_strength = strength * 0.3
        ab_strength = strength
        result_lab[:, :, 0] = src_lab[:, :, 0] * (1 - l_strength) + result_lab[:, :, 0] * l_strength
        result_lab[:, :, 1] = src_lab[:, :, 1] * (1 - ab_strength) + result_lab[:, :, 1] * ab_strength
        result_lab[:, :, 2] = src_lab[:, :, 2] * (1 - ab_strength) + result_lab[:, :, 2] * ab_strength

        # 软裁剪 A/B 通道，接近边界时平滑压缩避免硬色块
        for ch in [1, 2]:
            ch_data = result_lab[:, :, ch]
            ch_data = np.where(ch_data > 240, 240 + (ch_data - 240) * 0.3, ch_data)
            ch_data = np.where(ch_data < 16, 16 - (16 - ch_data) * 0.3, ch_data)
            result_lab[:, :, ch] = ch_data

        result_lab = np.clip(result_lab, 0, 255).astype(np.uint8)

        try:
            return Image.fromarray(result_lab, mode="LAB").convert("RGB")
        except Exception:
            return _lab_to_rgb(result_lab)


def _srgb_to_linear(c: np.ndarray) -> np.ndarray:
    """sRGB gamma 解码到线性 RGB"""
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(c: np.ndarray) -> np.ndarray:
    """线性 RGB 编码到 sRGB"""
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(np.clip(c, 0, None), 1 / 2.4) - 0.055)


def _rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB (float32, 0-1) -> LAB (float32, L:0-100, A:-128-127, B:-128-127) 映射到 0-255"""
    linear = _srgb_to_linear(rgb)
    # sRGB -> XYZ (D65)
    m = np.array([
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ], dtype=np.float32)
    xyz = linear @ m.T
    # D65 白点
    xyz_n = np.array([0.95047, 1.0, 1.08883], dtype=np.float32)
    xyz_norm = xyz / xyz_n

    delta = 6 / 29
    f = np.where(xyz_norm > delta ** 3, np.cbrt(xyz_norm), xyz_norm / (3 * delta ** 2) + 4 / 29)
    L = 116 * f[:, :, 1] - 16
    A = 500 * (f[:, :, 0] - f[:, :, 1])
    B = 200 * (f[:, :, 1] - f[:, :, 2])

    lab = np.stack([L, A + 128, B + 128], axis=-1)  # 映射到 ~0-255 范围
    return np.clip(lab, 0, 255).astype(np.float32)


def _lab_to_rgb(lab_uint8: np.ndarray) -> Image.Image:
    """LAB (uint8, L:0-255 映射自 0-100, A/B:0-255 映射自 -128~127) -> PIL RGB"""
    lab = lab_uint8.astype(np.float32)
    L = lab[:, :, 0] * 100 / 255
    A = lab[:, :, 1] - 128
    B = lab[:, :, 2] - 128

    fy = (L + 16) / 116
    fx = A / 500 + fy
    fz = fy - B / 200

    delta = 6 / 29
    x = np.where(fx > delta, fx ** 3, 3 * delta ** 2 * (fx - 4 / 29))
    y = np.where(fy > delta, fy ** 3, 3 * delta ** 2 * (fy - 4 / 29))
    z = np.where(fz > delta, fz ** 3, 3 * delta ** 2 * (fz - 4 / 29))

    xyz_n = np.array([0.95047, 1.0, 1.08883], dtype=np.float32)
    xyz = np.stack([x, y, z], axis=-1) * xyz_n

    m_inv = np.array([
        [3.2404542, -1.5371385, -0.4985314],
        [-0.9692660, 1.8760108, 0.0415560],
        [0.0556434, -0.2040259, 1.0572252],
    ], dtype=np.float32)
    linear = xyz @ m_inv.T
    srgb = _linear_to_srgb(np.clip(linear, 0, 1))
    return Image.fromarray((srgb * 255).clip(0, 255).astype(np.uint8), mode="RGB")
