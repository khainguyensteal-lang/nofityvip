"""
====================================================================
 DISCORD BOT - WELCOME + INVITE TRACKER (1 File Duy Nhất)
====================================================================
Chức Năng:
  - Chào Mừng Thành Viên Mới (Kèm Ai Đã Mời Họ)
  - Theo Dõi Lượt Mời: Hợp Lệ / Rời Đi / Ảo / Thưởng
  - Lệnh Slash: /invites, /invite-leaderboard, /who-invited, /welcome-test,
    /ping, /settings, /set-welcome-channel (Kèm Tùy Chọn Rules/Roles/Giới
    Thiệu/Role Ping), /set-leave-channel, /set-invites-channel,
    /set-confession-channel (Gửi Panel Confession Ẩn Danh/Công Khai)
  - Lệnh Văn Bản: !sync (Đồng Bộ Lại Slash Command)

Cài Đặt:
    pip install -r requirements.txt

Cấu Hình: Copy .env.example -> .env Rồi Điền Token + Channel Id

Chạy:
    python bot.py

QUAN TRỌNG: Vào Discord Developer Portal -> App -> Bot ->
Bật "SERVER MEMBERS INTENT" (Bắt Buộc Để Bot Nhận Sự Kiện
Join/Leave Và Đọc Danh Sách Invite).

Quyền Bot Cần Khi Mời Vào Server: Manage Server, Send Messages,
Embed Links, View Channels.
====================================================================
"""

import os
import json
from threading import Lock

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

# ── Cấu Hình ──────────────────────────────────────────────────────────────
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
WELCOME_CHANNEL_ID = os.getenv("WELCOME_CHANNEL_ID")
LEAVE_CHANNEL_ID = os.getenv("LEAVE_CHANNEL_ID")
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "!")

# Chỉ Có Người Dùng Với ID Này Mới Được Phép Dùng Lệnh Của Bot
OWNER_ID = 1512303397120901191

WELCOME_CHANNEL_ID = int(WELCOME_CHANNEL_ID) if WELCOME_CHANNEL_ID else None
LEAVE_CHANNEL_ID = int(LEAVE_CHANNEL_ID) if LEAVE_CHANNEL_ID else None

# Kênh welcome đặt qua lệnh /set-welcome-channel sẽ được ưu tiên hơn .env
# và lưu bền vào data.json theo từng server.

DATA_FILE = os.path.join(os.path.dirname(__file__), "data.json")
_lock = Lock()

intents = discord.Intents.default()
intents.members = True  # Bắt Buộc Để Theo Dõi Join/Leave Và Đọc Invite
intents.guilds = True
intents.message_content = True  # Cần để đọc nội dung tin nhắn

bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)


def is_owner():
    """Check Chỉ Cho Phép Owner (OWNER_ID) Dùng Lệnh Slash."""
    async def predicate(interaction: discord.Interaction) -> bool:
        return interaction.user.id == OWNER_ID
    return app_commands.check(predicate)


async def handle_owner_check_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> bool:
    """Xử Lý Riêng Lỗi CheckFailure (Không Phải Owner). Trả Về True Nếu Đã Xử Lý."""
    if isinstance(error, app_commands.CheckFailure):
        if interaction.response.is_done():
            await interaction.followup.send(
                view=build_setting_error_view("Chỉ Chủ Sở Hữu Bot Mới Được Dùng Lệnh Này."), ephemeral=True
            )
        else:
            await interaction.response.send_message(
                view=build_setting_error_view("Chỉ Chủ Sở Hữu Bot Mới Được Dùng Lệnh Này."), ephemeral=True
            )
        return True
    return False

# Cache Lượt Dùng Của Mỗi Invite: { guild_id: { invite_code: uses } }
invites_cache: dict[int, dict[str, int]] = {}

# Lưu tin nhắn panel confession để xóa khi gửi confession mới
confession_panel_messages: dict[int, int] = {}  # guild_id -> message_id


# ── Lưu Trữ Dữ Liệu (Json Đơn Giản, Không Cần Database) ─────────────────────
def _default_data():
    return {
        "invite_counts": {},    # guild_id -> { user_id -> {regular, left, fake, bonus} }
        "invited_by": {},       # guild_id -> { member_id -> inviter_id }
        "welcome_channel": {},  # guild_id -> channel_id
        "leave_channel": {},    # guild_id -> channel_id
        "invites_channel": {},  # guild_id -> channel_id
        "rules_channel": {},    # guild_id -> channel_id
        "roles_channel": {},    # guild_id -> channel_id
        "intro_channel": {},    # guild_id -> channel_id
        "welcome_role": {},     # guild_id -> role_id (Role Được Ping Trong Tin Nhắn Welcome)
        "confession_channel": {},   # guild_id -> channel_id
        "confession_nickname": {},  # guild_id -> { user_id -> biệt danh }
        "confession_count": {},     # guild_id -> số thứ tự confession đã gửi
        "confession_threads": {},   # guild_id -> { confession_number -> thread_id }
        "visual_channel": {},       # guild_id -> channel_id (Kênh Chỉ Nhận Ảnh/Video)
        "pickrole_channel": {},     # guild_id -> channel_id (Kênh Đăng Panel Pick Role)
    }


def get_welcome_channel_id(data, guild_id):
    """Ưu tiên kênh đặt qua lệnh, nếu không có thì dùng giá trị trong .env."""
    saved = data["welcome_channel"].get(str(guild_id))
    return int(saved) if saved else WELCOME_CHANNEL_ID


def get_leave_channel_id(data, guild_id):
    saved = data["leave_channel"].get(str(guild_id))
    return int(saved) if saved else LEAVE_CHANNEL_ID


def get_invites_channel_id(data, guild_id):
    saved = data["invites_channel"].get(str(guild_id))
    return int(saved) if saved else None


def get_rules_channel_id(data, guild_id):
    saved = data["rules_channel"].get(str(guild_id))
    return int(saved) if saved else None


def get_roles_channel_id(data, guild_id):
    saved = data["roles_channel"].get(str(guild_id))
    return int(saved) if saved else None


def get_intro_channel_id(data, guild_id):
    saved = data["intro_channel"].get(str(guild_id))
    return int(saved) if saved else None


def get_welcome_role_id(data, guild_id):
    saved = data["welcome_role"].get(str(guild_id))
    return int(saved) if saved else None


def get_confession_channel_id(data, guild_id):
    saved = data["confession_channel"].get(str(guild_id))
    return int(saved) if saved else None


def get_confession_nickname(data, guild_id, user_id):
    g = data["confession_nickname"].get(str(guild_id), {})
    return g.get(str(user_id))


def set_confession_nickname(data, guild_id, user_id, nickname: str):
    g = data["confession_nickname"].setdefault(str(guild_id), {})
    g[str(user_id)] = nickname


def next_confession_number(data, guild_id) -> int:
    gid = str(guild_id)
    data["confession_count"][gid] = data["confession_count"].get(gid, 0) + 1
    return data["confession_count"][gid]


def get_confession_thread(data, guild_id, confession_number):
    g = data["confession_threads"].get(str(guild_id), {})
    return g.get(str(confession_number))


def set_confession_thread(data, guild_id, confession_number, thread_id):
    g = data["confession_threads"].setdefault(str(guild_id), {})
    g[str(confession_number)] = thread_id


def get_visual_channel_id(data, guild_id):
    saved = data["visual_channel"].get(str(guild_id))
    return int(saved) if saved else None


def get_pickrole_channel_id(data, guild_id):
    saved = data["pickrole_channel"].get(str(guild_id))
    return int(saved) if saved else None


def load_data():
    with _lock:
        if not os.path.exists(DATA_FILE):
            return _default_data()
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                default = _default_data()
                for k in default:
                    data.setdefault(k, default[k])
                return data
        except (json.JSONDecodeError, FileNotFoundError):
            return _default_data()


def save_data(data):
    with _lock:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def get_user_stats(data, guild_id, user_id):
    g = data["invite_counts"].setdefault(str(guild_id), {})
    return g.setdefault(str(user_id), {"regular": 0, "left": 0, "fake": 0, "bonus": 0})


def total_invites(stats):
    return stats["regular"] + stats["bonus"] - stats["left"] - stats["fake"]


def set_invited_by(data, guild_id, member_id, inviter_id):
    g = data["invited_by"].setdefault(str(guild_id), {})
    g[str(member_id)] = str(inviter_id) if inviter_id else None


def get_invited_by(data, guild_id, member_id):
    g = data["invited_by"].get(str(guild_id), {})
    return g.get(str(member_id))


# ── Hàm Hỗ Trợ ────────────────────────────────────────────────────────────
async def cache_guild_invites(guild: discord.Guild):
    """Lưu Lại Số Lượt Dùng Hiện Tại Của Toàn Bộ Invite Trong 1 Server."""
    try:
        invites = await guild.invites()
    except discord.Forbidden:
        print(f"[!] Thiếu Quyền 'Manage Server' Để Lấy Invites Ở Guild: {guild.name}")
        invites_cache[guild.id] = {}
        return

    invites_cache[guild.id] = {invite.code: invite.uses for invite in invites}

    if "VANITY_URL" in guild.features:
        try:
            vanity = await guild.vanity_invite()
            if vanity:
                invites_cache[guild.id][vanity.code] = vanity.uses
        except (discord.Forbidden, discord.HTTPException):
            pass


