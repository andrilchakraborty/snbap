#!/usr/bin/env python3
import asyncio
import aiohttp
import aiofiles
import json
import logging
import os
import re
import sys
import zipfile
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, unquote
from bs4 import BeautifulSoup
import streamlit as st

# ----------------- Logging -----------------
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")

# ----------------- Utilities -----------------
def slugify(text: str) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text or "unknown"

def safe_filename_from_url(url: str) -> str:
    parsed = urlparse(url)
    name = unquote(os.path.basename(parsed.path))
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    return name or "file"

async def fetch_next_data(session: aiohttp.ClientSession, url: str):
    headers = {"User-Agent": "Mozilla/5.0"}
    async with session.get(url, headers=headers) as resp:
        if resp.status == 404:
            return None
        text = await resp.text()
        try:
            soup = BeautifulSoup(text, "html.parser")
            el = soup.find(id="__NEXT_DATA__")
            if not el or not el.string:
                return None
            return json.loads(el.string)
        except Exception:
            logging.exception("Failed to parse __NEXT_DATA__")
            return None

def extract_media_urls(data: dict):
    """
    Recursively collect every snapList under props.pageProps,
    keyed by its storyTitle.value (if present), else title/displayName,
    else the parent key.
    Returns dict: {album_title: [mediaUrl, ...], ...}
    """
    media = {}
    page_props = data.get("props", {}).get("pageProps", {})

    def recurse(obj, path):
        if isinstance(obj, dict):
            for key, val in obj.items():
                if key == "snapList" and isinstance(val, list):
                    title = (
                        (obj.get("storyTitle") or {}).get("value")
                        or obj.get("title")
                        or obj.get("displayName")
                        or (path[-1] if path else "unknown")
                    )
                    urls = [
                        snap.get("snapUrls", {}).get("mediaUrl")
                        for snap in val
                        if snap.get("snapUrls", {}).get("mediaUrl")
                    ]
                    media.setdefault(title, []).extend(urls)
                else:
                    recurse(val, path + [key])
        elif isinstance(obj, list):
            for item in obj:
                recurse(item, path)

    recurse(page_props, [])
    return media

async def download_media_to_dir(session: aiohttp.ClientSession, url: str, dest_dir: str):
    os.makedirs(dest_dir, exist_ok=True)
    parsed = urlparse(url)
    base = unquote(os.path.basename(parsed.path))
    base = re.sub(r'[<>:"/\\|?*]', "", base)
    # try to get extension from content-type
    async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}) as resp:
        if resp.status != 200:
            logging.error(f"Failed to download {url}: HTTP {resp.status}")
            return None
        ct = resp.headers.get("Content-Type", "")
        ext = ".jpg" if "image" in ct else ".mp4" if "video" in ct else ""
        filename = base
        if ext and not filename.lower().endswith(ext):
            filename = f"{filename}{ext}"
        path = os.path.join(dest_dir, filename)
        # write file
        try:
            async with aiofiles.open(path, "wb") as f:
                async for chunk in resp.content.iter_chunked(1024):
                    await f.write(chunk)
            return path
        except Exception:
            logging.exception("Error writing file")
            return None

def make_zip_from_files(files: list[str], username: str, kind: str = "snaps"):
    if not files:
        return None
    zdir = tempfile.mkdtemp(prefix="snap_zip_")
    zname = f"{username}_{kind}_{datetime.now():%Y-%m-%d_%H%M%S}.zip"
    zpath = os.path.join(zdir, zname)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            try:
                zf.write(f, os.path.basename(f))
            except Exception:
                logging.exception("Failed to add to zip")
    return zpath

# ----------------- Async helpers for Streamlit usage -----------------
async def async_get_json_for_user(session: aiohttp.ClientSession, username: str):
    url = f"https://story.snapchat.com/@{username}"
    return await fetch_next_data(session, url)

def fetch_json_sync(username: str):
    async def _fetch():
        async with aiohttp.ClientSession() as session:
            return await async_get_json_for_user(session, username)
    return asyncio.run(_fetch())

def download_and_collect_sync(urls: list[str], username: str, subfolder: str):
    """
    Downloads list of urls to a temp folder and returns list of saved file paths.
    Runs asynchronously but wrapped for synchronous call.
    """
    async def _dl():
        dest_root = tempfile.mkdtemp(prefix=f"snap_{username}_{subfolder}_")
        files = []
        async with aiohttp.ClientSession() as session:
            tasks = [download_media_to_dir(session, u, dest_root) for u in urls]
            results = await asyncio.gather(*tasks)
            for r in results:
                if r:
                    files.append(r)
        return files
    return asyncio.run(_dl())

