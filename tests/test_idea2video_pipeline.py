"""Unit tests for pipelines/idea2video_pipeline.py"""
import json
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from PIL import Image
from pipelines.idea2video_pipeline import Idea2VideoPipeline
from interfaces.character import CharacterInScene
from interfaces.image_output import ImageOutput


def make_pipeline(tmp_path):
    """Construct a pipeline with fully mocked dependencies."""
    mock_chat = MagicMock()
    mock_image_gen = MagicMock()
    mock_video_gen = MagicMock()
    pipeline = Idea2VideoPipeline(
        chat_model=mock_chat,
        image_generator=mock_image_gen,
        video_generator=mock_video_gen,
        working_dir=str(tmp_path),
    )
    return pipeline


def make_image_output():
    img = Image.new("RGB", (16, 16), color=(200, 100, 50))
    return ImageOutput(fmt="pil", ext="png", data=img)


@pytest.fixture
def character():
    return CharacterInScene(
        idx=0,
        identifier_in_scene="Alice",
        is_visible=True,
        static_features="blonde hair, blue eyes",
        dynamic_features="red dress",
    )


class TestPipelineInit:
    def test_working_dir_created(self, tmp_path):
        working_dir = str(tmp_path / "new_subdir")
        Idea2VideoPipeline(
            chat_model=MagicMock(),
            image_generator=MagicMock(),
            video_generator=MagicMock(),
            working_dir=working_dir,
        )
        assert os.path.isdir(working_dir)

    def test_attributes_set(self, tmp_path):
        mock_chat = MagicMock()
        mock_img = MagicMock()
        mock_vid = MagicMock()
        pipeline = Idea2VideoPipeline(
            chat_model=mock_chat,
            image_generator=mock_img,
            video_generator=mock_vid,
            working_dir=str(tmp_path),
        )
        assert pipeline.chat_model is mock_chat
        assert pipeline.image_generator is mock_img
        assert pipeline.video_generator is mock_vid
        assert pipeline.working_dir == str(tmp_path)


class TestDevelopStory:
    async def test_calls_screenwriter_and_returns_story(self, tmp_path):
        pipeline = make_pipeline(tmp_path)
        pipeline.screenwriter.develop_story = AsyncMock(return_value="My great story")

        result = await pipeline.develop_story(idea="An idea", user_requirement="For adults")
        assert result == "My great story"
        pipeline.screenwriter.develop_story.assert_called_once_with(
            idea="An idea", user_requirement="For adults"
        )

    async def test_saves_story_to_file(self, tmp_path):
        pipeline = make_pipeline(tmp_path)
        pipeline.screenwriter.develop_story = AsyncMock(return_value="Saved story text")

        await pipeline.develop_story(idea="idea", user_requirement=None)

        story_path = tmp_path / "story.txt"
        assert story_path.exists()
        assert story_path.read_text(encoding="utf-8") == "Saved story text"

    async def test_loads_from_existing_file_without_calling_llm(self, tmp_path):
        story_path = tmp_path / "story.txt"
        story_path.write_text("Cached story content", encoding="utf-8")

        pipeline = make_pipeline(tmp_path)
        pipeline.screenwriter.develop_story = AsyncMock()

        result = await pipeline.develop_story(idea="idea", user_requirement=None)

        pipeline.screenwriter.develop_story.assert_not_called()
        assert result == "Cached story content"


