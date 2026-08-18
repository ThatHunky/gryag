import types as pytypes

from gryag import media


def make(**kw):
    base = dict(photo=None, animation=None, voice=None, video=None, video_note=None,
                audio=None, sticker=None, document=None, reply_to_message=None)
    base.update(kw)
    return pytypes.SimpleNamespace(**base)


def test_photo_takes_the_largest_size():
    m = make(photo=[pytypes.SimpleNamespace(file_id="small"),
                    pytypes.SimpleNamespace(file_id="big")])

    assert media.detect(m) == ("photo", "big")


def test_animation_is_detected_as_its_own_kind():
    m = make(animation=pytypes.SimpleNamespace(file_id="gif"))

    assert media.detect(m) == ("animation", "gif")


def test_gif_is_sent_as_video():
    assert media.mime_for("animation") == "video/mp4"


def test_animated_stickers_are_refused():
    m = make(sticker=pytypes.SimpleNamespace(file_id="s", is_animated=True, is_video=False))

    assert media.mime_for("sticker", m) is None


def test_static_stickers_are_allowed():
    m = make(sticker=pytypes.SimpleNamespace(file_id="s", is_animated=False, is_video=False))

    assert media.mime_for("sticker", m) == "image/webp"


def test_documents_only_pass_when_they_are_readable_media():
    pdf = make(document=pytypes.SimpleNamespace(file_id="d", mime_type="application/pdf"))
    png = make(document=pytypes.SimpleNamespace(file_id="d", mime_type="image/png"))

    assert media.mime_for("document", pdf) is None
    assert media.mime_for("document", png) == "image/png"


def test_target_prefers_the_attachment_on_the_trigger_itself():
    m = make(photo=[pytypes.SimpleNamespace(file_id="own")])

    assert media.target(m)[0] == "own"


def test_target_falls_back_to_the_message_being_replied_to():
    parent = make(animation=pytypes.SimpleNamespace(file_id="gif"))
    m = make(reply_to_message=parent)

    file_id, mime, source = media.target(m)

    assert (file_id, mime) == ("gif", "video/mp4")
    assert source is parent


def test_target_is_none_when_there_is_nothing_to_look_at():
    assert media.target(make()) is None


async def test_fetch_returns_none_when_the_file_is_too_big():
    class Bot:
        async def get_file(self, file_id):
            return pytypes.SimpleNamespace(file_size=media.MAX_BYTES + 1)

    assert await media.fetch(Bot(), "f", "image/jpeg") is None


async def test_fetch_returns_none_instead_of_raising():
    class Bot:
        async def get_file(self, file_id):
            raise RuntimeError("telegram is down")

    assert await media.fetch(Bot(), "f", "image/jpeg") is None


async def test_fetch_returns_bytes_and_mime():
    class Bot:
        async def get_file(self, file_id):
            return pytypes.SimpleNamespace(file_size=10)

        async def download(self, file, destination):
            destination.write(b"jpegdata")

    assert await media.fetch(Bot(), "f", "image/jpeg") == (b"jpegdata", "image/jpeg")
