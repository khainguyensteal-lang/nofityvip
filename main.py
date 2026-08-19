"""
====================================================================
 DISCORD BOT - WELCOME + INVITE TRACKER (1 File Duy Nhất)
====================================================================
Chức Năng:
  - Chào Mừng Thành Viên Mới (Kèm Ai Đã Mời Họ)
  - Theo Dõi Lượt Mời: Hợp Lệ / Rời Đi / Ảo / Thưởng
  - Lệnh Slash: /invites, /invite-leaderboard, /who-invited, /welcome-test,
    /ping, /settings, /set-welcome-channel (Kèm Tùy Chọn Rules/Roles/Giới
    Thiệu/Role Ping), /set-leave-channel, /set-invites-channel
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
        f"> 📣 **Welcome Role Ping:** {fmt_role(get_welcome_role_id(data, guild.id))}"
    )

    footer = discord.ui.TextDisplay(
        "-# Dùng `/set-welcome-channel` (Kèm Tùy Chọn Rules/Roles/Giới Thiệu/Role), "
        "`/set-leave-channel`, `/set-invites-channel` Để Thay Đổi."
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


# ── Sự Kiện ───────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"✅ Đã Đăng Nhập Với Tên {bot.user} (ID: {bot.user.id})")
    for guild in bot.guilds:
        await cache_guild_invites(guild)
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
