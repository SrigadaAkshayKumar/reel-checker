import pytest

from app.pipeline import extract

from .conftest import make_video, reel_frame, scene


def test_probe_keyframes_and_audio(tmp_path):
    video = make_video(tmp_path / "reel.mp4", [reel_frame(scene(1)), reel_frame(scene(2)), reel_frame(scene(3))])
    info = extract.probe(video, 90, 50)
    assert 5.5 < info.duration < 6.5
    assert (info.width, info.height) == (360, 640)
    assert info.has_audio and len(info.sha256) == 64

    frames = extract.keyframes(video, info, tmp_path / "frames", max_frames=12)
    assert 3 <= len(frames) <= 12
    # Every scene is represented and near-duplicates are dropped.
    from app.pipeline import fingerprint as fp
    for seed in (1, 2, 3):
        target = fp.variants(reel_frame(scene(seed)))
        assert fp.best_match([k.variants for k in frames], target)[0] >= 0.9
    assert all(k.usable for k in frames)

    wav = extract.extract_audio(video, tmp_path / "a.wav")
    assert wav and wav.stat().st_size > 10000

    picked = extract.pick_frames(frames, 2)
    assert len(picked) == 2 and picked[0].time < picked[1].time


def test_rejects_corrupt_file(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video" * 100)
    with pytest.raises(extract.InputError, match="readable"):
        extract.probe(bad, 90, 50)


def test_rejects_oversized_and_too_long(tmp_path):
    video = make_video(tmp_path / "reel.mp4", [reel_frame(scene(1))], seconds_each=4)
    with pytest.raises(extract.InputError, match="MB"):
        extract.probe(video, 90, 0.001)
    with pytest.raises(extract.InputError, match="limit"):
        extract.probe(video, 2, 50)


def test_missing_file(tmp_path):
    with pytest.raises(extract.InputError, match="not found"):
        extract.probe(tmp_path / "nope.mp4", 90, 50)
