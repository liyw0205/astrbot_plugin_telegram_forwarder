"""Tests for QQSender helper behavior."""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestDispatchMediaFile:
    def test_dispatch_by_extension(self, sender):
        cases = [
            ("/tmp/photo.jpg", "Image"),
            ("/tmp/photo.png", "Image"),
            ("/tmp/photo.webp", "Image"),
            ("/tmp/photo.gif", "Image"),
            ("/tmp/audio.wav", "Record"),
            ("/tmp/audio.mp3", "Record"),
            ("/tmp/audio.flac", "Record"),
            ("/tmp/audio.ogg", "Record"),
            ("/tmp/video.mp4", "Video"),
            ("/tmp/video.webm", "Video"),
            ("/tmp/video.mkv", "Video"),
            ("/tmp/data.zip", "File"),
            ("/tmp/doc.pdf", "File"),
        ]
        for filename, expected_type in cases:
            result = sender._dispatch_media_file(filename)
            assert len(result) == 1
            assert type(result[0]).__name__ == expected_type

    def test_case_insensitive(self, sender):
        result = sender._dispatch_media_file("/tmp/PHOTO.JPG")
        assert len(result) == 1
        assert type(result[0]).__name__ == "Image"

    def test_video_path_mapping(self, sender):
        sender._map_path = lambda p: "/mapped" + p
        result = sender._dispatch_media_file("/tmp/video.mp4")
        assert len(result) == 1
        assert type(result[0]).__name__ == "Video"

    def test_unknown_ext_path_mapping(self, sender):
        sender._map_path = lambda p: "/mapped" + p
        result = sender._dispatch_media_file("/tmp/data.zip")
        assert len(result) == 1
        assert type(result[0]).__name__ == "File"

    def test_file_preserves_host_path_and_mapped_url_when_mapping_exists(self, sender):
        sender._map_path = lambda p: "/mapped" + p
        result = sender._dispatch_media_file("/tmp/data.zip")
        assert len(result) == 1
        assert type(result[0]).__name__ == "File"
        assert result[0].file == "/tmp/data.zip"
        assert result[0].url == "/mapped/tmp/data.zip"
        assert result[0].name == "data.zip"

    def test_audio_file_only_mode_returns_file(self, sender):
        result = sender._dispatch_media_file("/tmp/audio.ogg", audio_mode="file_only")
        assert len(result) == 1
        assert type(result[0]).__name__ == "File"


class TestGetSenderDisplayName:
    def test_post_author_channel(self, sender):
        msg = type("Msg", (), {"post_author": "channel-editor", "sender": None})()
        assert sender._get_sender_display_name(msg) == "channel-editor"

    def test_sender_first_name(self, sender):
        user = type("User", (), {"first_name": "Alice"})()
        msg = type("Msg", (), {"post_author": None, "sender": user})()
        assert sender._get_sender_display_name(msg) == "Alice"

    def test_post_author_takes_priority(self, sender):
        user = type("User", (), {"first_name": "Alice"})()
        msg = type("Msg", (), {"post_author": "channel-editor", "sender": user})()
        assert sender._get_sender_display_name(msg) == "channel-editor"

    def test_no_name_returns_empty(self, sender):
        msg = type("Msg", (), {"post_author": None, "sender": None})()
        assert sender._get_sender_display_name(msg) == ""

    def test_sender_without_first_name(self, sender):
        user = type("User", (), {})()
        msg = type("Msg", (), {"post_author": None, "sender": user})()
        assert sender._get_sender_display_name(msg) == ""

    def test_sender_first_name_none(self, sender):
        user = type("User", (), {"first_name": None})()
        msg = type("Msg", (), {"post_author": None, "sender": user})()
        assert sender._get_sender_display_name(msg) == ""

    def test_channel_title_fallback(self, sender):
        channel = type("Channel", (), {"title": "MyChannel", "username": "mychannel"})()
        msg = type("Msg", (), {"post_author": None, "sender": channel})()
        assert sender._get_sender_display_name(msg) == "MyChannel"

    def test_channel_username_fallback(self, sender):
        channel = type("Channel", (), {"title": None, "username": "mychannel"})()
        msg = type("Msg", (), {"post_author": None, "sender": channel})()
        assert sender._get_sender_display_name(msg) == "mychannel"

    def test_user_username_fallback(self, sender):
        user = type("User", (), {"first_name": None, "username": "john_doe"})()
        msg = type("Msg", (), {"post_author": None, "sender": user})()
        assert sender._get_sender_display_name(msg) == "john_doe"


