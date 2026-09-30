#!/usr/bin/env python3
"""Regenerate glyphs.json — the picker's glyph catalogue.

Names and codepoints come from the Nerd Fonts project's own glyphnames.json,
so nothing here is hand-typed and nothing drifts from what the font actually
ships. Every candidate is then checked against the cmap of the installed
Nerd Font: a glyph the user's font can't draw is a tofu box in the picker,
so it never makes the list (the 3.5.x name list is ahead of most packaged
fonts by ~100 devicons).

Entries carry `cat` for the picker's category chips and `pop` for the
curated "Popular" tab, which is the hand-picked list below — the one part
of the file that is a judgement call rather than derived data.

    ./scripts/build-glyphs.py [--font PATH] [--offline]

Stdlib only, so it runs anywhere; --offline reuses the cached name list.
"""

import argparse, collections, json, os, re, struct, sys, urllib.request

GLYPHNAMES_URL = "https://raw.githubusercontent.com/ryanoasis/nerd-fonts/master/glyphnames.json"
DEFAULT_FONT = "/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Regular.ttf"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(REPO, "scripts", ".glyphnames.cache.json")

# Sets that are structural rather than iconic: powerline separators, indent
# guides and IEC power symbols are never what someone wants on a dock tile.
DROP_SETS = {"ple", "pl", "iec", "indent", "indentation"}

# The "Popular" tab, in the order it is shown. Nerd Font names, not
# codepoints, so a rename upstream fails the build loudly instead of
# silently swapping in the wrong picture.
POPULAR = """
md-google_chrome md-firefox md-microsoft_edge md-web dev-chrome dev-firefox dev-safari linux-tor
md-console md-console_line oct-terminal cod-terminal_bash md-microsoft_windows md-apple md-linux
linux-archlinux linux-ubuntu linux-fedora linux-debian linux-nixos linux-hyprland
md-folder md-folder_open md-file_document md-file md-file_multiple md-download md-upload md-archive md-folder_zip
md-microsoft_visual_studio_code dev-vscode dev-vim dev-neovim custom-neovim custom-vim custom-obsidian dev-notion
md-git dev-git md-github dev-github oct-mark_github md-gitlab dev-gitlab dev-bitbucket
md-docker dev-docker md-kubernetes md-database md-server md-package_variant md-api md-code_braces md-code_tags
dev-python dev-nodejs dev-rust dev-go dev-ruby dev-php dev-java dev-javascript dev-react dev-html5 dev-css3
dev-postgresql dev-mysql dev-redis dev-terminal dev-markdown dev-npm dev-android dev-swift
md-remote_desktop md-monitor md-laptop md-desktop_tower md-harddisk md-usb md-cpu_64_bit md-memory md-keyboard md-mouse md-printer
cod-claude cod-openai md-robot md-robot_outline md-brain md-auto_fix md-creation md-shimmer md-lightbulb_on
md-message md-message_text md-chat md-email md-email_outline linux-thunderbird md-calendar md-calendar_month
md-clock_outline md-bell md-account md-account_group
md-music md-spotify md-youtube md-video md-vlc md-camera md-image md-image_multiple md-palette md-microphone
md-headphones md-volume_high md-play md-pause md-plex md-kodi
md-cog md-cog_outline md-tune md-apps md-view_grid md-information md-help_circle md-magnify md-filter_variant
md-refresh md-lock md-lock_open md-power md-close md-plus md-minus md-check md-pin md-star md-heart md-bookmark
md-wifi md-bluetooth md-network md-vpn md-shield_check md-key md-security
md-discord md-slack fa-telegram md-whatsapp md-signal md-reddit md-linkedin md-mastodon
md-notebook md-note_text md-format_list_bulleted md-checkbox_marked_outline md-calculator md-currency_usd
md-chart_line md-chart_bar md-microsoft_teams md-microsoft_excel md-microsoft_word linux-libreoffice
md-map_marker md-home md-cart md-briefcase md-school md-book_open_variant md-coffee md-rocket_launch md-ghost
md-google_controller md-controller_classic fa-steam dev-figma dev-blender dev-gimp dev-inkscape linux-krita
md-weather_night md-weather_sunny md-water md-fire md-leaf md-paw md-cat md-dog
md-trash_can md-delete md-content_save md-share_variant md-link_variant md-eye md-pencil md-magnify_plus_outline
""".split()