def channel_mention_or_fallback(guild: discord.Guild, channel_id, fallback: str) -> str:
    """Trả Về Mention Của Kênh Nếu Đã Đặt Và Còn Tồn Tại, Ngược Lại Trả Về Chữ Mặc Định."""
    if channel_id:
        channel = guild.get_channel(channel_id)
        if channel:
            return channel.mention
    return fallback


def build_intro_view(member: discord.Member) -> discord.ui.LayoutView:
    """Layout Chào Mừng Cho Kênh Intro (Components V2) — CÓ PING ROLE."""
    data = load_data()
    guild = member.guild

    rules_mention = channel_mention_or_fallback(guild, get_rules_channel_id(data, guild.id), "`#RULES`")
    roles_mention = channel_mention_or_fallback(guild, get_roles_channel_id(data, guild.id), "`#ROLES`")
    intro_mention = channel_mention_or_fallback(guild, get_intro_channel_id(data, guild.id), "`#GIỚI-THIỆU`")

    role_id = get_welcome_role_id(data, guild.id)
    role = guild.get_role(role_id) if role_id else None

    items = []

    if role:
        items.append(discord.ui.TextDisplay(f"{role.mention} | 🌟 Có Thành Viên Mới Vừa Gia Nhập!"))
        items.append(discord.ui.Separator())

    title = discord.ui.TextDisplay(f"## 🌟 Chào Mừng Đến Với **{guild.name}**")

    intro = discord.ui.Section(
        discord.ui.TextDisplay(f"### 👋 Xin Chào, {member.mention}!"),
        discord.ui.TextDisplay(
            "Chúng Mình Rất Vui Khi Có Bạn Tham Gia Cộng Đồng!\n"
            "Hãy Cùng Nhau Tạo Ra Những Kỷ Niệm Thật Vui Vẻ Nhé! 🎮"
        ),
        accessory=discord.ui.Thumbnail(media=member.display_avatar.url),
    )

    guide = discord.ui.TextDisplay(
        f"> 📖 Đọc Nội Quy Tại {rules_mention}\n"
        f"> 🎭 Nhận Vai Trò Tại {roles_mention}\n"
        f"> 💬 Giới Thiệu Bản Thân Tại {intro_mention}"
    )

    joined = discord.utils.format_dt(member.joined_at or discord.utils.utcnow(), style="R")
    footer = discord.ui.TextDisplay(
        f"-# 🆔 Thành Viên Thứ #{member.guild.member_count}  •  🕒 Tham Gia {joined}"
    )

    items.extend([
        title,
        discord.ui.Separator(spacing=discord.SeparatorSpacing.large),
        intro,
        discord.ui.Separator(),
        guide,
        discord.ui.Separator(),
        footer,
    ])

    view = discord.ui.LayoutView(timeout=None)
    view.add_item(
        discord.ui.Container(
            *items,
            accent_color=discord.Color.teal(),
        )
    )
    return view


def build_welcome_view(member: discord.Member) -> discord.ui.LayoutView:
    """Layout Chào Mừng (Components V2) — Phong Cách Cyberspace. Ping Role Nằm Ở Đây."""
    data = load_data()
    guild = member.guild

    rules_mention = channel_mention_or_fallback(guild, get_rules_channel_id(data, guild.id), "`#RULES`")
    roles_mention = channel_mention_or_fallback(guild, get_roles_channel_id(data, guild.id), "`#ROLES`")
    intro_mention = channel_mention_or_fallback(guild, get_intro_channel_id(data, guild.id), "`#GIỚI-THIỆU`")

    role_id = get_welcome_role_id(data, guild.id)
    role = guild.get_role(role_id) if role_id else None

    items = []

    if role:
        items.append(discord.ui.TextDisplay(f"{role.mention} | 📣 Có Thành Viên Mới Vừa Gia Nhập!"))
        items.append(discord.ui.Separator())

    title = discord.ui.TextDisplay(f"## 🪐 Chào Mừng Đến Với **{guild.name}**")

    intro = discord.ui.Section(
        discord.ui.TextDisplay(f"### 👋 Xin Chào, {member.mention}!"),
        discord.ui.TextDisplay(
            "Bạn Vừa Kết Nối Thành Công Vào Hệ Thống.\n"
            "Hãy Dành Chút Thời Gian Làm Quen Với Server Nhé!"
        ),
        accessory=discord.ui.Thumbnail(media=member.display_avatar.url),
    )

    guide = discord.ui.TextDisplay(
        f"> 📖 Đọc Nội Quy Tại {rules_mention}\n"
        f"> 🎭 Nhận Vai Trò Tại {roles_mention}\n"
        f"> 💬 Giới Thiệu Bản Thân Tại {intro_mention}"
    )

    joined = discord.utils.format_dt(member.joined_at or discord.utils.utcnow(), style="R")
    footer = discord.ui.TextDisplay(
        f"-# 🆔 Thành Viên Thứ #{member.guild.member_count}  •  🕒 Tham Gia {joined}"
    )

    items.extend([
        title,
        discord.ui.Separator(spacing=discord.SeparatorSpacing.large),
        intro,
        discord.ui.Separator(),
        guide,
        discord.ui.Separator(),
        footer,
    ])

    view = discord.ui.LayoutView(timeout=None)
    view.add_item(
        discord.ui.Container(
            *items,
            accent_color=discord.Color.green(),
        )
    )
    return view


def build_invite_log_view(member: discord.Member, inviter, invite_code, is_fake: bool) -> discord.ui.LayoutView:
    """Layout Riêng Cho Kênh Invites — Nhiều Section, Rõ Ràng, Đẹp Mắt."""
    data = load_data()
    stats = get_user_stats(data, member.guild.id, inviter.id) if inviter else None

    title = discord.ui.TextDisplay("## ⚡ Kết Nối Mới Qua Lời Mời")

    intro = discord.ui.Section(
        discord.ui.TextDisplay(f"### 📥 {member.mention} Vừa Tham Gia"),
        discord.ui.TextDisplay(
            f"Được Mời Bởi {inviter.mention}!" if inviter else "Không Xác Định Người Mời."
        ),
        accessory=discord.ui.Thumbnail(media=member.display_avatar.url),
    )

    items = [title, discord.ui.Separator(spacing=discord.SeparatorSpacing.large), intro, discord.ui.Separator()]

    if inviter and stats is not None:
        total = total_invites(stats)
        items.append(
            discord.ui.TextDisplay(
                f"> 🔗 Mã Mời: `{invite_code}`\n"
                f"> 🏆 Tổng Lượt Mời Của {inviter.mention}: **{total}** Lượt"
            )
        )
    else:
        items.append(
            discord.ui.TextDisplay(
                "> ❓ Có Thể Qua Link Vanity, Invite Tạm Thời, Hoặc Bot Thiếu Quyền."
            )
        )

    if is_fake:
        items.append(discord.ui.Separator())
        items.append(
            discord.ui.TextDisplay("> ⚠️ **Cảnh Báo:** Tài Khoản Này Vừa Được Tạo Gần Đây, Có Thể Là Invite Ảo.")
        )

    view = discord.ui.LayoutView(timeout=None)
    view.add_item(discord.ui.Container(*items, accent_color=discord.Color.blurple()))
    return view


def build_leave_view(member: discord.Member) -> discord.ui.LayoutView:
    """Layout Log Khi Thành Viên Rời Server — Nhiều Section, Đẹp Mắt."""
    title = discord.ui.TextDisplay("## 🔌 Mất Kết Nối")

    intro = discord.ui.Section(
        discord.ui.TextDisplay(f"### 📤 {member} Đã Rời **{member.guild.name}**"),
        discord.ui.TextDisplay("Tín Hiệu Đã Mất. Hẹn Gặp Lại Bạn Ở Lần Đăng Nhập Tiếp Theo!"),
        accessory=discord.ui.Thumbnail(media=member.display_avatar.url),
    )

    now = discord.utils.format_dt(discord.utils.utcnow(), style="R")
    footer = discord.ui.TextDisplay(
        f"-# 🆔 ID: {member.id}  •  🕒 Rời Đi {now}  •  👥 Còn Lại **{member.guild.member_count}** Thành Viên"
    )

    view = discord.ui.LayoutView(timeout=None)
    view.add_item(
        discord.ui.Container(
            title,
            discord.ui.Separator(spacing=discord.SeparatorSpacing.large),
            intro,
            discord.ui.Separator(),
            footer,
            accent_color=discord.Color.red(),
        )
    )
    return view