class TestBatchAudioDetection:
    def test_detects_record_component(self, sender, qq_module):
        plain = qq_module.Plain("hello")
        record = qq_module.Record.fromFileSystem("/tmp/audio.ogg")
        assert sender._batch_contains_audio([[plain], [record]]) is True

    def test_ignores_non_audio_components(self, sender, qq_module):
        plain = qq_module.Plain("hello")
        image = qq_module.Image.fromFileSystem("/tmp/photo.jpg")
        file_comp = qq_module.File("/tmp/doc.pdf")
        assert sender._batch_contains_audio([[plain], [image, file_comp]]) is False

    def test_file_only_audio_fallback_is_not_treated_as_audio_batch(self, sender):
        file_comp = sender._dispatch_media_file("/tmp/audio.ogg", audio_mode="file_only")[0]
        assert sender._batch_contains_audio([[file_comp]]) is False


class TestBatchMergeDecision:
    def test_audio_batch_never_uses_nodes_merge(self, sender):
        batch_data = {
            "nodes_data": [["text"], ["record"]],
            "contains_audio": True,
        }
        assert sender._should_merge_batch_nodes(batch_data) is False

    def test_non_audio_multi_node_batch_can_use_nodes_merge(self, sender):
        batch_data = {
            "nodes_data": [["text"], ["image"]],
            "contains_audio": False,
        }
        assert sender._should_merge_batch_nodes(batch_data) is True


class TestReplyPreview:
    def test_reply_media_label_variants(self, sender):
        assert sender._reply_media_label(type("Msg", (), {"photo": object()})()) == "[图片]"
        assert sender._reply_media_label(type("Msg", (), {"video": object()})()) == "[视频]"
        assert sender._reply_media_label(type("Msg", (), {"audio": object()})()) == "[音频]"
        assert sender._reply_media_label(type("Msg", (), {"document": object()})()) == "[文件]"
        assert sender._reply_media_label(type("Msg", (), {})()) == "[消息]"

    def test_build_reply_preview_text(self, sender):
        user = type("User", (), {"first_name": "Alice"})()
        msg = type("Msg", (), {"sender": user, "post_author": None, "text": "hello\nworld"})()
        assert sender._build_reply_preview(msg) == "↩ 回复 Alice:\nhello world"

    def test_build_reply_preview_truncates_long_text(self, sender):
        msg = type("Msg", (), {"sender": None, "post_author": None, "text": "x" * 120})()
        result = sender._build_reply_preview(msg)
        assert result.startswith("↩ 回复:\n")
        assert result.endswith("...")

    @pytest.mark.asyncio
    async def test_prefetch_reply_previews_skips_existing_batch_message(self, sender):
        source = type("Msg", (), {"id": 1, "reply_to": None})()
        reply_header = type("Reply", (), {"reply_to_msg_id": 1})()
        reply_msg = type("Msg", (), {"id": 2, "reply_to": reply_header})()
        sender.downloader.client = MagicMock()
        sender.downloader.client.get_messages = AsyncMock()

        result = await sender._prefetch_reply_previews([source, reply_msg], "demo")

        assert result == {}
        sender.downloader.client.get_messages.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_prefetch_reply_previews_fetches_missing_reply(self, sender):
        reply_header = type("Reply", (), {"reply_to_msg_id": 99})()
        msg = type("Msg", (), {"id": 2, "reply_to": reply_header})()
        quoted = type("Msg", (), {"id": 99, "sender": None, "post_author": None, "text": "quoted text"})()
        sender.downloader.client = MagicMock()
        sender.downloader.client.get_messages = AsyncMock(return_value=[quoted])

        result = await sender._prefetch_reply_previews([msg], "demo")

        assert result == {99: "↩ 回复:\nquoted text"}
        sender.downloader.client.get_messages.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_prefetch_reply_previews_ignores_fetch_failure(self, sender):
        reply_header = type("Reply", (), {"reply_to_msg_id": 99})()
        msg = type("Msg", (), {"id": 2, "reply_to": reply_header})()
        sender.downloader.client = MagicMock()
        sender.downloader.client.get_messages = AsyncMock(side_effect=RuntimeError("boom"))

        result = await sender._prefetch_reply_previews([msg], "demo")

        assert result == {}


