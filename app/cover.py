"""Custom Instagram Reel cover (thumbnail): any image -> 1080x1920 JPEG."""
import io

from PIL import Image, ImageOps

W, H = 1080, 1920


def normalize(raw, out_path):
    """Center-crop the image to 9:16, convert to JPEG and save to out_path.

    Raises on data that is not an image. Output stays far below Zernio's 10 MB limit.
    """
    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img).convert("RGB")
    img = ImageOps.fit(img, (W, H), method=Image.LANCZOS, centering=(0.5, 0.5))
    img.save(out_path, "JPEG", quality=90, optimize=True)
    return out_path
