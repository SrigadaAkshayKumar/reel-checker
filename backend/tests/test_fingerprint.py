from PIL import ImageFilter, ImageOps

from app.pipeline import fingerprint as fp

from .conftest import jpeg, reel_frame, scene, yt_thumb


def _sim(a, b) -> float:
    return fp.best_match([fp.variants(a)], fp.variants(b))[0]


def test_same_footage_survives_common_edits():
    original = scene(1)
    edited = {
        "reencoded": fp.open_image(jpeg(original, 30)),
        "downscaled": original.resize((160, 90)),
        "letterboxed_9x16": fp.open_image(jpeg(reel_frame(original))),
        "caption_strip": fp.open_image(jpeg(reel_frame(original, "TODAY HYDERABAD"))),
        "youtube_thumbnail": fp.open_image(yt_thumb(original)),
        "mirrored": ImageOps.mirror(original),
        "slight_blur": original.filter(ImageFilter.GaussianBlur(1.5)),
    }
    for name, img in edited.items():
        assert _sim(img, original) >= 0.90, name


def test_unrelated_footage_stays_below_weak_threshold():
    original = scene(1)
    for seed in range(2, 12):
        assert _sim(scene(seed), original) < 0.75, seed


def test_content_box_trims_black_bars():
    framed = reel_frame(scene(3))
    box = fp.content_box(framed)
    assert box.size[1] < 260  # 202 px of footage inside a 640 px frame


def test_flat_frames_are_not_usable(tmp_path):
    from PIL import Image
    brightness, detail = fp.image_stats(Image.new("RGB", (100, 100), (5, 5, 5)))
    assert brightness < 20 and detail < 8


def test_hamming_and_similarity():
    assert fp.hamming("ffffffffffffffff", "0000000000000000") == 64
    assert fp.similarity("abcdef0123456789", "abcdef0123456789") == 1.0
