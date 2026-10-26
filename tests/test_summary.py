import io
from datetime import datetime, timedelta, timezone

from PIL import Image

from gryag import pages, store, summary

CHAT = -1004291515714
BOT = 8082154386
T0 = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)


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


async def _at(db, message_id, user_id, minute, text="ок", is_bot=False, reply_to=None):
    await store.save_message(
        db, chat_id=CHAT, message_id=message_id, user_id=user_id,
        ts=(T0 + timedelta(minutes=minute)).isoformat(timespec="seconds"),
        text=text, media_kind=None, file_id=None, reply_to=reply_to, is_bot=is_bot,
    )


async def _pick(db, user_id, minute, count=None, batch=1000):
    return await summary.select(
        db, CHAT, user_id, before_message_id=999, count=count, batch=batch,
        now=T0 + timedelta(minutes=minute), away=timedelta(minutes=30),
    )


async def test_unread_starts_where_the_caller_was_last_away(db):
    await _at(db, 1, user_id=7, minute=0, text="бувайте")
    for n in range(2, 6):
        await _at(db, n, user_id=8, minute=n * 20)
    # Back after two hours, and already chatting before asking.
    await _at(db, 6, user_id=7, minute=120, text="я тут")
    await _at(db, 7, user_id=8, minute=121)
    await _at(db, 8, user_id=7, minute=122, text="що було?")

    chosen = await _pick(db, 7, minute=123)

    # Only the absence: from 6 on, the caller was back and saw it.
    assert [m["message_id"] for m in chosen.messages] == [2, 3, 4, 5]
    assert chosen.away_since == T0.isoformat(timespec="seconds")


async def test_asking_on_return_covers_everything_since_leaving(db):
    await _at(db, 1, user_id=7, minute=0)
    for n in range(2, 6):
        await _at(db, n, user_id=8, minute=n * 20)

    chosen = await _pick(db, 7, minute=121)

    assert [m["message_id"] for m in chosen.messages] == [2, 3, 4, 5]


async def test_someone_who_was_here_all_along_missed_nothing(db):
    for n in range(1, 8):
        await _at(db, n, user_id=7 if n % 2 else 8, minute=n)

    chosen = await _pick(db, 7, minute=8)

    assert chosen.messages == []


async def test_someone_who_never_wrote_gets_the_whole_window(db):
    for n in range(1, 6):
        await _at(db, n, user_id=8, minute=n)

    chosen = await _pick(db, 7, minute=6)

    assert [m["message_id"] for m in chosen.messages] == [1, 2, 3, 4, 5]
    assert chosen.away_since is None


async def test_unread_past_one_batch_keeps_the_newest_and_counts_the_rest(db):
    await _at(db, 1, user_id=7, minute=0)
    for n in range(2, 12):
        await _at(db, n, user_id=8, minute=60 + n)

    chosen = await _pick(db, 7, minute=80, batch=4)

    assert [m["message_id"] for m in chosen.messages] == [8, 9, 10, 11]
    assert chosen.skipped == 6


async def test_earlier_summaries_are_not_summarised_again(db):
    await _at(db, 1, user_id=7, minute=0)
    await _at(db, 2, user_id=8, minute=60, text="справжнє")
    await _at(db, 3, user_id=9, minute=61, text="/summary@gryag_bot")
    await _at(db, 4, user_id=BOT, minute=61, text="• підсумок", is_bot=True, reply_to=3)
    await _at(db, 5, user_id=BOT, minute=62, text="звичайна відповідь", is_bot=True)

    chosen = await _pick(db, 7, minute=63)

    assert [m["message_id"] for m in chosen.messages] == [2, 5]


async def test_a_number_takes_the_last_n_instead(db):
    for n in range(1, 11):
        await _at(db, n, user_id=7 if n == 9 else 8, minute=n)

    chosen = await _pick(db, 7, minute=11, count=3)

    assert [m["message_id"] for m in chosen.messages] == [8, 9, 10]


def test_the_word_for_messages_agrees_with_the_number():
    words = {n: summary.messages_word(n) for n in (1, 3, 5, 11, 14, 21, 34, 112)}

    assert words == {
        1: "повідомлення", 3: "повідомлення", 5: "повідомлень", 11: "повідомлень",
        14: "повідомлень", 21: "повідомлення", 34: "повідомлення", 112: "повідомлень",
    }


def test_the_scope_line_says_what_was_covered():
    batch = summary.Batch([{}] * 12, skipped=3, away_since="2020-01-01T10:00:00+00:00")

    assert summary.scope(batch, None) == (
        "(12 повідомлень з 01.01 12:00, поки тебе не було, ще 3 старіших не влізло)"
    )
    assert summary.scope(summary.Batch([{}] * 5, 0), 5) == "(останні 5 повідомлень)"


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


def test_several_numbers_link_to_the_first_one_in_the_batch():
    messages = [{"message_id": 500}, {"message_id": 501}]

    out = summary.to_html("[Лобстер про стікери](99, 2) і [ще](1 ; 2)", CHAT, messages)

    assert out == (
        '<a href="https://t.me/c/4291515714/501">Лобстер про стікери</a> і '
        '<a href="https://t.me/c/4291515714/500">ще</a>'
    )


def test_an_overlong_summary_is_cut_at_whole_points():
    messages = [{"message_id": 1}]
    text = "\n".join(f"• [пункт {n}](1) " + "х" * 300 for n in range(30))

    out = summary.fit(text, CHAT, messages, note="\n\n<i>(ще 5)</i>")

    assert len(out) <= summary.TELEGRAM_LIMIT
    assert out.endswith("<i>(ще 5)</i>")
    assert out.count("<a ") == out.count("</a>")


def test_one_endless_point_is_cut_without_breaking_a_tag():
    text = " ".join(f"[слово](1) &" for _ in range(800))

    out = summary.fit(text, CHAT, [{"message_id": 1}])

    assert len(out) <= summary.TELEGRAM_LIMIT
    assert out.count("<a ") == out.count("</a>")
    assert not out.rstrip().endswith(("&am", "<a", "&"))
