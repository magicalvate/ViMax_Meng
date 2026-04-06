"""Unit tests for agents/character_extractor.py"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from agents.character_extractor import CharacterExtractor, ExtractCharactersResponse
from interfaces.character import CharacterInScene


def make_extractor_with_chain(chain_return_value):
    """
    Build a CharacterExtractor whose internal `chat_model | parser` chain
    returns `chain_return_value` when ainvoke() is awaited.
    """
    mock_chain = MagicMock()
    mock_chain.ainvoke = AsyncMock(return_value=chain_return_value)

    mock_chat = MagicMock()
    # `chat_model | parser` calls chat_model.__or__(parser)
    mock_chat.__or__.return_value = mock_chain

    return CharacterExtractor(chat_model=mock_chat), mock_chain


def make_sample_response(n: int = 1):
    characters = [
        CharacterInScene(
            idx=i,
            identifier_in_scene=f"Character_{i}",
            is_visible=True,
            static_features=f"static features of character {i}",
            dynamic_features=f"dynamic features of character {i}",
        )
        for i in range(n)
    ]
    return ExtractCharactersResponse(characters=characters)


class TestExtractCharacters:
    async def test_returns_list_of_character_in_scene(self):
        response = make_sample_response(2)
        extractor, _ = make_extractor_with_chain(response)
        result = await extractor.extract_characters("A script with two characters.")
        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(c, CharacterInScene) for c in result)

    async def test_character_fields_preserved(self):
        response = make_sample_response(1)
        extractor, _ = make_extractor_with_chain(response)
        result = await extractor.extract_characters("script text")
        assert result[0].identifier_in_scene == "Character_0"
        assert result[0].is_visible is True

    async def test_chain_ainvoke_called_once(self):
        response = make_sample_response(1)
        extractor, mock_chain = make_extractor_with_chain(response)
        await extractor.extract_characters("script")
        mock_chain.ainvoke.assert_called_once()

    async def test_empty_character_list(self):
        response = ExtractCharactersResponse(characters=[])
        extractor, _ = make_extractor_with_chain(response)
        result = await extractor.extract_characters("A script with no named characters.")
        assert result == []

    async def test_retry_on_failure_then_success(self):
        """Verify tenacity retries: 2 failures then 1 success → 3 total calls."""
        sample_char = CharacterInScene(
            idx=0,
            identifier_in_scene="Alice",
            is_visible=True,
            static_features="features",
            dynamic_features="clothes",
        )
        call_count = 0

        async def side_effect(messages):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Simulated API error")
            return ExtractCharactersResponse(characters=[sample_char])

        mock_chain = MagicMock()
        mock_chain.ainvoke = AsyncMock(side_effect=side_effect)
        mock_chat = MagicMock()
        mock_chat.__or__.return_value = mock_chain

        extractor = CharacterExtractor(chat_model=mock_chat)
        result = await extractor.extract_characters("script")
        assert call_count == 3
        assert len(result) == 1