class TestAudioBatchSending:
    @pytest.mark.asyncio
    async def test_captioned_audio_batch_sends_text_record_and_file(self, sender, qq_module):
        sender.context.send_message = AsyncMock()
        plain = qq_module.Plain("caption")
        record = qq_module.Record.fromFileSystem("/tmp/audio.ogg")
        record.path = "/tmp/audio.ogg"
        record.file = "file:////tmp/audio.ogg"
        sender._map_path = lambda p: p

        await sender._send_processed_batch(
            batch_data={
                "nodes_data": [[plain], [record]],
                "contains_audio": True,
            },
            unified_msg_origin="target",
            self_id=1,
            node_name="bot",
            target_session="target",
        )

        assert sender.context.send_message.await_count == 3

    @pytest.mark.asyncio
    async def test_file_send_logs_final_payload_with_file_file__and_url(self, sender, qq_module):
        sender.context.send_message = AsyncMock()
        qq_module.logger.info.reset_mock()
        file_component = qq_module.File(file="/tmp/audio.ogg", name="audio.ogg")
        file_component.file_ = "/tmp/audio.ogg"
        file_component.url = ""

        await sender._send_processed_batch(
            batch_data={
                "nodes_data": [[file_component]],
                "contains_audio": False,
            },
            unified_msg_origin="target",
            self_id=1,
            node_name="bot",
            target_session="target",
        )

        assert sender.context.send_message.await_count == 1
        qq_module.logger.info.assert_any_call(
            "[QQSender] File payload -> target: file='/tmp/audio.ogg', file_='/tmp/audio.ogg', url='', name='audio.ogg'"
        )

    @pytest.mark.asyncio
    async def test_file_send_copies_file_path_from_file_compat_field(self, sender, qq_module):
        sender.context.send_message = AsyncMock()
        file_component = qq_module.File(name="audio.ogg")
        file_component.file = ""
        file_component.file_ = "/mapped/audio.ogg"

        await sender._send_processed_batch(
            batch_data={
                "nodes_data": [[file_component]],
                "contains_audio": False,
            },
            unified_msg_origin="target",
            self_id=1,
            node_name="bot",
            target_session="target",
        )

        sent_file = sender.context.send_message.await_args_list[0].args[1].chain[0]
        assert sent_file.file == "/mapped/audio.ogg"

    @pytest.mark.asyncio
    async def test_audio_batch_normalizes_file_component_from_file_compat_field(self, sender, qq_module):
        sender.context.send_message = AsyncMock()
        sender._map_path = lambda p: p
        record = qq_module.Record.fromFileSystem("/tmp/audio.ogg")
        record.path = "/tmp/audio.ogg"
        file_component = qq_module.File(name="extra.ogg")
        file_component.file = ""
        file_component.file_ = "/mapped/extra.ogg"

        await sender._send_processed_batch(
            batch_data={
                "nodes_data": [[record, file_component]],
                "contains_audio": True,
            },
            unified_msg_origin="target",
            self_id=1,
            node_name="bot",
            target_session="target",
        )

        assert sender.context.send_message.await_count == 3
        sent_file = sender.context.send_message.await_args_list[2].args[1].chain[0]
        assert sent_file.file == "/mapped/extra.ogg"

    @pytest.mark.asyncio
    async def test_audio_batch_logs_file_payload_with_file_file__and_url(self, sender, qq_module):
        sender.context.send_message = AsyncMock()
        qq_module.logger.info.reset_mock()
        file_component = qq_module.File(name="audio.ogg", file="/tmp/audio.ogg", url="/mapped/audio.ogg")
        file_component.file_ = "/tmp/audio.ogg"

        await sender._send_processed_batch(
            batch_data={
                "nodes_data": [[file_component]],
                "contains_audio": False,
            },
            unified_msg_origin="target",
            self_id=1,
            node_name="bot",
            target_session="target",
        )

        qq_module.logger.info.assert_any_call(
            "[QQSender] File payload -> target: file='/tmp/audio.ogg', file_='/tmp/audio.ogg', url='/mapped/audio.ogg', name='audio.ogg'"
        )

    @pytest.mark.asyncio
    async def test_audio_record_with_mapped_file_sends_record_and_file(self, sender, qq_module):
        sender.context.send_message = AsyncMock()
        record = qq_module.Record.fromFileSystem("/tmp/audio.ogg")
        record.path = "/tmp/audio.ogg"
        record.file = "file:////tmp/audio.ogg"
        sender._map_path = lambda p: "/mapped/audio.ogg"

        await sender._send_processed_batch(
            batch_data={
                "nodes_data": [[record]],
                "contains_audio": True,
            },
            unified_msg_origin="target",
            self_id=1,
            node_name="bot",
            target_session="target",
        )

        assert sender.context.send_message.await_count == 2
        file_component = sender.context.send_message.await_args_list[1].args[1].chain[0]
        assert type(file_component).__name__ == "File"
        assert file_component.file == "/tmp/audio.ogg"
        assert file_component.url == "/mapped/audio.ogg"

    @pytest.mark.asyncio
    async def test_audio_record_without_mapping_still_sends_file_fallback(self, sender, qq_module):
        sender.context.send_message = AsyncMock()
        record = qq_module.Record.fromFileSystem("/tmp/audio.ogg")
        record.path = "/tmp/audio.ogg"
        record.file = "file:////tmp/audio.ogg"
        sender._map_path = lambda p: p

        await sender._send_processed_batch(
            batch_data={
                "nodes_data": [[record]],
                "contains_audio": True,
            },
            unified_msg_origin="target",
            self_id=1,
            node_name="bot",
            target_session="target",
        )

        assert sender.context.send_message.await_count == 2

    @pytest.mark.asyncio
    async def test_audio_batch_preserves_node_order(self, sender, qq_module):
        sender.context.send_message = AsyncMock()
        sender._map_path = lambda p: p
        plain_a = qq_module.Plain("caption-a")
        record_a = qq_module.Record.fromFileSystem("/tmp/a.ogg")
        record_a.path = "/tmp/a.ogg"
        plain_b = qq_module.Plain("caption-b")
        record_b = qq_module.Record.fromFileSystem("/tmp/b.ogg")
        record_b.path = "/tmp/b.ogg"

        await sender._send_processed_batch(
            batch_data={
                "nodes_data": [[plain_a], [record_a], [plain_b], [record_b]],
                "contains_audio": True,
            },
            unified_msg_origin="target",
            self_id=1,
            node_name="bot",
            target_session="target",
        )

        calls = sender.context.send_message.await_args_list
        assert calls[0].args[1].chain[0].text == "caption-a"
        assert type(calls[1].args[1].chain[0]).__name__ == "Record"
        assert type(calls[2].args[1].chain[0]).__name__ == "File"
        assert calls[3].args[1].chain[0].text == "caption-b"
        assert type(calls[4].args[1].chain[0]).__name__ == "Record"
        assert type(calls[5].args[1].chain[0]).__name__ == "File"