class TestExtractCharacters:
    async def test_calls_extractor_and_returns_characters(self, tmp_path, character):
        pipeline = make_pipeline(tmp_path)
        pipeline.character_extractor.extract_characters = AsyncMock(return_value=[character])

        result = await pipeline.extract_characters(story="A story with Alice.")
        assert len(result) == 1
        assert result[0].identifier_in_scene == "Alice"

    async def test_saves_characters_to_json(self, tmp_path, character):
        pipeline = make_pipeline(tmp_path)
        pipeline.character_extractor.extract_characters = AsyncMock(return_value=[character])

        await pipeline.extract_characters(story="story")

        chars_path = tmp_path / "characters.json"
        assert chars_path.exists()
        data = json.loads(chars_path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["identifier_in_scene"] == "Alice"

    async def test_loads_from_existing_json_without_calling_extractor(self, tmp_path, character):
        chars_path = tmp_path / "characters.json"
        chars_path.write_text(
            json.dumps([character.model_dump()]),
            encoding="utf-8",
        )

        pipeline = make_pipeline(tmp_path)
        pipeline.character_extractor.extract_characters = AsyncMock()

        result = await pipeline.extract_characters(story="story")

        pipeline.character_extractor.extract_characters.assert_not_called()
        assert len(result) == 1
        assert result[0].identifier_in_scene == "Alice"


class TestGeneratePortraitsForSingleCharacter:
    async def test_returns_registry_dict_with_three_views(self, tmp_path, character):
        pipeline = make_pipeline(tmp_path)
        pipeline.character_portraits_generator.generate_front_portrait = AsyncMock(
            return_value=make_image_output()
        )
        pipeline.character_portraits_generator.generate_side_portrait = AsyncMock(
            return_value=make_image_output()
        )
        pipeline.character_portraits_generator.generate_back_portrait = AsyncMock(
            return_value=make_image_output()
        )

        result = await pipeline.generate_portraits_for_single_character(character, style="Realistic")

        assert character.identifier_in_scene in result
        portraits = result[character.identifier_in_scene]
        assert "front" in portraits
        assert "side" in portraits
        assert "back" in portraits

    async def test_portrait_files_created(self, tmp_path, character):
        pipeline = make_pipeline(tmp_path)
        pipeline.character_portraits_generator.generate_front_portrait = AsyncMock(
            return_value=make_image_output()
        )
        pipeline.character_portraits_generator.generate_side_portrait = AsyncMock(
            return_value=make_image_output()
        )
        pipeline.character_portraits_generator.generate_back_portrait = AsyncMock(
            return_value=make_image_output()
        )

        await pipeline.generate_portraits_for_single_character(character, style="Realistic")

        char_dir = tmp_path / "character_portraits" / f"0_Alice"
        assert (char_dir / "front.png").exists()
        assert (char_dir / "side.png").exists()
        assert (char_dir / "back.png").exists()

    async def test_skips_existing_portrait_files(self, tmp_path, character):
        """If portrait files already exist, the generator should not be called."""
        char_dir = tmp_path / "character_portraits" / "0_Alice"
        char_dir.mkdir(parents=True)
        dummy_img = Image.new("RGB", (4, 4))
        for name in ("front.png", "side.png", "back.png"):
            dummy_img.save(str(char_dir / name))

        pipeline = make_pipeline(tmp_path)
        pipeline.character_portraits_generator.generate_front_portrait = AsyncMock(
            return_value=make_image_output()
        )
        pipeline.character_portraits_generator.generate_side_portrait = AsyncMock(
            return_value=make_image_output()
        )
        pipeline.character_portraits_generator.generate_back_portrait = AsyncMock(
            return_value=make_image_output()
        )

        await pipeline.generate_portraits_for_single_character(character, style="Realistic")

        pipeline.character_portraits_generator.generate_front_portrait.assert_not_called()
        pipeline.character_portraits_generator.generate_side_portrait.assert_not_called()
        pipeline.character_portraits_generator.generate_back_portrait.assert_not_called()

    async def test_front_path_passed_to_side_and_back(self, tmp_path, character):
        pipeline = make_pipeline(tmp_path)
        pipeline.character_portraits_generator.generate_front_portrait = AsyncMock(
            return_value=make_image_output()
        )
        pipeline.character_portraits_generator.generate_side_portrait = AsyncMock(
            return_value=make_image_output()
        )
        pipeline.character_portraits_generator.generate_back_portrait = AsyncMock(
            return_value=make_image_output()
        )

        await pipeline.generate_portraits_for_single_character(character, style="Realistic")

        expected_front_path = str(
            tmp_path / "character_portraits" / "0_Alice" / "front.png"
        )
        side_kwargs = pipeline.character_portraits_generator.generate_side_portrait.call_args
        back_kwargs = pipeline.character_portraits_generator.generate_back_portrait.call_args
        assert side_kwargs.args[1] == expected_front_path
        assert back_kwargs.args[1] == expected_front_path