BRANDS = (
    "google|microsoft|apple|adobe|amazon|aws|azure|facebook|meta|twitter|instagram|youtube|spotify|netflix|"
    "discord|slack|telegram|whatsapp|wechat|weibo|reddit|linkedin|mastodon|tumblr|pinterest|snapchat|tiktok|vimeo|twitch|"
    "github|gitlab|bitbucket|codeberg|gitea|jira|trello|asana|notion|obsidian|evernote|dropbox|onedrive|"
    "docker|kubernetes|jenkins|ansible|terraform|vagrant|heroku|digitalocean|cloudflare|firebase|"
    "firefox|chrome|chromium|edge|safari|opera|brave|vivaldi|tor|"
    "vlc|plex|kodi|jellyfin|steam|xbox|playstation|nintendo|epic|itch|unity|unreal|godot|"
    "android|windows|ubuntu|debian|fedora|centos|redhat|suse|manjaro|mint|nixos|gentoo|alpine|"
    "nvidia|intel|amd|arm|raspberry|arduino|qualcomm|"
    "paypal|stripe|visa|mastercard|bitcoin|ethereum|"
    "wordpress|drupal|joomla|shopify|magento|squarespace|wix|"
    "figma|sketch|blender|autocad|photoshop|illustrator|"
    "python|nodejs|node_js|rust|golang|ruby|php|java|javascript|typescript|react|angular|vuejs|svelte|django|laravel|rails|"
    "postgresql|mysql|mariadb|mongodb|redis|sqlite|elasticsearch|"
    "npm|yarn|pypi|maven|gradle|nuget|"
    "zoom|skype|teamviewer|signal_app|matrix_org|element|thunderbird|protonmail|gmail|outlook|"
    "soundcloud|bandcamp|deezer|tidal|lastfm|"
    "goodreads|medium|substack|patreon|kofi|buymeacoffee|"
    "bootstrap|tailwind|jquery|webpack|vite|babel|eslint|"
    "stackoverflow|stack_overflow|hackernews|producthunt|devto|codepen|jsfiddle|replit|"
    "uber|lyft|airbnb|zapier|ifttt|"
    "discourse|blogger|flickr|behance|dribbble|deviantart|artstation|"
    "usps|fedex|ups|dhl|opencollective|opensource|creative_commons|wikipedia|archive_org|internet_archive|"
    "vim|neovim|emacs|sublime|atom|jetbrains|intellij|pycharm|webstorm|eclipse|netbeans|xcode|"
    "linux|gnu|freebsd|openbsd|netbsd|solaris|"
    "hyprland|sway|i3|awesome|bspwm|dwm|xmonad|gnome|kde|xfce|cinnamon|mate|budgie|lxde|lxqt|"
    "alacritty|kitty|wezterm|foot|ghostty|konsole|tilix|"
    "krita|gimp|inkscape|darktable|rawtherapee|audacity|ardour|kdenlive|obs|handbrake|ffmpeg|"
    "libreoffice|openoffice|onlyoffice|latex|texstudio|pandoc|"
    "claude|openai|anthropic|chatgpt|copilot|huggingface|tensorflow|pytorch|jupyter"
)