# ----------------- Streamlit UI -----------------
def add_custom_css():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Work+Sans&display=swap');
    .stApp { font-family: 'Work Sans', sans-serif; }
    .snap-title { text-align:center; font-weight:700; font-size:28px; }
    </style>
    """, unsafe_allow_html=True)

def display_media_grid(media_files: list[str], cols_per_row: int = 3):
    if not media_files:
        st.info("No media to display.")
        return
    cols = st.columns(cols_per_row)
    for i, m in enumerate(media_files):
        col = cols[i % cols_per_row]
        try:
            if m.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                col.image(m, use_column_width=True, caption=os.path.basename(m))
            elif m.lower().endswith((".mp4", ".mov", ".webm")):
                col.video(m)
            else:
                col.write(os.path.basename(m))
        except Exception:
            col.write(os.path.basename(m))

def snapchat_page():
    add_custom_css()
    snapchat_logo_url = "https://pngimg.com/uploads/snapchat/snapchat_PNG61.png"
    st.image(snapchat_logo_url, width=160)
    st.markdown("<div class='snap-title'>👻 Snapify — Snapchat Media Viewer</div>", unsafe_allow_html=True)
    st.write("Enter a Snapchat username and fetch stories. Use the dedicated tabs for Highlights and Spotlights.")

    username = st.text_input("Snapchat username", value="", help="example: ricardo", key="stories_username")
    zip_toggle = st.checkbox("Offer ZIP download", value=True, key="stories_zip")

    if st.button("Fetch Stories", key="fetch_stories_btn"):
        if not username:
            st.error("Please enter a valid Snapchat username.")
        else:
            with st.spinner("Fetching stories..."):
                data = fetch_json_sync(username)
                if not data:
                    st.error("No data found or can't access the user's page.")
                else:
                    # Collect story snapList (if any)
                    snaps = (data.get("props", {})
                                .get("pageProps", {})
                                .get("story", {})
                                .get("snapList", []))
                    story_urls = [s.get("snapUrls", {}).get("mediaUrl") for s in snaps if s.get("snapUrls", {}).get("mediaUrl")]
                    if not story_urls:
                        st.info("No story snaps found.")
                    else:
                        st.success(f"Found {len(story_urls)} story snaps. Downloading...")
                        files = download_and_collect_sync(story_urls, username, "stories")
                        display_media_grid(files, cols_per_row=3)
                        if zip_toggle and files:
                            z = make_zip_from_files(files, username, kind="stories")
                            if z:
                                with open(z, "rb") as f:
                                    st.download_button("Download Stories ZIP", data=f, file_name=os.path.basename(z), mime="application/zip")

def highlights_tab():
    st.header("Highlights")
    st.write("Enter username and pick highlight album. (This tab focuses only on highlights.)")
    username = st.text_input("Username (highlights tab)", key="high_user")
    zip_toggle = st.checkbox("Offer ZIP download", value=True, key="high_zip")
    if st.button("Fetch Highlights (tab)", key="fetch_high_tab"):
        if not username:
            st.error("Please enter a username.")
        else:
            with st.spinner("Fetching highlights..."):
                data = fetch_json_sync(username)
                if not data:
                    st.error("No data found or cannot access page.")
                else:
                    media_map = extract_media_urls(data)
                    highlight_keys = sorted([k for k in media_map.keys() if "spotlight" not in k.lower()], key=lambda s: s.lower())
                    if not highlight_keys:
                        st.info("No highlights found.")
                        return
                    album_choice = st.selectbox("Choose highlight album to download (or All)", ["All"] + highlight_keys, key="high_album_choice")
                    selected_urls = []
                    if album_choice == "All":
                        for k in highlight_keys:
                            selected_urls.extend(media_map.get(k, []))
                    else:
                        selected_urls = media_map.get(album_choice, [])
                    if not selected_urls:
                        st.info("No media urls for selection.")
                    else:
                        files = download_and_collect_sync(selected_urls, username, f"highlights_{slugify(album_choice)}")
                        display_media_grid(files)
                        if zip_toggle and files:
                            z = make_zip_from_files(files, username, kind=f"highlights_{slugify(album_choice)}")
                            if z:
                                with open(z, "rb") as f:
                                    st.download_button("Download Highlights ZIP", data=f, file_name=os.path.basename(z), mime="application/zip")

def spotlights_tab():
    st.header("Spotlights")
    st.write("Enter username and pick spotlight album. (This tab focuses only on spotlight content.)")
    username = st.text_input("Username (spotlights tab)", key="spot_user")
    zip_toggle = st.checkbox("Offer ZIP download", value=True, key="spot_zip")
    if st.button("Fetch Spotlights (tab)", key="fetch_spot_tab"):
        if not username:
            st.error("Please enter a username.")
        else:
            with st.spinner("Fetching spotlights..."):
                data = fetch_json_sync(username)
                if not data:
                    st.error("No data found or cannot access page.")
                else:
                    media_map = extract_media_urls(data)
                    spotlight_keys = sorted([k for k in media_map.keys() if "spotlight" in k.lower()], key=lambda s: s.lower())
                    if not spotlight_keys:
                        st.info("No spotlights found.")
                        return
                    album_choice = st.selectbox("Choose spotlight album to download (or All)", ["All"] + spotlight_keys, key="spot_album_choice")
                    selected_urls = []
                    if album_choice == "All":
                        for k in spotlight_keys:
                            selected_urls.extend(media_map.get(k, []))
                    else:
                        selected_urls = media_map.get(album_choice, [])
                    if not selected_urls:
                        st.info("No media urls for selection.")
                    else:
                        files = download_and_collect_sync(selected_urls, username, f"spotlights_{slugify(album_choice)}")
                        display_media_grid(files)
                        if zip_toggle and files:
                            z = make_zip_from_files(files, username, kind=f"spotlights_{slugify(album_choice)}")
                            if z:
                                with open(z, "rb") as f:
                                    st.download_button("Download Spotlights ZIP", data=f, file_name=os.path.basename(z), mime="application/zip")

def main():
    st.set_page_config(
        page_title="Snapify",
        page_icon="https://pngimg.com/uploads/snapchat/snapchat_PNG61.png",
        layout="wide",
    )

    tabs = st.tabs(["Snapchat Downloader", "Highlights", "Spotlights"])
    with tabs[0]:
        snapchat_page()
    with tabs[1]:
        highlights_tab()
    with tabs[2]:
        spotlights_tab()

if __name__ == "__main__":
    main()