def build_invites_stats_view(target: discord.abc.User, stats: dict) -> discord.ui.LayoutView:
    """Layout Thống Kê Lượt Mời Cho Lệnh /invites."""
    total = total_invites(stats)
    section = discord.ui.Section(
        discord.ui.TextDisplay(f"## 📊 Thống Kê Lượt Mời Của {target.display_name}"),
        discord.ui.TextDisplay(f"**Tổng Lượt Mời:** {total}"),
        accessory=discord.ui.Thumbnail(media=target.display_avatar.url),
    )
    detail = discord.ui.TextDisplay(
        f"**Hợp Lệ:** {stats['regular']}\n"
        f"**Thưởng:** {stats['bonus']}\n"
        f"**Đã Rời Đi:** {stats['left']}\n"
        f"**Nghi Vấn Ảo:** {stats['fake']}"
    )
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(discord.ui.Container(section, discord.ui.Separator(), detail, accent_color=discord.Color.blurple()))
    return view


def build_leaderboard_view(lines: list[str]) -> discord.ui.LayoutView:
    """Layout Bảng Xếp Hạng Cho Lệnh /invite-leaderboard."""
    text = discord.ui.TextDisplay("## 🏆 Bảng Xếp Hạng Invite\n" + "\n".join(lines))
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(discord.ui.Container(text, accent_color=discord.Color.gold()))
    return view


# ── Components V2 Cho Các Lệnh Cấu Hình (/set-...) Và /settings ──────────
def build_setting_confirm_view(
    emoji: str,
    label: str,
    channel: discord.TextChannel,
    extra_lines: list[str] | None = None,
) -> discord.ui.LayoutView:
    """Layout (Components V2) Xác Nhận Sau Khi Đặt 1 Hoặc Nhiều Kênh Cấu Hình."""
    section = discord.ui.Section(
        discord.ui.TextDisplay(f"## {emoji} Đã Cập Nhật Cài Đặt"),
        discord.ui.TextDisplay(f"Kênh **{label}** Đã Được Đặt Thành {channel.mention}."),
        accessory=discord.ui.Thumbnail(media=channel.guild.icon.url) if channel.guild.icon else discord.ui.Thumbnail(media=bot.user.display_avatar.url),
    )

    items = [section, discord.ui.Separator()]

    if extra_lines:
        items.append(discord.ui.TextDisplay("**Đã Cập Nhật Thêm:**\n" + "\n".join(extra_lines)))
        items.append(discord.ui.Separator())

    items.append(discord.ui.TextDisplay("-# Dùng `/settings` Để Xem Toàn Bộ Cài Đặt Hiện Tại."))

    view = discord.ui.LayoutView(timeout=None)
    view.add_item(discord.ui.Container(*items, accent_color=discord.Color.green()))
    return view


def build_ping_view(latency: float) -> discord.ui.LayoutView:
    """Layout (Components V2) Cho Lệnh /ping."""
    ms = round(latency * 1000)
    if ms < 150:
        status = "🟢 Tuyệt Vời"
    elif ms < 300:
        status = "🟡 Ổn Định"
    else:
        status = "🔴 Chậm"

    text = discord.ui.TextDisplay(
        f"## 🏓 Pong!\n"
        f"> ⏱️ Độ Trễ: **{ms}ms**\n"
        f"> 📶 Trạng Thái: {status}"
    )
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(discord.ui.Container(text, accent_color=discord.Color.blurple()))
    return view


def build_setting_error_view(message: str) -> discord.ui.LayoutView:
    """Layout (Components V2) Báo Lỗi Cho Các Lệnh Cấu Hình."""
    text = discord.ui.TextDisplay(f"## ❌ Có Lỗi Xảy Ra\n{message}")
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(discord.ui.Container(text, accent_color=discord.Color.red()))
    return view


def build_settings_view(guild: discord.Guild, data: dict) -> discord.ui.LayoutView:
    """Layout (Components V2) Tổng Hợp Toàn Bộ Kênh Đã Cấu Hình Cho /settings."""

    def fmt(channel_id):
        if not channel_id:
            return "❌ Chưa Đặt"
        channel = guild.get_channel(int(channel_id))
        return channel.mention if channel else "⚠️ Kênh Không Tồn Tại"

    def fmt_role(role_id):
        if not role_id:
            return "❌ Chưa Đặt"
        role = guild.get_role(int(role_id))
        return role.mention if role else "⚠️ Role Không Tồn Tại"

    header = discord.ui.Section(
        discord.ui.TextDisplay(f"## ⚙️ Cài Đặt Hiện Tại — {guild.name}"),
        discord.ui.TextDisplay("Danh Sách Các Kênh Đã Được Cấu Hình Cho Server Này."),
        accessory=discord.ui.Thumbnail(media=guild.icon.url) if guild.icon else discord.ui.Thumbnail(media=bot.user.display_avatar.url),
    )

    body = discord.ui.TextDisplay(
        f"> 🌟 **Intro:** {fmt(get_intro_channel_id(data, guild.id))}\n"
        f"> 👋 **Welcome:** {fmt(get_welcome_channel_id(data, guild.id))}\n"
        f"> 🔌 **Leave:** {fmt(get_leave_channel_id(data, guild.id))}\n"
        f"> ⚡ **Invites Log:** {fmt(get_invites_channel_id(data, guild.id))}\n"
        f"> 📖 **Rules:** {fmt(get_rules_channel_id(data, guild.id))}\n"
        f"> 🎭 **Roles:** {fmt(get_roles_channel_id(data, guild.id))}\n"
        f"> 📣 **Welcome Role Ping:** {fmt_role(get_welcome_role_id(data, guild.id))}\n"
        f"> ❤️ **Confession:** {fmt(get_confession_channel_id(data, guild.id))}\n"
        f"> 📸 **Visual-Check (Ảnh/Video):** {fmt(get_visual_channel_id(data, guild.id))}\n"
        f"> 🎭 **Pick Role:** {fmt(get_pickrole_channel_id(data, guild.id))}"
    )

    footer = discord.ui.TextDisplay(
        "-# Dùng `/set-welcome-channel` (Kèm Tùy Chọn Rules/Roles/Giới Thiệu/Role), "
        "`/set-leave-channel`, `/set-invites-channel`, `/set-confession-channel`, "
        "`/set-visual-channel`, `/set-pickrole-channel` Để Thay Đổi."
    )

    view = discord.ui.LayoutView(timeout=None)
    view.add_item(
        discord.ui.Container(
            header,
            discord.ui.Separator(spacing=discord.SeparatorSpacing.large),
            body,
            discord.ui.Separator(),
            footer,
            accent_color=discord.Color.blurple(),
        )
    )
    return view


# ── Confession System (Components V2 + Modal + Nút Bấm Bền Vững) ───────────
def build_simple_info_view(emoji: str, message: str, color: discord.Color = discord.Color.green()) -> discord.ui.LayoutView:
    """Layout (Components V2) Thông Báo Đơn Giản 1 Dòng."""
    text = discord.ui.TextDisplay(f"## {emoji} {message}")
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(discord.ui.Container(text, accent_color=color))
    return view


def build_confession_panel_container(guild_name: str) -> discord.ui.Container:
    """Nội Dung Panel Confession (Dùng Chung Cho View Bền Vững)."""
    header = discord.ui.TextDisplay(f"## 💌 Góc Tâm Sự — **{guild_name}**")

    welcome = discord.ui.TextDisplay(
        "🕯️ **Chào Mừng Bạn Đến Với Góc Tâm Sự!**\n\n"
        "Nơi Bạn Có Thể Trút Bỏ Những Nỗi Niềm Thầm Kín, Gửi Gắm Lời Yêu Thương Ngọt "
        "Ngào Hay Những Lời Xin Lỗi Chưa Dám Ngỏ. Bạn Có Thể Chọn Gửi Ẩn Danh Hoặc "
        "Công Khai Tùy Thích!"
    )

    rules = discord.ui.TextDisplay(
        "> ⚠️ **Hướng Dẫn & Nguyên Tắc**\n"
        "> 🎭 **Gửi Ẩn Danh:** Câu Chuyện Được Bảo Mật, Chỉ Hiện Biệt Danh (Nếu Đặt) Hoặc \"Ẩn Danh\".\n"
        "> 📢 **Gửi Công Khai:** Confession Sẽ Ping Thẳng Tên Và Ảnh Đại Diện Thật Của Bạn.\n"
        "> 🚫 Nghiêm Cấm Nội Dung Đả Kích Cá Nhân, Thô Tục, Xúc Phạm Tôn Giáo, Chính Trị "
        "Hoặc Vi Phạm Luật Chung Của Server.\n"
        "> 💫 Hãy Cùng Nhau Lan Tỏa Những Câu Chuyện Ấm Áp Và Năng Lượng Tích Cực Nhé!"
    )

    footer = discord.ui.TextDisplay("-# 👇 Nhấn Nút Tương Ứng Bên Dưới Để Viết Confession")

    buttons = discord.ui.ActionRow(
        ConfessionAnonButton(),
        ConfessionPublicButton(),
        ConfessionNicknameButton(),
    )

    return discord.ui.Container(
        header,
        discord.ui.Separator(spacing=discord.SeparatorSpacing.large),
        welcome,
        discord.ui.Separator(),
        rules,
        discord.ui.Separator(),
        footer,
        buttons,
        accent_color=discord.Color.green(),
    )


