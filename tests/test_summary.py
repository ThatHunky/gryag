import io

from PIL import Image

from gryag import pages, store, summary

CHAT = -1004291515714


async def _say(db, message_id, user_id, text="ок"):
    await store.save_message(
        db, chat_id=CHAT, message_id=message_id, user_id=user_id,
        ts=f"2026-10-26T10:{message_id // 60:02d}:{message_id % 60:02d}+00:00",
        text=text, media_kind=None, file_id=None, reply_to=None, is_bot=False,
    )


def test_positions_become_links_to_the_real_messages():
    messages = [{"message_id": 500}, {"message_id": 501}]

    out = summary.to_html("• [Олег знову](2) про крипту", CHAT, messages)

    assert out == '• <a href="https://t.me/c/4291515714/501">Олег знову</a> про крипту'


def test_a_position_outside_the_batch_keeps_its_words_and_loses_the_link():
    out = summary.to_html("[вигадане](99)", CHAT, [{"message_id": 1}])

    assert out == "вигадане"


def test_text_around_the_links_is_escaped():
    out = summary.to_html("<b>x</b> [a & b](1)", CHAT, [{"message_id": 7}])

    assert out == '&lt;b&gt;x&lt;/b&gt; <a href="https://t.me/c/4291515714/7">a &amp; b</a>'


def test_lines_are_numbered_within_the_batch():
    lines = summary.numbered_lines(
        [{"message_id": 900, "text": "привіт", "display_name": "Олег"}]
    )

    assert lines[0].startswith("[1] ")
    assert lines[0].endswith(": привіт")


async def test_unread_is_everything_after_the_callers_own_last_line(db):
    await _say(db, 1, user_id=7, text="я тут")
    for n in range(2, 6):
        await _say(db, n, user_id=8, text=f"msg {n}")
    await _say(db, 6, user_id=7, text="/summary")

    chosen = await summary.select(db, CHAT, 7, before_message_id=6, count=None, batch=1000)

    assert [m["message_id"] for m in chosen.messages] == [2, 3, 4, 5]
    assert chosen.skipped == 0


async def test_unread_past_one_batch_keeps_the_newest_and_counts_the_rest(db):
    await _say(db, 1, user_id=7)
    for n in range(2, 12):
        await _say(db, n, user_id=8)

    chosen = await summary.select(db, CHAT, 7, before_message_id=99, count=None, batch=4)

    assert [m["message_id"] for m in chosen.messages] == [8, 9, 10, 11]
    assert chosen.skipped == 6


async def test_a_number_takes_the_last_n_instead(db):
    for n in range(1, 11):
        await _say(db, n, user_id=7 if n == 9 else 8)

    chosen = await summary.select(db, CHAT, 7, before_message_id=10, count=3, batch=1000)

    assert [m["message_id"] for m in chosen.messages] == [7, 8, 9]


def test_pages_draw_names_and_emoji_without_failing():
    lines = [f"[{n}] ٠ 𝒎𝒂𝒕𝒔𝒖𝒓𝒊۶ৎ: привіт 😭👍🏻 ☕" for n in range(1, 400)]

    rendered = pages.render(lines)

    assert len(rendered) >= 2
    image = Image.open(io.BytesIO(rendered[0]))
    assert image.size == (pages.WIDTH, pages.HEIGHT)


def test_the_emoji_is_drawn_in_colour():
    image = Image.new("RGB", (60, 30), "white")

    pages.Typesetter(20).draw(image, (0, 0), "😭")

    assert image.convert("HSV").getextrema()[1][1] > 0


def test_contact_sheet_skips_what_it_cannot_open():
    buffer = io.BytesIO()
    Image.new("RGB", (40, 40), "red").save(buffer, "JPEG")

    sheets = pages.contact_sheet([("[1]", buffer.getvalue()), ("[2]", b"not an image")])

    assert len(sheets) == 1
