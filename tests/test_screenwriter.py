"""Unit tests for agents/screenwriter.py"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from agents.screenwriter import Screenwriter


def make_mock_chat(content: str):
    """Return a chat model mock whose ainvoke() returns a response with .content = content."""
    mock_response = MagicMock()
    mock_response.content = content
    mock_chat = MagicMock()
    mock_chat.ainvoke = AsyncMock(return_value=mock_response)
    return mock_chat


class TestDevelopStory:
    async def test_returns_string(self):
        expected = "Once upon a time in a neon-lit gym..."
        screenwriter = Screenwriter(chat_model=make_mock_chat(expected))
        result = await screenwriter.develop_story(idea="A gym story", user_requirement=None)
        assert result == expected

    async def test_ainvoke_called_once(self):
        mock_chat = make_mock_chat("some story")
        screenwriter = Screenwriter(chat_model=mock_chat)
        await screenwriter.develop_story(idea="Any idea", user_requirement="Adults only")
        mock_chat.ainvoke.assert_called_once()

    async def test_idea_appears_in_messages(self):
        mock_chat = make_mock_chat("story text")
        screenwriter = Screenwriter(chat_model=mock_chat)
        await screenwriter.develop_story(idea="unique_idea_xyz", user_requirement=None)

        call_args = mock_chat.ainvoke.call_args
        messages = call_args[0][0]
        # messages is a list of (role, content) tuples; flatten to search
        full_text = str(messages)
        assert "unique_idea_xyz" in full_text

    async def test_user_requirement_appears_in_messages(self):
        mock_chat = make_mock_chat("story text")
        screenwriter = Screenwriter(chat_model=mock_chat)
        await screenwriter.develop_story(idea="idea", user_requirement="requirement_sentinel_abc")

        call_args = mock_chat.ainvoke.call_args
        full_text = str(call_args[0][0])
        assert "requirement_sentinel_abc" in full_text


class TestWriteScriptBasedOnStory:
    async def test_returns_list_of_strings(self):
        scenes = ["Scene 1: INT. GYM - DAY", "Scene 2: EXT. BEACH - SUNSET"]
        response_json = json.dumps({"script": scenes})
        screenwriter = Screenwriter(chat_model=make_mock_chat(response_json))
        result = await screenwriter.write_script_based_on_story(
            story="A story about a gym and a beach.",
            user_requirement=None,
        )
        assert result == scenes

    async def test_returns_all_scene_entries(self):
        scenes = [f"Scene {i}" for i in range(3)]
        response_json = json.dumps({"script": scenes})
        screenwriter = Screenwriter(chat_model=make_mock_chat(response_json))
        result = await screenwriter.write_script_based_on_story(story="multi-scene story", user_requirement=None)
        assert len(result) == 3

    async def test_story_appears_in_messages(self):
        response_json = json.dumps({"script": ["s1"]})
        mock_chat = make_mock_chat(response_json)
        screenwriter = Screenwriter(chat_model=mock_chat)
        await screenwriter.write_script_based_on_story(story="story_sentinel_xyz", user_requirement=None)

        full_text = str(mock_chat.ainvoke.call_args[0][0])
        assert "story_sentinel_xyz" in full_text