# Ảnh Placeholder Màu Đen Tuyền — Dùng Làm Thumbnail Khi Gửi Confession Ẩn Danh
ANONYMOUS_THUMBNAIL_URL = "https://placehold.co/128x128/000000/000000.png"


def build_visual_panel_container(guild_name: str) -> discord.ui.Container:
    """Nội Dung Panel Kênh Chia Sẻ Ảnh & Video."""
    header = discord.ui.TextDisplay(f"## 📸 Kênh Chia Sẻ Ảnh & Video")

    welcome = discord.ui.TextDisplay(
        "🎨 **Chào Mừng Đến Kênh Chia Sẻ Ảnh & Video!**\n\n"
        "🎬 Đây Là Nơi Để Mọi Người Chia Sẻ Những Khoảnh Khắc Đẹp, Video Thú Vị!"
    )

    rules = discord.ui.TextDisplay(
        "> ⚠️ **Quy Tắc:**\n"
        "> 📸 Chỉ Gửi Ảnh Hoặc Video Vào Kênh Này.\n"
        "> 💬 Vui Lòng Bình Luận Trong Thread Của Ảnh/Video.\n"
        "> 🧵 Thread Sẽ Được Tạo Tự Động Khi Bạn Gửi Ảnh/Video.\n"
        "> ❌ Không Gửi Tin Nhắn Văn Bản Đơn Thuần (Không Có Ảnh/Video)."
    )

    footer = discord.ui.TextDisplay("-# ❤️ Hãy Tương Tác & Bình Luận Trong Thread Nhé!")

    return discord.ui.Container(
        header,
        discord.ui.Separator(spacing=discord.SeparatorSpacing.large),
        welcome,
        discord.ui.Separator(),
        rules,
        discord.ui.Separator(),
        footer,
        accent_color=discord.Color.purple(),
    )


# ── Pick Role — Chọn Role Theo Nhóm Bằng Dropdown (Chỉnh Sửa Trực Tiếp Ở Đây) ─
PICKROLE_BANNER_URL = "https://i.imgur.com/8xQ2sJ1.png"  # Đổi Link Banner "PICK ROLE" Nếu Muốn

# ── Pick Role — Chọn Role Theo Nhóm Bằng Nút Bấm (Chỉnh Sửa Trực Tiếp Ở Đây) ─
PICKROLE_BANNER_URL = "https://i.imgur.com/8xQ2sJ1.png"  # Đổi Link Banner "PICK ROLE" Nếu Muốn

# LƯU Ý: "role_id" Là ID Thật Của Role Trong Server (Lấy Từ `/debug-server`).
# Match Theo ID Chính Xác Tuyệt Đối, Không Sợ Bị Lỗi Nếu Role Có Tên Kiểu Chữ Đặc
# Biệt (In Đậm Unicode...) Hoặc Sau Này Đổi Tên Role.
PICKROLE_GROUPS = [
    {
        "label": "Giới Tính Của Bạn Là Gì?",
        "multi_select": True,
        "options": [
            {"label": "Cyber Boy", "emoji": "<:Boy:1540036279431856179>", "role_id": 1540030835514806374},
            {"label": "Cyber Girl", "emoji": "<:Girl:1540036350353477764>", "role_id": 1540031029438582814},
            {"label": "Cyber Soul", "emoji": "<a:Soul:1540036402073305198>", "role_id": 1540031034219958333},
        ],
    },
    {
        "label": "Game Bạn Thường Hay Chơi Là Gì?",
        "multi_select": True,
        "options": [
            {"label": "Free Fire", "emoji": "<:freefire33:1540018282810179805>", "role_id": 1540029017263046816},
            {"label": "Liên Quân", "emoji": "<:aov98:1540018262278938684>", "role_id": 1540030469675028481},
            {"label": "Valorant", "emoji": "<:valorant:1540018328054005760>", "role_id": 1540030131966574714},
            {"label": "PUBG", "emoji": "<:pubg:1540018361641996388>", "role_id": 1540030240515035307},
            {"label": "Roblox", "emoji": "<:roblox:1540014226431545386>", "role_id": 1540030234412322929},
            {"label": "TFT/LOL", "emoji": "<:3873_league_of_legends_logo:1540018242062647356>", "role_id": 1540030534028099584},
            {"label": "Game Khác", "emoji": "<:steam7:1540018308806484070>", "role_id": 1540030354914541709},
        ],
    },
    {
        "label": "Bạn Có Người Yêu Chưa?",
        "multi_select": False,
        "options": [
            {"label": "Chưa Có", "emoji": "<a:no:1540040792821866596>", "role_id": 1540039884625158164},
            {"label": "Có Rùiii", "emoji": "<a:ohhyes:1540040773083332818>", "role_id": 1540039895387602996},
            {"label": "Đang Kiếm Nghệ", "emoji": "<:frogyes:1540040899520761927>", "role_id": 1540040086383497306},
        ],
    },
    {
        "label": "Bạn Có Muốn Nhận Thông Báo Từ Server Này Không?",
        "multi_select": True,
        "options": [
            {"label": "Ping Event", "emoji": "<:event:1540039571918684213>", "role_id": 1540040113604665445},
            {"label": "Ping Giveaways", "emoji": "<a:giveawayntexe59:1540041594298957965>", "role_id": 1540040213068382278},
            {"label": "Không Ping", "emoji": "<a:pingrage:1540039280515354844>", "role_id": 1540040272728301668},
        ],
    },
]


def build_pickrole_panel_container(guild: discord.Guild) -> discord.ui.Container:
    """Nội Dung Panel Pick Role — Banner + Mô Tả + Nút Bấm Chọn Role Theo Nhóm."""
    items: list = []

    if PICKROLE_BANNER_URL:
        items.append(discord.ui.MediaGallery(discord.MediaGalleryItem(media=PICKROLE_BANNER_URL)))

    items.append(
        discord.ui.TextDisplay(
            "Đây Là Nơi Để Bạn Tự Do Chọn Những Role Thể Hiện Cá Tính, Sở Thích Và Cả "
            "Vùng Miền Của Mình.\nChọn Xong Rồi Thì Mọi Người Sẽ Dễ Dàng Kết Nối, Làm "
            "Quen Với Bạn Hơn Đó! ⭐"
        )
    )
    items.append(discord.ui.Separator())

    for i, group in enumerate(PICKROLE_GROUPS, start=1):
        items.append(discord.ui.TextDisplay(f"**{i}️⃣ {group['label']}**"))

        buttons = [
            PickRoleButton(
                group_index=i,
                option_label=opt["label"],
                role_id=opt["role_id"],
                emoji=opt["emoji"],
            )
            for opt in group["options"]
        ]
        # Discord Giới Hạn Tối Đa 5 Nút / ActionRow -> Tự Chia Thành Nhiều Hàng
        for row_start in range(0, len(buttons), 5):
            items.append(discord.ui.ActionRow(*buttons[row_start:row_start + 5]))

        if i < len(PICKROLE_GROUPS):
            items.append(discord.ui.Separator())

    items.append(discord.ui.Separator())
    items.append(
        discord.ui.TextDisplay("-# 👉 Chỉ Cần Bấm Vào Nút Bên Trên Là Có Role Ngay. Thử Pick Vài Cái Cho Vui Nhé! ⭐")
    )

    return discord.ui.Container(*items, accent_color=discord.Color.from_str("#f7b7c8"))


def build_confession_post_view(
    guild_name: str,
    number: int,
    content: str,
    anonymous: bool,
    member: discord.Member | None = None,
    nickname: str | None = None,
    target_name: str | None = None,
) -> discord.ui.LayoutView:
    """Layout (Components V2) Cho 1 Confession — Kèm Thumbnail (Avatar Hoặc Ảnh Đen Nếu Ẩn Danh)."""

    # Người Gửi + Thumbnail
    # - Ẩn Danh: Hiện Biệt Danh Nếu Đã Đặt (Không Lộ Danh Tính Thật), Mặc Định "Ẩn Danh".
    # - Công Khai: Luôn Ping Thật + Kèm Username Trong Ngoặc, Không Dùng Biệt Danh.
    if anonymous:
        anon_label = nickname or "Ẩn Danh"
        sender_text = discord.ui.TextDisplay(f"🕵️ **Người Gửi:** {anon_label}")
        thumbnail = discord.ui.Thumbnail(media=ANONYMOUS_THUMBNAIL_URL)
    else:
        sender_text = discord.ui.TextDisplay(f"👤 **Người Gửi:** {member.mention} (`{member.name}`)")
        thumbnail = discord.ui.Thumbnail(media=member.display_avatar.url)

    header_section = discord.ui.Section(
        discord.ui.TextDisplay(f"## 💌 Góc Tâm Sự — **{guild_name}**"),
        discord.ui.TextDisplay(f"**#Confession {number}**"),
        accessory=thumbnail,
    )

    content_display = discord.ui.TextDisplay(f"💌 **Tâm Sự**\n> 💬 {content}")

    if target_name:
        target = discord.ui.TextDisplay(f"💝 **Gửi Đến / Ký Tên:** {target_name}")
    else:
        target = discord.ui.TextDisplay("💝 **Gửi Đến / Ký Tên:** Không Có")

    now = discord.utils.utcnow()
    time_display = discord.ui.TextDisplay(f"🕒 **Thời Gian:** {now.strftime('%H:%M:%S %d/%m/%Y')}")

    footer = discord.ui.TextDisplay("-# 💚 Hãy Tôn Trọng, Chia Sẻ Và Lan Tỏa Yêu Thương Cùng Nhau Nhé!")

    reply_button = discord.ui.ActionRow(ConfessionReplyButton(number))

    view = discord.ui.LayoutView(timeout=None)
    view.add_item(
        discord.ui.Container(
            header_section,
            discord.ui.Separator(spacing=discord.SeparatorSpacing.large),
            content_display,
            discord.ui.Separator(),
            sender_text,
            target,
            time_display,
            discord.ui.Separator(),
            footer,
            discord.ui.Separator(),
            reply_button,
            accent_color=discord.Color.green(),
        )
    )
    return view