class TestReplyPreviewIntegration:
    @pytest.mark.asyncio
    async def test_reply_preview_prepended_before_message_text(self, sender, qq_module):
        sender.context.send_message = AsyncMock()
        sender._bootstrap_qq_runtime = AsyncMock()
        sender._ensure_node_name = AsyncMock(return_value="bot")
        sender.downloader.download_media = AsyncMock(return_value=[])
        sender.downloader.client = MagicMock()
        quoted = type("Msg", (), {"id": 99, "sender": None, "post_author": None, "text": "quoted text"})()
        sender.downloader.client.get_messages = AsyncMock(return_value=[quoted])
        bot = MagicMock()
        bot.get_login_info = AsyncMock(return_value={"user_id": 1})
        sender.bot = bot

        reply_header = type("Reply", (), {"reply_to_msg_id": 99})()
        msg = type("Msg", (), {"id": 2, "text": "reply body", "reply_to": reply_header})()

        await sender.send(
            batches=[[msg]],
            src_channel="demo",
            display_name="demo",
            effective_cfg={"effective_target_qq_sessions": ["test:GroupMessage:1"]},
        )

        sent_chain = sender.context.send_message.await_args_list[0].args[1]
        texts = [component.text for component in sent_chain.chain if hasattr(component, "text")]
        assert any("↩ 回复:" in text for text in texts)
        assert any("quoted text" in text for text in texts)
        assert any("reply body" in text for text in texts)


