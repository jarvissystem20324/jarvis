"""10.0 content creators: ideas, scripts, hooks, hashtags, threads, turning a
video into posts, keyword ideas from real YouTube searches, a thumbnail seen
in a feed, stream overlays, and the teleprompter (on the Creator page).

The writing is the AI's; the facts are fetched — keyword ideas are what
people really type into YouTube, and a video is repurposed from its own
captions, not from what the AI imagines it says.
"""

from __future__ import annotations

from pathlib import Path

from .. import creator, kit, shield
from ..registry import command, field, split

G = "Media"
PLATFORMS = ("YouTube", "TikTok", "Instagram", "X", "LinkedIn")


class Creator:
    @command("videoideas", "ideas", group=G, usage="/videoideas <your niche or channel> [| platform]",
             help="video ideas with a title and the hook for each", title="Video idea generator", icon="💡",
             page="creator", fields=(field("niche", "text", "Your niche or channel", hint="budget travel in Türkiye"),
                                     field("platform", "choice", "Platform", "YouTube", PLATFORMS)))
    def videoideas_cmd(self, args: str, routed: bool = False):
        niche, platform = split(args, 2)
        if not niche.strip():
            return "Usage: /videoideas home coffee for beginners | YouTube"
        real = creator.keyword_ideas(niche.strip())[:15]
        searches = ("\nPeople really search for: " + "; ".join(real)) if real else ""
        with kit.more_room(self.brain, 3000):
            answer = self.brain.ask_once(
                f"Give 10 {platform.strip() or 'YouTube'} video ideas for a creator about: {niche.strip()}. "
                f"Write in the language of the request.{searches}\nFor each: a title (under 60 characters, specific, "
                "no clickbait it can't deliver), one sentence on the angle, and the first line the creator says. "
                "Lean on what people really search for when it fits.")
        return "💡 " + answer.strip()

    @command("script", "videoscript", group=G, usage="/script <topic> | [minutes] | [style]",
             help="a video script with the hook, sections, b-roll notes and a call to action (Word file)",
             title="Video script writer", icon="📝", page="creator",
             fields=(field("topic", "long", "What's the video about?"),
                     field("minutes", "number", "Length (minutes)", "8"),
                     field("style", "choice", "Style", "explainer",
                           ("explainer", "story", "review", "tutorial", "vlog", "short"))))
    def script_cmd(self, args: str, routed: bool = False):
        from .. import writer

        topic, minutes, style = split(args, 3)
        if not topic.strip():
            return "Usage: /script why Istanbul has so many cats | 6 | story"
        length = minutes.strip() or "8"
        with kit.more_room(self.brain, 7000):
            markdown = self.brain.ask_once(
                f"Write a {length}-minute {style.strip() or 'explainer'} video script about: {topic.strip()}. "
                "Write in the language of the request. Markdown: a '# ' title, then '## Hook (0:00)', then timed "
                "sections ('## Section name (m:ss)'), each with what to say, and [B-ROLL: …] and [ON SCREEN: …] "
                "notes in brackets, then '## Call to action'. Spoken, natural sentences; about 150 words a minute.")
        try:
            files = writer.save(markdown, ("docx",))
        except Exception:
            files = []
        return f"📝 {writer.title_of(markdown)}\n\n{markdown.strip()[:1500]}" + \
            ("\n…" if len(markdown) > 1500 else "") + "".join(f"\n{f}" for f in files)

    @command("hooks", "hook", group=G, usage="/hooks <what the video is about>",
             help="ten first lines that make people keep watching, in different styles", title="Hook writer",
             icon="🪝", page="creator", fields=(field("topic", "long", "What's the video about?"),))
    def hooks_cmd(self, args: str, routed: bool = False):
        if not args.strip():
            return "Usage: /hooks I tried living on 100 lira a day"
        return "🪝 " + self.brain.ask_once(
            f"Write 10 different opening hooks (the first 1-2 spoken sentences) for a video about: {args.strip()}. "
            "Write in the language of the request. One each of: a question, a bold claim, a surprising number, a "
            "story's first line, a mistake viewers make, a promise of what they'll learn, a 'stop doing X', a "
            "before/after, a challenge, a quote. Label each style. No lies the video can't back up.").strip()

    @command("hashtags", group=G, usage="/hashtags <topic> [| platform]",
             help="hashtags that mix broad and niche tags for a post", title="Hashtag generator", icon="#️⃣",
             page="creator", fields=(field("topic", "text", "What's the post about?"),
                                     field("platform", "choice", "Platform", "Instagram", PLATFORMS)))
    def hashtags_cmd(self, args: str, routed: bool = False):
        topic, platform = split(args, 2)
        if not topic.strip():
            return "Usage: /hashtags street food in Kadıköy | Instagram"
        platform = platform.strip() or "Instagram"
        count = {"Instagram": "20", "TikTok": "5", "X": "2-3", "LinkedIn": "3-5", "YouTube": "3"}.get(platform, "10")
        return "#️⃣ " + self.brain.ask_once(
            f"Suggest {count} hashtags for a {platform} post about: {topic.strip()}. Mix a few broad ones with "
            "specific niche and local ones (Turkish tags too if it's about Türkiye). Put them on one line ready to "
            "paste, then one line on why the niche ones help. Don't invent follower counts.").strip()

    @command("repurpose", group=G, usage="/repurpose <YouTube link or a transcript file>",
             help="turns a video into posts for X, LinkedIn, Instagram, a short and a newsletter",
             title="Repurpose a video into posts", icon="♻", page="creator",
             fields=(field("video", "text", "YouTube link or transcript file", hint="https://youtu.be/…"),))
    def repurpose_cmd(self, args: str, routed: bool = False):
        from .. import youtube

        source = args.strip().strip('"')
        path = kit.path_arg(source)
        if path is not None and path.is_file():
            transcript = path.read_text(encoding="utf-8", errors="replace")[:60_000]
            name = path.stem
        else:
            vid = youtube.video_id(source)
            if not vid:
                return "Usage: /repurpose https://youtu.be/… (or a transcript .txt file)"
            try:
                _, transcript = youtube.transcript(vid)
            except youtube.YouTubeError as exc:
                return f"♻ {exc}"
            name = youtube.title(vid) or vid
        wrapped, _ = shield.wrap(transcript, "video transcript")
        with kit.more_room(self.brain, 5000):
            answer = self.brain.ask_once(
                f"{shield.RULE}\nFrom this video's transcript ({name}), write, in the video's language:\n"
                "1. An X thread (5-7 posts, each under 270 characters)\n2. A LinkedIn post (150-250 words)\n"
                "3. An Instagram caption with a hook first line\n4. A 45-second vertical short script\n"
                "5. A newsletter paragraph with three takeaways.\nOnly use what the video actually says.\n\n" +
                wrapped)
        return f"♻ From “{name}”:\n\n{answer.strip()}"

    @command("seo", "keywords", group=G, usage="/seo <topic>",
             help="keyword ideas from what people really search on YouTube, and titles that use them",
             title="SEO keyword ideas", icon="🔎", page="creator",
             fields=(field("topic", "text", "Topic", hint="iPhone photography"),))
    def seo_cmd(self, args: str, routed: bool = False):
        topic = args.strip()
        if not topic:
            return "Usage: /seo budget gaming pc"
        ideas = creator.keyword_ideas(topic)
        if not ideas:
            return f"🔎 YouTube's search suggestions didn't answer for {topic!r} (offline?)."
        lines = [f"🔎 What people search for around “{topic}” (YouTube's own suggestions):"]
        lines += [f"  • {idea}" for idea in ideas[:25]]
        titles = self.brain.ask_once(
            f"Using these real YouTube searches: {'; '.join(ideas[:25])}\nWrite 5 video titles (under 60 "
            f"characters) that would rank for them, in the language of the searches, and one line saying which "
            "searches look least competitive (long, specific ones) and why.")
        return "\n".join(lines) + "\n\n" + titles.strip()

    @command("thread", group=G, usage="/thread <topic or your text> [| X or Threads] [| how many posts]",
             help="a thread where every post fits the limit, numbered", title="Thread writer", icon="🧵",
             page="creator", fields=(field("topic", "long", "Topic, or your own text to split"),
                                     field("platform", "choice", "Platform", "X", ("X", "Threads", "Bluesky")),
                                     field("posts", "number", "Posts", "6")))
    def thread_cmd(self, args: str, routed: bool = False):
        topic, platform, count = split(args, 3)
        if not topic.strip():
            return "Usage: /thread 5 things I learned moving to Ankara | X | 6"
        limit = {"Threads": 500, "Bluesky": 300}.get(platform.strip(), 280)
        if len(topic) > 400:
            text = topic           # their own text: just split it
        else:
            text = self.brain.ask_once(
                f"Write a {count.strip() or '6'}-post thread for {platform.strip() or 'X'} about: {topic.strip()}. "
                "Write in the language of the request. First post: a hook that makes people open it. Last: a short "
                f"takeaway. Separate posts with a blank line; keep each under {limit - 10} characters; no "
                "hashtags in every post.")
        posts = creator.split_thread(text, limit)
        return f"🧵 {len(posts)} posts, each under {limit} characters:\n\n" + "\n\n".join(posts)

    @command("thumbpreview", "feedpreview", group=G, usage="/thumbpreview <thumbnail image> | <title> | [channel]",
             help="your thumbnail and title as viewers see them: small, in a feed, on desktop and phone",
             title="Thumbnail preview in a feed", icon="🖼", page="creator",
             fields=(field("image", "file", "Thumbnail", types=(("Pictures", "*.png *.jpg *.jpeg *.webp"),)),
                     field("title", "text", "Video title"), field("channel", "text", "Channel", optional=True)))
    def thumbpreview_cmd(self, args: str, routed: bool = False):
        from ..assistant import JarvisResponse

        image, title, channel = split(args, 3)
        path = kit.path_arg(image)
        if path is None or not title.strip():
            return "Usage: /thumbpreview C:/thumb.png | I Tried Every Kebab in Istanbul | My Channel"
        try:
            dark = creator.feed_preview(path, title.strip(), channel.strip() or "Your channel", dark=True)
            light = creator.feed_preview(path, title.strip(), channel.strip() or "Your channel", dark=False,
                                         out=dark.with_name(dark.stem + "_light.png"))
        except OSError:
            return "I can't open that as a picture."
        return JarvisResponse(text=f"🖼 How it looks in a feed (dark and light):\n{dark}\n{light}", image_path=dark,
                              image_paths=[dark, light])

    @command("overlays", "streamoverlay", group=G, usage="/overlays <channel name> [| colour] [| socials]",
             help="stream overlays for OBS: webcam frame, lower third, starting soon, be right back, the end",
             title="Stream overlay maker", icon="📺", page="creator",
             fields=(field("name", "text", "Channel name"), field("colour", "color", "Colour", "#00d4ff"),
                     field("socials", "text", "Socials line", optional=True, hint="@you on Twitch & YouTube")))
    def overlays_cmd(self, args: str, routed: bool = False):
        from ..assistant import JarvisResponse

        name, colour, socials = split(args, 3)
        if not name.strip():
            return "Usage: /overlays MyChannel | #ff4f9a | @mychannel"
        files = creator.stream_overlays(name.strip(), colour.strip() or "#00d4ff", socials=socials.strip())
        return JarvisResponse(text=f"📺 {len(files)} overlays in {files[0].parent}\nIn OBS: add each as an Image "
                                   "source (the frame and lower third are see-through).\n" +
                                   "\n".join(str(f) for f in files), image_path=files[2], image_paths=files[2:4])

    @command("teleprompter", "prompter", group=G, usage="/teleprompter", help="scrolls your script at a steady pace",
             title="Teleprompter", icon="📜", page="creator")
    def teleprompter_cmd(self, args: str, routed: bool = False):
        from ..assistant import JarvisResponse

        return JarvisResponse(text="📜 The teleprompter is on the Creator page — paste your script and press Start.",
                              open_page="creator:teleprompter")