class PickRoleButton(discord.ui.Button):
    """Nút Bấm Gán/Gỡ 1 Role Có Sẵn Trong Server (Tìm Theo ID, Không Tự Tạo Role)."""

    def __init__(self, group_index: int, option_label: str, role_id: int, emoji: str):
        super().__init__(
            label=option_label,
            emoji=emoji,
            style=discord.ButtonStyle.secondary,
            custom_id=f"pickrole_btn_{group_index}_{option_label}",
        )
        self.group_index = group_index
        self.role_id = role_id
        self.option_label = option_label

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        member = interaction.user

        role = guild.get_role(self.role_id)
        if role is None:
            await interaction.response.send_message(
                view=build_setting_error_view(
                    f"Không Tìm Thấy Role Với ID `{self.role_id}` (**{self.option_label}**) Trong Server. "
                    "Role Có Thể Đã Bị Xóa."
                ),
                ephemeral=True,
            )
            return

        group = PICKROLE_GROUPS[self.group_index - 1]

        try:
            if role in member.roles:
                await member.remove_roles(role, reason="Bỏ Chọn Pick Role")
                message = f"➖ Đã Gỡ Role **{self.option_label}**."
            else:
                # Nhóm Chỉ-Chọn-1 (multi_select=False) -> Gỡ Các Role Khác Cùng Nhóm Trước
                if not group.get("multi_select", True):
                    for opt in group["options"]:
                        if opt["role_id"] == self.role_id:
                            continue
                        other_role = guild.get_role(opt["role_id"])
                        if other_role and other_role in member.roles:
                            await member.remove_roles(other_role, reason="Đổi Lựa Chọn Pick Role")

                await member.add_roles(role, reason="Pick Role")
                message = f"✅ Đã Thêm Role **{self.option_label}**."
        except discord.Forbidden:
            await interaction.response.send_message(
                view=build_setting_error_view("Bot Không Đủ Quyền Để Gán/Gỡ Role Này (Kiểm Tra Vị Trí Role Của Bot)."),
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            view=build_simple_info_view("🎭", message, discord.Color.green()),
            ephemeral=True,
        )


class ConfessionReplyModal(discord.ui.Modal):
    """Form Trả Lời Ẩn Danh Cho Confession."""

    def __init__(self, confession_number: int):
        super().__init__(title=f"💚 Trả Lời Confession #{confession_number}")
        self.confession_number = confession_number
        
        self.reply_input = discord.ui.TextInput(
            label="💬 Nội Dung Trả Lời",
            style=discord.TextStyle.paragraph,
            placeholder="Nhập Câu Trả Lời Của Bạn...",
            max_length=1500,
            required=True,
            min_length=10,
        )
        self.add_item(self.reply_input)

    async def on_submit(self, interaction: discord.Interaction):
        data = load_data()
        guild = interaction.guild
        
        # Lấy thread ID từ data
        thread_id = get_confession_thread(data, guild.id, self.confession_number)
        
        if not thread_id:
            await interaction.response.send_message(
                view=build_setting_error_view("Không Tìm Thấy Thread Cho Confession Này."),
                ephemeral=True,
            )
            return
        
        # Lấy thread
        thread = guild.get_thread(thread_id)
        if not thread:
            await interaction.response.send_message(
                view=build_setting_error_view("Thread Đã Bị Xóa Hoặc Không Tồn Tại."),
                ephemeral=True,
            )
            return
        
        # Gửi reply ẩn danh vào thread
        await thread.send(f"> **🕵️ Ẩn Danh:**\n> {self.reply_input.value}")
        
        await interaction.response.send_message(
            view=build_simple_info_view(
                "✅", f"Đã Gửi Câu Trả Lời Ẩn Danh Cho Confession #{self.confession_number}! 💌", discord.Color.green()
            ),
            ephemeral=True,
        )


class ConfessionReplyButton(discord.ui.Button):
    """Nút Trả Lời Ẩn Danh Cho Confession."""

    def __init__(self, confession_number: int):
        super().__init__(
            label="💬 Trả Lời Ẩn Danh",
            style=discord.ButtonStyle.green,
            custom_id=f"confession_reply_{confession_number}",
        )
        self.confession_number = confession_number

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ConfessionReplyModal(self.confession_number))


class ConfessionModal(discord.ui.Modal):
    """Form Nhập Nội Dung Confession (Ẩn Danh Hoặc Công Khai)."""

    def __init__(self, anonymous: bool):
        title_text = "💚 Gửi Confession Ẩn Danh" if anonymous else "💚 Gửi Confession Công Khai"
        super().__init__(title=title_text)
        self.anonymous = anonymous
        
        # Nội dung confession
        self.content_input = discord.ui.TextInput(
            label="📝 Nội Dung Tâm Sự",
            style=discord.TextStyle.paragraph,
            placeholder="Nhập Những Câu Chuyện, Lời Nhắn Nhủ Thầm Kín Của Bạn Ở Đây...",
            max_length=1500,
            required=True,
            min_length=10,
        )
        self.add_item(self.content_input)
        
        # Tên người nhận hoặc biệt danh ký tên
        self.target_input = discord.ui.TextInput(
            label="💌 Gửi Đến Ai Hoặc Biệt Danh Ký Tên (Tùy Chọn)",
            style=discord.TextStyle.short,
            placeholder="Ví Dụ: Crush 12A3, Bé Thỏ, Hoặc Bỏ Trống Để Ẩn Danh Hoàn Toàn",
            max_length=100,
            required=False,
        )
        self.add_item(self.target_input)

    async def on_submit(self, interaction: discord.Interaction):
        # Defer Ngay Lập Tức — Tránh Timeout 3 Giây Của Discord Vì Phía Dưới
        # Có Nhiều Thao Tác Nặng (Gửi Tin, Tạo Thread, Gửi Lại Panel...).
        await interaction.response.defer(ephemeral=True)

        data = load_data()
        guild = interaction.guild
        channel_id = get_confession_channel_id(data, guild.id)
        channel = guild.get_channel(channel_id) if channel_id else None

        if not channel:
            await interaction.followup.send(
                view=build_simple_info_view(
                    "❌", "Kênh Confession Chưa Được Thiết Lập. Vui Lòng Báo Admin.", discord.Color.green()
                ),
                ephemeral=True,
            )
            return

        number = next_confession_number(data, guild.id)
        
        # Lấy biệt danh đã đặt (nếu có)
        nickname = get_confession_nickname(data, guild.id, interaction.user.id)
        target_name = self.target_input.value if self.target_input.value else None

        # Tạo view confession
        view = build_confession_post_view(
            guild.name,
            number, 
            self.content_input.value, 
            self.anonymous, 
            interaction.user, 
            nickname,
            target_name
        )

        try:
            # Xóa tin nhắn panel cũ nếu có
            if guild.id in confession_panel_messages:
                try:
                    old_msg = await channel.fetch_message(confession_panel_messages[guild.id])
                    await old_msg.delete()
                except (discord.NotFound, discord.HTTPException):
                    pass
                del confession_panel_messages[guild.id]
            
            # Gửi Confession Với View (Cho Phép Ping User Thật Khi Công Khai, Không Ping Role/Everyone)
            confession_msg = await channel.send(
                view=view,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
            
            # Tạo thread cho confession
            thread = await confession_msg.create_thread(
                name=f"💬 Trả Lời Confession #{number}",
                auto_archive_duration=60,
            )
            
            # Lưu thread ID
            set_confession_thread(data, guild.id, number, thread.id)
            
            # Gửi tin nhắn hướng dẫn trong thread
            await thread.send("**💚 Chào Mừng Bạn Đến Với Thread Trả Lời Confession!**\n"
                              "Hãy Chia Sẻ Cảm Nghĩ Của Bạn Về Confession Này Một Cách Văn Minh Và Tôn Trọng Nhé!")
            
            # Gửi lại panel mới
            panel_container = build_confession_panel_container(guild.name)
            panel_view = discord.ui.LayoutView(timeout=None)
            panel_view.add_item(panel_container)
            panel_msg = await channel.send(view=panel_view)
            confession_panel_messages[guild.id] = panel_msg.id
            
        except discord.HTTPException as e:
            await interaction.followup.send(
                view=build_setting_error_view(f"Gửi Confession Thất Bại: {e}"),
                ephemeral=True,
            )
            save_data(data)
            return

        save_data(data)

        # Gửi Response Thành Công (Interaction Đã Được Defer Ở Trên)
        await interaction.followup.send(
            view=build_simple_info_view(
                "✅", f"Đã Gửi Confession #{number}! Cảm Ơn Bạn Đã Chia Sẻ 💌", discord.Color.green()
            ),
            ephemeral=True,
        )


class ConfessionNicknameModal(discord.ui.Modal):
    """Form Đặt Biệt Danh Hiển Thị Khi Gửi Confession Ẩn Danh."""

    def __init__(self, current_nickname: str | None = None):
        super().__init__(title="💚 Thiết Lập Biệt Danh")
        self.nickname_input = discord.ui.TextInput(
            label="🏷️ Biệt Danh (Để Trống Để Xóa)",
            placeholder="Ví Dụ: Bé Thỏ, Crush 12A3, Mèo Ú...",
            max_length=32,
            required=False,
            default=current_nickname,
        )
        self.add_item(self.nickname_input)

    async def on_submit(self, interaction: discord.Interaction):
        data = load_data()
        if self.nickname_input.value:
            set_confession_nickname(data, interaction.guild_id, interaction.user.id, self.nickname_input.value)
            message = f"Biệt Danh Của Bạn Đã Được Đặt Thành **{self.nickname_input.value}**."
        else:
            # Xóa biệt danh
            g = data["confession_nickname"].setdefault(str(interaction.guild_id), {})
            g.pop(str(interaction.user.id), None)
            message = "Đã Xóa Biệt Danh Của Bạn."
        
        save_data(data)
        await interaction.response.send_message(
            view=build_simple_info_view("⚙️", message, discord.Color.green()),
            ephemeral=True,
        )


class ConfessionAnonButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="🎭 Gửi Ẩn Danh",
            style=discord.ButtonStyle.green,
            custom_id="confession_anon_btn",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ConfessionModal(anonymous=True))


class ConfessionPublicButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="📢 Gửi Công Khai",
            style=discord.ButtonStyle.blurple,
            custom_id="confession_public_btn",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ConfessionModal(anonymous=False))


class ConfessionNicknameButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="⚙️ Cài Đặt Biệt Danh",
            style=discord.ButtonStyle.gray,
            custom_id="confession_nickname_btn",
        )

    async def callback(self, interaction: discord.Interaction):
        data = load_data()
        current_nickname = get_confession_nickname(data, interaction.guild_id, interaction.user.id)
        await interaction.response.send_modal(ConfessionNicknameModal(current_nickname=current_nickname))


# ── Sự Kiện ───────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"✅ Đã Đăng Nhập Với Tên {bot.user} (ID: {bot.user.id})")
    for guild in bot.guilds:
        await cache_guild_invites(guild)
    
    # Đăng ký các view bền vững
    for guild in bot.guilds:
        panel_container = build_confession_panel_container(guild.name)
        panel_view = discord.ui.LayoutView(timeout=None)
        panel_view.add_item(panel_container)
        bot.add_view(panel_view)

        pickrole_view = discord.ui.LayoutView(timeout=None)
        pickrole_view.add_item(build_pickrole_panel_container(guild))
        bot.add_view(pickrole_view)
    
    # Lưu lại tin nhắn panel confession cho các server
    data = load_data()
    for guild in bot.guilds:
        channel_id = get_confession_channel_id(data, guild.id)
        if channel_id:
            channel = guild.get_channel(channel_id)
            if channel:
                try:
                    async for msg in channel.history(limit=50):
                        if msg.author == bot.user and msg.components:
                            confession_panel_messages[guild.id] = msg.id
                            break
                except (discord.HTTPException, discord.Forbidden):
                    pass
    
    try:
        synced = await bot.tree.sync()
        print(f"✅ Đã Đồng Bộ {len(synced)} Slash Command.")
    except Exception as e:
        print(f"[!] Lỗi Đồng Bộ Slash Command: {e}")
    print("🚀 Bot Đã Sẵn Sàng.")


@bot.event
async def on_guild_join(guild: discord.Guild):
    await cache_guild_invites(guild)


@bot.event
async def on_invite_create(invite: discord.Invite):
    invites_cache.setdefault(invite.guild.id, {})[invite.code] = invite.uses


@bot.event
async def on_invite_delete(invite: discord.Invite):
    invites_cache.get(invite.guild.id, {}).pop(invite.code, None)


@bot.event
async def on_member_join(member: discord.Member):
    guild = member.guild
    inviter = None
    used_code = None
    is_fake = False

    old_invites = invites_cache.get(guild.id, {})

    try:
        new_invites = await guild.invites()
    except discord.Forbidden:
        new_invites = []

    new_invites_map = {inv.code: inv.uses for inv in new_invites}

    for invite in new_invites:
        if invite.uses > old_invites.get(invite.code, 0):
            inviter = invite.inviter
            used_code = invite.code
            break

    if used_code is None and "VANITY_URL" in guild.features:
        try:
            vanity = await guild.vanity_invite()
            if vanity and vanity.uses > old_invites.get(vanity.code, 0):
                used_code = vanity.code
                new_invites_map[vanity.code] = vanity.uses
        except (discord.Forbidden, discord.HTTPException):
            pass

    invites_cache[guild.id] = new_invites_map

    data = load_data()
    set_invited_by(data, guild.id, member.id, inviter.id if inviter else None)

    if inviter:
        account_age = discord.utils.utcnow() - member.created_at
        is_fake = account_age.total_seconds() < 600

        stats = get_user_stats(data, guild.id, inviter.id)
        if is_fake:
            stats["fake"] += 1
        else:
            stats["regular"] += 1

    save_data(data)

    # ── GỬI CARD ĐẸP VÀO KÊNH INTRO (Components V2 - CÓ PING ROLE) ──
    intro_channel_id = get_intro_channel_id(data, guild.id)
    if intro_channel_id:
        channel = guild.get_channel(intro_channel_id)
        if channel:
            try:
                await channel.send(
                    view=build_intro_view(member),
                    allowed_mentions=discord.AllowedMentions(roles=True, users=True, everyone=False),
                )
            except discord.HTTPException as e:
                print(f"[!] Lỗi Gửi Tin Nhắn Intro Ở Guild {guild.name}: {e}")

    # ── GỬI CARD ĐẸP VÀO KÊNH WELCOME (Components V2 - CÓ PING ROLE) ──
    welcome_channel_id = get_welcome_channel_id(data, guild.id)
    if welcome_channel_id:
        channel = guild.get_channel(welcome_channel_id)
        if channel:
            try:
                await channel.send(
                    view=build_welcome_view(member),
                    allowed_mentions=discord.AllowedMentions(roles=True, users=True, everyone=False),
                )
            except discord.HTTPException as e:
                print(f"[!] Lỗi Gửi Tin Nhắn Welcome Ở Guild {guild.name}: {e}")

    # ── GỬI LOG INVITE (KÊNH INVITES RIÊNG) ──
    invites_channel_id = get_invites_channel_id(data, guild.id)
    if invites_channel_id:
        channel = guild.get_channel(invites_channel_id)
        if channel:
            await channel.send(view=build_invite_log_view(member, inviter, used_code, is_fake))


@bot.event
async def on_member_remove(member: discord.Member):
    data = load_data()
    inviter_id = get_invited_by(data, member.guild.id, member.id)

    if inviter_id:
        stats = get_user_stats(data, member.guild.id, inviter_id)
        stats["left"] += 1
        save_data(data)

    channel_id = get_leave_channel_id(data, member.guild.id)
    if channel_id:
        channel = member.guild.get_channel(channel_id)
        if channel:
            await channel.send(view=build_leave_view(member))


IMAGE_VIDEO_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff",  # Ảnh
    ".mp4", ".mov", ".webm", ".avi", ".mkv", ".m4v",            # Video
)


def message_has_media(message: discord.Message) -> bool:
    """Kiểm Tra Tin Nhắn Có Đính Kèm Ảnh Hoặc Video Hay Không."""
    for att in message.attachments:
        if att.content_type and (att.content_type.startswith("image/") or att.content_type.startswith("video/")):
            return True
        if att.filename.lower().endswith(IMAGE_VIDEO_EXTENSIONS):
            return True
    # Cho Phép Cả Link Ảnh/Video Có Preview (Embed Loại image/video/gifv)
    for embed in message.embeds:
        if embed.type in ("image", "video", "gifv"):
            return True
    return False