class TestBigMergeFallback:
    @staticmethod
    def _make_msg(msg_id, text=None):
        return type("Msg", (), {"id": msg_id, "text": text, "reply_to": None})()

    @staticmethod
    def _configure_sender(sender):
        attempts = {"count": 0}

        async def send_message(*args, **kwargs):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("merged-forward boom")
            return None

        sender.context.send_message = AsyncMock(side_effect=send_message)
        sender.config = {"forward_config": {"qq_merge_threshold": 2}}
        sender._bootstrap_qq_runtime = AsyncMock()
        sender._ensure_node_name = AsyncMock(return_value="bot")
        sender.downloader.client = MagicMock()
        sender._map_path = lambda path: path
        bot = MagicMock()
        bot.get_login_info = AsyncMock(return_value={"user_id": 1})
        sender.bot = bot

    @pytest.mark.asyncio
    async def test_big_merge_failure_fallback_keeps_image_album_merge(self, sender):
        self._configure_sender(sender)
        image_a = self._make_msg(1)
        image_b = self._make_msg(2)
        plain_msg = self._make_msg(3, text="tail")

        async def download_media(msg, max_size_mb=0):
            return {
                1: ["/tmp/a.jpg"],
                2: ["/tmp/b.jpg"],
                3: [],
            }[msg.id]

        sender.downloader.download_media = AsyncMock(side_effect=download_media)

        await sender.send(
            batches=[[image_a, image_b], [plain_msg]],
            src_channel="demo",
            display_name="demo",
            effective_cfg={"effective_target_qq_sessions": ["test:GroupMessage:1"]},
            involved_channels=None,
        )

        calls = sender.context.send_message.await_args_list
        assert sender.context.send_message.await_count == 3
        assert type(calls[1].args[1].chain[0]).__name__ == "Nodes"
        assert len(calls[1].args[1].chain[0].value) == 2

    @pytest.mark.asyncio
    async def test_big_merge_failure_fallback_splits_video_and_file_components(self, sender):
        self._configure_sender(sender)
        mixed_media_msg = self._make_msg(1, text="caption")
        plain_msg = self._make_msg(2, text="tail")

        async def download_media(msg, max_size_mb=0):
            return {
                1: ["/tmp/video.mp4", "/tmp/doc.zip"],
                2: [],
            }[msg.id]

        sender.downloader.download_media = AsyncMock(side_effect=download_media)

        await sender.send(
            batches=[[mixed_media_msg], [plain_msg]],
            src_channel="demo",
            display_name="demo",
            effective_cfg={"effective_target_qq_sessions": ["test:GroupMessage:1"]},
            involved_channels=None,
        )

        calls = sender.context.send_message.await_args_list
        assert sender.context.send_message.await_count == 5
        assert any(
            len(call.args[1].chain) == 1 and type(call.args[1].chain[0]).__name__ == "Video"
            for call in calls[1:]
        )
        assert any(
            len(call.args[1].chain) == 1 and type(call.args[1].chain[0]).__name__ == "File"
            for call in calls[1:]
        )
        assert all(
            not any(type(component).__name__ == "Video" for component in call.args[1].chain)
            or len(call.args[1].chain) == 1
            for call in calls[1:]
        )

    @pytest.mark.asyncio
    async def test_big_merge_failure_fallback_keeps_audio_record_and_file_semantics(self, sender):
        self._configure_sender(sender)
        audio_msg = self._make_msg(1, text="caption")
        plain_msg = self._make_msg(2, text="tail")

        async def download_media(msg, max_size_mb=0):
            return {
                1: ["/tmp/audio.ogg"],
                2: [],
            }[msg.id]

        sender.downloader.download_media = AsyncMock(side_effect=download_media)

        await sender.send(
            batches=[[audio_msg], [plain_msg]],
            src_channel="demo",
            display_name="demo",
            effective_cfg={"effective_target_qq_sessions": ["test:GroupMessage:1"]},
            involved_channels=None,
        )

        calls = sender.context.send_message.await_args_list
        assert sender.context.send_message.await_count == 5
        assert any(
            len(call.args[1].chain) == 1 and type(call.args[1].chain[0]).__name__ == "Record"
            for call in calls[1:]
        )
        assert sum(
            1
            for call in calls[1:]
            if len(call.args[1].chain) == 1 and type(call.args[1].chain[0]).__name__ == "File"
        ) >= 1
