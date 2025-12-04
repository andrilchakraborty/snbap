import asyncio
import aiohttp
import json
import os
import zipfile
import streamlit as st
from bs4 import BeautifulSoup
import aiofiles
from subprocess import Popen, PIPE
        
async def get_json(session, username):
    base_url = "https://story.snapchat.com/@"
    headers = {'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:94.0) Gecko/20100101 Firefox/103.0.2'}
    mix = base_url + username
    print(f"[DEBUG] Fetching URL: {mix}")

    async with session.get(mix, headers=headers) as response:
        if response.status == 404:
            return None
        elif not response.ok:
            return None

        content = await response.text()
        print(f"[DEBUG] HTML content fetched for {username}.")
        soup = BeautifulSoup(content, "html.parser")
        snap_data = soup.find(id="__NEXT_DATA__").string.strip()
        data = json.loads(snap_data)
        print(f"[DEBUG] Parsed JSON data for {username}.")
        return data

# Function to download media from Snapchat
async def download_media(json_dict, session):
    media_files = []
    try:
        for snap in json_dict["props"]["pageProps"]["story"]["snapList"]:
            file_url = snap["snapUrls"]["mediaUrl"]
            print(f"[DEBUG] Found file URL: {file_url}")

            if not file_url:
                continue

            file_type = None
            file_name = None

            # Ensure the media directory exists
            media_dir = os.getcwd()
            os.makedirs(media_dir, exist_ok=True)

            async with session.get(file_url, headers={'User-Agent': 'Mozilla/5.0'}) as response:
                print(f"[DEBUG] Downloading media from {file_url}")

                if response.status == 200:
                    file_type = response.headers.get('Content-Type', '')
                    file_name = response.headers.get('ETag', '').replace('"', '')

                    if "image" in file_type:
                        file_name += ".jpeg"
                        file_path = os.path.join(media_dir, file_name)

                        # Delete the existing file if it exists
                        if os.path.isfile(file_path):
                            os.remove(file_path)

                        # Download the image
                        async with aiofiles.open(file_path, 'wb') as f:
                            while True:
                                chunk = await response.content.read(1024)
                                if not chunk:
                                    break
                                await f.write(chunk)

                        media_files.append(file_path)
                        print(f"[DEBUG] Image downloaded and added: {file_name}")

                    elif "video" in file_type:
                        file_name += ".mp4"
                        file_path = os.path.join(media_dir, file_name)

                        # Delete the existing file if it exists
                        if os.path.isfile(file_path):
                            os.remove(file_path)

                        # Download the video
                        async with aiofiles.open(file_path, 'wb') as f:
                            while True:
                                chunk = await response.content.read(1024)
                                if not chunk:
                                    break
                                await f.write(chunk)

                        media_files.append(file_path)
                        print(f"[DEBUG] Video downloaded and added: {file_name}")
                else:
                    print("[DEBUG] Failed to download media.")
    except KeyError:
        print("[DEBUG] No stories found.")
    except Exception as e:
        print(f"[ERROR] An unexpected error occurred: {e}")

    return media_files

# Function to zip all media files
def zip_media(media_files, username):
    # Set the filename to TTK_{username}_Snaps.zip
    zip_filename = f"TTK_{username}_Snaps.zip"
    
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for media_file in media_files:
            zipf.write(media_file, os.path.basename(media_file))
            print(f"[DEBUG] Added {media_file} to zip.")
    
    return zip_filename


# Streamlit page to display Snapchat media
def snapchat_page():
    # Add custom CSS for Snapchat font (you can adjust this to any Snapchat-like font you like)
    add_custom_css()

    # Add Snapchat Logo at the top
    snapchat_logo_url = "https://postcron.com/en/blog/wp-content/uploads/2017/10/snapchat-logo.png"  # Snapchat logo URL
    st.image(snapchat_logo_url, width=200, caption="Snapchat")  # Adjust width and caption as needed

    # Snapchat title with a custom font (you can adjust the font style in the CSS)
    st.markdown("<h1 style='text-align: center; font-family: \"Snapchat\", sans-serif;'>👻 Snapchat Media Viewer</h1>", unsafe_allow_html=True)

    st.markdown(
        "<p style='text-align: center; font-family: \"Snapchat\", sans-serif;'>View and download Snapchat media effortlessly!</p>",
        unsafe_allow_html=True,
    )

    # Input field for Snapchat Username
    username = st.text_input("Enter Snapchat Username:")

    if st.button("Fetch Snaps"):
        if username:
            # Display a message indicating fetching snaps for the username
            st.markdown(f"<p style='font-family: \"Snapchat\", sans-serif; color: gray;'>Fetching snaps from <strong>{username}</strong>...</p>", unsafe_allow_html=True)

            async def display_media():
                async with aiohttp.ClientSession() as session:
                    json_data = await get_json(session, username)
                    if json_data:
                        media_files = await download_media(json_data, session)
                        if media_files:
                            # Display the media in a grid format
                            cols = st.columns(3)  # Adjust this number to control how many images/videos per row
                            for i, media_file in enumerate(media_files):
                                with cols[i % 3]:  # Ensure we cycle through columns
                                    if media_file.endswith(".jpeg"):
                                        st.image(media_file, caption="Image", use_container_width=True)
                                    elif media_file.endswith(".mp4"):
                                        st.write("Video")  # Display the caption
                                        st.video(media_file, format="video/mp4")
                            # Add a download button for the zip
                            zip_filename = zip_media(media_files, username)
                            with open(zip_filename, "rb") as f:
                                st.download_button(
                                    label="Download All Snaps",
                                    data=f,
                                    file_name=zip_filename,
                                    mime="application/zip"
                                )
                        else:
                            st.warning("No media found.")
                    else:
                        st.error(f"No stories found for username: {username}")

            asyncio.run(display_media())
        else:
            st.error("Please enter a valid Snapchat username.")


# Custom CSS for Snapchat font
def add_custom_css():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Work+Sans&display=swap');  /* Using a Snapchat-like font */
    body {
        font-family: 'Work Sans', sans-serif;
    }
    </style>
    """, unsafe_allow_html=True)
# Main Function with Navigation
def main():
    st.set_page_config(
        page_title="Snapify",
        page_icon="https://pngimg.com/uploads/snapchat/snapchat_PNG61.png",  # Image URL
        layout="wide",
    )

    # Top menu bar with tabs
    tabs = st.tabs([
        "Snapchat Downloader", 
    ])

    with tabs[0]:
        snapchat_page()  # Ensure the snapchat_page() function is defined elsewhere


    


if __name__ == "__main__":
    main()