@bot.event
async def on_message(message: discord.Message):
    # Luôn Cho Bot Xử Lý Lệnh Văn Bản (Vd: !sync) Trước Tiên
    if message.author.bot:
        return

    if message.guild:
        data = load_data()
        visual_channel_id = get_visual_channel_id(data, message.guild.id)

        if visual_channel_id and message.channel.id == visual_channel_id:
            if not message_has_media(message):
                try:
                    await message.delete()
                except (discord.Forbidden, discord.HTTPException):
                    pass
                try:
                    await message.channel.send(
                        f"⚠️ {message.author.mention} Kênh Này Chỉ Nhận Ảnh Hoặc Video — "
                        "Tin Nhắn Văn Bản Đơn Thuần Đã Bị Xóa Tự Động.",
                        delete_after=6,
                        allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                    )
                except discord.HTTPException:
                    pass
                return

            # Có Ảnh/Video Hợp Lệ -> Tự Động Tạo Thread Để Bình Luận
            try:
                await message.create_thread(
                    name=f"💬 Bình Luận — {message.author.display_name}"[:100],
                    auto_archive_duration=1440,
                )
            except (discord.Forbidden, discord.HTTPException):
                pass

    await bot.process_commands(message)


# ── Lệnh Slash ────────────────────────────────────────────────────────────
@bot.tree.command(name="invites", description="Xem Số Lượt Mời Của Bạn Hoặc Người Khác")
@app_commands.describe(member="Thành Viên Muốn Xem (Bỏ Trống = Xem Của Bạn)")
@is_owner()
@app_commands.default_permissions(administrator=True)
async def invites_cmd(interaction: discord.Interaction, member: discord.Member | None = None):
    target = member or interaction.user
    data = load_data()
    stats = get_user_stats(data, interaction.guild_id, target.id)

    await interaction.response.send_message(view=build_invites_stats_view(target, stats))


@invites_cmd.error
async def invites_cmd_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if await handle_owner_check_error(interaction, error):
        return
    await interaction.response.send_message(view=build_setting_error_view(str(error)), ephemeral=True)


@bot.tree.command(name="invite-leaderboard", description="Bảng Xếp Hạng Thành Viên Mời Nhiều Nhất")
@is_owner()
@app_commands.default_permissions(administrator=True)
async def leaderboard_cmd(interaction: discord.Interaction):
    data = load_data()
    guild_stats = data["invite_counts"].get(str(interaction.guild_id), {})

    ranking = sorted(guild_stats.items(), key=lambda kv: total_invites(kv[1]), reverse=True)
    ranking = [r for r in ranking if total_invites(r[1]) > 0][:10]

    if not ranking:
        await interaction.response.send_message("Chưa Có Dữ Liệu Lượt Mời Nào.")
        return

    lines = []
    medals = ["🥇", "🥈", "🥉"]
    for i, (user_id, stats) in enumerate(ranking):
        medal = medals[i] if i < 3 else f"`#{i + 1}`"
        lines.append(f"{medal} <@{user_id}> — **{total_invites(stats)}** Lượt Mời")

    await interaction.response.send_message(view=build_leaderboard_view(lines))


@leaderboard_cmd.error
async def leaderboard_cmd_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if await handle_owner_check_error(interaction, error):
        return
    await interaction.response.send_message(view=build_setting_error_view(str(error)), ephemeral=True)


@bot.tree.command(name="who-invited", description="Xem Ai Đã Mời Một Thành Viên Vào Server")
@app_commands.describe(member="Thành Viên Cần Kiểm Tra")
@is_owner()
@app_commands.default_permissions(administrator=True)
async def who_invited_cmd(interaction: discord.Interaction, member: discord.Member):
    data = load_data()
    inviter_id = get_invited_by(data, interaction.guild_id, member.id)

    if inviter_id:
        await interaction.response.send_message(f"👤 {member.mention} Được Mời Bởi <@{inviter_id}>.")
    else:
        await interaction.response.send_message(f"❓ Không Rõ Ai Đã Mời {member.mention}.")


@who_invited_cmd.error
async def who_invited_cmd_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if await handle_owner_check_error(interaction, error):
        return
    await interaction.response.send_message(view=build_setting_error_view(str(error)), ephemeral=True)


@bot.tree.command(name="welcome-test", description="Xem Thử Tin Nhắn Welcome Của Bạn")
@is_owner()
@app_commands.default_permissions(administrator=True)
async def welcome_test_cmd(interaction: discord.Interaction):
    await interaction.response.send_message(
        view=build_welcome_view(interaction.user),
        allowed_mentions=discord.AllowedMentions(roles=True, users=True, everyone=False),
    )


@welcome_test_cmd.error
async def welcome_test_cmd_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if await handle_owner_check_error(interaction, error):
        return
    await interaction.response.send_message(view=build_setting_error_view(str(error)), ephemeral=True)


@bot.tree.command(name="settings", description="Xem Toàn Bộ Cài Đặt Kênh Hiện Tại Của Server")
@is_owner()
@app_commands.default_permissions(administrator=True)
async def settings_cmd(interaction: discord.Interaction):
    data = load_data()
    await interaction.response.send_message(view=build_settings_view(interaction.guild, data), ephemeral=True)


@settings_cmd.error
async def settings_cmd_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if await handle_owner_check_error(interaction, error):
        return
    await interaction.response.send_message(view=build_setting_error_view(str(error)), ephemeral=True)


@bot.tree.command(name="set-welcome-channel", description="[Admin] Đặt Kênh Welcome (Kèm Rules/Roles/Giới Thiệu/Role Ping Nếu Cần)")
@app_commands.describe(
    channel="Kênh Sẽ Gửi Tin Nhắn Chào Mừng Thành Viên Mới",
    rules="(Tùy Chọn) Kênh Nội Quy — Hiện Trong Tin Nhắn Welcome",
    roles="(Tùy Chọn) Kênh Nhận Vai Trò — Hiện Trong Tin Nhắn Welcome",
    intro="(Tùy Chọn) Kênh Giới Thiệu Bản Thân — Hiện Trong Tin Nhắn Welcome",
    role="(Tùy Chọn) Role Sẽ Được Ping Trong Tin Nhắn Welcome (Vd: @Receptionist)",
)
@is_owner()
@app_commands.default_permissions(administrator=True)
async def set_welcome_channel_cmd(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    rules: discord.TextChannel | None = None,
    roles: discord.TextChannel | None = None,
    intro: discord.TextChannel | None = None,
    role: discord.Role | None = None,
):
    data = load_data()
    gid = str(interaction.guild_id)
    data["welcome_channel"][gid] = str(channel.id)

    lines = [f"> 👋 **Welcome:** {channel.mention}"]
    if rules:
        data["rules_channel"][gid] = str(rules.id)
        lines.append(f"> 📖 **Rules:** {rules.mention}")
    if roles:
        data["roles_channel"][gid] = str(roles.id)
        lines.append(f"> 🎭 **Roles:** {roles.mention}")
    if intro:
        data["intro_channel"][gid] = str(intro.id)
        lines.append(f"> 🌟 **Intro:** {intro.mention}")
    if role:
        data["welcome_role"][gid] = str(role.id)
        lines.append(f"> 📣 **Role Ping:** {role.mention}")

    save_data(data)
    await interaction.response.send_message(
        view=build_setting_confirm_view("👋", "Welcome", channel, extra_lines=lines[1:]), ephemeral=True
    )


@set_welcome_channel_cmd.error
async def set_welcome_channel_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if await handle_owner_check_error(interaction, error):
        return
    await interaction.response.send_message(view=build_setting_error_view(str(error)), ephemeral=True)


@bot.tree.command(name="set-leave-channel", description="[Admin] Đặt Kênh Gửi Log Khi Thành Viên Rời Server")
@app_commands.describe(channel="Kênh Sẽ Gửi Thông Báo Khi Có Người Rời Server")
@is_owner()
@app_commands.default_permissions(administrator=True)
async def set_leave_channel_cmd(interaction: discord.Interaction, channel: discord.TextChannel):
    data = load_data()
    data["leave_channel"][str(interaction.guild_id)] = str(channel.id)
    save_data(data)
    await interaction.response.send_message(view=build_setting_confirm_view("🔌", "Leave", channel), ephemeral=True)


@set_leave_channel_cmd.error
async def set_leave_channel_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if await handle_owner_check_error(interaction, error):
        return
    await interaction.response.send_message(view=build_setting_error_view(str(error)), ephemeral=True)


@bot.tree.command(name="set-invites-channel", description="[Admin] Đặt Kênh Gửi Log Ai Đã Mời Ai")
@app_commands.describe(channel="Kênh Sẽ Gửi Log Thành Viên Mới Kèm Thông Tin Người Mời")
@is_owner()
@app_commands.default_permissions(administrator=True)
async def set_invites_channel_cmd(interaction: discord.Interaction, channel: discord.TextChannel):
    data = load_data()
    data["invites_channel"][str(interaction.guild_id)] = str(channel.id)
    save_data(data)
    await interaction.response.send_message(view=build_setting_confirm_view("⚡", "Invites Log", channel), ephemeral=True)


@set_invites_channel_cmd.error
async def set_invites_channel_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if await handle_owner_check_error(interaction, error):
        return
    await interaction.response.send_message(view=build_setting_error_view(str(error)), ephemeral=True)