# First rule to match wins, so brands beat the generic nouns inside them
# ("docker" is an app, not a boat).
RULES = [
 ("apps",    r"\b(" + BRANDS + r")\b"),
 ("code",    r"\b(code|git|branch|commit|merge|pull|repo|terminal|console|bash|shell|script|api|bug|debug|breakpoint|function|variable|method|class|namespace|regex|json|xml|yaml|sql|database|server|package|library|compile|build|test|deploy|editor|ide|snippet|symbol|syntax|lambda|binary|hex|source|patch|diff|issue|milestone|fork|clone|tag|versions?)\b"),
 ("files",   r"\b(file|files|folder|folders|directory|document|archive|zip|paperclip|clipboard|note|notes|book|text|page|pages|pdf|doc|sheet|table|form|invoice|receipt|newspaper|scroll|drawer)\b"),
 ("system",  r"\b(cpu|memory|ram|chip|monitor|laptop|desktop|tower|harddisk|hdd|ssd|disc|disk|usb|battery|power|plug|network|wifi|ethernet|lan|router|modem|bluetooth|printer|scanner|keyboard|mouse|gpu|fan|thermometer|sd|sim|nas|cable|port|hardware|motherboard|processor|expansion|circuit)\b"),
 ("media",   r"\b(music|song|album|playlist|play|pause|stop|rewind|forward|skip|shuffle|repeat|volume|speaker|headphones|headset|microphone|mic|video|movie|film|television|tv|camera|photo|image|picture|gallery|radio|podcast|cast|record|equalizer|guitar|piano|drum|violin|saxophone|trumpet|metronome|subtitle|vhs|dvd|cd)\b"),
 ("comm",    r"\b(message|messages|chat|comment|email|mail|envelope|phone|call|voicemail|send|forum|bell|notification|share|rss|feed|contact|contacts|account|user|users|people|person|group|team|at|reply|inbox|outbox|broadcast|announcement|megaphone|bullhorn)\b"),
 ("nature",  r"\b(weather|cloud|clouds|sun|sunny|moon|rain|rainy|snow|snowy|storm|thunder|lightning|wind|windy|fog|tornado|hurricane|temperature|tree|forest|leaf|flower|plant|seed|sprout|grass|water|wave|fire|flame|earth|mountain|volcano|animal|dog|cat|bird|fish|paw|butterfly|spider|horse|cow|pig|sheep|rabbit|turtle|snake|elephant|panda|koala|bee)\b"),
 ("places",  r"\b(home|house|building|office|bank|hospital|school|store|shop|shopping|cart|city|church|castle|factory|warehouse|hotel|restaurant|cafe|coffee|beer|wine|food|pizza|burger|map|marker|pin|compass|globe|world|navigation|road|car|bus|train|plane|airplane|bike|bicycle|motorbike|truck|boat|ship|rocket|walk|run|traffic)\b"),
 ("ui",      r"^(format|align|text)\b|\b(tooltip|dialog|icons|apps_box|logout|login|transfer|order_bool)\b"),
 ("ui",      r"\b(arrow|arrows|chevron|caret|angle|plus|minus|add|remove|check|close|cancel|cog|gear|settings|menu|hamburger|dots|search|magnify|filter|sort|view|window|tab|tabs|dock|pin|unpin|lock|unlock|key|eye|edit|pencil|write|trash|delete|bin|refresh|reload|sync|undo|redo|download|upload|export|import|star|heart|bookmark|flag|toggle|switch|slider|checkbox|radiobox|progress|loading|spinner|resize|expand|collapse|fullscreen|drag|grid|list|layout|columns|rows|split|panel|sidebar|dashboard|zoom|crop|move|swap|link|unlink|copy|paste|cut|select|cursor|pointer|hand|touch|gesture|scroll|alert|information|help|question|exclamation|warning|error|success)\b"),
 ("symbols", r"\b(alpha|numeric|roman|abjad|math|equal|percent|currency|cash|coin|money|dollar|euro|pound|yen|circle|square|rectangle|hexagon|pentagon|octagon|rhombus|shape|chess|dice|card|cards|emoticon|emoji|gender|zodiac|sign|symbol|braille|blank|dot|line|border|shading|vector)\b"),
]

# Whoever gets to keep the bare name when several sets draw the same thing;
# the hand-drawn brand sets first, since those are the nicer logos.
SET_ORDER = ["dev", "linux", "oct", "cod", "fa", "md", "seti", "weather",
             "fae", "custom", "extra", "pom"]
CAT_ORDER = ["apps", "code", "files", "system", "media", "comm", "ui",
             "places", "nature", "symbols", "misc"]


