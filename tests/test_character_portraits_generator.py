"""Unit tests for agents/character_portraits_generator.py"""
import pytest
from unittest.mock import AsyncMock, MagicMock, call
from PIL import Image
from agents.character_portraits_generator import CharacterPortraitsGenerator
from interfaces.character import CharacterInScene
from interfaces.image_output import ImageOutput


def make_image_output():
    img = Image.new("RGB", (16, 16), color=(0, 128, 255))
    return ImageOutput(fmt="pil", ext="png", data=img)


def make_mock_image_generator(return_value=None):
    mock_gen = MagicMock()
    mock_gen.generate_single_image = AsyncMock(
        return_value=return_value or make_image_output()
    )
    return mock_gen


@pytest.fixture
def character():
    return CharacterInScene(
        idx=0,
        identifier_in_scene="Eve",
        is_visible=True,
        static_features="dark wavy hair, green eyes, tall slender build",
        dynamic_features="white gym outfit, black sneakers",
    )


class TestGenerateFrontPortrait:
    async def test_returns_image_output(self, character):
        gen = CharacterPortraitsGenerator(image_generator=make_mock_image_generator())
        result = await gen.generate_front_portrait(character, style="Realistic")
        assert isinstance(result, ImageOutput)

    async def test_calls_generate_single_image_once(self, character):
        mock_gen = make_mock_image_generator()
        gen = CharacterPortraitsGenerator(image_generator=mock_gen)
        await gen.generate_front_portrait(character, style="Realistic")
        mock_gen.generate_single_image.assert_called_once()

    async def test_prompt_contains_static_and_dynamic_features(self, character):
        mock_gen = make_mock_image_generator()
        gen = CharacterPortraitsGenerator(image_generator=mock_gen)
        await gen.generate_front_portrait(character, style="Cinematic")

        prompt_arg = mock_gen.generate_single_image.call_args.kwargs["prompt"]
        assert "(static)" in prompt_arg
        assert "(dynamic)" in prompt_arg
        assert character.static_features in prompt_arg
        assert character.dynamic_features in prompt_arg

    async def test_prompt_contains_identifier(self, character):
        mock_gen = make_mock_image_generator()
        gen = CharacterPortraitsGenerator(image_generator=mock_gen)
        await gen.generate_front_portrait(character, style="Realistic")

        prompt_arg = mock_gen.generate_single_image.call_args.kwargs["prompt"]
        assert character.identifier_in_scene in prompt_arg

    async def test_prompt_contains_style(self, character):
        mock_gen = make_mock_image_generator()
        gen = CharacterPortraitsGenerator(image_generator=mock_gen)
        await gen.generate_front_portrait(character, style="Warm cinematic look")

        prompt_arg = mock_gen.generate_single_image.call_args.kwargs["prompt"]
        assert "Warm cinematic look" in prompt_arg

    async def test_retry_on_failure_then_success(self, character):
        """2 failures then success → 3 total calls."""
        call_count = 0

        async def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError("Simulated image generation error")
            return make_image_output()

        mock_gen = MagicMock()
        mock_gen.generate_single_image = AsyncMock(side_effect=side_effect)
        gen = CharacterPortraitsGenerator(image_generator=mock_gen)
        result = await gen.generate_front_portrait(character, style="Realistic")
        assert call_count == 3
        assert isinstance(result, ImageOutput)


class TestGenerateSidePortrait:
    async def test_returns_image_output(self, character):
        gen = CharacterPortraitsGenerator(image_generator=make_mock_image_generator())
        result = await gen.generate_side_portrait(character, front_image_path="/tmp/front.png")
        assert isinstance(result, ImageOutput)

    async def test_passes_front_image_as_reference(self, character):
        mock_gen = make_mock_image_generator()
        gen = CharacterPortraitsGenerator(image_generator=mock_gen)
        await gen.generate_side_portrait(character, front_image_path="/tmp/front.png")

        kwargs = mock_gen.generate_single_image.call_args.kwargs
        assert "reference_image_paths" in kwargs
        assert "/tmp/front.png" in kwargs["reference_image_paths"]

    async def test_prompt_contains_identifier(self, character):
        mock_gen = make_mock_image_generator()
        gen = CharacterPortraitsGenerator(image_generator=mock_gen)
        await gen.generate_side_portrait(character, front_image_path="/tmp/front.png")

        prompt_arg = mock_gen.generate_single_image.call_args.kwargs["prompt"]
        assert character.identifier_in_scene in prompt_arg


class TestGenerateBackPortrait:
    async def test_returns_image_output(self, character):
        gen = CharacterPortraitsGenerator(image_generator=make_mock_image_generator())
        result = await gen.generate_back_portrait(character, front_image_path="/tmp/front.png")
        assert isinstance(result, ImageOutput)

    async def test_passes_front_image_as_reference(self, character):
        mock_gen = make_mock_image_generator()
        gen = CharacterPortraitsGenerator(image_generator=mock_gen)
        await gen.generate_back_portrait(character, front_image_path="/tmp/front.png")

        kwargs = mock_gen.generate_single_image.call_args.kwargs
        assert "reference_image_paths" in kwargs
        assert "/tmp/front.png" in kwargs["reference_image_paths"]

    async def test_prompt_contains_identifier(self, character):
        mock_gen = make_mock_image_generator()
        gen = CharacterPortraitsGenerator(image_generator=mock_gen)
        await gen.generate_back_portrait(character, front_image_path="/tmp/front.png")

        prompt_arg = mock_gen.generate_single_image.call_args.kwargs["prompt"]
        assert character.identifier_in_scene in prompt_arg
