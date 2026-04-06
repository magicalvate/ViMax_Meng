"""Unit tests for interfaces/ data models."""
import base64
import os
import pytest
from PIL import Image
from interfaces.character import CharacterInScene
from interfaces.image_output import ImageOutput
from interfaces.video_output import VideoOutput
from interfaces.environment import EnvironmentInScene
from interfaces.scene import Scene


class TestCharacterInScene:
    def test_valid_construction(self):
        char = CharacterInScene(
            idx=0,
            identifier_in_scene="Bob",
            is_visible=True,
            static_features="brown hair, tall",
            dynamic_features="blue jeans, white shirt",
        )
        assert char.idx == 0
        assert char.identifier_in_scene == "Bob"
        assert char.is_visible is True

    def test_invisible_character(self):
        char = CharacterInScene(
            idx=1,
            identifier_in_scene="Narrator",
            is_visible=False,
            static_features="",
            dynamic_features="",
        )
        assert char.is_visible is False

    def test_str_contains_identifier(self):
        char = CharacterInScene(
            idx=0,
            identifier_in_scene="Carol",
            is_visible=True,
            static_features="red hair",
            dynamic_features="green coat",
        )
        s = str(char)
        assert "Carol" in s
        assert "red hair" in s
        assert "green coat" in s

    def test_model_dump_and_validate_roundtrip(self):
        char = CharacterInScene(
            idx=2,
            identifier_in_scene="Dave",
            is_visible=True,
            static_features="grey eyes",
            dynamic_features="suit",
        )
        dumped = char.model_dump()
        restored = CharacterInScene.model_validate(dumped)
        assert restored == char


class TestImageOutput:
    def test_save_pil_creates_file(self, tmp_path):
        img = Image.new("RGB", (8, 8), color=(255, 0, 0))
        output = ImageOutput(fmt="pil", ext="png", data=img)
        dest = str(tmp_path / "test.png")
        output.save(dest)
        assert os.path.isfile(dest)
        loaded = Image.open(dest)
        assert loaded.size == (8, 8)

    def test_save_b64_creates_file(self, tmp_path):
        img = Image.new("RGB", (4, 4), color=(0, 255, 0))
        from io import BytesIO
        buf = BytesIO()
        img.save(buf, format="PNG")
        b64_data = base64.b64encode(buf.getvalue()).decode("utf-8")

        output = ImageOutput(fmt="b64", ext="png", data=b64_data)
        dest = str(tmp_path / "test_b64.png")
        output.save(dest)
        assert os.path.isfile(dest)
        # Verify the saved file is a valid PNG
        loaded = Image.open(dest)
        assert loaded.size == (4, 4)

    def test_fmt_and_ext_attributes(self):
        img = Image.new("RGB", (2, 2))
        output = ImageOutput(fmt="pil", ext="png", data=img)
        assert output.fmt == "pil"
        assert output.ext == "png"


class TestVideoOutput:
    def test_save_bytes_creates_file(self, tmp_path):
        fake_bytes = b"\x00\x01\x02\x03video_data"
        output = VideoOutput(fmt="bytes", ext="mp4", data=fake_bytes)
        dest = str(tmp_path / "video.mp4")
        output.save(dest)
        assert os.path.isfile(dest)
        assert open(dest, "rb").read() == fake_bytes

    def test_fmt_and_ext_attributes(self):
        output = VideoOutput(fmt="bytes", ext="mp4", data=b"data")
        assert output.fmt == "bytes"
        assert output.ext == "mp4"


class TestEnvironmentInScene:
    def test_valid_construction(self):
        env = EnvironmentInScene(
            slugline="INT. GYM - DAY",
            description="A bright gym with glass windows overlooking a beach.",
        )
        assert env.slugline == "INT. GYM - DAY"

    def test_str_contains_slugline_and_description(self):
        env = EnvironmentInScene(
            slugline="EXT. BEACH - SUNSET",
            description="Waves crashing gently on golden sand.",
        )
        s = str(env)
        assert "EXT. BEACH - SUNSET" in s
        assert "Waves crashing" in s


class TestScene:
    def test_valid_construction(self):
        env = EnvironmentInScene(slugline="INT. OFFICE - DAY", description="A busy open-plan office.")
        char = CharacterInScene(
            idx=0,
            identifier_in_scene="Alice",
            is_visible=True,
            static_features="short black hair",
            dynamic_features="business suit",
        )
        scene = Scene(
            idx=0,
            is_last=False,
            environment=env,
            characters=[char],
            script="<Alice> strides into the office and sits down.",
        )
        assert scene.idx == 0
        assert scene.is_last is False
        assert len(scene.characters) == 1

    def test_str_contains_scene_index(self):
        env = EnvironmentInScene(slugline="EXT. PARK - DAY", description="Sunny park.")
        char = CharacterInScene(
            idx=0, identifier_in_scene="Bob", is_visible=True,
            static_features="tall", dynamic_features="casual"
        )
        scene = Scene(idx=3, is_last=True, environment=env, characters=[char], script="Action.")
        assert "3" in str(scene)