@bot.tree.command(name="set-confession-channel", description="[Admin] Đặt Kênh Confession Và Đăng Panel Gửi Confession")
@app_commands.describe(channel="Kênh Sẽ Đăng Panel Và Nhận Confession Ẩn Danh/Công Khai")
@is_owner()
@app_commands.default_permissions(administrator=True)
async def set_confession_channel_cmd(interaction: discord.Interaction, channel: discord.TextChannel):
    data = load_data()
    data["confession_channel"][str(interaction.guild_id)] = str(channel.id)
    save_data(data)

    try:
        panel_container = build_confession_panel_container(interaction.guild.name)
        panel_view = discord.ui.LayoutView(timeout=None)
        panel_view.add_item(panel_container)
        panel_msg = await channel.send(view=panel_view)
        confession_panel_messages[interaction.guild_id] = panel_msg.id
    except discord.HTTPException as e:
        await interaction.response.send_message(
            view=build_setting_error_view(f"Đặt Kênh Thành Công Nhưng Gửi Panel Thất Bại: {e}"), ephemeral=True
        )
        return

    await interaction.response.send_message(view=build_setting_confirm_view("💚", "Confession", channel), ephemeral=True)


@set_confession_channel_cmd.error
async def set_confession_channel_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if await handle_owner_check_error(interaction, error):
        return
    await interaction.response.send_message(view=build_setting_error_view(str(error)), ephemeral=True)


@bot.tree.command(name="set-visual-channel", description="[Admin] Đặt Kênh Chỉ Nhận Ảnh/Video (Tự Xóa Tin Nhắn Văn Bản, Tự Tạo Thread)")
@app_commands.describe(channel="Kênh Chỉ Cho Phép Gửi Ảnh Hoặc Video")
@is_owner()
@app_commands.default_permissions(administrator=True)
async def set_visual_channel_cmd(interaction: discord.Interaction, channel: discord.TextChannel):
    data = load_data()
    data["visual_channel"][str(interaction.guild_id)] = str(channel.id)
    save_data(data)

    try:
        panel_container = build_visual_panel_container(interaction.guild.name)
        panel_view = discord.ui.LayoutView(timeout=None)
        panel_view.add_item(panel_container)
        await channel.send(view=panel_view)
    except discord.HTTPException as e:
        await interaction.response.send_message(
            view=build_setting_error_view(f"Đặt Kênh Thành Công Nhưng Gửi Panel Thất Bại: {e}"), ephemeral=True
        )
        return

    await interaction.response.send_message(
        view=build_setting_confirm_view("📸", "Visual-Check", channel), ephemeral=True
    )


@set_visual_channel_cmd.error
async def set_visual_channel_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if await handle_owner_check_error(interaction, error):
        return
    await interaction.response.send_message(view=build_setting_error_view(str(error)), ephemeral=True)


@bot.tree.command(name="set-pickrole-channel", description="[Admin] Đặt Kênh Và Đăng Panel Pick Role (Chọn Role Bằng Dropdown)")
@app_commands.describe(channel="Kênh Sẽ Đăng Panel Pick Role")
@is_owner()
@app_commands.default_permissions(administrator=True)
async def set_pickrole_channel_cmd(interaction: discord.Interaction, channel: discord.TextChannel):
    data = load_data()
    data["pickrole_channel"][str(interaction.guild_id)] = str(channel.id)
    save_data(data)

    try:
        panel_view = discord.ui.LayoutView(timeout=None)
        panel_view.add_item(build_pickrole_panel_container(interaction.guild))
        await channel.send(view=panel_view)
    except discord.HTTPException as e:
        await interaction.response.send_message(
            view=build_setting_error_view(f"Đặt Kênh Thành Công Nhưng Gửi Panel Thất Bại: {e}"), ephemeral=True
        )
        return

    await interaction.response.send_message(
        view=build_setting_confirm_view("🎭", "Pick Role", channel), ephemeral=True
    )


@set_pickrole_channel_cmd.error
async def set_pickrole_channel_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if await handle_owner_check_error(interaction, error):
        return
    await interaction.response.send_message(view=build_setting_error_view(str(error)), ephemeral=True)


def _chunk_list(items: list, size: int):
    """Chia 1 List Thành Nhiều List Con — Dùng Để Tránh Vượt Giới Hạn Ký Tự Của Discord."""
    for i in range(0, len(items), size):
        yield items[i:i + size]


@bot.tree.command(name="debug-server", description="[Admin] Debug: Liệt Kê Toàn Bộ Role Và Emoji Tùy Chỉnh Của Server (Kèm ID)")
@is_owner()
@app_commands.default_permissions(administrator=True)
async def debug_server_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild

    # ── Danh Sách Role (Trừ @Everyone) — Sắp Theo Vị Trí Cao -> Thấp Giống Server Settings
    roles = [r for r in guild.roles if r.name != "@everyone"]
    roles.sort(key=lambda r: r.position, reverse=True)
    role_lines = [f"`{r.id}` — {r.mention} (Vị Trí: {r.position})" for r in roles]
    if not role_lines:
        role_lines = ["*(Server Chưa Có Role Nào Ngoài @Everyone)*"]

    for i, chunk in enumerate(_chunk_list(role_lines, 35), start=1):
        total = -(-len(role_lines) // 35)  # Làm Tròn Lên
        title = f"## 🛡️ Danh Sách Role — {guild.name}" + (f" ({i}/{total})" if total > 1 else "")
        text = discord.ui.TextDisplay(title + "\n" + "\n".join(chunk))
        view = discord.ui.LayoutView(timeout=None)
        view.add_item(discord.ui.Container(text, accent_color=discord.Color.blurple()))
        await interaction.followup.send(view=view, ephemeral=True)

    # ── Danh Sách Emoji Tùy Chỉnh Của Server (Dùng Cho Nút Bấm Pick Role, Hướng Dẫn Làm Quen...)
    emojis = list(guild.emojis)
    emoji_lines = [
        f"{e} `{e.id}` — Tên: `{e.name}` — Code Dán Vào: `<{'a' if e.animated else ''}:{e.name}:{e.id}>`"
        for e in emojis
    ]
    if not emoji_lines:
        emoji_lines = ["*(Server Chưa Có Emoji Tùy Chỉnh Nào — Emoji Đang Dùng Là Emoji Unicode Mặc Định)*"]

    for i, chunk in enumerate(_chunk_list(emoji_lines, 35), start=1):
        total = -(-len(emoji_lines) // 35)
        title = f"## 😄 Emoji Tùy Chỉnh Của Server — {guild.name}" + (f" ({i}/{total})" if total > 1 else "")
        text = discord.ui.TextDisplay(title + "\n" + "\n".join(chunk))
        view = discord.ui.LayoutView(timeout=None)
        view.add_item(discord.ui.Container(text, accent_color=discord.Color.gold()))
        await interaction.followup.send(view=view, ephemeral=True)

    footer_text = discord.ui.TextDisplay(
        "-# 💡 Copy `ID` Role Để Dùng Trong Lệnh Discord. Copy Chuỗi `<:tên:id>` "
        "Của Emoji Để Dán Vào `PICKROLE_GROUPS` (Thay Cho Emoji Unicode) Nếu Muốn Dùng "
        "Emoji Tùy Chỉnh Của Server Trong Panel Pick Role Hoặc Hướng Dẫn Làm Quen."
    )
    footer_view = discord.ui.LayoutView(timeout=None)
    footer_view.add_item(discord.ui.Container(footer_text, accent_color=discord.Color.green()))
    await interaction.followup.send(view=footer_view, ephemeral=True)


@debug_server_cmd.error
async def debug_server_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if await handle_owner_check_error(interaction, error):
        return
    await interaction.response.send_message(view=build_setting_error_view(str(error)), ephemeral=True)


@bot.tree.command(name="ping", description="Kiểm Tra Độ Trễ Của Bot")
@is_owner()
@app_commands.default_permissions(administrator=True)
async def ping_cmd(interaction: discord.Interaction):
    await interaction.response.send_message(view=build_ping_view(bot.latency), ephemeral=True)


@ping_cmd.error
async def ping_cmd_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if await handle_owner_check_error(interaction, error):
        return
    await interaction.response.send_message(view=build_setting_error_view(str(error)), ephemeral=True)


# ── Lệnh Văn Bản ──────────────────────────────────────────────────────────
@bot.command(name="sync")
async def sync_cmd(ctx: commands.Context):
    """Đồng Bộ Lại Toàn Bộ Slash Command Với Discord (!sync)."""
    if ctx.author.id != OWNER_ID:
        await ctx.reply("❌ Chỉ Chủ Sở Hữu Bot Mới Được Dùng Lệnh Này.")
        return
    msg = await ctx.reply("🔄 Đang Đồng Bộ Slash Command...")
    try:
        synced = await bot.tree.sync()
        await msg.edit(content=f"✅ Đã Đồng Bộ Thành Công **{len(synced)}** Slash Command.")
    except Exception as e:
        await msg.edit(content=f"❌ Đồng Bộ Thất Bại: {e}")


@sync_cmd.error
async def sync_cmd_error(ctx: commands.Context, error: commands.CommandError):
    await ctx.reply(f"❌ Có Lỗi Xảy Ra: {error}")


# ── Chạy Bot ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit(
            "❌ Chưa Có DISCORD_TOKEN. Hãy Tạo File .env Từ .env.example Rồi Điền Token Vào."
        )
    bot.run(TOKEN)