def font_codepoints(path):
    """Every codepoint the font can actually draw, straight out of its cmap."""
    f = open(path, "rb").read()
    tables = struct.unpack(">H", f[4:6])[0]
    cmap = None
    for i in range(tables):
        tag, _, off, _ = struct.unpack(">4sIII", f[12 + 16 * i:28 + 16 * i])
        if tag == b"cmap":
            cmap = off
    if cmap is None:
        sys.exit(f"{path}: no cmap table")

    best = None
    for i in range(struct.unpack(">H", f[cmap + 2:cmap + 4])[0]):
        _, _, sub = struct.unpack(">HHI", f[cmap + 4 + 8 * i:cmap + 12 + 8 * i])
        fmt = struct.unpack(">H", f[cmap + sub:cmap + sub + 2])[0]
        # Format 12 reaches past the BMP, where the 6.9k Material icons live.
        if fmt == 12:
            best = cmap + sub
        elif fmt == 4 and best is None:
            best = cmap + sub

    cps = set()
    fmt = struct.unpack(">H", f[best:best + 2])[0]
    if fmt == 12:
        for i in range(struct.unpack(">I", f[best + 12:best + 16])[0]):
            s, e, _ = struct.unpack(">III", f[best + 16 + 12 * i:best + 28 + 12 * i])
            cps.update(range(s, e + 1))
    else:
        seg2 = struct.unpack(">H", f[best + 6:best + 8])[0]
        ends, starts = best + 14, best + 14 + seg2 + 2
        for i in range(seg2 // 2):
            e = struct.unpack(">H", f[ends + 2 * i:ends + 2 * i + 2])[0]
            s = struct.unpack(">H", f[starts + 2 * i:starts + 2 * i + 2])[0]
            if s != 0xFFFF:
                cps.update(range(s, e + 1))
    return cps


def glyphnames(offline):
    if not offline:
        try:
            with urllib.request.urlopen(GLYPHNAMES_URL, timeout=60) as r:
                data = r.read()
            open(CACHE, "wb").write(data)
            return json.loads(data)
        except Exception as e:
            print(f"fetch failed ({e}), falling back to cache", file=sys.stderr)
    if not os.path.exists(CACHE):
        sys.exit("no cached glyphnames.json; run once online")
    return json.load(open(CACHE))


def categorise(prefix, human):
    if prefix in ("dev", "linux", "seti"):
        return "apps"
    if prefix in ("cod", "oct"):
        return "code"
    if prefix == "weather":
        return "nature"
    for cat, rx in RULES:
        if re.search(rx, human):
            return cat
    return "misc"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--font", default=DEFAULT_FONT)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--out", default=os.path.join(REPO, "glyphs.json"))
    args = ap.parse_args()

    names = glyphnames(args.offline)
    meta = names.pop("METADATA", {})
    cps = font_codepoints(args.font)

    rows, dropped = [], collections.Counter()
    for key, v in names.items():
        prefix = key.split("-", 1)[0]
        if prefix in DROP_SETS:
            continue
        cp = int(v["code"], 16)
        if cp not in cps:
            dropped[prefix] += 1
            continue
        human = key.split("-", 1)[1].replace("_", " ").strip()
        rows.append({"key": key, "prefix": prefix, "name": human,
                     "glyph": chr(cp), "cat": categorise(prefix, human)})

    by_key = {r["key"]: r for r in rows}
    absent = [k for k in POPULAR if k not in by_key]
    if absent:
        sys.exit("POPULAR names missing from this font: " + ", ".join(absent))
    popular = set(POPULAR)

    # Several sets draw a "folder"; the first claims the bare name and the
    # rest get their set in brackets, so the picker never shows two rows
    # that read identically.
    order = {p: i for i, p in enumerate(SET_ORDER)}
    rows.sort(key=lambda r: (r["name"], 0 if r["key"] in popular else 1,
                             order.get(r["prefix"], 99)))
    counts = collections.Counter(r["name"] for r in rows)
    taken = set()
    for r in rows:
        r["display"] = (f"{r['name']} ({r['prefix']})"
                        if counts[r["name"]] > 1 and r["name"] in taken
                        else r["name"])
        taken.add(r["name"])

    cat_idx = {c: i for i, c in enumerate(CAT_ORDER)}
    out = [{"name": by_key[k]["display"], "glyph": by_key[k]["glyph"],
            "cat": by_key[k]["cat"], "set": by_key[k]["prefix"], "pop": 1}
           for k in POPULAR]
    out += [{"name": r["display"], "glyph": r["glyph"], "cat": r["cat"],
             "set": r["prefix"]}
            for r in sorted((r for r in rows if r["key"] not in popular),
                            key=lambda r: (cat_idx[r["cat"]], r["display"]))]

    # One entry per line: a 700KB blob still diffs and greps like a list.
    with open(args.out, "w") as f:
        f.write("[\n")
        f.write(",\n".join(json.dumps(e, ensure_ascii=False,
                                      separators=(",", ":")) for e in out))
        f.write("\n]\n")

    print(f"{args.out}: {len(out)} glyphs "
          f"({len(POPULAR)} popular) from Nerd Fonts {meta.get('version','?')}")
    print("  by category: " + ", ".join(
        f"{c}={n}" for c, n in collections.Counter(e["cat"] for e in out).most_common()))
    if dropped:
        print("  not in " + os.path.basename(args.font) + ", skipped: " + ", ".join(
            f"{k}={v}" for k, v in dropped.most_common()))


if __name__ == "__main__":
    main()
