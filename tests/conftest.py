import pytest
from PIL import Image
from interfaces.character import CharacterInScene
from interfaces.image_output import ImageOutput
from interfaces.video_output import VideoOutput


@pytest.fixture
def sample_character():
    return CharacterInScene(
        idx=0,
        identifier_in_scene="Alice",
        is_visible=True,
        static_features="long blonde hair, blue eyes, slender build",
        dynamic_features="red sundress, white sneakers",
    )


@pytest.fixture
def sample_image_output():
    img = Image.new("RGB", (16, 16), color=(128, 64, 32))
    return ImageOutput(fmt="pil", ext="png", data=img)


@pytest.fixture
def sample_video_output():
    return VideoOutput(fmt="bytes", ext="mp4", data=b"\x00\x01\x02fake_mp4_bytes")
